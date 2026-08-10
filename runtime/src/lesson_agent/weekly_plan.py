from __future__ import annotations

import re
import subprocess
import base64
import mimetypes
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from zipfile import BadZipFile, ZipFile

from lxml import etree

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
        return _extract_image(path, vision_client, vision_model, target_date, class_number)
    raise PlanParseError("unsupported", f"지원하지 않는 파일 형식입니다: {suffix}")


def _extract_image(
    path: Path, client, model: str, target_date: date, class_number: int
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
                            f"이 이미지는 초등학교 주간학습안내다. 6학년 {class_number}반의 "
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
                             "Include every visible class-2 weekday and period record before CONTENT records."
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
            parser = etree.XMLParser(resolve_entities=False, no_network=True, recover=False)
            for name in names:
                root = etree.fromstring(archive.read(name), parser=parser)
                for paragraph in root.xpath("//*[local-name()='p']"):
                    parts = paragraph.xpath(".//*[local-name()='t']/text()")
                    if parts:
                        output.append("".join(parts).strip())
            return "\n".join(line for line in output if line)
    except PlanParseError:
        raise
    except (BadZipFile, etree.XMLSyntaxError, OSError, ValueError) as exc:
        raise PlanParseError("table_unreadable", "HWPX 내용을 읽을 수 없습니다.") from exc


def _extract_hwp(path: Path) -> str:
    try:
        completed = subprocess.run(
            ["hwp5txt", str(path)],
            shell=False,
            timeout=30,
            capture_output=True,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        raise PlanParseError(
            "unsupported", "구형 HWP를 읽으려면 hwp5txt가 필요합니다."
        ) from exc
    if completed.returncode != 0:
        raise PlanParseError("table_unreadable", "hwp5txt 변환에 실패했습니다.")
    return completed.stdout.decode("utf-8", errors="replace")


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
    if [cell.period for cell in target_cells] != list(range(1, 7)):
        raise PlanParseError("timetable_incomplete", "요청한 반·요일의 1~6교시 시간표가 완전하지 않습니다.")
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


def parse_lessons(text: str, target_date: date, class_number: int) -> list[Lesson]:
    if any(line.lstrip().startswith("TIMETABLE |") for line in text.splitlines()):
        cells, contents = parse_structured_week(text)
        return resolve_structured_lessons(cells, contents, target_date, class_number)
    class_pattern = rf"6\s*학년\s*{class_number}\s*반"
    if not re.search(class_pattern, text):
        raise PlanParseError(
            "class_missing", f"문서에서 6학년 {class_number}반을 찾지 못했습니다."
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
