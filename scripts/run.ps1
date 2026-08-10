[CmdletBinding()]
param(
    [datetime]$Date,
    [switch]$DryRun,
    [switch]$TestKakao,
    [switch]$SetupKakao
)

$ErrorActionPreference = 'Stop'
$LocalRoot = Join-Path $env:LOCALAPPDATA 'LessonAgent'
$ConfigRoot = Join-Path $LocalRoot 'config'
$VenvPython = Join-Path $LocalRoot 'venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $VenvPython -PathType Leaf)) { throw 'Run scripts\setup.ps1 first.' }
if (-not (Test-Path -LiteralPath (Join-Path $ConfigRoot '.env') -PathType Leaf)) { throw 'Configuration not found. Run scripts\setup.ps1 first.' }

$arguments = @('-m', 'lesson_agent.cli')
if ($TestKakao) {
    $arguments += 'test-kakao'
} elseif ($SetupKakao) {
    $arguments += 'setup-kakao'
} else {
    $arguments += 'run'
    if ($Date) { $arguments += @('--date', $Date.ToString('yyyy-MM-dd')) }
    if ($DryRun) { $arguments += '--dry-run' }
}

Push-Location $ConfigRoot
try { & $VenvPython @arguments; exit $LASTEXITCODE }
finally { Pop-Location }
