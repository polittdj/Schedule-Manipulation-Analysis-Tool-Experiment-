@echo off
rem Schedule Forensics - one-click launcher (Windows 11).
rem Double-click to run, or run Install-Desktop-Shortcut.bat once to put it on your Desktop.
rem First run sets up the environment; later runs just start the tool.
setlocal enableextensions

rem -- Optional config (edit if you like) --
if not defined SF_PORT set SF_PORT=5000
rem To use a LOCAL Qwen-class model for polished summaries, start your local
rem OpenAI-compatible server (llama.cpp / LM Studio / vLLM) first, then uncomment:
rem set SF_LLM_BASE_URL=http://127.0.0.1:8080/v1
rem set SF_LLM_MODEL=qwen

rem -- Go to the repo root (this script lives in <repo>\launch) --
cd /d "%~dp0.."

rem -- Find Python: prefer the official "py" launcher, fall back to "python" --
set "PYLAUNCH="
py -3 --version >nul 2>&1 && set "PYLAUNCH=py -3"
if not defined PYLAUNCH ( python --version >nul 2>&1 && set "PYLAUNCH=python" )
if not defined PYLAUNCH goto :nopython

rem -- First-run setup: virtual environment + install --
if not exist ".venv\Scripts\python.exe" (
  echo First run: setting up the environment ^(one-time, ~1-2 minutes^)...
  %PYLAUNCH% -m venv .venv || goto :setupfail
  ".venv\Scripts\python.exe" -m pip install --upgrade pip
  rem [com] adds pywin32 so the "MS Project (COM)" .mpp reader works on Windows.
  ".venv\Scripts\python.exe" -m pip install -e ".[com]" || goto :setupfail
)

echo.
echo   Schedule Forensics is starting at http://127.0.0.1:%SF_PORT%
echo   Your browser will open in a moment. Keep this window open while you work;
echo   close it to stop the tool. All data stays on this machine.
echo.
start "" "http://127.0.0.1:%SF_PORT%"
".venv\Scripts\python.exe" -m schedule_forensics.webapp
goto :eof

:nopython
echo.
echo   Python 3.11+ was not found. Install it from https://www.python.org/downloads/
echo   (tick "Add Python to PATH" during setup), then run this again.
echo.
pause
goto :eof

:setupfail
echo.
echo   Setup failed (see the messages above). Usually this means Python 3.11+ is
echo   missing or not on PATH. Install it, then run this again.
echo.
pause
goto :eof
