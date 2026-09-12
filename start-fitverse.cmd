@echo off
title FITVERSE Server
cd /d "%~dp0"

echo.
echo  ============================================
echo    FITVERSE - Fitness is more fun together
echo  ============================================
echo.

REM If Python is missing, say so plainly and pause so the window stays open
where python >nul 2>nul
if errorlevel 1 (
    echo  [X] Python was not found on this PC.
    echo      Install it from https://www.python.org/downloads/
    echo      and tick "Add Python to PATH" during install.
    echo.
    pause
    exit /b 1
)

REM If something is already running on port 4173, the app is probably open already
netstat -ano | findstr ":4173" | findstr "LISTENING" >nul 2>nul
if not errorlevel 1 (
    echo  [!] FITVERSE is already running at http://127.0.0.1:4173
    echo      Opening it in your browser...
    echo      (Close the other FITVERSE window to restart the server.)
    start "" "http://127.0.0.1:4173"
    timeout /t 4 >nul
    exit /b 0
)

echo  [..] Starting server...
echo.

REM Launch the browser after a short delay, then run the server in this window
start "" cmd /c "timeout /t 2 >nul & start "" http://127.0.0.1:4173"

:run
python server.py
echo.
echo  [!] The server stopped unexpectedly. Check the error above.
echo      Press a key to try starting it again, or close this window.
pause >nul
goto run
