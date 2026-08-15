from __future__ import annotations

import argparse
import sys
import webbrowser
from functools import partial
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from lesson_agent.app import LessonAgent, _read_plan
from lesson_agent.config import Settings
from lesson_agent.indischool import IndischoolBrowser
from lesson_agent.kakao import KakaoAuthRequired, KakaoClient
from lesson_agent.models import SearchLesson
from lesson_agent.school import LocalPlanClient
from lesson_agent.state import RunState
from lesson_agent.summarize import Summarizer
from lesson_agent.weekly_plan import build_search_lessons, extract_document_text, parse_lessons


def _safe_print(value: object, *, stream=None) -> None:
    stream = stream or sys.stdout
    text = str(value)
    try:
        stream.write(text + "\n")
    except UnicodeEncodeError:
        encoding = getattr(stream, "encoding", None) or "utf-8"
        safe = text.encode(encoding, errors="replace").decode(encoding)
        stream.write(safe + "\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="lesson-agent")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("setup-indischool")
    commands.add_parser("setup-kakao")
    commands.add_parser("test-kakao")
    preview = commands.add_parser("preview")
    preview.add_argument("--file", type=Path, required=True)
    preview.add_argument("--date", type=date.fromisoformat)
    run = commands.add_parser("run")
    run.add_argument("--date", type=date.fromisoformat)
    run.add_argument("--dry-run", action="store_true")
    smoke = commands.add_parser("smoke-indischool")
    smoke.add_argument("--subject", required=True)
    smoke.add_argument("--topic", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = Settings()
    try:
        if args.command == "setup-indischool":
            IndischoolBrowser(settings.indischool_profile_path, settings.max_results).setup_login()
            return 0
        if args.command == "setup-kakao":
            kakao = _kakao(settings)
            url = kakao.authorization_url()
            _safe_print(f"카카오 인증 페이지: {url}")
            webbrowser.open(url)
            kakao.save_authorization_code(input("리디렉션 주소의 code 값을 붙여넣으세요: ").strip())
            return 0
        if args.command == "test-kakao":
            _kakao(settings).send_to_me(
                [f"수업 자료 에이전트 카카오 연결 시험 완료\n{_kakao_link(settings)}"]
            )
            return 0
        if args.command == "preview":
            run_date = args.date or _today(settings)
            openai_client = None
            if settings.openai_api_key:
                from openai import OpenAI

                openai_client = OpenAI(api_key=settings.openai_api_key)
            lessons = parse_lessons(
                extract_document_text(
                    args.file,
                    vision_client=openai_client,
                    vision_model=settings.openai_model,
                    target_date=run_date,
                    class_number=settings.class_number,
                    grade=settings.grade,
                ),
                run_date,
                settings.class_number,
                grade=settings.grade,
            )
            searchable, excluded = build_search_lessons(lessons, settings.excluded_subjects)
            for lesson in lessons:
                _safe_print(f"{lesson.period}교시 {lesson.subject}: {lesson.topic}")
            _safe_print("전담 제외: " + (", ".join(item.subject for item in excluded) or "없음"))
            _safe_print("검색 대상: " + (", ".join(item.subject for item in searchable) or "없음"))
            return 0
        if args.command == "smoke-indischool":
            browser = IndischoolBrowser(settings.indischool_profile_path, settings.max_results)
            for resource in browser.search(SearchLesson(args.subject, args.topic, (1,))):
                _safe_print(f"{resource.rank}. {resource.title}\n   {resource.url}")
            return 0
        if args.command == "run":
            result = _build_agent(settings).run(
                args.date or _today(settings), dry_run=args.dry_run
            )
            if args.dry_run:
                _safe_print("\n\n--- 다음 메시지 ---\n\n".join(result.messages))
            return 0
    except KakaoAuthRequired as exc:
        _safe_print(str(exc), stream=sys.stderr)
        return 2
    except Exception as exc:
        _safe_print(f"실행 실패: {exc}", stream=sys.stderr)
        return 1
    return 1


def _today(settings: Settings) -> date:
    return datetime.now(ZoneInfo(settings.timezone)).date()


def _kakao(settings: Settings) -> KakaoClient:
    if not settings.kakao_rest_api_key:
        raise KakaoAuthRequired("LESSON_AGENT_KAKAO_REST_API_KEY 설정이 필요합니다.")
    return KakaoClient(
        settings.kakao_rest_api_key,
        settings.kakao_redirect_uri,
        link_url=_kakao_link(settings),
    )


def _build_agent(settings: Settings) -> LessonAgent:
    openai_client = None
    if settings.openai_api_key:
        from openai import OpenAI

        openai_client = OpenAI(api_key=settings.openai_api_key)
    return LessonAgent(
        settings=settings,
        school=LocalPlanClient(settings.local_plan_dir),
        indischool=IndischoolBrowser(
            settings.indischool_profile_path, settings.max_results, grade=settings.grade
        ),
        summarizer=Summarizer(openai_client, settings.openai_model),
        kakao=_kakao(settings),
        state=RunState(settings.state_path),
        plan_reader=partial(
            _read_plan,
            vision_client=openai_client,
            vision_model=settings.openai_model,
            grade=settings.grade,
        ),
    )


def _kakao_link(settings: Settings) -> str:
    return "https://indischool.com"


if __name__ == "__main__":
    raise SystemExit(main())
