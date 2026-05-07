# NeeCo DMS Deployment Guide

This project can run on another Windows PC without VS Code.

## 1. Copy the project

Copy the full `neeco_dms` folder to the target PC.

Recommended location:

`C:\neeco_dms`

Avoid placing the live server copy inside OneDrive, Desktop sync folders, or removable drives.

## 2. Install Python once

1. Download Python from [python.org](https://www.python.org/downloads/windows/)
2. During installation, enable `Add Python to PATH`

## 3. Run the one-time setup

On the target PC:

1. Open the copied project folder
2. Double-click `setup.bat`

This will:

- create a local virtual environment in `.venv`
- install all required packages from `requirements.txt`
- create `.env` from `.env.example` if needed
- initialize the SQLite database

## 4. Test the server

Double-click `start_server.bat`

Then open:

[http://localhost:5000](http://localhost:5000)

Default admin account:

- Username: `admin`
- Password: `admin123`

Change the password after the first login.

## 5. Enable automatic startup

Right-click `register_startup_task.bat` and choose `Run as administrator`

This creates a Windows Task Scheduler task that starts the server automatically when the PC boots.

## 6. Allow other department PCs to access it

If other computers need to open the system in their browser:

1. Right-click `allow_firewall.bat` and choose `Run as administrator`
2. Find the server PC's IP address by opening Command Prompt and running:

   `ipconfig`

3. On another PC, open:

   `http://SERVER_IP:5000`

Example:

`http://192.168.1.20:5000`

## Notes

- Keep the server PC powered on while the department is using the system
- The database file is stored under `instance`
- Uploaded files are stored under `uploads`
- Server logs are written to `logs\server.log`

## If you need to remove auto-start later

Run:

`remove_startup_task.bat`
