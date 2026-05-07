@echo off
setlocal

cd /d "%~dp0"

echo ==========================================
echo NeeCo DMS - One-Time Setup
echo ==========================================
echo.

where py >nul 2>nul
if %errorlevel%==0 (
    set "PYTHON_CMD=py -3"
) else (
    where python >nul 2>nul
    if %errorlevel%==0 (
        set "PYTHON_CMD=python"
    ) else (
        echo Python was not found on this PC.
        echo Install Python first from https://www.python.org/downloads/windows/
        echo During installation, enable "Add Python to PATH".
        pause
        exit /b 1
    )
)

if exist ".venv\Scripts\python.exe" (
    call ".venv\Scripts\python.exe" --version >nul 2>nul
    if errorlevel 1 (
        echo Existing virtual environment is broken or points to a missing Python install.
        echo Recreating virtual environment...
        rmdir /S /Q ".venv"
    )
)

if not exist ".venv\Scripts\python.exe" (
    echo Creating virtual environment...
    call %PYTHON_CMD% -m venv .venv
    if errorlevel 1 (
        echo Failed to create the virtual environment.
        pause
        exit /b 1
    )
)

echo Upgrading pip...
call ".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 (
    echo Failed to upgrade pip.
    pause
    exit /b 1
)

echo Installing required packages...
call ".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
    echo Failed to install the required packages.
    pause
    exit /b 1
)

if not exist ".env" if exist ".env.example" (
    echo Creating .env from .env.example...
    copy /Y ".env.example" ".env" >nul
)

if not exist "instance" mkdir "instance"
if not exist "uploads" mkdir "uploads"
if not exist "logs" mkdir "logs"

echo Running database initialization...
call ".venv\Scripts\python.exe" init_db.py
if errorlevel 1 (
    echo Failed to initialize the database.
    pause
    exit /b 1
)

echo.
echo Setup complete.
echo Next steps:
echo 1. Review the .env file if you want to change the port or admin account.
echo 2. Double-click start_server.bat to test the server.
echo 3. If it works, run register_startup_task.bat as Administrator for auto-start.
echo.
if not "%NEECO_SETUP_NO_PAUSE%"=="1" pause
