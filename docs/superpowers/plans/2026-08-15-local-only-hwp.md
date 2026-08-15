# 로컬 주안 기본화 및 HWP/HWPX 판독 보강 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 공개 패키지를 로컬 주안 파일 전용으로 단순화하고 HWP/HWPX 판독·설정 일반화·테스트를 보강한다.

**Architecture:** 공개 runtime은 `LocalPlanClient`와 형식별 주안 어댑터만 사용한다. HWPX는 XML 표 셀을 보존하고, HWP는 `hwp5txt` 어댑터를 사용한다. 기존 홈페이지 수집 코드는 GitHub runtime에서 제거하되 로컬 백업과 packaging 소스에 보존한다.

**Tech Stack:** Python 3.11+, pytest, lxml, pydantic-settings, PowerShell setup scripts, HWPX XML, optional `hwp5txt`.

## Global Constraints

- 실제 학교 HWP 파일은 GitHub에 커밋하지 않는다.
- 공개 기본 입력은 `LESSON_AGENT_PLAN_SOURCE=local`이다.
- 공개 runtime에는 학교 홈페이지 URL 수집 코드를 포함하지 않는다.
- 학년·반·제외 과목은 설정값으로만 결정한다.
- 판독이 불확실하면 추측하지 않고 `PlanParseError` 또는 과목별 확인 필요로 처리한다.
- 각 구현 단계는 실패 테스트를 먼저 작성하고 실행한 뒤 최소 구현을 추가한다.

### Task 1: 공개 패키지를 local 전용으로 전환

**Files:**
- Modify: `runtime/src/lesson_agent/config.py`
- Modify: `runtime/src/lesson_agent/cli.py`
- Modify: `runtime/src/lesson_agent/app.py`
- Modify: `runtime/src/lesson_agent/school.py`
- Modify: `scripts/setup.ps1`
- Modify: `.env.example`
- Test: `tests/test_local_defaults.py`

**Interfaces:**
- `Settings.plan_source`는 `Literal["local"]`이며 기본값은 `local`이다.
- `LocalPlanClient.find_plan_for(date) -> WeeklyPlanPost | None`와 `download(post, destination) -> Path`는 유지한다.
- 공개 `_build_agent`는 항상 `LocalPlanClient(settings.local_plan_dir)`를 사용한다.

- [ ] **Step 1: Write the failing tests**

```python
def test_plan_source_defaults_to_local(monkeypatch):
    monkeypatch.delenv("LESSON_AGENT_PLAN_SOURCE", raising=False)
    settings = Settings(_env_file=None)
    assert settings.plan_source == "local"

def test_settings_accept_non_default_class(monkeypatch):
    settings = Settings(_env_file=None, grade=5, class_number=3)
    assert (settings.grade, settings.class_number) == (5, 3)
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `python -m pytest tests/test_local_defaults.py -q`

Expected: the default plan source is `web` or the test cannot import the test module before implementation.

- [ ] **Step 3: Implement the minimum change**

Set the public settings default and example to `local`, remove public `SchoolClient` selection from `_build_agent`, and make setup ask only for the local plan directory. Keep the existing web-capable source under `packaging` and copy it to `local-only/indischool-web-mode-backup` without adding that backup to the public repository.

- [ ] **Step 4: Run the tests and verify they pass**

Run: `python -m pytest tests/test_local_defaults.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```text
git add runtime scripts .env.example tests/test_local_defaults.py
git commit -m "Make local weekly plans the public default"
```

### Task 2: Preserve HWPX table rows and cells

**Files:**
- Modify: `runtime/src/lesson_agent/weekly_plan.py`
- Test: `tests/test_hwpx_tables.py`
- Create: `tests/fixtures/minimal_weekly_plan.hwpx`

**Interfaces:**
- `_extract_hwpx(path: Path) -> str` returns newline-separated table records without losing cell order.
- New helper `_extract_hwpx_table_rows(path: Path) -> list[list[str]]` returns rows of normalized cell text.

- [ ] **Step 1: Write the failing tests**

