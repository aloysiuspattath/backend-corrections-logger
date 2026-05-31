@echo off
echo ======================================================
echo   Backend Corrections Portal - OFFLINE INSTALLER
echo   (Virtual Environment + Bundled Dependencies)
echo ======================================================
echo.

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python is not installed or not in PATH.
    echo Please install Python 3.11+ and try again.
    pause
    exit /b 1
)

for /f "tokens=2 delims= " %%v in ('python --version 2^>^&1') do set PYVER=%%v
echo [OK] Found Python %PYVER%

:: Create virtual environment if it doesn't exist
if not exist "venv" (
    echo.
    echo Creating virtual environment...
    python -m venv venv
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment.
        echo Make sure the 'venv' module is available.
        pause
        exit /b 1
    )
    echo [OK] Virtual environment created.
) else (
    echo [OK] Virtual environment already exists.
)

:: Activate venv and install
echo.
echo Installing dependencies from vendor folder (offline)...
call venv\Scripts\activate.bat

pip install --no-index --find-links=vendor -r requirements.txt
if errorlevel 1 (
    echo.
    echo [ERROR] Installation failed.
    echo Possible causes:
    echo   - Python version mismatch (need 3.11-3.14, 64-bit)
    echo   - Vendor folder missing or incomplete
    echo.
    pause
    exit /b 1
)

echo.
echo ======================================================
echo   [OK] All dependencies installed in virtual environment!
echo.
echo   To start the portal, run:  start.bat
echo ======================================================
pause
