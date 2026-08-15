from __future__ import annotations

import re
import subprocess
import base64
import mimetypes
import shutil
import sys
import tempfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from zipfile import BadZipFile, ZipFile

from lxml import etree
from bs4 import BeautifulSoup

from lesson_agent.models import Lesson, SearchLesson


class PlanParseError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class TimetableCell:
    class_number: int
    weekday: str
    period: int
    subject: str


@dataclass(frozen=True, slots=True)
class WeeklyContent:
    subject: str
    unit_name: str | None
    topic: str
    pages: str | None
    occurrence: int


WEEKDAY_ORDER = {"월": 0, "화": 1, "수": 2, "목": 3, "금": 4}


def extract_document_text(
    path: Path,
    *,
    vision_client=None,
    vision_model: str = "gpt-5-mini",
    target_date: date | None = None,
    class_number: int | None = None,
    grade: int = 6,
) -> str:
    suffix = path.suffix.lower()
    if suffix == ".hwpx":
        return _extract_hwpx(path)
    if suffix == ".hwp":
        return _extract_hwp(path)
    if suffix in {".jpg", ".jpeg", ".png", ".webp"}:
        if vision_client is None:
            raise PlanParseError(
                "vision_required",
                "학교 게시물이 이미지입니다. OpenAI API 키를 설정하거나 HWP/HWPX 파일을 직접 지정하세요.",
            )
        if target_date is None or class_number is None:
            raise PlanParseError("date_missing", "이미지 판독에는 날짜와 반 정보가 필요합니다.")
        return _extract_image(path, vision_client, vision_model, target_date, class_number, grade)
    raise PlanParseError("unsupported", f"지원하지 않는 파일 형식입니다: {suffix}")


def _extract_image(
    path: Path, client, model: str, target_date: date, class_number: int, grade: int
) -> str:
    mime = mimetypes.guess_type(path.name)[0] or "image/jpeg"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    response = client.responses.create(
        model=model,
        input=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": (
                            f"이 이미지는 초등학교 주간학습안내다. {grade}학년 {class_number}반의 "
                            f"{target_date.year}년 {target_date.month}월 {target_date.day}일 시간표만 읽어라. "
                            "오른쪽 학급 시간표의 해당 요일 과목 순서와 왼쪽 과목별 학습내용·차시 순서를 "
                            "결합해야 한다. 각 과목은 월요일 1교시부터 목표 수업까지의 주간 누적 등장 순번을 "
                            "센 뒤, 왼쪽 학습내용에서 그 과목의 같은 순번 행만 대응시켜라. 차시명은 확대해 "
                            "글자 단위로 다시 읽고 비슷한 다른 행이나 검색 결과로 추측하지 마라. "
                            "첫 줄에 정확한 학년·반, 다음 줄에 정확한 날짜와 요일, 이후 각 수업을 "
                            "'N교시 | 과목 | 학습 주제 | 쪽수' 형식으로 출력하라. 보이지 않는 내용은 추측하지 마라."
                             " Output five pipe-delimited fields and put the weekly-plan unit name in field five; leave field five blank only when it is unreadable."
                             " Ignore the earlier single-day output format. Output only structured records for the full week: "
                             "TIMETABLE | class_number | Korean weekday (월, 화, 수, 목, 금) | period 1-6 | subject, "
                             "then CONTENT | subject | unit name | lesson topic | pages | weekly occurrence such as 4/9. "
                             f" Include every visible class-{class_number} weekday and period record before CONTENT records."
                        ),
                    },
                    {"type": "input_image", "image_url": f"data:{mime};base64,{encoded}"},
                ],
            }
        ],
    )
    text = response.output_text.strip()
    if not text:
        raise PlanParseError("table_unreadable", "이미지에서 주간학습안내를 읽지 못했습니다.")
    return text


