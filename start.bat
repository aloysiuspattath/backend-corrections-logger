@echo off
echo Starting Backend Corrections Portal...
echo.

:: Use venv if it exists, otherwise use system Python
if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
    echo [OK] Using virtual environment
) else (
    echo [WARN] No virtual environment found. Using system Python.
    echo        Run install.bat first for best results.
)

python server.py
if errorlevel 1 (
    echo.
    echo [ERROR] Server failed to start.
    echo   - Run install.bat first if you haven't already
    echo   - Check if port 5000 is already in use
    pause
)
