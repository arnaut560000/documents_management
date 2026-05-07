@echo off
setlocal

echo Allowing inbound traffic on TCP port 5000...
netsh advfirewall firewall add rule name="NeeCo DMS 5000" dir=in action=allow protocol=TCP localport=5000

if errorlevel 1 (
    echo.
    echo Failed to add the firewall rule.
    echo Run this file as Administrator.
    pause
    exit /b 1
)

echo.
echo Firewall rule added successfully.
echo Other PCs can connect to this server on port 5000.
echo.
pause
