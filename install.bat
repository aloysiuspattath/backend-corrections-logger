@echo off
echo ======================================================
echo   Backend Corrections Portal - OFFLINE INSTALLER
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

:: Install from vendor folder (offline, no internet needed)
echo.
echo Installing dependencies from vendor folder (offline)...
pip install --no-index --find-links=vendor -r requirements.txt
if errorlevel 1 (
    echo.
    echo [ERROR] Installation failed.
    echo Possible causes:
    echo   - Python version mismatch (need 3.11, 3.12, or 3.13, 64-bit)
    echo   - Vendor folder missing or incomplete
    echo.
    pause
    exit /b 1
)

echo.
echo ======================================================
echo   [OK] All dependencies installed successfully!
echo   Run start.bat to launch the portal.
echo ======================================================
pause
