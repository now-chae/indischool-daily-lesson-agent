from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit, urlunsplit

import httpx
from bs4 import BeautifulSoup


MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024
PLAN_SUFFIXES = {".hwp", ".hwpx", ".jpg", ".jpeg", ".png", ".webp"}


class SchoolError(RuntimeError):
    pass


class SchoolDownloadError(SchoolError):
    pass


@dataclass(frozen=True, slots=True)
class WeeklyPlanPost:
    title: str
    post_url: str
    attachment_url: str
    filename: str
    published_on: date


class LocalPlanClient:
    """Read accumulated weekly-plan files from a local directory.

    Files are selected only when their filename contains one or two ISO-like
    dates. One date means that date; two dates define an inclusive range.
    """

    def __init__(self, plan_dir: Path) -> None:
        self.plan_dir = Path(plan_dir)

    def find_plan_for(self, target_date: date) -> WeeklyPlanPost | None:
        if not self.plan_dir.exists():
            return None
        candidates = [
            path
            for path in self.plan_dir.iterdir()
            if path.is_file()
            and path.suffix.lower() in PLAN_SUFFIXES
            and _filename_covers_date(path.name, target_date)
        ]
        if not candidates:
            return None
        source = max(candidates, key=lambda path: path.stat().st_mtime_ns)
        modified = date.fromtimestamp(source.stat().st_mtime)
        return WeeklyPlanPost(
            title=source.stem,
            post_url=source.as_uri(),
            attachment_url=str(source),
            filename=source.name,
            published_on=modified,
        )

    def download(self, post: WeeklyPlanPost, destination: Path) -> Path:
        source = Path(post.attachment_url)
        if not source.is_file():
            raise SchoolDownloadError(f"로컬 주간안내 파일을 찾을 수 없습니다: {source}")
        destination.mkdir(parents=True, exist_ok=True)
        target = destination / source.name
        shutil.copy2(source, target)
        return target


