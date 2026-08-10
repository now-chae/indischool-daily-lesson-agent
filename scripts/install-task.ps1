[CmdletBinding(SupportsShouldProcess)]
param(
    [string]$PythonExe = (Join-Path $env:LOCALAPPDATA 'LessonAgent\venv\Scripts\python.exe'),
    [string]$ConfigDir = (Join-Path $env:LOCALAPPDATA 'LessonAgent\config')
)

$ErrorActionPreference = 'Stop'
$TaskName = 'IndischoolDailyLessonAgent'
$ResolvedPython = (Resolve-Path -LiteralPath $PythonExe).Path
$ResolvedConfig = (Resolve-Path -LiteralPath $ConfigDir).Path

if (-not (Test-Path -LiteralPath $ResolvedPython -PathType Leaf)) { throw "Python executable not found: $ResolvedPython" }
if (-not (Test-Path -LiteralPath (Join-Path $ResolvedConfig '.env') -PathType Leaf)) { throw "Configuration not found: $ResolvedConfig\.env" }

$Action = New-ScheduledTaskAction -Execute $ResolvedPython -Argument '-m lesson_agent.cli run' -WorkingDirectory $ResolvedConfig
$Trigger = New-ScheduledTaskTrigger -Daily -At '08:40'
$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 20)
$Principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
$Task = New-ScheduledTask -Action $Action -Trigger $Trigger -Settings $Settings -Principal $Principal

if ($PSCmdlet.ShouldProcess($TaskName, 'Register daily 08:40 lesson agent task')) {
    Register-ScheduledTask -TaskName $TaskName -InputObject $Task -Force | Out-Null
    Write-Host "Registered $TaskName for 08:40 daily."
}
