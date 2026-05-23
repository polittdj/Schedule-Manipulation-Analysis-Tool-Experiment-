@echo off
rem Run this ONCE: it creates a "Schedule Forensics" icon on your Desktop that
rem points to the launcher (with the custom icon). After that, just use the icon.
setlocal
set "SF_LAUNCHER=%~dp0Schedule-Forensics.bat"
set "SF_ICON=%~dp0icon.ico"
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$d=[Environment]::GetFolderPath('Desktop');" ^
  "$w=New-Object -ComObject WScript.Shell;" ^
  "$s=$w.CreateShortcut((Join-Path $d 'Schedule Forensics.lnk'));" ^
  "$s.TargetPath=$env:SF_LAUNCHER;" ^
  "$s.WorkingDirectory=(Split-Path $env:SF_LAUNCHER);" ^
  "if (Test-Path $env:SF_ICON) { $s.IconLocation=$env:SF_ICON };" ^
  "$s.Description='Schedule Forensics (local forensic schedule analysis)';" ^
  "$s.Save();"
echo.
echo   Done. A "Schedule Forensics" icon is now on your Desktop -- double-click it.
echo.
pause
