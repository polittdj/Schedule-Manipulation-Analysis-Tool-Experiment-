@echo off
REM Double-click (Windows) to BUILD a self-contained app. The result needs no Python to run.
REM (PyInstaller does not cross-compile: run this on Windows to get a Windows .exe.)

cd /d "%~dp0"

if not exist ".venv" (
  py -3.13 -m venv .venv 2>nul || python -m venv .venv
  if errorlevel 1 ( echo Install Python 3.13 first, then try again. & pause & exit /b 1 )
)

".venv\Scripts\python" -m pip install --quiet --upgrade pip
".venv\Scripts\python" -m pip install --quiet -r requirements.txt pyinstaller
if errorlevel 1 ( echo Install failed. & pause & exit /b 1 )

REM Optional: native .mpp support. Needs Java; if absent we still build a working app (no .mpp).
".venv\Scripts\python" -m pip install --quiet -r requirements-mpp.txt 2>nul && (echo MPXJ installed ^(native .mpp enabled^).) || (echo Skipping MPXJ ^(.mpp import will be unavailable^).)
set "JLINK="
if exist "%JAVA_HOME%\bin\jlink.exe" set "JLINK=%JAVA_HOME%\bin\jlink.exe"
if not defined JLINK for %%J in (jlink.exe) do if not "%%~$PATH:J"=="" set "JLINK=%%~$PATH:J"
if defined JLINK (
  if exist jre rmdir /s /q jre
  "%JLINK%" --add-modules ALL-MODULE-PATH --output jre --no-header-files --no-man-pages && (echo Bundled a JRE in .\jre ^(the app will read .mpp with no separate Java^).) || (echo jlink failed; .mpp will need Java on the user's machine.)
) else (
  echo No Java ^(jlink^) found; the app will build but .mpp needs Java on the user's machine.
)

".venv\Scripts\pyinstaller" --noconfirm --clean schedule_tool.spec
if errorlevel 1 ( echo Build failed. & pause & exit /b 1 )

echo.
echo Done! Your app is:  dist\ScheduleTool.exe
echo Double-click it to run the tool (no Python needed). You can move it anywhere.
pause
