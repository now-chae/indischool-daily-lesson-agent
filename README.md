# 🤖 인디스쿨 오늘 수업자료 에이전트

매일 아침 **주간학습안내를 읽고**, 오늘 수업에 맞는 인디스쿨 자료를 찾아 **카카오톡 `나와의 채팅`으로 보내는** 교사용 AI 보조 도구입니다.

> 처음 설치하는 분은 이 페이지의 명령을 위에서부터 한 줄씩 실행하면 됩니다. 전체 설명은 [📘 초보자용 설치 안내](docs/초보자용-설치안내.md)를 참고하세요.

## 🌟 이 프로그램이 하는 일

1. 학교 홈페이지의 주간학습안내에서 오늘 날짜와 6학년 2반 시간표를 확인합니다.
2. 체육·영어를 제외한 수업의 학습 주제를 읽습니다.
3. 과목별 규칙에 맞는 핵심 검색어를 만듭니다.
4. 인디스쿨 6학년 게시판에서 관련 자료를 찾고 제목·링크·한 줄 요약을 정리합니다.
5. 정리한 내용을 카카오톡 `나와의 채팅`으로 보냅니다.

📌 인디스쿨 파일을 복제하거나 재배포하지 않습니다. 게시글 링크와 짧은 요약만 제공합니다.

## 🧰 준비물

- Windows 10 또는 11
- Python 3.11 이상
- Google Chrome
- 인디스쿨 계정
- 카카오톡 계정
- Kakao Developers REST API 키

OpenAI API 키는 **학교 홈페이지의 주간안내 이미지를 자동으로 읽을 때만 선택적으로 필요**합니다.

## 🚀 5단계 설치

### 1️⃣ ZIP 받기

GitHub 화면 오른쪽 위 **Code → Download ZIP**을 누릅니다. ZIP은 OneDrive가 아닌 `C:\LessonAgent` 같은 폴더에 풀어 주세요.

PowerShell을 열고 압축을 푼 폴더로 이동합니다.

```powershell
cd C:\LessonAgent\indischool-daily-lesson-agent
Set-ExecutionPolicy -Scope Process Bypass
```

### 2️⃣ 프로그램 설치

```powershell
.\scripts\setup.ps1 -RegisterStartupSession
```

질문이 나오면 학교 홈페이지 주소, 학년 `6`, 반 `2`, Kakao REST API 키를 입력합니다. OpenAI 키가 없으면 그냥 Enter를 눌러도 됩니다.

🔒 로그인 쿠키·토큰·실행 상태는 OneDrive 밖의 `%LOCALAPPDATA%\LessonAgent`에 저장됩니다.

### 3️⃣ 인디스쿨 로그인

```powershell
.\scripts\start-indischool-session.cmd
```

새로 열린 전용 Chrome에서 인디스쿨에 직접 로그인합니다. 로그인한 창은 닫지 말고 최소화해 두세요. 처음 한 번 로그인하면 이후에는 저장된 세션을 사용합니다.

### 4️⃣ 카카오 연결

Kakao Developers에서 앱을 만든 뒤 로그인 리디렉션 URI에 다음 주소를 등록합니다.

```text
http://localhost:8765/callback
```

그다음 실행합니다.

```powershell
.\scripts\run.ps1 -SetupKakao
```

브라우저에서 카카오 로그인을 승인하고, 주소창의 `code=` 뒤 값을 PowerShell에 붙여넣습니다. 연결 확인은 다음 명령으로 합니다.

```powershell
.\scripts\run.ps1 -TestKakao
```

카카오톡 `나와의 채팅`에 시험 메시지가 오면 성공입니다. 🎉

### 5️⃣ 매일 오전 8시 40분 예약

```powershell
.\scripts\install-task.ps1
```

이제 Windows 작업 스케줄러가 매일 오전 8시 40분에 실행합니다.

## 🧪 먼저 시험해 보기

실제 카카오 발송 없이 시간표와 검색어만 확인하려면:

```powershell
.\scripts\run.ps1 -Date 2026-06-26 -DryRun
```

실제 발송은 다음처럼 실행합니다.

```powershell
.\scripts\run.ps1 -Date 2026-06-26
```

## ⚠️ 꼭 알아둘 점

- PC 전원이 켜져 있고 Windows 사용자가 로그인되어 있어야 합니다.
- 인터넷 연결과 인디스쿨 전용 Chrome 세션이 필요합니다.
- 인디스쿨 운영진의 자동화 허가 범위를 먼저 확인해야 합니다.
- 허가 전에는 사용자가 직접 찾은 링크를 정리하는 보조 모드로 사용하세요.
- 계정 비밀번호·쿠키·API 토큰을 GitHub에 올리지 마세요.

## 🆘 문제가 생기면

| 증상 | 해결 방법 |
|---|---|
| `session_browser_missing` | `.\scripts\start-indischool-session.cmd` 실행 |
| 인디스쿨 로그인 필요 | 전용 Chrome에서 다시 로그인 |
| 카카오 재인증 필요 | `.\scripts\run.ps1 -SetupKakao` 재실행 |
| 오늘 자료가 오지 않음 | `.\scripts\run.ps1 -DryRun`으로 오류 확인 |

예약을 중지하려면 다음을 실행합니다.

```powershell
.\scripts\remove-task.ps1
```

📘 [초보자용 전체 설치·문제 해결 안내](docs/초보자용-설치안내.md)
