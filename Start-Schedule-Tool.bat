@echo off
REM Double-click this file (Windows) to start the Schedule Manipulation Analysis Tool.
REM It opens in your web browser. Close this window to stop the tool.

cd /d "%~dp0"

REM First run only: build the local environment and install the tool's parts.
if not exist ".venv" (
  echo First-time setup - this takes about a minute...
  py -3.13 -m venv .venv 2>nul || python -m venv .venv
  if errorlevel 1 ( echo Could not create the environment. Install Python 3.13 first. & pause & exit /b 1 )
  ".venv\Scripts\python" -m pip install --quiet --upgrade pip
  ".venv\Scripts\python" -m pip install -r requirements.txt
  if errorlevel 1 ( echo Install failed. & pause & exit /b 1 )
)

".venv\Scripts\python" launch.py
pause
