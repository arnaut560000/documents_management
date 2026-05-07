@echo off
setlocal

cd /d "%~dp0"

set "TASK_NAME=NeeCo DMS Server"
set "START_SCRIPT=%~dp0start_server.bat"
set "TASK_COMMAND=%ComSpec% /c ""%START_SCRIPT%"""

if not exist "%START_SCRIPT%" (
    echo start_server.bat was not found.
    pause
    exit /b 1
)

echo Creating the Windows startup task...
schtasks /Create /TN "%TASK_NAME%" /SC ONSTART /RU SYSTEM /RL HIGHEST /TR "%TASK_COMMAND%" /F

if errorlevel 1 (
    echo.
    echo Failed to create the startup task.
    echo Run this file as Administrator.
    pause
    exit /b 1
)

echo.
echo Startup task created successfully.
echo The server will now start automatically when Windows boots.
echo.
pause