def _extract_hwpx(path: Path) -> str:
    try:
        with ZipFile(path) as archive:
            names = sorted(
                (name for name in archive.namelist() if re.fullmatch(r"Contents/section\d+\.xml", name)),
                key=lambda name: int(re.search(r"\d+", name).group()),
            )
            if not names:
                raise PlanParseError("table_unreadable", "HWPX 본문 XML이 없습니다.")
            output: list[str] = []
            table_groups: list[list[list[str]]] = []
            parser = etree.XMLParser(resolve_entities=False, no_network=True, recover=False)
            for name in names:
                root = etree.fromstring(archive.read(name), parser=parser)
                groups = _extract_hwpx_table_groups_from_root(root)
                table_groups.extend(groups)
                for group in groups:
                    for row_index, row in enumerate(group):
                        for column_index, value in enumerate(row):
                            if value:
                                output.append(f"TABLE | {row_index} | {column_index} | {value}")
                table_nodes = {id(node) for node in root.xpath("//*[local-name()='tbl']")}
                for paragraph in root.xpath("//*[local-name()='p']"):
                    if any(id(table) in table_nodes for table in paragraph.iterancestors()):
                        continue
                    parts = paragraph.xpath(".//*[local-name()='t']/text()")
                    value = _normalize_cell_text(" ".join(parts))
                    if value:
                        output.append(f"PARAGRAPH | {value}")
            output.extend(_structured_from_hwpx_tables(table_groups))
            if not output:
                raise PlanParseError("table_unreadable", "HWPX 표와 본문을 읽지 못했습니다.")
            return "\n".join(output)
    except PlanParseError:
        raise
    except (BadZipFile, etree.XMLSyntaxError, OSError, ValueError) as exc:
        raise PlanParseError("table_unreadable", "HWPX 내용을 읽을 수 없습니다.") from exc


def _extract_hwpx_table_rows(path: Path) -> list[list[str]]:
    try:
        with ZipFile(path) as archive:
            names = sorted(
                (name for name in archive.namelist() if re.fullmatch(r"Contents/section\d+\.xml", name)),
                key=lambda name: int(re.search(r"\d+", name).group()),
            )
            parser = etree.XMLParser(resolve_entities=False, no_network=True, recover=False)
            rows: list[list[str]] = []
            for name in names:
                root = etree.fromstring(archive.read(name), parser=parser)
                rows.extend(_extract_hwpx_table_rows_from_root(root))
            return rows
    except (BadZipFile, etree.XMLSyntaxError, OSError, ValueError) as exc:
        raise PlanParseError("table_unreadable", "HWPX 표를 읽을 수 없습니다.") from exc


def _extract_hwpx_table_rows_from_root(root) -> list[list[str]]:
    return [row for group in _extract_hwpx_table_groups_from_root(root) for row in group]


def _extract_hwpx_table_groups_from_root(root) -> list[list[list[str]]]:
    groups: list[list[list[str]]] = []
    tables = root.xpath("//*[local-name()='tbl' and not(ancestor::*[local-name()='tbl'])]")
    for table in tables:
        grid: list[list[str | None]] = []
        for row_index, row in enumerate(table.xpath("./*[local-name()='tr']")):
            while len(grid) <= row_index:
                grid.append([])
            column_index = 0
            for cell in row.xpath("./*[local-name()='tc']"):
                while column_index < len(grid[row_index]) and grid[row_index][column_index] is not None:
                    column_index += 1
                span = cell.xpath("./*[local-name()='tcPr']/*[local-name()='cellSpan']")
                span_node = span[0] if span else None
                try:
                    colspan = max(1, int((span_node.get("colSpan") or span_node.get("colspan") or "1"))) if span_node is not None else 1
                    rowspan = max(1, int((span_node.get("rowSpan") or span_node.get("rowspan") or "1"))) if span_node is not None else 1
                except ValueError:
                    colspan = rowspan = 1
                parts = cell.xpath(".//*[local-name()='t']/text()")
                value = _normalize_cell_text(" ".join(parts))
                for row_offset in range(rowspan):
                    target_row = row_index + row_offset
                    while len(grid) <= target_row:
                        grid.append([])
                    while len(grid[target_row]) < column_index + colspan:
                        grid[target_row].append(None)
                    for column_offset in range(colspan):
                        if grid[target_row][column_index + column_offset] is None:
                            grid[target_row][column_index + column_offset] = value if column_offset == 0 else ""
                column_index += colspan
        table_rows = [[cell or "" for cell in row] for row in grid]
        if table_rows:
            groups.append(table_rows)
    return groups


