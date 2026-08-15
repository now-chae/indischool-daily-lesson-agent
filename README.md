# 🤖 오늘 수업자료를 찾아주는 인디스쿨 에이전트

이 저장소는 **완성된 에이전트를 내려받아 설정하고 사용하는 사람**을 위한 패키지입니다. 직접 같은 에이전트를 처음부터 만들어 보려면 [📗 초보자용 제작 원고](docs/초보자용-제작원고.md)를 읽으세요. 제작 원고는 설치 안내를 대신하지 않습니다.

매일 아침 이 프로그램이 다음 일을 대신합니다.

1. 주간학습안내에서 오늘 수업을 확인합니다.
2. 인디스쿨에서 과목·학년·학습내용에 맞는 자료를 찾습니다.
3. 제목, 링크, 핵심요약 한 줄을 카카오톡 **나와의 채팅**으로 보냅니다.

> 바로 사용하려는 분은 아래 설치 순서와 [📘 초보자용 설치 안내](docs/초보자용-설치안내.md)를 따라 하세요. 여기서는 완성 코드의 설치·설정·실행만 설명합니다.

## 🧰 준비물

- Windows 10 또는 11 컴퓨터
- Python 3.11 이상
- Google Chrome
- 인디스쿨 계정
- 카카오 계정과 Kakao Developers REST API 키

주간학습안내가 **이미지**일 때만 OpenAI API 키가 필요합니다. HWPX는 표의 행·열을 보존해 판독하고, 구형 HWP는 설치 과정에서 `pyhwp`(`hwp5txt`·`hwp5html`)를 함께 설치합니다. 키가 있으면 이미지 보조 판독과 자료 요약을 사용할 수 있습니다.

## 🚀 설치 순서

### 🔐 설정 파일은 설치할 때 한 번에 만듭니다

이 프로젝트는 처음부터 `.env.example`, `.gitignore`, `config.py`, `setup.ps1`를 함께 사용합니다. 사용자는 `.env` 파일을 직접 만들거나 GitHub에 올릴 필요가 없습니다.

- `.env.example`: 어떤 설정이 필요한지 보여 주는 빈 예시
- `setup.ps1`: 주안 폴더, 학년·반, API 키를 질문해 사용자 PC의 `%LOCALAPPDATA%\LessonAgent\config\.env`에 저장
- `.env`: 실제 값이 들어 있는 비공개 파일. 프로젝트 폴더와 OneDrive 밖에 저장
- `.gitignore`: `.env`가 GitHub에 올라가지 않도록 차단

카카오 access token과 refresh token은 `.env`에 저장하지 않고 Windows 자격 증명 저장소에 보관합니다. 따라서 설치자는 설정 파일을 직접 편집하지 않고 `setup.ps1`, `run.ps1 -SetupKakao`만 실행하면 됩니다.

### 1️⃣ ZIP 내려받기

GitHub 화면에서 **Code → Download ZIP**을 누릅니다. ZIP은 OneDrive 폴더가 아닌 `C:\LessonAgent`에 풀어 주세요.

PowerShell을 열고 다음을 실행합니다.

```powershell
cd C:\LessonAgent\indischool-daily-lesson-agent
Set-ExecutionPolicy -Scope Process Bypass
```

### 2️⃣ 프로그램 설치하기

```powershell
.\scripts\setup.ps1 -RegisterStartupSession
```

질문이 나오면 다음 순서로 답합니다.

- 주간안내 파일을 넣어 둘 로컬 폴더 (Enter를 누르면 기본 폴더)
- 담당 학년과 반
- 제외할 전담 과목 (예: `체육,영어`)
- Kakao REST API 키
- OpenAI API 키 (이미지 판독을 할 때만)

### 3️⃣ 주간안내 파일 넣기

공개 패키지는 학교 홈페이지를 자동 탐색하지 않고, 로컬 폴더의 주간안내 파일을 사용합니다. 기본 폴더는 다음과 같습니다.

```text
%LOCALAPPDATA%\LessonAgent\plans
```

파일을 삭제하지 말고 계속 추가해 두세요. 파일명에는 반드시 날짜를 넣습니다.

