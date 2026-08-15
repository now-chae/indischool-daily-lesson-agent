from pathlib import Path


def test_public_skill_has_no_fixed_class_instruction():
    skill_path = Path(__file__).parents[2] / "skills" / "indischool-daily-lesson-agent" / "SKILL.md"
    text = skill_path.read_text(encoding="utf-8")

    assert "2반의 해당 요일" not in text
    assert "설정한 학년·반" in text


def test_public_runtime_does_not_include_homepage_client():
    root = Path(__file__).parents[1]
    school = (root / "src" / "lesson_agent" / "school.py").read_text(encoding="utf-8")
    config = (root / "src" / "lesson_agent" / "config.py").read_text(encoding="utf-8")

    assert "class SchoolClient" not in school
    assert "school_base_url" not in config
