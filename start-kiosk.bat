@echo off
rem ============================================================
rem  Cubot kiosk launcher
rem  Keep this file in the same folder as welcome-kiosk.html
rem ============================================================
cd /d "%~dp0"

rem 1. Start the local AI (Ollama) if it is installed and not running yet
set "OLLAMA_ORIGINS=*"
set "OLLAMA=%LocalAppData%\Programs\Ollama\ollama.exe"
if not exist "%OLLAMA%" if exist "%~dp0Ollama\ollama.exe" set "OLLAMA=%~dp0Ollama\ollama.exe"
if not exist "%OLLAMA%" for %%I in (ollama.exe) do set "OLLAMA=%%~$PATH:I"
if not defined OLLAMA goto server
if not exist "%OLLAMA%" goto server
curl -s http://127.0.0.1:11434 >nul 2>&1
if errorlevel 1 start "Ollama" /min "%OLLAMA%" serve

:server
rem 2. Find Python
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

rem 3. Get the newest Cubot from GitHub (skipped quietly when there is no internet)
if exist "%~dp0cubot-update.py" (
  echo Checking for Cubot updates...
  "%PY%" "%~dp0cubot-update.py"
)
rem    If the update changed this file, swap it in and start again. The whole ( ) block is read before it runs,
rem    so replacing this file here is safe.
if exist "%~dp0start-kiosk.bat.new" (
  copy /y "%~dp0start-kiosk.bat.new" "%~f0" >nul
  del "%~dp0start-kiosk.bat.new"
  start "" "%~f0"
  exit /b 0
)

rem 4. Start the local web server. It only answers this PC (127.0.0.1), not the office network.
rem kiosk-server.py also lets Cubot search the internet; plain http.server is the fallback
if exist "%~dp0kiosk-server.py" (
  start "Kiosk server" /min "%PY%" "%~dp0kiosk-server.py"
) else (
  start "Kiosk server" /min "%PY%" -m http.server 8000 --bind 127.0.0.1
)

rem 5. Give everything a few seconds to start
timeout /t 8 /nobreak >nul

rem 6. Use Chrome (it can listen for "Hey Cubot" on this PC without sending sound online), or Edge if Chrome is missing
set "PROFILE=browser-profile-chrome"
set "BROWSER=%ProgramFiles%\Google\Chrome\Application\chrome.exe"
if not exist "%BROWSER%" set "BROWSER=%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"
if not exist "%BROWSER%" set "BROWSER=%LocalAppData%\Google\Chrome\Application\chrome.exe"
if exist "%BROWSER%" goto launch
set "PROFILE=browser-profile"
set "BROWSER=%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"
if not exist "%BROWSER%" set "BROWSER=%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"

:launch
rem 7. Open the kiosk full screen with no address bar
rem The random number makes the browser load the newest version of the page every time
start "" "%BROWSER%" --kiosk "http://localhost:8000/welcome-kiosk.html?v=%RANDOM%" --disk-cache-size=1 ^
  --user-data-dir="%~dp0%PROFILE%" ^
  --no-first-run --noerrdialogs --disable-session-crashed-bubble --disable-infobars ^
  --autoplay-policy=no-user-gesture-required --use-fake-ui-for-media-stream ^
  --overscroll-history-navigation=0 --disable-pinch --disable-features=Translate