def _structured_from_hwpx_tables(table_groups: list[list[list[str]]]) -> list[str]:
    output: list[str] = []
    for table in table_groups:
        header_index = next(
            (
                index
                for index, row in enumerate(table)
                if any(re.sub(r"\s+", "", cell) == "과목" for cell in row)
            ),
            None,
        )
        if header_index is not None:
            header = table[header_index]
            subject_index = _find_header_column(header, "과목", default=0)
            unit_index = _find_header_column(header, "단원명", default=1)
            topic_index = _find_header_column(header, "학습내용", default=2)
            pages_index = _find_header_column(header, "쪽수", default=max(0, topic_index + 1))
            occurrence_index = _find_header_column(header, "차시", default=max(0, pages_index + 1))
            required_index = max(subject_index, unit_index, topic_index, pages_index, occurrence_index)
            for row in table[header_index + 1 :]:
                if len(row) <= required_index:
                    continue
                occurrence = re.sub(r"\s+", "", row[occurrence_index])
                if not re.fullmatch(r"\d+/\d+", occurrence):
                    continue
                subject = _normalize_timetable_subject(row[subject_index])
                topic = row[topic_index].strip()
                if subject and topic:
                    output.append(
                        f"CONTENT | {subject} | {row[unit_index].strip()} | {topic} | {row[pages_index].strip()} | {occurrence}"
                    )
        if not table or not table[0] or not re.fullmatch(r"\d+반", re.sub(r"\s+", "", table[0][0])):
            continue
        class_number_match = re.search(r"\d+", re.sub(r"\s+", "", table[0][0]))
        if class_number_match is None:
            continue
        class_number = int(class_number_match.group())
        weekdays = [re.sub(r"\s+", "", value) for value in table[0][1:6]]
        if weekdays != ["월", "화", "수", "목", "금"]:
            continue
        for row in table[1:]:
            if not row or not re.fullmatch(r"\d+", row[0]):
                continue
            period = int(row[0])
            for index, subject in enumerate(row[1:6]):
                normalized = _normalize_timetable_subject(subject)
                if normalized:
                    output.append(f"TIMETABLE | {class_number} | {weekdays[index]} | {period} | {normalized}")
    return output


