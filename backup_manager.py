"""
backup_manager.py — Create, list, download and delete database backups
"""
import os
import shutil
import json
from datetime import datetime
import database

BACKUP_DIR = 'backups'

def _format_size(n):
    if n < 1024:       return f'{n} B'
    if n < 1024**2:    return f'{n/1024:.1f} KB'
    return f'{n/1024**2:.1f} MB'

def _safe_path(filename):
    """Resolve backup path and ensure it stays within BACKUP_DIR."""
    abs_dir  = os.path.abspath(BACKUP_DIR)
    abs_path = os.path.abspath(os.path.join(BACKUP_DIR, os.path.basename(filename)))
    if not abs_path.startswith(abs_dir + os.sep):
        raise Exception('Invalid backup filename.')
    return abs_path

# ─── LIST ──────────────────────────────────────────────────────────────────────

def list_backups():
    os.makedirs(BACKUP_DIR, exist_ok=True)
    result = []
    for fname in sorted(os.listdir(BACKUP_DIR), reverse=True):
        fpath = os.path.join(BACKUP_DIR, fname)
        if not os.path.isfile(fpath):
            continue
        if not (fname.endswith('.db') or fname.endswith('.json')):
            continue
        stat = os.stat(fpath)
        result.append({
            'filename':  fname,
            'size':      stat.st_size,
            'size_human': _format_size(stat.st_size),
            'created':   datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S'),
            'type':      'sqlite' if fname.endswith('.db') else 'oracle_json',
        })
    return result

# ─── CREATE ────────────────────────────────────────────────────────────────────

def create_backup(label=''):
    os.makedirs(BACKUP_DIR, exist_ok=True)
    config = database.get_config()
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    label_part = ('_' + label.strip().replace(' ', '_')[:30]) if label.strip() else ''

    if config['db_type'] != 'oracle':
        # SQLite: just copy the .db file
        src = config['sqlite']['path']
        if not os.path.exists(src):
            raise Exception(f'Database file not found: {src}')
        fname = f'backup_{ts}{label_part}.db'
        dest = os.path.join(BACKUP_DIR, fname)
        shutil.copy2(src, dest)
        stat = os.stat(dest)
        return {
            'filename':   fname,
            'size':       stat.st_size,
            'size_human': _format_size(stat.st_size),
            'created':    datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'type':       'sqlite',
            'message':    f'SQLite backup created: {fname}'
        }
    else:
        # Oracle: export all records to JSON
        records = database.get_all_for_export()
        fname = f'backup_{ts}{label_part}.json'
        dest = os.path.join(BACKUP_DIR, fname)
        payload = {
            'created':  datetime.now().isoformat(),
            'source':   'oracle',
            'count':    len(records),
            'records':  records
        }
        with open(dest, 'w', encoding='utf-8') as f:
            json.dump(payload, f, indent=2, default=str)
        stat = os.stat(dest)
        return {
            'filename':   fname,
            'size':       stat.st_size,
            'size_human': _format_size(stat.st_size),
            'created':    datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'type':       'oracle_json',
            'message':    f'Oracle JSON backup created: {fname} ({len(records)} records)'
        }

# ─── GET PATH ──────────────────────────────────────────────────────────────────

def get_backup_path(filename):
    path = _safe_path(filename)
    if not os.path.exists(path):
        raise Exception(f'Backup not found: {filename}')
    return path

# ─── DELETE ────────────────────────────────────────────────────────────────────

def delete_backup(filename):
    path = _safe_path(filename)
    if not os.path.exists(path):
        raise Exception(f'Backup not found: {filename}')
    os.remove(path)
    return True
