from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import re

from lesson_agent.models import Lesson, SearchLesson
from lesson_agent.summarize import ResourceSummary
from lesson_agent.weekly_plan import query_variants


@dataclass(frozen=True, slots=True)
class DailyReport:
    run_date: date
    lessons: tuple[Lesson, ...]
    excluded_subjects: tuple[str, ...]
    results: tuple[tuple[SearchLesson, tuple[ResourceSummary, ...]], ...]
    warnings: tuple[str, ...]
    art_recent: tuple[ResourceSummary, ...] = ()


def format_messages(report: DailyReport, max_chars: int = 900) -> list[str]:
    header = (
        f"[{report.run_date.month}월 {report.run_date.day}일 수업자료]\n"
        "인천백석초 6학년 2반"
    )
    messages = _pack_blocks([header], max_chars)
    remaining_warnings = list(report.warnings)
    for lesson, summaries in report.results:
        searches = " / ".join(query_variants(lesson)) or "확인 필요"
        subject_blocks = [
            f"📚 과목: {lesson.subject}\n"
            f"🔎 검색어: {searches}"
        ]
        subject_blocks.extend(_summary_blocks(summaries))
        if lesson.subject == "미술" and report.art_recent:
            subject_blocks.extend(_summary_blocks(report.art_recent))
        subject_warnings, remaining_warnings = _take_subject_warnings(
            remaining_warnings, lesson.subject
        )
        if subject_warnings:
            subject_blocks.append(
                "⚠ 확인사항: " + " / ".join(subject_warnings)
            )
        messages.extend(_pack_blocks(subject_blocks, max_chars))
    if remaining_warnings:
        messages.extend(
            _pack_blocks(
                ["⚠ 확인사항\n" + "\n".join(f"- {warning}" for warning in remaining_warnings)],
                max_chars,
            )
        )
    return messages


def _summary_blocks(summaries: tuple[ResourceSummary, ...]) -> list[str]:
    blocks: list[str] = []
    for index, item in enumerate(summaries, start=1):
        one_line_summary = _one_sentence(item.summary)
        blocks.append(
            f"{index}. 📝 제목: {item.resource.title}\n"
            f"🔗 링크: {item.resource.url}\n"
            f"💡 핵심요약: {one_line_summary}"
        )
    return blocks


def _one_sentence(text: str, max_chars: int = 120) -> str:
    first_line = text.splitlines()[0] if text.splitlines() else text
    normalized = " ".join(first_line.split())
    sentence = re.split(r"(?<=[.!?])\s+", normalized, maxsplit=1)[0]
    if len(sentence) <= max_chars:
        return sentence
    return sentence[: max_chars - 1].rstrip() + "…"


def _take_subject_warnings(
    warnings: list[str], subject: str
) -> tuple[list[str], list[str]]:
    selected: list[str] = []
    remaining: list[str] = []
    for warning in warnings:
        if warning.startswith(f"{subject} 검색어:"):
            continue
        if warning.startswith(f"{subject}:"):
            selected.append(warning.split(":", 1)[1].strip())
        elif warning.startswith(f"{subject} "):
            selected.append(warning[len(subject) :].strip())
        else:
            remaining.append(warning)
    return selected, remaining


def _pack_blocks(blocks: list[str], max_chars: int) -> list[str]:
    messages: list[str] = []
    current = ""
    for block in blocks:
        if len(block) > max_chars:
            block = block[: max_chars - 1] + "…"
        candidate = f"{current}\n\n{block}" if current else block
        if current and len(candidate) > max_chars:
            messages.append(current)
            current = block
        else:
            current = candidate
    if current:
        messages.append(current)
    return messages
