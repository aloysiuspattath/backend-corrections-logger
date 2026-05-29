@echo off
echo ============================================
echo  Backend Corrections Portal
echo ============================================
echo.
echo Starting server...
echo.
echo Access the portal at:
echo   Local:   http://localhost:5000
echo   Network: http://%COMPUTERNAME%:5000
echo.
echo Press Ctrl+C to stop the server.
echo ============================================
python server.py
pause
