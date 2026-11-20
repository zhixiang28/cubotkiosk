@echo off
rem ============================================================
rem  Update Cubot now (double-click this file)
rem  1. Downloads the newest updater (cubot-update.py) from GitHub
rem  2. Installs the newest Cubot with it
rem  3. Offers to restart Cubot so the new version is used
rem  Keep this file in the same folder as welcome-kiosk.html.
rem  Your own files (office-info.txt, kiosk-config.json, ...) are never touched.
rem ============================================================
cd /d "%~dp0"
title Update Cubot
set "REPO=zhixiang28/cubotkiosk"
set "RAW=https://raw.githubusercontent.com/%REPO%/main/cubot-update.py"

rem Find Python (same way as start-kiosk.bat)
set "PY="
if exist "%~dp0python-path.txt" set /p PY=<"%~dp0python-path.txt"
if defined PY if not exist "%PY%" set "PY="
if not defined PY py --version >nul 2>&1 && set "PY=py"
if not defined PY python -c "import sys" >nul 2>&1 && set "PY=python"
if not defined PY (
  echo Python was not found. Run 1-INSTALL.bat again, or install Python from python.org.
  pause
  exit /b 1
)

echo.
echo  Step 1 of 2: getting the newest updater from GitHub...
if exist "cubot-update.py.download" del "cubot-update.py.download"
curl.exe -fsSL --ssl-revoke-best-effort --max-time 60 -o "cubot-update.py.download" "%RAW%" >nul 2>&1
if not exist "cubot-update.py.download" curl.exe -fsSL --max-time 60 -o "cubot-update.py.download" "%RAW%" >nul 2>&1
if not exist "cubot-update.py.download" powershell -NoProfile -ExecutionPolicy Bypass -Command "$ProgressPreference='SilentlyContinue'; try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 } catch {}; Invoke-WebRequest -UseBasicParsing -Uri '%RAW%' -OutFile 'cubot-update.py.download' -TimeoutSec 60" >nul 2>&1
if exist "cubot-update.py.download" (
  "%PY%" -c "import ast,sys; s=open('cubot-update.py.download',encoding='utf-8').read(); ast.parse(s); sys.exit(0 if 'def run(' in s else 1)" >nul 2>&1
  if errorlevel 1 (
    echo  The download looked broken, keeping the updater this PC already has.
    del "cubot-update.py.download"
  ) else (
    move /y "cubot-update.py.download" "cubot-update.py" >nul
    echo  OK
  )
) else (
  echo  Could not download it. Is this PC on the internet? Trying with the updater it already has...
)

echo.
echo  Step 2 of 2: installing the newest Cubot...
echo.
"%PY%" "%~dp0cubot-update.py" --now
echo.
if exist "%~dp0start-kiosk.bat.new" (
  copy /y "%~dp0start-kiosk.bat.new" "%~dp0start-kiosk.bat" >nul
  del "%~dp0start-kiosk.bat.new"
)
echo  The last lines of update-log.txt:
echo  ---------------------------------
powershell -NoProfile -Command "if (Test-Path 'update-log.txt') { Get-Content 'update-log.txt' -Tail 8 }"
echo.
choice /c YN /t 30 /d N /m "Restart Cubot now so the new version is used"
if errorlevel 2 goto done
if exist "%~dp0stop-kiosk.bat" call "%~dp0stop-kiosk.bat"
timeout /t 2 /nobreak >nul
start "" "%~dp0start-kiosk.bat"
exit /b 0

:done
echo  OK. The new version is used the next time Cubot opens.
timeout /t 10
