@echo off
echo ============================================
echo  Backend Corrections Portal - Installer
echo ============================================
echo.
echo Installing Python dependencies...
pip install flask flask-socketio flask-cors gevent gevent-websocket openpyxl oracledb
echo.
echo ============================================
echo  Installation complete!
echo  Run start.bat to launch the portal.
echo ============================================
pause
