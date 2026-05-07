@echo off
setlocal

cd /d "%~dp0"

if not exist "logs" mkdir "logs"

set "PYTHON_EXE=.venv\Scripts\python.exe"
if not exist "%PYTHON_EXE%" (
    echo The virtual environment was not found.
    echo Run setup.bat on this PC first.
    pause
    exit /b 1
)

echo Starting NeeCo DMS server...
echo Visit http://localhost:5000 on this PC after startup.
echo.

"%PYTHON_EXE%" run_server.py >> "logs\server.log" 2>&1
