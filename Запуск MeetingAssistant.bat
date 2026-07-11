@echo off
rem ============================================================
rem  MeetingAssistant - launcher (lightweight)
rem  Launches the PyQt6 GUI without a console window.
rem  Logs are written to the Logs\ folder by the app itself.
rem ============================================================

rem Always run from the project folder (where this .bat is located),
rem so relative paths (.env, Recordings, Logs...) resolve correctly.
cd /d "%~dp0"

rem Pick the interpreter:
rem   1) project venv (if it ever gets created),
rem   2) otherwise the system pythonw.exe from PATH.
set "PYW=pythonw.exe"
if exist "%~dp0venv\Scripts\pythonw.exe"  set "PYW=%~dp0venv\Scripts\pythonw.exe"
if exist "%~dp0.venv\Scripts\pythonw.exe" set "PYW=%~dp0.venv\Scripts\pythonw.exe"

rem Make sure the interpreter exists before launching.
where "%PYW%" >nul 2>&1
if errorlevel 1 (
    echo.
    echo  [ERROR] pythonw.exe not found.
    echo  Install Python and add it to PATH, then try again.
    echo.
    pause
    exit /b 1
)

rem Launch the GUI detached (no console window). The .bat exits immediately.
start "MeetingAssistant" "%PYW%" "%~dp0main.py"
exit /b 0
