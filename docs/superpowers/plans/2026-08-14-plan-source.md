# 주간학습안내 입력 경로 확장 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans or superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** 홈페이지와 누적 로컬파일 폴더를 모두 지원하고, 초보자용 안내서와 제작 원고를 따라 하기식으로 다시 작성한다.

**Architecture:** `SchoolClient`와 나란히 `LocalPlanClient`를 두고, CLI가 설정에 따라 하나를 선택한다. 선택된 파일은 기존 파서·검증·검색·카카오 파이프라인으로 전달한다. 로컬 원본은 별도 작업 폴더에 복사하고 삭제하지 않는다.

**Tech Stack:** Python 3.11+, pydantic-settings, pathlib, pytest, PowerShell, Markdown.

## Global Constraints

- 로컬 파일명에는 `YYYY-MM-DD` 날짜가 있어야 한다.
- 지원 확장자는 `.hwp`, `.hwpx`, `.jpg`, `.jpeg`, `.png`, `.webp`다.
- 원본 파일은 삭제하지 않는다.
- 홈페이지·로컬 입력 뒤의 차시 판독 및 인디스쿨 검색 규칙은 동일하게 유지한다.
- 공개 패키지 문서에는 특정 학교·학년·반을 기본값으로 고정하지 않는다.

### Task 1: 설정과 로컬 파일 선택기

**Files:**
- Modify: `src/lesson_agent/config.py`
- Modify: `src/lesson_agent/school.py`
- Test: `tests/test_config.py`
- Test: `tests/test_school.py`

- [ ] `plan_source`와 `local_plan_dir` 설정을 추가한다.
- [ ] 날짜가 파일명에 포함된 후보만 선택하는 `LocalPlanClient.find_plan_for()`를 추가한다.
- [ ] 같은 날짜 후보가 여러 개면 최신 수정 파일을 선택한다.
- [ ] `download()`는 원본을 `download_path`로 복사한다.

### Task 2: CLI와 실행 경로 연결

**Files:**
- Modify: `src/lesson_agent/cli.py`
- Modify: `src/lesson_agent/app.py`
- Test: `tests/test_app.py`
- Test: `tests/test_cli.py`

- [ ] `plan_source=local`이면 `LocalPlanClient`를 사용한다.
- [ ] 로컬 방식의 미발견 메시지는 홈페이지 URL 대신 로컬 폴더를 표시한다.
- [ ] 카카오 테스트 링크는 홈페이지 방식과 로컬 방식 모두 유효한 웹 주소를 사용한다.

### Task 3: 설치 스크립트와 문서

**Files:**
- Modify: `packaging/indischool-daily-lesson-agent/scripts/setup.ps1`
- Modify: `packaging/indischool-daily-lesson-agent/README.md`
- Modify: `packaging/indischool-daily-lesson-agent/docs/초보자용-설치안내.md`
- Create: `packaging/indischool-daily-lesson-agent/docs/초보자용-제작원고.md`

- [ ] 설치 질문에 홈페이지/로컬파일 선택을 넣는다.
- [ ] 누적 파일명 규칙과 테스트 명령을 단계별로 설명한다.
- [ ] 제작 원고를 6단계로 다시 작성한다.

### Task 4: 패키지 동기화와 검증

**Files:**
- Sync: `dist/indischool-daily-lesson-agent/`

- [ ] 소스·문서·스크립트를 dist 패키지에 동기화한다.
- [ ] 전체 pytest, 플러그인 validator, school-neutral 검색을 실행한다.
- [ ] 공개 GitHub 저장소에 의도한 파일만 커밋·푸시한다.
