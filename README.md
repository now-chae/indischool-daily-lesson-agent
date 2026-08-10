# 인디스쿨 오늘 수업자료 에이전트

이 패키지는 Codex Skill과 로컬 Python 실행기를 함께 제공한다. 설치 시 인증정보와 브라우저 프로필은 패키지에 포함되지 않고 사용자 PC에 새로 생성된다.

처음 설치하는 분은 [초보자용 설치 안내](docs/초보자용-설치안내.md)를 먼저 읽는다.

## 설치

PowerShell에서 패키지 폴더로 이동한 뒤 실행한다.

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\setup.ps1 -RegisterStartupSession
```

설치 후 전용 Chrome에서 인디스쿨 로그인을 완료하고, Kakao Developers REST API 키를 입력해 `run.ps1 -SetupKakao`를 실행한다. 연결 시험은 `run.ps1 -TestKakao`로 수행한다.

자동 발송을 등록하려면 다음을 실행한다.

```powershell
.\scripts\install-task.ps1
```

예약 작업은 매일 오전 8시 40분에 실행된다. 첫 배포 전에는 인디스쿨 운영진의 허가 범위와 robots.txt 정책을 확인한다.

예약을 해제하려면 `scripts\remove-task.ps1`을 실행한다.
