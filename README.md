# Backend Corrections Portal

A local web app to track backend corrections (SQL queries, commands) executed against service tickets — replacing Excel-based tracking.

## Features

- **Dashboard** with stats and activity chart
- **CRUD** for corrections (ticket, query, executor, date, status, notes)
- **Full-text search** with filters (executor, status, date range)
- **Authentication** with admin/user roles
- **Excel import** with column mapping + export (XLSX/CSV)
- **Shared Excel sync** — auto-sync to OneDrive/network drive
- **Configurable server** — set custom host/port from Settings
- **Database backups** with download/restore
- **Real-time sync** across multiple users (Socket.IO)
- **Oracle DB migration** option (Settings)
- **Offline-ready** — all dependencies bundled in `vendor/`, uses virtual environment

## Quick Start (Offline — No Internet Needed)

### 1. Copy the entire folder to the target machine

Copy this whole project folder (including `vendor/`) to the target Windows machine.

### 2. Install dependencies

```
install.bat
```

This creates a **virtual environment** (`venv/`) and installs all packages from `vendor/` — **no internet required**.

> You should see `[OK] All core packages verified.` at the end.

### 3. Start the portal

```
start.bat
```

Open **http://localhost:5000** in your browser.

### 4. Default Login

| Username | Password   | Role  |
|----------|-----------|-------|
| `admin`  | `admin123` | Admin |

> ⚠️ Change the admin password after first login (Settings → Change Password).

## Requirements

- **Python 3.11, 3.12, 3.13, or 3.14** (64-bit, Windows)
- No internet needed — all dependencies are in `vendor/`
- No database installation needed — uses SQLite (built-in)

## Shared Excel Sync (OneDrive / Network Drive)

Keep a shared Excel file automatically in sync with portal data:

1. Go to **Settings → Shared Excel Sync**
2. Set the path (e.g. `C:\Users\john\OneDrive - Company\Team\corrections.xlsx`)
3. Enable **Auto-sync** — every add/edit/delete updates the Excel
4. Use **Sync Now** for manual sync, **Import from Shared** to pull new entries

> If someone has the file open in Excel, data is saved alongside with a timestamp.

## Permissions

| Feature | Basic User | Admin |
|---------|-----------|-------|
| View/Add/Search corrections | ✅ | ✅ |
| Edit own corrections | ✅ | ✅ |
| Edit any / Delete corrections | ❌ | ✅ |
| Import / Export | ❌ | ✅ |
| Backups | ❌ | ✅ |
| Settings / User Management | ❌ | ✅ |
| Shared Excel Sync | ❌ | ✅ |

## Project Structure

```
├── server.py          # Flask backend + API routes + app config
├── database.py        # SQLite/Oracle DB layer + FTS5
├── auth.py            # Authentication & user management
├── excel_handler.py   # Excel import/export/sync with column mapping
├── backup_manager.py  # Database backup/restore
├── index.html         # Frontend SPA
├── style.css          # Premium dark theme
├── app.js             # Frontend JavaScript
├── requirements.txt   # Python dependencies
├── install.bat        # Offline venv installer
├── start.bat          # Launch script (uses venv)
├── vendor/            # Pre-downloaded Python wheels (3.11-3.14)
└── .gitignore
```