```text
2026-08-17_주간학습안내.hwpx
2026-08-24_2026-08-28_주간학습안내.hwp
6학년_주간학습안내_8월18일 - 8월21일(1주).hwp
```

날짜가 두 개면 그 날짜 사이의 주간으로 인식합니다. 연도가 파일명에 없으면 실행하는 해의 날짜로 해석합니다. 같은 날짜 파일이 여러 개면 가장 최근에 수정한 파일을 사용합니다. 날짜가 없는 `current.hwpx` 같은 파일은 안전을 위해 사용하지 않습니다.

### 4️⃣ 인디스쿨 로그인하기

```powershell
.\scripts\start-indischool-session.cmd
```

새로 열린 전용 Chrome에서 인디스쿨에 로그인합니다. 로그인 후 창을 닫지 말고 최소화하세요. 이 Chrome 프로필은 OneDrive 밖에 저장됩니다.

### 5️⃣ 카카오 연결하기

Kakao Developers에서 앱을 만든 뒤 로그인 리디렉션 URI에 다음 주소를 등록합니다.

```text
http://localhost:8765/callback
```

그다음 실행합니다.

```powershell
.\scripts\run.ps1 -SetupKakao
```

브라우저에서 카카오 로그인을 승인하고, 주소창의 `code=` 뒤 값을 PowerShell에 붙여넣습니다. 시험 메시지를 보냅니다.

```powershell
.\scripts\run.ps1 -TestKakao
```

카카오톡 **나와의 채팅**에 메시지가 오면 연결 완료입니다. 🎉

### 6️⃣ 먼저 시험하고 매일 자동 실행하기

카카오로 보내지 않고 결과만 확인합니다.

```powershell
.\scripts\run.ps1 -Date 2026-06-26 -DryRun
```

결과가 맞으면 실제 발송을 한 번 시험합니다.

```powershell
.\scripts\run.ps1 -Date 2026-06-26
```

이상이 없으면 Codex 앱의 **예약 메뉴**에서 매일 오전 8시 40분 실행을 등록합니다. 예약 지시문에는 이 저장소의 실행 파일과 주안 확인·인디스쿨 검색·카카오 발송 순서를 적어 주세요. 이 프로젝트의 기본 사용 흐름은 Windows 작업 스케줄러가 아니라 Codex 예약입니다.

## 📩 카카오 메시지 형식

```text
📚 과목: 수학
🔎 검색어: 소수의 나눗셈
📝 제목: 게시글 제목
🔗 링크: https://indischool.com/boards/...
💡 핵심요약: 자료의 핵심을 한 문장으로 정리
⚠ 확인사항: 자료가 부족하거나 판독이 불확실할 때만 표시
```

## ⚠️ 꼭 알아둘 점

- Codex 예약 실행 환경에서 로컬 주안 폴더와 전용 Chrome 세션에 접근할 수 있어야 합니다.
- 인터넷과 인디스쿨 전용 Chrome 세션이 필요합니다.
- 인디스쿨 운영진의 자동화 허가 범위를 먼저 확인하세요.
- 자료 파일 자체를 복제·재배포하지 않고 게시글 링크와 짧은 요약만 보냅니다.
- 비밀번호, 쿠키, API 키는 GitHub에 올리지 않습니다.
- OneDrive에는 Chrome 프로필·토큰·실행 상태를 저장하지 않습니다.

## 🆘 문제가 생기면

| 증상 | 해결 방법 |
|---|---|
| `session_browser_missing` | `start-indischool-session.cmd` 실행 후 전용 Chrome 로그인 |
| 인디스쿨 로그인 필요 | 전용 Chrome에서 다시 로그인 |
| 카카오 재인증 필요 | `run.ps1 -SetupKakao` 다시 실행 |
| 로컬파일을 찾지 못함 | 파일명에 `YYYY-MM-DD`가 있는지, `plans` 폴더에 있는지 확인 |
| 오늘 자료가 오지 않음 | `run.ps1 -Date YYYY-MM-DD -DryRun`으로 오류 확인 |

예약 발송을 중지하려면 Codex 앱의 예약 메뉴에서 해당 예약을 해제합니다. 파일과 로그인 설정은 삭제하지 않습니다.
