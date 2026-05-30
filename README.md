# Backend Corrections Portal

A local web app to track backend corrections (SQL queries, commands) executed against service tickets — replacing Excel-based tracking.

## Features

- **Dashboard** with stats and activity chart
- **CRUD** for corrections (ticket, query, executor, date, status, notes)
- **Full-text search** with filters (executor, status, date range)
- **Authentication** with admin/user roles
- **Excel import** with column mapping + export (XLSX/CSV)
- **Database backups** with download/restore
- **Real-time sync** across multiple users (Socket.IO)
- **Oracle DB migration** option (Settings)
- **Offline-ready** — all dependencies bundled in `vendor/`

## Quick Start (Offline — No Internet Needed)

### 1. Copy the entire folder to the target machine

Copy this whole project folder (including `vendor/`) to the target Windows machine.

### 2. Install dependencies

```
install.bat
```

This installs all Python packages from the `vendor/` folder — **no internet required**.

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

- **Python 3.11, 3.12, or 3.13** (64-bit, Windows)
- No internet needed — all dependencies are in `vendor/`
- No database installation needed — uses SQLite (built-in)

## Permissions

| Feature | Basic User | Admin |
|---------|-----------|-------|
| View/Add/Search corrections | ✅ | ✅ |
| Edit own corrections | ✅ | ✅ |
| Edit any / Delete corrections | ❌ | ✅ |
| Import / Export | ❌ | ✅ |
| Backups | ❌ | ✅ |
| Settings / User Management | ❌ | ✅ |

## Project Structure

```
├── server.py          # Flask backend + API routes
├── database.py        # SQLite/Oracle DB layer + FTS5
├── auth.py            # Authentication & user management
├── excel_handler.py   # Excel import/export with column mapping
├── backup_manager.py  # Database backup/restore
├── index.html         # Frontend SPA
├── style.css          # Premium dark theme
├── app.js             # Frontend JavaScript
├── requirements.txt   # Python dependencies
├── install.bat        # Offline dependency installer
├── start.bat          # Launch script
├── vendor/            # Pre-downloaded Python wheels (offline)
└── .gitignore
```
