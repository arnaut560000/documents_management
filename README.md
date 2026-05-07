# NEECO Document Management System

This system is intended to run on one Windows PC in the department as the main server. Other computers can open it in a browser using the server PC's IP address.

## Download as ZIP from GitHub

1. Open the repository on GitHub.
2. Click the green `Code` button.
3. Click `Download ZIP`.
4. Extract the ZIP on the target server PC.

Recommended server PC folder:

```text
C:\neeco_dms
```

Avoid running the live server copy from OneDrive, Desktop sync folders, USB drives, or temporary folders.

## Server PC Setup

On the target server PC:

1. Install Python from https://www.python.org/downloads/windows/
2. During Python installation, check `Add Python to PATH`.
3. Extract the downloaded ZIP to `C:\neeco_dms`.
4. Right-click `install_server_pc.bat`.
5. Choose `Run as administrator`.

The installer will:

- create the Python virtual environment
- install the required packages
- initialize the local database
- open Windows Firewall for port `5000`
- register the app to start automatically when Windows boots

## Open the System

On the server PC:

```text
http://localhost:5000
```

From another department PC:

```text
http://SERVER_PC_IP:5000
```

Example:

```text
http://192.168.1.20:5000
```

Default admin account:

```text
Username: admin
Password: admin123
```

Change the password after first login.

## Important

- The server PC must stay powered on while users need the system.
- The server PC should have a static IP address or router DHCP reservation.
- The database is stored in `instance`.
- Uploaded files are stored in `uploads`.
- Server logs are stored in `logs`.
