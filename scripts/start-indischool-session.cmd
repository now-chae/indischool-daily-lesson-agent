@echo off
setlocal

powershell -NoProfile -Command "try { Invoke-WebRequest -UseBasicParsing http://127.0.0.1:9222/json/version -TimeoutSec 1 ^| Out-Null; exit 0 } catch { exit 1 }"
if not errorlevel 1 exit /b 0

set "PROFILE=%LOCALAPPDATA%\LessonAgent\indischool-profile"
echo "%PROFILE%" | findstr /I "\OneDrive" >nul
if not errorlevel 1 (
    echo Refusing to start: the Indischool profile must not be inside OneDrive.
    exit /b 1
)
if not exist "%PROFILE%" mkdir "%PROFILE%" >nul 2>&1
set "CHROME=%ProgramFiles%\Google\Chrome\Application\chrome.exe"
if not exist "%CHROME%" set "CHROME=%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"

if exist "%CHROME%" (
    start "Indischool Session" /min "%CHROME%" --remote-debugging-address=127.0.0.1 --remote-debugging-port=9222 --user-data-dir="%PROFILE%" https://indischool.com/
) else (
    start "Indischool Session" /min chrome.exe --remote-debugging-address=127.0.0.1 --remote-debugging-port=9222 --user-data-dir="%PROFILE%" https://indischool.com/
)
