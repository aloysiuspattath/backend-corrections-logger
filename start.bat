@echo off
echo Starting Backend Corrections Portal...
echo.

:: Use venv python directly (most reliable method)
if exist "venv\Scripts\python.exe" (
    echo [OK] Using virtual environment
    venv\Scripts\python.exe server.py
) else (
    echo [WARN] No virtual environment found.
    echo        Run install.bat first!
    echo.
    echo Trying system Python as fallback...
    python server.py
)

if errorlevel 1 (
    echo.
    echo [ERROR] Server failed to start.
    echo   - Run install.bat first if you haven't already
    echo   - Check if port 5000 is already in use
    pause
)