```python
def test_hwpx_table_keeps_row_and_column_order(tmp_path):
    path = tmp_path / "minimal.hwpx"
    path.write_bytes(MINIMAL_HWPX_BYTES)
    text = _extract_hwpx(path)
    assert "TABLE | 0 | 0 | 요일" in text
    assert "TABLE | 1 | 1 | 국어" in text
    assert text.index("TABLE | 1 | 1 | 국어") < text.index("TABLE | 1 | 2 | 수학")

def test_hwpx_empty_table_is_unreadable(tmp_path):
    path = tmp_path / "empty.hwpx"
    path.write_bytes(EMPTY_HWPX_BYTES)
    with pytest.raises(PlanParseError, match="표"):
        _extract_hwpx(path)
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `python -m pytest tests/test_hwpx_tables.py -q`

Expected: current paragraph-only extraction does not emit `TABLE` records.

- [ ] **Step 3: Implement the minimum change**

Parse `hp:tbl`, `hp:tr`, and `hp:tc` elements using namespace-agnostic XPath. For each cell, join its text nodes with spaces, normalize whitespace, emit `TABLE | row | column | text`, and retain non-table paragraphs as `PARAGRAPH | text`. Raise `PlanParseError("table_unreadable", ...)` when no meaningful table or paragraph text exists.

- [ ] **Step 4: Run the tests and verify they pass**

Run: `python -m pytest tests/test_hwpx_tables.py -q`

Expected: all HWPX table tests pass.

- [ ] **Step 5: Commit**

```text
git add runtime/src/lesson_agent/weekly_plan.py tests/test_hwpx_tables.py tests/fixtures/minimal_weekly_plan.hwpx
git commit -m "Preserve HWPX weekly-plan table structure"
```

### Task 3: Strengthen HWP extraction and errors

**Files:**
- Modify: `runtime/src/lesson_agent/weekly_plan.py`
- Modify: `runtime/pyproject.toml`
- Modify: `scripts/setup.ps1`
- Test: `tests/test_hwp_reader.py`

**Interfaces:**
- `_extract_hwp(path: Path, runner: Callable[..., CompletedProcess] | None = None) -> str` supports dependency injection for tests.
- Missing executable raises `PlanParseError("hwp_reader_missing", ...)` with the exact setup remedy.

- [ ] **Step 1: Write the failing tests**

```python
def test_hwp_reader_missing_has_actionable_error(monkeypatch, tmp_path):
    monkeypatch.setattr("lesson_agent.weekly_plan.shutil.which", lambda name: None)
    with pytest.raises(PlanParseError) as error:
        _extract_hwp(tmp_path / "plan.hwp")
    assert error.value.code == "hwp_reader_missing"
    assert "hwp5txt" in str(error.value)

def test_hwp_reader_rejects_empty_output(tmp_path):
    result = CompletedProcess(["hwp5txt"], 0, stdout=b"", stderr=b"")
    with pytest.raises(PlanParseError, match="비어"):
        _extract_hwp(tmp_path / "plan.hwp", runner=lambda *args, **kwargs: result)
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `python -m pytest tests/test_hwp_reader.py -q`

Expected: current code reports generic `unsupported` and does not distinguish empty output.

- [ ] **Step 3: Implement the minimum change**

Check `shutil.which("hwp5txt")`, run it without `shell=True`, decode UTF-8 and CP949 fallbacks, and raise separate actionable errors for missing executable, non-zero conversion, and empty output. Document the dependency in `pyproject.toml`/setup output without silently claiming HWP is always available.

- [ ] **Step 4: Run the tests and verify they pass**

Run: `python -m pytest tests/test_hwp_reader.py -q`

Expected: all HWP reader tests pass.

- [ ] **Step 5: Run the local attachment smoke test**

Run the preview command against a local HWP file whose filename contains an 8월 18일–8월 21일 range. Do not copy the file into Git or the public package.

- [ ] **Step 6: Commit**

```text
git add runtime scripts tests/test_hwp_reader.py
git commit -m "Improve HWP reader diagnostics"
```

### Task 4: Remove hardcoded class language and align docs

**Files:**
- Modify: `skills/indischool-daily-lesson-agent/SKILL.md`
- Modify: `README.md`
- Modify: `docs/초보자용-설치안내.md`
- Modify: `docs/초보자용-제작원고.md`
- Test: `tests/test_no_hardcoded_class.py`

**Interfaces:**
- Public documentation describes local files as the default and does not promise universal school-homepage scraping.
- Skill language uses “설정한 학년·반” rather than “2반”.

- [ ] **Step 1: Write the failing test**

```python
def test_public_skill_has_no_fixed_class_instruction():
    text = Path("skills/indischool-daily-lesson-agent/SKILL.md").read_text(encoding="utf-8")
    assert "2반의 해당 요일" not in text
    assert "설정한 학년·반" in text
```

- [ ] **Step 2: Run the test and verify it fails**

Run: `python -m pytest tests/test_no_hardcoded_class.py -q`

Expected: current Skill contains “2반의 해당 요일”.

- [ ] **Step 3: Implement the minimum change**

Rewrite public docs to describe local input first, remove public homepage setup instructions, and state that the private web-mode copy is not part of the GitHub package. Keep Codex reservation as the scheduling path.

- [ ] **Step 4: Run the test and verify it passes**

Run: `python -m pytest tests/test_no_hardcoded_class.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```text
git add skills README.md docs tests/test_no_hardcoded_class.py
git commit -m "Document configurable class and local plan workflow"
```

### Task 5: Run the full verification suite and publish

**Files:**
- Modify: `packaging/indischool-daily-lesson-agent/` only if source synchronization is required
- Test: `tests/`

- [ ] **Step 1: Run the full test suite**

Run: `python -m pytest -q`

Expected: zero failures and no collection errors.

- [ ] **Step 2: Run static checks**

Run: `python -m compileall runtime/src`

Expected: exit code 0.

- [ ] **Step 3: Verify the public diff**

Run: `git diff --check` and search the public tree for `SchoolClient`, `LESSON_AGENT_SCHOOL_BASE_URL`, and user-provided HWP filenames. The public tree must not contain the web client or the attached HWP.

- [ ] **Step 4: Commit and push**

```text
git add .
git commit -m "Ship local-first HWP weekly-plan agent"
git push origin agent/local-plans-and-beginner-guide
```