class SchoolClient:
    def __init__(
        self,
        base_url: str,
        grade: int = 6,
        *,
        client: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/") + "/"
        self.home_url = urljoin(self.base_url, "main.do?s=ibs")
        self.grade = grade
        self.client = client or httpx.Client(follow_redirects=True, timeout=20)

    def find_plan_for(self, target_date: date) -> WeeklyPlanPost | None:
        home = self._get_html(self.home_url)
        board_url = self._find_grade_board(home)
        for page_number in range(1, 11):
            page_url = board_url if page_number == 1 else _with_page(board_url, page_number)
            board = self._get_html(page_url)
            for anchor in board.find_all("a", href=True):
                title = anchor.get_text(" ", strip=True)
                if not _title_covers_date(title, target_date):
                    continue
                post_url = self._resolve_post_url(anchor, page_url)
                return self._parse_post(self._get_html(post_url), post_url, title)
        return None

    def download(self, post: WeeklyPlanPost, destination: Path) -> Path:
        suffix = Path(post.filename).suffix.lower()
        if suffix not in PLAN_SUFFIXES:
            raise SchoolDownloadError(f"지원하지 않는 첨부 형식입니다: {suffix}")
        response = self.client.get(post.attachment_url)
        response.raise_for_status()
        content_type = response.headers.get("content-type", "").lower()
        if "text/html" in content_type or response.content.lstrip().startswith(b"<html"):
            raise SchoolDownloadError("첨부파일 대신 HTML 오류 페이지가 반환되었습니다.")
        if len(response.content) > MAX_ATTACHMENT_BYTES:
            raise SchoolDownloadError("첨부파일이 20 MiB 제한을 초과합니다.")
        destination.mkdir(parents=True, exist_ok=True)
        safe_name = Path(post.filename.replace("\\", "/")).name
        target = destination / safe_name
        target.write_bytes(response.content)
        return target

    def _get_html(self, url: str) -> BeautifulSoup:
        response = self.client.get(url)
        response.raise_for_status()
        return BeautifulSoup(response.text, "lxml")

    def _find_grade_board(self, home: BeautifulSoup) -> str:
        wanted = f"{self.grade}학년"
        for anchor in home.find_all("a", href=True):
            text = anchor.get_text(" ", strip=True)
            href = anchor["href"]
            if text == wanted and "boardCnts/" in href:
                return urljoin(self.base_url, anchor["href"])
        raise SchoolError(f"{wanted} 주간학습안내 게시판을 찾지 못했습니다.")

    def _resolve_post_url(self, anchor, board_url: str) -> str:
        onclick = anchor.get("onclick", "")
        match = re.search(
            r"goView\('([^']+)'\s*,\s*'([^']+)'\s*,\s*'([^']+)'\s*,\s*'([^']+)'\s*,\s*'[^']*'\s*,\s*'([^']+)'\s*,\s*'([^']+)'",
            onclick,
        )
        if not match:
            return urljoin(board_url, anchor["href"])
        board_id, view_board_id, sequence, level, status, page = match.groups()
        board_query = parse_qs(urlsplit(board_url).query)
        query = [
            ("boardID", board_id),
            ("viewBoardID", view_board_id),
            ("boardSeq", sequence),
            ("lev", level),
            ("action", "view"),
            ("searchType", "S"),
            ("statusYN", status),
            ("page", page),
            ("m", board_query.get("m", [""])[0]),
            ("s", board_query.get("s", [""])[0]),
        ]
        return urljoin(self.base_url, "boardCnts/updateCnt.do") + "?" + urlencode(query)

    def _parse_post(
        self, soup: BeautifulSoup, post_url: str, fallback_title: str
    ) -> WeeklyPlanPost:
        heading = soup.find(["h1", "h2", "h3"])
        title = heading.get_text(" ", strip=True) if heading else fallback_title
        attachment = next(
            (
                a
                for a in soup.find_all("a", href=True)
                if Path(a.get("download") or a.get_text(" ", strip=True)).suffix.lower()
                in {".hwp", ".hwpx"}
            ),
            None,
        )
        if attachment is not None:
            filename = attachment.get("download") or attachment.get_text(" ", strip=True)
            attachment_url = urljoin(post_url, attachment["href"])
        else:
            image = next(
                (
                    img
                    for img in soup.find_all("img", src=True)
                    if "/upload/keditor/" in img["src"]
                    and Path(urlsplit(img["src"]).path).suffix.lower()
                    in PLAN_SUFFIXES - {".hwp", ".hwpx"}
                ),
                None,
            )
            if image is None:
                raise SchoolError("게시물에서 HWP/HWPX 첨부 또는 주간안내 이미지를 찾지 못했습니다.")
            attachment_url = urljoin(post_url, image["src"])
            filename = Path(urlsplit(attachment_url).path).name
        date_node = soup.select_one(".date")
        published = _parse_iso_date(date_node.get_text(strip=True) if date_node else "")
        return WeeklyPlanPost(
            title=title,
            post_url=post_url,
            attachment_url=attachment_url,
            filename=filename,
            published_on=published,
        )


def _title_covers_date(title: str, target: date) -> bool:
    matches = re.findall(r"(\d{1,2})\s*월\s*(\d{1,2})\s*일", title)
    if not matches:
        return False
    dates = [date(target.year, int(month), int(day)) for month, day in matches[:2]]
    if len(dates) == 1:
        return dates[0] == target
    start, end = dates
    if end < start:
        end = date(target.year + 1, end.month, end.day)
    return start <= target <= end


def _filename_covers_date(filename: str, target: date) -> bool:
    dates = _dates_from_filename(filename)
    if not dates:
        return False
    if len(dates) == 1:
        return dates[0] == target
    start, end = dates[0], dates[1]
    if end < start:
        end = date(start.year + 1, end.month, end.day)
    return start <= target <= end


def _dates_from_filename(filename: str) -> list[date]:
    stem = Path(filename).stem
    found: list[date] = []
    patterns = (
        r"(?<!\d)(\d{4})[-_.년\s]+(\d{1,2})[-_.월\s]+(\d{1,2})일?",
        r"(?<!\d)(\d{4})(\d{2})(\d{2})(?!\d)",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, stem):
            try:
                value = date(*(int(part) for part in match.groups()))
            except ValueError:
                continue
            if value not in found:
                found.append(value)
    return sorted(found)


def _with_page(url: str, page_number: int) -> str:
    parts = urlsplit(url)
    query = parse_qs(parts.query)
    query["page"] = [str(page_number)]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query, doseq=True), parts.fragment))


def _parse_iso_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError:
        return date.min