def _normalize_cell_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _extract_hwp(
    path: Path,
    *,
    runner=None,
) -> str:
    command = "hwp5txt"
    if runner is None:
        command = _find_hwp_command("hwp5txt")
        if command is None:
            raise PlanParseError(
                "hwp_reader_missing",
                "HWP 파일을 읽으려면 hwp5txt가 필요합니다. pyhwp를 설치한 뒤 다시 실행하세요.",
            )
        runner = subprocess.run
    try:
        completed = runner(
            [command, str(path)],
            shell=False,
            timeout=30,
            capture_output=True,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        raise PlanParseError(
            "hwp_reader_missing", "HWP 파일을 읽는 hwp5txt 실행에 실패했습니다. pyhwp 설치를 확인하세요."
        ) from exc
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        raise PlanParseError("table_unreadable", f"hwp5txt 변환에 실패했습니다. {detail}".strip())
    raw = completed.stdout or b""
    text = raw.decode("utf-8", errors="replace").strip()
    if not text:
        text = raw.decode("cp949", errors="replace").strip()
    if not text:
        raise PlanParseError("table_unreadable", "hwp5txt 변환 결과가 비어 있습니다.")
    if "<표>" in text or "<그림>" in text:
        return _extract_hwp_html(path, runner=runner)
    return text


def _extract_hwp_html(path: Path, *, runner) -> str:
    with tempfile.TemporaryDirectory(prefix="lesson-agent-hwp-") as output_dir:
        try:
            completed = runner(
                [_find_hwp_command("hwp5html") or "hwp5html", "--output", output_dir, str(path)],
                shell=False,
                timeout=60,
                capture_output=True,
                check=False,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            raise PlanParseError(
                "hwp_reader_missing",
                "표가 포함된 HWP를 읽으려면 hwp5html가 필요합니다. pyhwp 설치를 확인하세요.",
            ) from exc
        if completed.returncode != 0:
            detail = completed.stderr.decode("utf-8", errors="replace").strip()
            raise PlanParseError("table_unreadable", f"hwp5html 변환에 실패했습니다. {detail}".strip())
        html_files = sorted(Path(output_dir).glob("*.xhtml"))
        if not html_files:
            raise PlanParseError("table_unreadable", "hwp5html 결과 XHTML을 찾지 못했습니다.")
        return _structured_from_hwp_html(html_files[0].read_text(encoding="utf-8", errors="replace"))


def _structured_from_hwp_html(html: str) -> str:
    soup = BeautifulSoup(html, "xml")
    tables = soup.find_all("table")
    if not tables:
        raise PlanParseError("table_unreadable", "HWP HTML에서 표를 찾지 못했습니다.")
    output: list[str] = []
    main_grid = _html_table_grid(tables[0])
    header_index = next(
        (
            index
            for index, row in enumerate(main_grid)
            if any(re.sub(r"\s+", "", cell) == "과목" for cell in row)
        ),
        None,
    )
    if header_index is not None:
        header = main_grid[header_index]
        subject_index = _find_header_column(header, "과목", default=0)
        unit_index = _find_header_column(header, "단원명", default=1)
        topic_index = _find_header_column(header, "학습내용", default=2)
        pages_index = _find_header_column(header, "쪽수", default=max(0, topic_index + 1))
        occurrence_index_from_header = _find_header_column(header, "차시", default=max(0, pages_index + 1))
        for row in main_grid[header_index + 1 :]:
            cells = [cell.strip() for cell in row]
            required_index = max(
                subject_index,
                unit_index,
                topic_index,
                pages_index,
                occurrence_index_from_header,
            )
            if len(cells) <= required_index:
                continue
            subject = _normalize_timetable_subject(cells[subject_index])
            occurrence_index = occurrence_index_from_header
            if not re.fullmatch(r"\d+/\d+", re.sub(r"\s+", "", cells[occurrence_index])):
                occurrence_index = next(
                    (
                        index
                        for index in range(len(cells) - 1, -1, -1)
                        if re.fullmatch(r"\d+/\d+", re.sub(r"\s+", "", cells[index]))
                    ),
                    None,
                )
            if occurrence_index is None:
                continue
            occurrence = re.sub(r"\s+", "", cells[occurrence_index])
            pages = cells[pages_index] if pages_index < len(cells) else ""
            topic = cells[topic_index] if topic_index < len(cells) else ""
            unit = cells[unit_index] if unit_index < len(cells) else ""
            if not subject or not topic or not pages:
                continue
            output.append(
                "CONTENT | "
                f"{subject} | {unit} | {topic} | {pages} | {occurrence}"
            )
    for table in tables[1:]:
        grid = _html_table_grid(table)
        if not grid or not grid[0] or not re.fullmatch(r"\d+반", re.sub(r"\s+", "", grid[0][0])):
            continue
        class_number = int(re.search(r"\d+", re.sub(r"\s+", "", grid[0][0])).group())
        weekdays = [re.sub(r"\s+", "", value) for value in grid[0][1:6]]
        if weekdays != ["월", "화", "수", "목", "금"]:
            continue
        for row in grid[1:]:
            if not row or not re.fullmatch(r"\d+", row[0]):
                continue
            period = int(row[0])
            for index, subject in enumerate(row[1:6]):
                normalized = _normalize_timetable_subject(subject)
                if normalized:
                    output.append(f"TIMETABLE | {class_number} | {weekdays[index]} | {period} | {normalized}")
    if not output:
        raise PlanParseError("table_unreadable", "HWP 표에서 시간표와 학습내용을 찾지 못했습니다.")
    return "\n".join(output)


def _find_header_column(header: list[str], label: str, *, default: int) -> int:
    normalized_label = re.sub(r"\s+", "", label)
    for index, value in enumerate(header):
        if re.sub(r"\s+", "", value) == normalized_label:
            return index
    return default


def _normalize_timetable_subject(value: str) -> str:
    """Expand the one-character subject abbreviations used in HWP tables."""

    normalized = re.sub(r"\s+", "", value)
    aliases = {
        "국": "국어",
        "수": "수학",
        "과": "과학",
        "사": "사회",
        "도": "도덕",
        "미": "미술",
        "음": "음악",
        "영": "영어",
        "체": "체육",
        "자": "자율",
    }
    return aliases.get(normalized, normalized)


def _html_table_grid(table) -> list[list[str]]:
    grid: list[list[str | None]] = []
    for row_index, row in enumerate(table.find_all("tr", recursive=False)):
        while len(grid) <= row_index:
            grid.append([])
        column_index = 0
        for cell in row.find_all(["td", "th"], recursive=False):
            while column_index < len(grid[row_index]) and grid[row_index][column_index] is not None:
                column_index += 1
            try:
                rowspan = max(1, int(cell.get("rowspan", "1")))
                colspan = max(1, int(cell.get("colspan", "1")))
            except ValueError:
                rowspan = colspan = 1
            value = "" if cell.find("table") else _normalize_cell_text(cell.get_text(" ", strip=True))
            for row_offset in range(rowspan):
                target_row = row_index + row_offset
                while len(grid) <= target_row:
                    grid.append([])
                while len(grid[target_row]) < column_index + colspan:
                    grid[target_row].append(None)
                for column_offset in range(colspan):
                    if grid[target_row][column_index + column_offset] is None:
                        grid[target_row][column_index + column_offset] = value if column_offset == 0 else ""
            column_index += colspan
    return [[cell or "" for cell in row] for row in grid]


def _find_hwp_command(name: str) -> str | None:
    found = shutil.which(name)
    if found:
        return found
    python_dir = Path(sys.executable).resolve().parent
    for suffix in (".exe", ""):
        candidate = python_dir / f"{name}{suffix}"
        if candidate.is_file():
            return str(candidate)
    return None


def parse_structured_week(text: str) -> tuple[list[TimetableCell], list[WeeklyContent]]:
    cells: list[TimetableCell] = []
    contents: list[WeeklyContent] = []
    for line in text.splitlines():
        columns = [part.strip() for part in line.split("|")]
        if not columns:
            continue
        if columns[0] == "TIMETABLE" and len(columns) >= 5:
            try:
                class_number = int(columns[1])
                period = int(columns[3])
            except ValueError:
                continue
            if columns[2] in WEEKDAY_ORDER and columns[4]:
                cells.append(TimetableCell(class_number, columns[2], period, columns[4]))
        if columns[0] == "CONTENT" and len(columns) >= 6:
            occurrence_text = columns[5].split("/", 1)[0].strip()
            try:
                occurrence = int(occurrence_text)
            except ValueError:
                continue
            if columns[1] and columns[3]:
                contents.append(
                    WeeklyContent(
                        subject=columns[1],
                        unit_name=columns[2] or None,
                        topic=columns[3],
                        pages=columns[4] or None,
                        occurrence=occurrence,
                    )
                )
    if not cells and not contents:
        raise PlanParseError("table_unreadable", "구조화된 주간안내 기록을 찾지 못했습니다.")
    return cells, contents


def resolve_structured_lessons(
    cells: list[TimetableCell],
    contents: list[WeeklyContent],
    target_date: date,
    class_number: int,
) -> list[Lesson]:
    target_weekday = ("월", "화", "수", "목", "금")[target_date.weekday()]
    class_cells = [cell for cell in cells if cell.class_number == class_number]
    target_cells = sorted(
        (cell for cell in class_cells if cell.weekday == target_weekday),
        key=lambda cell: cell.period,
    )
    target_periods = [cell.period for cell in target_cells]
    if not target_periods or target_periods != list(range(1, max(target_periods) + 1)):
        raise PlanParseError("timetable_incomplete", "요청한 반·요일의 시간표가 1교시부터 연속으로 확인되지 않습니다.")
    ordered_cells = sorted(
        class_cells,
        key=lambda cell: (WEEKDAY_ORDER[cell.weekday], cell.period),
    )
    content_by_key = {
        (_normalize_subject(content.subject), content.occurrence): content
        for content in contents
    }
    lessons: list[Lesson] = []
    for cell in target_cells:
        occurrence = sum(
            1
            for prior in ordered_cells
            if _normalize_subject(prior.subject) == _normalize_subject(cell.subject)
            and (WEEKDAY_ORDER[prior.weekday], prior.period)
            <= (WEEKDAY_ORDER[cell.weekday], cell.period)
        )
        content = content_by_key.get((_normalize_subject(cell.subject), occurrence))
        if content is None or _is_placeholder_topic(content.topic):
            raise PlanParseError(
                "lesson_content_missing",
                f"{cell.period}교시 {cell.subject}의 학습 주제를 확인하지 못했습니다.",
            )
        else:
            lessons.append(
                Lesson(cell.period, cell.subject, content.topic, content.pages, content.unit_name)
            )
    return lessons


def parse_lessons(
    text: str, target_date: date, class_number: int, *, grade: int = 6
) -> list[Lesson]:
    if any(line.lstrip().startswith("TIMETABLE |") for line in text.splitlines()):
        cells, contents = parse_structured_week(text)
        return resolve_structured_lessons(cells, contents, target_date, class_number)
    class_pattern = rf"{grade}\s*학년\s*{class_number}\s*반"
    if not re.search(class_pattern, text):
        raise PlanParseError(
            "class_missing", f"문서에서 {grade}학년 {class_number}반을 찾지 못했습니다."
        )
    date_pattern = rf"{target_date.year}\s*년\s*{target_date.month}\s*월\s*{target_date.day}\s*일"
    if not re.search(date_pattern, text):
        raise PlanParseError("date_missing", "문서에서 요청 날짜를 찾지 못했습니다.")

    lessons: list[Lesson] = []
    for line in text.splitlines():
        columns = [part.strip() for part in line.split("|")]
        if len(columns) < 3:
            continue
        period_match = re.fullmatch(r"(\d{1,2})\s*교시", columns[0])
        if not period_match:
            continue
        subject = re.sub(r"\s+", "", columns[1])
        topic = columns[2].strip()
        pages = columns[3].strip() if len(columns) > 3 else ""
        unit_name = columns[4].strip() if len(columns) > 4 else None
        pages = re.sub(r"\s*쪽\s*$", "", pages) or None
        if subject and topic:
            lessons.append(
                Lesson(int(period_match.group(1)), subject, topic, pages, unit_name)
            )
    if not lessons:
        raise PlanParseError("table_unreadable", "오늘의 교시 표를 해석하지 못했습니다.")
    return lessons


def build_search_lessons(
    lessons: list[Lesson], excluded_subjects: tuple[str, ...]
) -> tuple[list[SearchLesson], list[Lesson]]:
    excluded_keys = {_normalize_subject(item) for item in excluded_subjects}
    excluded: list[Lesson] = []
    grouped: dict[tuple[str, str], list[Lesson]] = {}
    for lesson in lessons:
        normalized_subject = _normalize_subject(lesson.subject)
        if normalized_subject in excluded_keys:
            excluded.append(
                Lesson(lesson.period, normalized_subject, lesson.topic, lesson.pages, lesson.unit_name)
            )
            continue
        topic_key = "__art_continuous__" if normalized_subject == "미술" else _normalize_topic(lesson.topic)
        key = (normalized_subject, topic_key)
        grouped.setdefault(key, []).append(lesson)

    searchable = [
        SearchLesson(
            subject=subject,
            topic=(
                " 및 ".join(item.topic.strip() for item in items)
                if subject == "미술" and len(items) > 1
                else items[0].topic.strip()
            ),
            periods=tuple(item.period for item in items),
            pages=items[0].pages,
            unit_name=items[0].unit_name,
        )
        for (subject, _), items in grouped.items()
    ]
    return searchable, excluded


def query_variants(item: SearchLesson) -> tuple[str, ...]:
    exact = item.topic.strip()
    searchable_topic = _without_period_marker(exact)
    review_markers = (
        "\uc2a4\uc2a4\ub85c",
        "\ub9c8\ubb34\ub9ac",
        "\ubcf5\uc2b5",
        "\ucd1d\uc815\ub9ac",
        "\ub418\ub3cc\uc544\ubcf4\uae30",
        "\uc815\ub9ac\ud558\uae30",
    )
    if item.unit_name and any(marker in exact for marker in review_markers):
        terms = ("\ubcf5\uc2b5", "\ucd1d\uc815\ub9ac", "\ub9c8\ubb34\ub9ac")
        return _unique_search_terms(tuple(f"{item.unit_name} {term}" for term in terms))
    generic_markers = ("마무리", "복습", "총정리", "되돌아보기", "정리하기")
    if item.unit_name and any(marker in exact for marker in generic_markers):
        return _unique_search_terms((f"{item.unit_name} {exact}", item.unit_name, exact))
    if item.subject == "국어":
        reading_or_writing = re.search(r"(.+?)\s*(?:읽기|쓰기)", searchable_topic)
        if reading_or_writing:
            return _unique_search_terms(
                (re.sub(r"\s+", "", reading_or_writing.group(1)),)
            )
        return _unique_search_terms((searchable_topic,))
    if item.subject == "음악":
        return _unique_search_terms((searchable_topic,))
    if item.subject == "미술":
        art_terms: list[str] = []
        for segment in re.split(r"\s+(?:및|그리고)\s+", searchable_topic):
            segment_terms, segment_actions = concept_action_terms(segment)
            if segment_terms and segment_actions:
                art_terms.append(_primary_phrase(segment, segment_terms))
            elif segment.strip():
                art_terms.append(segment.strip())
        return _unique_search_terms(tuple(art_terms))
    concept_terms, action_terms = concept_action_terms(searchable_topic)
    if concept_terms and action_terms:
        return (_primary_phrase(searchable_topic, concept_terms),)
    phrases = _original_key_phrases(searchable_topic)
    if item.subject == "수학":
        return _unique_search_terms((searchable_topic, *phrases))
    return _unique_search_terms(phrases)


_ACTION_STEMS = (
    "사용", "활용", "대응", "실천", "탐구", "비교", "분석", "설명", "표현",
    "토의", "토론", "조사", "관찰", "이해", "판단", "해결", "계획", "제작",
    "감상", "구성", "읽기", "쓰기", "계산", "구하기", "알아보", "살펴보", "찾", "변하", "될",
)
_PARTICLE_SUFFIXES = ("으로", "에서", "에게", "부터", "까지", "은", "는", "이", "가", "을", "를", "에", "의", "와", "과", "도", "로", "까")
_NON_CONCEPT_WORDS = {"어떻게", "어떤", "무엇", "우리", "함께", "할", "까요", "볼", "볼까요", "로봇", "것", "경우", "방법"}


def concept_action_terms(topic: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Separate a Korean lesson title into searchable concept words and action words."""
    words = [_strip_particle(word) for word in re.findall(r"[가-힣A-Za-z0-9]+", _without_period_marker(topic))]
    action_index: int | None = None
    action_indexes: list[int] = []
    actions: list[str] = []
    for index, word in enumerate(words):
        action = next((stem for stem in _ACTION_STEMS if word.startswith(stem)), None)
        if action is None:
            continue
        if action_index is None:
            action_index = index
        action_indexes.append(index)
        if action not in actions:
            actions.append(action)
    if action_index is None:
        return (), ()
    question_index = next(
        (index for index, word in enumerate(words) if word in {"어떻게", "어떤", "무엇"}),
        None,
    )
    if question_index is not None:
        prior_actions = [index for index in action_indexes if index < question_index]
        concept_slice = (
            words[prior_actions[-1] + 1 : question_index]
            if prior_actions
            else words[:question_index]
        )
    else:
        concept_slice = words[:action_index]
    concepts = [word for word in concept_slice if word and word not in _NON_CONCEPT_WORDS]
    return tuple(concepts[:2]), tuple(actions)


def concept_context_terms(topic: str) -> tuple[str, ...]:
    """Return meaningful concept words omitted from the primary search phrase."""
    primary, actions = concept_action_terms(topic)
    primary_set = set(primary)
    action_set = set(actions)
    words = [_strip_particle(word) for word in re.findall(r"[가-힣A-Za-z0-9]+", _without_period_marker(topic))]
    context: list[str] = []
    for word in words:
        if not word or word in primary_set or word in action_set or word in _NON_CONCEPT_WORDS:
            continue
        if any(word.startswith(stem) for stem in _ACTION_STEMS):
            continue
        if word not in context:
            context.append(word)
    return tuple(context)


def _primary_phrase(topic: str, terms: tuple[str, ...]) -> str:
    normalized = _without_period_marker(topic)
    if not terms:
        return normalized
    start = normalized.find(terms[0])
    if start < 0:
        return " ".join(terms)
    end = start + len(terms[0])
    for term in terms[1:]:
        position = normalized.find(term, end)
        if position < 0:
            return " ".join(terms)
        end = position + len(term)
    return normalized[start:end].strip()


def _strip_particle(word: str) -> str:
    if word.endswith("까요") and len(word) > 2:
        return word[:-2]
    if word.endswith("까") and len(word) > 1:
        return word[:-1]
    for suffix in _PARTICLE_SUFFIXES:
        if word.endswith(suffix) and len(word) > len(suffix) + 1:
            return word[: -len(suffix)]
    return word


def _without_period_marker(text: str) -> str:
    return re.sub(r"\s*\(\d+\s*/\s*\d+\)", "", text).strip()


def _original_key_phrases(text: str) -> tuple[str, ...]:
    parts = [part.strip() for part in re.split(r"(?:과|와)\s+|\s+(?:및|그리고)\s+|[,·]\s*", text) if part.strip()]
    if len(parts) < 2:
        return (text.strip(),) if text.strip() else ()
    first = parts[0]
    if "의 " in first:
        first = first.rsplit("의 ", 1)[1].strip()
    candidates = [first, *parts[1:]]
    token_counts = [len(re.findall(r"[가-힣A-Za-z0-9]+", value)) for value in candidates]
    if all(count >= 2 for count in token_counts):
        return tuple(candidates)
    return (text.strip(),)


def _unique_search_terms(candidates: tuple[str, ...]) -> tuple[str, ...]:
    terms: list[str] = []
    for candidate in candidates:
        normalized = re.sub(r"\s+", " ", candidate).strip()
        if normalized and normalized not in terms:
            terms.append(normalized)
    return tuple(terms)


def _legacy_query_variants(item: SearchLesson) -> tuple[str, ...]:
    exact = item.topic.strip()
    cleaned = re.sub(r"\([^)]*(?:쪽|p\.?)[^)]*\)", "", exact, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -–—,./")
    tokens = re.findall(r"[가-힣A-Za-z0-9]+", cleaned)
    core = " ".join(tokens[:4])
    variants: list[str] = []
    for candidate in (exact, cleaned, core):
        candidate = candidate.strip()
        if candidate and candidate != item.subject and candidate not in variants:
            variants.append(candidate)
    return tuple(variants[:3])


def _normalize_subject(value: str) -> str:
    return re.sub(r"\s+", "", value)


def _normalize_topic(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def _is_placeholder_topic(topic: str) -> bool:
    normalized = _normalize_topic(topic)
    return normalized in {"", "\ud559\uc2b5 \ub0b4\uc6a9 \ud655\uc778 \ud544\uc694", "\uc5c6\uc74c"}
