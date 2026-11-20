@echo off
rem Closes the Cubot kiosk window and its local web server (your other Chrome windows stay open).
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-CimInstance Win32_Process | Where-Object { $_.ProcessId -ne $PID -and ($_.CommandLine -like '*welcome-kiosk.html*' -or $_.CommandLine -like '*http.server 8000*' -or $_.CommandLine -like '*kiosk-server.py*') } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
taskkill /fi "WINDOWTITLE eq Kiosk server*" /f >nul 2>&1
