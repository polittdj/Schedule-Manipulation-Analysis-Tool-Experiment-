@echo off
rem Schedule Forensics - one-click launcher (Windows 11).
rem Double-click to run, or run Install-Desktop-Shortcut.bat once to put it on your Desktop.
rem First run sets up the environment; later runs just start the tool.
setlocal enableextensions

rem -- Optional config (edit if you like) --
if not defined SF_PORT set SF_PORT=5000
rem Optional local AI-polished executive summaries (all loopback-only, CUI-safe):
rem  * Easiest: install Ollama (https://ollama.com) and run "ollama pull llama3.2"
rem    once; this launcher then auto-starts Ollama and uses it (override: SF_OLLAMA_MODEL).
rem  * Or point at any local OpenAI-compatible server:
rem    set SF_LLM_BASE_URL=http://127.0.0.1:8080/v1
rem    set SF_LLM_MODEL=qwen

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

rem -- Optional: local AI summaries via Ollama (auto-detected; loopback-only, CUI-safe). --
rem Nothing is auto-downloaded; with no Ollama (or no pulled model) deterministic summaries are used.
set "SF_OLLAMA_FOUND="
set "SF_OLLAMA_WE_STARTED="
where ollama >nul 2>&1 && set "SF_OLLAMA_FOUND=1"
if defined SF_OLLAMA_FOUND curl -fsS http://127.0.0.1:11434/api/tags >nul 2>&1
if defined SF_OLLAMA_FOUND if errorlevel 1 set "SF_OLLAMA_WE_STARTED=1"
if defined SF_OLLAMA_WE_STARTED start "" /b ollama serve
if defined SF_OLLAMA_WE_STARTED timeout /t 2 /nobreak >nul 2>&1
if defined SF_OLLAMA_FOUND if not defined SF_OLLAMA_MODEL (
  for /f "skip=1 tokens=1" %%m in ('ollama list 2^>nul') do (
    if not defined SF_OLLAMA_MODEL set "SF_OLLAMA_MODEL=%%m"
  )
)
if defined SF_OLLAMA_MODEL echo   AI summaries: ON ^(local Ollama model: %SF_OLLAMA_MODEL%^).

echo.
echo   Schedule Forensics is starting at http://127.0.0.1:%SF_PORT%
echo   Your browser will open in a moment. Keep this window open while you work.
echo   Press Ctrl+C here (or close it) to stop the tool AND shut Ollama down.
echo   All data stays on this machine.
echo.
start "" "http://127.0.0.1:%SF_PORT%"
".venv\Scripts\python.exe" -m schedule_forensics.webapp

rem -- On exit: shut Ollama down (you asked it to stop with the tool). Unload the
rem    model, then stop the Ollama app/server. It starts again next time you launch.
rem    NOTE: this runs on a clean stop (Ctrl+C). If you close via the window's [X],
rem    Windows may skip it -- Ollama then unloads the idle model after ~5 min, or you
rem    can quit it from its system-tray icon.
if defined SF_OLLAMA_MODEL ollama stop %SF_OLLAMA_MODEL% >nul 2>&1
if defined SF_OLLAMA_FOUND taskkill /f /im "ollama app.exe" >nul 2>&1
if defined SF_OLLAMA_FOUND taskkill /f /im ollama.exe >nul 2>&1
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
