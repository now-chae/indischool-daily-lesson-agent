from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from datetime import date
from pathlib import Path


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
    """Select and copy a weekly-plan file from a local folder.

    A filename must contain one date (an exact day) or two dates (an inclusive
    range). The original file is never moved or deleted.
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


def _filename_covers_date(filename: str, target: date) -> bool:
    dates = _dates_from_filename(filename, target.year)
    if not dates:
        return False
    if len(dates) == 1:
        return dates[0] == target
    start, end = dates[0], dates[1]
    if end < start:
        end = date(start.year + 1, end.month, end.day)
    return start <= target <= end


def _dates_from_filename(filename: str, default_year: int | None = None) -> list[date]:
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
    if default_year is not None:
        for match in re.finditer(r"(?<![\d-])(\d{1,2})\s*월\s*(\d{1,2})\s*일?", stem):
            try:
                value = date(default_year, int(match.group(1)), int(match.group(2)))
            except ValueError:
                continue
            if value not in found:
                found.append(value)
    return sorted(found)
