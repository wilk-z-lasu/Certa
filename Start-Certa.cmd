@echo off
setlocal
cd /d "%~dp0" || exit /b 1
set "CERTA_CLOUD_ONLY=0"
set "CERTA_PROVIDER=openai"
set "CERTA_API_REQUESTS_PAUSED=1"
set "CERTA_NARRATION=offline"
set "CERTA_OVERVIEW_DB=%CD%\output\event-overviews.sqlite3"
set "certa_python="
set "certa_python_args="
if exist ".venv\Scripts\python.exe" call :try_python ".venv\Scripts\python.exe"
if not defined certa_python where py.exe >nul 2>nul && call :try_python py.exe -3
if not defined certa_python for /d %%D in ("%ProgramFiles%\WindowsApps\OpenAI.CodexPrimaryRuntime*") do if exist "%%~fD\dependencies\python\python.exe" call :try_python "%%~fD\dependencies\python\python.exe"
if not defined certa_python where python.exe >nul 2>nul && call :try_python python.exe
if not defined certa_python (
    echo Install Python 3.10 or newer, then start Certa again.
    pause
    exit /b 1
)
if not exist "%CERTA_OVERVIEW_DB%" (
    "%certa_python%" %certa_python_args% -B -m certa.daily --offline --date 2026-11-19
    if errorlevel 1 goto failed
)
"%certa_python%" %certa_python_args% -B app.py --port 50488
if errorlevel 1 goto failed
exit /b 0

:try_python
if defined certa_python exit /b 0
"%~1" %2 -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>nul
if errorlevel 1 exit /b 1
set "certa_python=%~1"
set "certa_python_args=%2"
exit /b 0

:failed
echo If Certa is already running, open http://127.0.0.1:50488/ in your browser.
pause
exit /b 1
