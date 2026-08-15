from lesson_agent.config import Settings


def test_plan_source_defaults_to_local(monkeypatch):
    monkeypatch.delenv("LESSON_AGENT_PLAN_SOURCE", raising=False)
    settings = Settings(_env_file=None)
    assert settings.plan_source == "local"


def test_settings_accept_non_default_class():
    settings = Settings(_env_file=None, grade=5, class_number=3)
    assert (settings.grade, settings.class_number) == (5, 3)
