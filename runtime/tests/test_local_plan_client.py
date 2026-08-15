from datetime import date

from lesson_agent.school import LocalPlanClient


def test_local_plan_client_selects_korean_month_day_range(tmp_path):
    plan = tmp_path / "6학년_주간학습안내_8월18일 - 8월21일(1주).hwp"
    plan.write_bytes(b"sample")
    client = LocalPlanClient(tmp_path)

    selected = client.find_plan_for(date(2026, 8, 20))

    assert selected is not None
    assert selected.filename == plan.name


def test_local_plan_client_selects_iso_date_range(tmp_path):
    plan = tmp_path / "2026-08-18_2026-08-21_주간학습안내.hwp"
    plan.write_bytes(b"sample")
    client = LocalPlanClient(tmp_path)

    selected = client.find_plan_for(date(2026, 8, 20))

    assert selected is not None
    assert selected.filename == plan.name


def test_local_plan_client_ignores_date_less_file(tmp_path):
    (tmp_path / "current.hwpx").write_bytes(b"sample")

    assert LocalPlanClient(tmp_path).find_plan_for(date(2026, 8, 20)) is None
