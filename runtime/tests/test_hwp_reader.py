from subprocess import CompletedProcess
from pathlib import Path

import pytest

import lesson_agent.weekly_plan as weekly_plan
from lesson_agent.weekly_plan import PlanParseError, _extract_hwp, parse_lessons


def test_hwp_reader_missing_has_actionable_error(monkeypatch, tmp_path):
    monkeypatch.setattr(weekly_plan, "_find_hwp_command", lambda name: None)

    with pytest.raises(PlanParseError) as error:
        _extract_hwp(tmp_path / "plan.hwp")

    assert error.value.code == "hwp_reader_missing"
    assert "hwp5txt" in str(error.value)


def test_hwp_reader_rejects_empty_output(tmp_path):
    result = CompletedProcess(["hwp5txt"], 0, stdout=b"", stderr=b"")

    with pytest.raises(PlanParseError, match="비어"):
        _extract_hwp(
            tmp_path / "plan.hwp",
            runner=lambda *args, **kwargs: result,
        )


def test_hwp_reader_uses_html_fallback_for_table_markers(tmp_path):
    html = """
    <html><body>
      <table>
        <tr><td>과 목</td><td>단 원 명</td><td>학 습 내 용</td><td>쪽수</td><td>차시</td></tr>
        <tr><td>국 어</td><td>독서 단원</td><td>책을 읽어요</td><td>8-9</td><td>1/1</td></tr>
      </table>
      <table>
        <tr><td>2반</td><td>월</td><td>화</td><td>수</td><td>목</td><td>금</td></tr>
        <tr><td>1</td><td>국</td><td>수</td><td>국</td><td>과</td><td>국</td></tr>
      </table>
    </body></html>
    """

    def runner(args, **kwargs):
        if args[0] == "hwp5txt":
            return CompletedProcess(args, 0, stdout="<표>".encode(), stderr=b"")
        output_dir = Path(args[2])
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "index.xhtml").write_text(html, encoding="utf-8")
        return CompletedProcess(args, 0, stdout=b"", stderr=b"")

    text = _extract_hwp(tmp_path / "plan.hwp", runner=runner)

    assert "CONTENT | 국어 | 독서 단원 | 책을 읽어요 | 8-9 | 1/1" in text
    assert "TIMETABLE | 2 | 월 | 1 | 국" in text


def test_hwp_html_subject_abbreviations_match_content_subjects(tmp_path):
    html = """
    <html><body>
      <table>
        <tr><td>과 목</td><td>단 원 명</td><td>학 습 내 용</td><td>쪽수</td><td>차시</td></tr>
        <tr><td>과 학</td><td>기체의 성질</td><td>기체의 부피를 관찰해요</td><td>10-11</td><td>1/1</td></tr>
      </table>
      <table>
        <tr><td>2반</td><td>월</td><td>화</td><td>수</td><td>목</td><td>금</td></tr>
        <tr><td>1</td><td>국</td><td>수</td><td>국</td><td>과</td><td>국</td></tr>
      </table>
    </body></html>
    """

    def runner(args, **kwargs):
        if args[0] == "hwp5txt":
            return CompletedProcess(args, 0, stdout="<표>".encode(), stderr=b"")
        output_dir = Path(args[2])
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "index.xhtml").write_text(html, encoding="utf-8")
        return CompletedProcess(args, 0, stdout=b"", stderr=b"")

    text = _extract_hwp(tmp_path / "plan.hwp", runner=runner)
    lessons = parse_lessons(text, target_date=__import__("datetime").date(2026, 8, 20), class_number=2)

    assert lessons[0].subject == "과학"
    assert lessons[0].topic == "기체의 부피를 관찰해요"
