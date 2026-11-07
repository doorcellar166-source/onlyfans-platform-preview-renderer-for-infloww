@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title Wrap Renderer
rem ---- 1. find Python (any 3.8+; nothing else needs installing) ----
set "PYW="
call :findpy
if not defined PYW (
  echo Python wasn't found - installing it once, this takes about a minute...
  winget install -e --id Python.Python.3.12 --scope user --silent --accept-package-agreements --accept-source-agreements
  call :findpy
)
if not defined PYW (
  echo.
  echo Couldn't install Python automatically.
  echo Install it from https://www.python.org/downloads/ then double-click this file again.
  pause
  exit /b 1
)
rem ---- 2. desktop shortcut (first run only) ----
set "APPDIR=%~dp0"
call :shortcut
rem ---- 3. launch without a console window ----
start "" "%PYW%" "%~dp0wrap_renderer.py"
exit /b 0

:findpy
for /f "usebackq delims=" %%P in (`py -3 -c "import sys,os,ctypes,http.server;print(os.path.join(os.path.dirname(sys.executable),'pythonw.exe'))" 2^>nul`) do if exist "%%P" set "PYW=%%P"
if defined PYW exit /b 0
for /f "usebackq delims=" %%P in (`python -c "import sys,os,ctypes,http.server;print(os.path.join(os.path.dirname(sys.executable),'pythonw.exe'))" 2^>nul`) do if exist "%%P" set "PYW=%%P"
if defined PYW exit /b 0
for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python3*") do if exist "%%D\pythonw.exe" set "PYW=%%D\pythonw.exe"
exit /b 0

:shortcut
powershell -NoProfile -ExecutionPolicy Bypass -Command "$d=[Environment]::GetFolderPath('Desktop'); $p=Join-Path $d 'Wrap Renderer.lnk'; if(-not (Test-Path $p)){ $s=(New-Object -ComObject WScript.Shell).CreateShortcut($p); $s.TargetPath=$env:PYW; $s.Arguments='\"' + (Join-Path $env:APPDIR 'wrap_renderer.py') + '\"'; $s.WorkingDirectory=$env:APPDIR; $s.Description='Wrap Renderer'; $s.Save() }" >nul 2>&1
exit /b 0
