from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Callable, Protocol

from lesson_agent.config import Settings
from lesson_agent.message import DailyReport, format_messages
from lesson_agent.models import Lesson
from lesson_agent.state import RunState
from lesson_agent.weekly_plan import build_search_lessons, extract_document_text, parse_lessons, query_variants


class PlanReader(Protocol):
    def __call__(self, path: Path, run_date: date, class_number: int) -> list[Lesson]: ...


@dataclass(frozen=True, slots=True)
class RunResult:
    status: str
    sent: bool
    messages: tuple[str, ...]


class LessonAgent:
    def __init__(
        self,
        *,
        settings: Settings,
        school,
        indischool,
        summarizer,
        kakao,
        state: RunState,
        plan_reader: PlanReader | None = None,
    ) -> None:
        self.settings = settings
        self.school = school
        self.indischool = indischool
        self.summarizer = summarizer
        self.kakao = kakao
        self.state = state
        self.plan_reader = plan_reader or _read_plan

    def run(self, target_date: date, *, dry_run: bool = False) -> RunResult:
        if self.state.was_sent(target_date) and not dry_run:
            return RunResult("already_sent", False, ())
        with self.state.acquire(target_date):
            post = self.school.find_plan_for(target_date)
            if post is None:
                source_reference = _source_reference(self.settings)
                messages = (
                    f"[{target_date.isoformat()}] {self.settings.grade}학년 주간학습안내를 찾지 못했습니다.\n"
                    f"{source_reference}",
                )
                if not dry_run:
                    self.kakao.send_to_me(list(messages))
                    self.state.mark_sent(target_date, source_reference, [], _hashes(messages))
                return RunResult("no_plan", not dry_run, messages)

            downloaded: Path | None = None
            try:
                downloaded = self.school.download(post, self.settings.download_path)
                lessons = self.plan_reader(downloaded, target_date, self.settings.class_number)
                searchable, excluded = build_search_lessons(
                    lessons, self.settings.excluded_subjects
                )
                results = []
                art_recent = ()
                warnings: list[str] = []
                resource_urls: list[str] = []
                for item in searchable:
                    queries = query_variants(item)
                    try:
                        resources = self.indischool.search(item)
                        if item.subject == "미술":
                            summaries = tuple(self.summarizer.summarize(item, resources[:2]))
                            recent_loader = getattr(self.indischool, "recent_art_resources", None)
                            if recent_loader is not None:
                                try:
                                    related_urls = {summary.resource.url for summary in summaries}
                                    recent_resources = [
                                        resource
                                        for resource in recent_loader(target_date, 3)
                                        if resource.url not in related_urls
                                    ]
                                    if len(recent_resources) < 3:
                                        warnings.append(
                                            f"미술 최근 인기글: {len(recent_resources)}/3개 — "
                                            "7일→14일→21일→28일 범위까지 확인했습니다."
                                        )
                                    art_recent = tuple(
                                        self.summarizer.summarize_recent_art(recent_resources[:3])
                                    )
                                except Exception:
                                    warnings.append("미술 최근 인기글: 조회 실패 — 주제 관련 자료는 전송합니다.")
                        else:
                            summaries = tuple(self.summarizer.summarize(item, resources))
                        results.append((item, summaries))
                        resource_urls.extend(summary.resource.url for summary in summaries)
                        if len(summaries) < self.settings.max_results:
                            warnings.append(f"{item.subject} 검색어: {', '.join(queries)}")
                        if len(summaries) < self.settings.max_results:
                            warnings.append(f"{item.subject}: 적합한 자료 {len(summaries)}개")
                    except Exception:
                        results.append((item, ()))
                        warnings.append(f"{item.subject} 검색어: {', '.join(queries)}")
                        warnings.append(f"{item.subject} 검색 실패 — 인디스쿨 화면 또는 로그인을 확인하세요.")
                report = DailyReport(
                    target_date,
                    tuple(lessons),
                    tuple(item.subject for item in excluded),
                    tuple(results),
                    tuple(warnings),
                    art_recent,
                    grade=self.settings.grade,
                    class_number=self.settings.class_number,
                )
                messages = tuple(format_messages(report))
                if not dry_run:
                    self.kakao.send_to_me(list(messages))
                    self.state.mark_sent(
                        target_date, post.post_url, resource_urls, _hashes(messages)
                    )
                return RunResult("preview" if dry_run else "sent", not dry_run, messages)
            finally:
                if downloaded is not None:
                    downloaded.unlink(missing_ok=True)


def _read_plan(
    path: Path,
    run_date: date,
    class_number: int,
    *,
    vision_client=None,
    vision_model: str = "gpt-5-mini",
    grade: int = 6,
) -> list[Lesson]:
    extract_kwargs = {
        "vision_client": vision_client,
        "vision_model": vision_model,
        "target_date": run_date,
        "class_number": class_number,
    }
    if grade != 6:
        extract_kwargs["grade"] = grade
    return parse_lessons(
        extract_document_text(path, **extract_kwargs),
        run_date,
        class_number,
        grade=grade,
    )


def _hashes(messages: tuple[str, ...]) -> list[str]:
    return [hashlib.sha256(message.encode("utf-8")).hexdigest() for message in messages]


def _source_reference(settings: Settings) -> str:
    if settings.plan_source == "local":
        return f"로컬 주간안내 폴더: {settings.local_plan_dir}"
    return settings.school_base_url
