@echo off
setlocal

set "TASK_NAME=NeeCo DMS Server"

schtasks /Delete /TN "%TASK_NAME%" /F

if errorlevel 1 (
    echo Could not remove the startup task.
    echo It may not exist, or this file needs Administrator access.
    pause
    exit /b 1
)

echo Startup task removed successfully.
echo.
pause
