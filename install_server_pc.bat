@echo off
setlocal

cd /d "%~dp0"

echo ==========================================
echo NEECO DMS - Server PC Installer
echo ==========================================
echo.

net session >nul 2>&1
if errorlevel 1 (
    echo This installer must be run as Administrator.
    echo.
    echo Right-click install_server_pc.bat and choose "Run as administrator".
    echo.
    pause
    exit /b 1
)

echo Step 1 of 4: Running application setup...
set "NEECO_SETUP_NO_PAUSE=1"
call "%~dp0setup.bat"
if errorlevel 1 (
    echo.
    echo Setup failed. Please review the message above.
    pause
    exit /b 1
)

echo.
echo Step 2 of 4: Opening Windows Firewall for port 5000...
netsh advfirewall firewall add rule name="NeeCo DMS 5000" dir=in action=allow protocol=TCP localport=5000 >nul
if errorlevel 1 (
    echo Failed to add the firewall rule.
    pause
    exit /b 1
)

echo.
echo Step 3 of 4: Registering automatic startup task...
set "TASK_NAME=NeeCo DMS Server"
set "START_SCRIPT=%~dp0start_server.bat"
set "TASK_COMMAND=%ComSpec% /c ""%START_SCRIPT%"""
schtasks /Create /TN "%TASK_NAME%" /SC ONSTART /RU SYSTEM /RL HIGHEST /TR "%TASK_COMMAND%" /F
if errorlevel 1 (
    echo Failed to create the startup task.
    pause
    exit /b 1
)

echo.
echo Step 4 of 4: Starting the server now...
Start "" /min "%~dp0start_server.bat"

echo.
echo Installation complete.
echo.
echo Open this on the server PC:
echo http://localhost:5000
echo.
echo Other department PCs should use:
echo http://SERVER_PC_IP:5000
echo.
echo The system will start automatically whenever this PC boots.
echo.
pause
