# NeeCo DMS Deployment Guide

This project can run on another Windows PC without VS Code.

## 1. Download the ZIP from GitHub

1. Open the GitHub repository.
2. Click the green `Code` button.
3. Click `Download ZIP`.
4. Extract the ZIP on the target server PC.

You can also copy the full project folder manually if you already have it on a USB drive or shared folder.

## 2. Copy or extract the project

Copy or extract the full `neeco_dms` folder to the target PC.

Recommended location:

`C:\neeco_dms`

Avoid placing the live server copy inside OneDrive, Desktop sync folders, or removable drives.

## 3. Install Python once

1. Download Python from [python.org](https://www.python.org/downloads/windows/)
2. During installation, enable `Add Python to PATH`

## 4. Recommended one-step server setup

On the target server PC:

1. Right-click `install_server_pc.bat`
2. Choose `Run as administrator`

This will run setup, open the firewall, register automatic startup, and start the server.

## 5. Manual setup option

On the target PC:

1. Open the copied project folder
2. Double-click `setup.bat`

This will:

- create a local virtual environment in `.venv`
- install all required packages from `requirements.txt`
- create `.env` from `.env.example` if needed
- initialize the SQLite database

## 6. Test the server

Double-click `start_server.bat`

Then open:

[http://localhost:5000](http://localhost:5000)

Default admin account:

- Username: `admin`
- Password: `admin123`

Change the password after the first login.

## 7. Enable automatic startup

Right-click `register_startup_task.bat` and choose `Run as administrator`

This creates a Windows Task Scheduler task that starts the server automatically when the PC boots.

## 8. Allow other department PCs to access it

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
