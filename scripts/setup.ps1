[CmdletBinding()]
param(
    [switch]$RegisterScheduledTask,
    [switch]$RegisterStartupSession,
    [switch]$ConfigureIndischool
)

$ErrorActionPreference = 'Stop'
$PackageRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$RuntimeRoot = Join-Path $PackageRoot 'runtime'
$LocalRoot = Join-Path $env:LOCALAPPDATA 'LessonAgent'
$ConfigRoot = Join-Path $LocalRoot 'config'
$VenvRoot = Join-Path $LocalRoot 'venv'
$ProfileRoot = Join-Path $LocalRoot 'indischool-profile'
$StateRoot = Join-Path $LocalRoot 'state'
$DownloadRoot = Join-Path $LocalRoot 'downloads'

if (-not (Test-Path -LiteralPath (Join-Path $RuntimeRoot 'pyproject.toml') -PathType Leaf)) {
    throw "runtime\pyproject.toml not found. Run scripts\build-agent-package.ps1 first."
}
if ($LocalRoot -match '(?i)\\OneDrive(?: - [^\\]+)?\\') {
    throw "Refusing to use OneDrive for runtime data: $LocalRoot"
}

foreach ($path in @($LocalRoot, $ConfigRoot, $ProfileRoot, $StateRoot, $DownloadRoot)) {
    New-Item -ItemType Directory -Force -Path $path | Out-Null
}

$pythonCommand = Get-Command python -ErrorAction SilentlyContinue
if (-not $pythonCommand) { $pythonCommand = Get-Command py -ErrorAction SilentlyContinue }
if (-not $pythonCommand) { throw 'Python 3.11 or newer is required. Install Python and run setup again.' }

if (-not (Test-Path -LiteralPath (Join-Path $VenvRoot 'Scripts\python.exe') -PathType Leaf)) {
    & $pythonCommand.Source -m venv $VenvRoot
}
$VenvPython = Join-Path $VenvRoot 'Scripts\python.exe'
& $VenvPython -m pip install --upgrade pip
& $VenvPython -m pip install $RuntimeRoot
& $VenvPython -m playwright install chromium

$EnvPath = Join-Path $ConfigRoot '.env'
if (-not (Test-Path -LiteralPath $EnvPath -PathType Leaf)) {
    $schoolUrl = Read-Host '학교 홈페이지 주소 (근무 학교의 주간학습안내 주소)'
    if ([string]::IsNullOrWhiteSpace($schoolUrl)) { throw '학교 홈페이지 주소는 필수입니다.' }
    $grade = Read-Host '담당 학년 (예: 6)'
    if ([string]::IsNullOrWhiteSpace($grade)) { throw '담당 학년은 필수입니다.' }
    $classNumber = Read-Host '담당 반 (예: 2)'
    if ([string]::IsNullOrWhiteSpace($classNumber)) { throw '담당 반은 필수입니다.' }
    $excludedSubjects = Read-Host '제외할 전담 과목 (쉼표로 구분, 예: 체육,영어)'
    if ([string]::IsNullOrWhiteSpace($excludedSubjects)) { $excludedSubjects = '체육,영어' }
    $kakaoKey = Read-Host 'Kakao REST API 키 (없으면 Enter)'
    $openAiKey = Read-Host 'OpenAI API 키 (이미지 자동 판독이 필요할 때만, 없으면 Enter)'
    $lines = @(
        "LESSON_AGENT_SCHOOL_BASE_URL=$schoolUrl",
        "LESSON_AGENT_GRADE=$grade",
        "LESSON_AGENT_CLASS_NUMBER=$classNumber",
        "LESSON_AGENT_EXCLUDED_SUBJECTS=$excludedSubjects",
        'LESSON_AGENT_TIMEZONE=Asia/Seoul',
        'LESSON_AGENT_MAX_RESULTS=5',
        'LESSON_AGENT_KAKAO_REDIRECT_URI=http://localhost:8765/callback',
        "LESSON_AGENT_INDISCHOOL_PROFILE_PATH=$ProfileRoot",
        "LESSON_AGENT_STATE_PATH=$StateRoot",
        "LESSON_AGENT_DOWNLOAD_PATH=$DownloadRoot"
    )
    if (-not [string]::IsNullOrWhiteSpace($kakaoKey)) { $lines += "LESSON_AGENT_KAKAO_REST_API_KEY=$kakaoKey" }
    if (-not [string]::IsNullOrWhiteSpace($openAiKey)) { $lines += "LESSON_AGENT_OPENAI_API_KEY=$openAiKey" }
    Set-Content -LiteralPath $EnvPath -Value $lines -Encoding utf8
    Write-Host "Created local configuration: $EnvPath"
}

if ($RegisterStartupSession) {
    $startupRoot = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\Startup'
    New-Item -ItemType Directory -Force -Path $startupRoot | Out-Null
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'start-indischool-session.cmd') -Destination (Join-Path $startupRoot 'LessonAgent-Indischool.cmd') -Force
    Write-Host 'Registered the local Indischool session launcher at Windows logon.'
}

if ($ConfigureIndischool) {
    Push-Location $ConfigRoot
    try { & $VenvPython -m lesson_agent.cli setup-indischool }
    finally { Pop-Location }
}

if ($RegisterScheduledTask) {
    & (Join-Path $PSScriptRoot 'install-task.ps1') -PythonExe $VenvPython -ConfigDir $ConfigRoot
}

Write-Host ''
Write-Host 'Installation complete.'
Write-Host "Configuration: $EnvPath"
Write-Host "Runtime data: $LocalRoot"
Write-Host 'Next: run setup.ps1 -ConfigureIndischool, then run run.ps1 -TestKakao.'
