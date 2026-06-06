"""
auth.py — Authentication & User Management
Session-based auth with admin/user roles
"""
import hashlib
import secrets
import sqlite3
import os
from datetime import datetime
from functools import wraps
from flask import request, jsonify, session

# ─── PASSWORD HASHING ──────────────────────────────────────────────────────────

def hash_password(password, salt=None):
    if salt is None:
        salt = secrets.token_hex(16)
    hashed = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt.encode('utf-8'), 10000)
    return f"{salt}:{hashed.hex()}"

def verify_password(password, stored_hash):
    try:
        salt, hashed = stored_hash.split(':')
        test = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt.encode('utf-8'), 10000)
        return test.hex() == hashed
    except Exception:
        return False

# ─── DB HELPERS ────────────────────────────────────────────────────────────────

def _get_conn():
    import database
    return database.get_sqlite_conn()

def init_users_table():
    conn = _get_conn()
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS users (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            username     TEXT NOT NULL UNIQUE COLLATE NOCASE,
            password_hash TEXT NOT NULL,
            display_name TEXT NOT NULL,
            role         TEXT NOT NULL DEFAULT 'user',
            active       INTEGER NOT NULL DEFAULT 1,
            created_at   TEXT DEFAULT (datetime('now','localtime')),
            updated_at   TEXT DEFAULT (datetime('now','localtime'))
        );
    ''')
    conn.commit()

    # Create default admin if no users exist
    c = conn.cursor()
    c.execute('SELECT COUNT(*) FROM users')
    if c.fetchone()[0] == 0:
        pw = hash_password('admin123')
        c.execute('''INSERT INTO users(username, password_hash, display_name, role)
                     VALUES(?, ?, ?, ?)''', ('admin', pw, 'Administrator', 'admin'))
        conn.commit()
        print('[Auth] Default admin user created: admin / admin123')

    conn.close()

# ─── AUTH FUNCTIONS ────────────────────────────────────────────────────────────

def authenticate(username, password):
    conn = _get_conn()
    c = conn.cursor()
    c.execute('SELECT id, username, password_hash, display_name, role, active FROM users WHERE username=?',
              (username.strip(),))
    row = c.fetchone()
    conn.close()

    if not row:
        return None, 'Invalid username or password.'
    if not row['active']:
        return None, 'Account is deactivated. Contact an administrator.'
    if not verify_password(password, row['password_hash']):
        return None, 'Invalid username or password.'

    return {
        'id': row['id'],
        'username': row['username'],
        'display_name': row['display_name'],
        'role': row['role'],
    }, None

def get_current_user():
    user_id = session.get('user_id')
    if not user_id:
        return None
    conn = _get_conn()
    c = conn.cursor()
    c.execute('SELECT id, username, display_name, role, active FROM users WHERE id=? AND active=1', (user_id,))
    row = c.fetchone()
    conn.close()
    if not row:
        return None
    return {
        'id': row['id'],
        'username': row['username'],
        'display_name': row['display_name'],
        'role': row['role'],
    }

# ─── DECORATORS ────────────────────────────────────────────────────────────────

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        user = get_current_user()
        if not user:
            return jsonify({'error': 'Authentication required', 'auth_required': True}), 401
        request.current_user = user
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        user = get_current_user()
        if not user:
            return jsonify({'error': 'Authentication required', 'auth_required': True}), 401
        if user['role'] != 'admin':
            return jsonify({'error': 'Admin access required'}), 403
        request.current_user = user
        return f(*args, **kwargs)
    return decorated

# ─── USER CRUD ─────────────────────────────────────────────────────────────────

def get_all_users(include_inactive=False):
    conn = _get_conn()
    c = conn.cursor()
    if include_inactive:
        c.execute('SELECT id, username, display_name, role, active, created_at FROM users ORDER BY display_name')
    else:
        c.execute('SELECT id, username, display_name, role, active, created_at FROM users WHERE active=1 ORDER BY display_name')
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows

def get_user_by_id(uid):
    conn = _get_conn()
    c = conn.cursor()
    c.execute('SELECT id, username, display_name, role, active, created_at FROM users WHERE id=?', (uid,))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None

def create_user(username, password, display_name, role='user'):
    username = username.strip().lower()
    display_name = display_name.strip()
    if not username or not password or not display_name:
        return None, 'Username, password, and display name are required.'
    if len(password) < 4:
        return None, 'Password must be at least 4 characters.'
    if role not in ('admin', 'user'):
        role = 'user'

    conn = _get_conn()
    c = conn.cursor()
    # Check if username exists
    c.execute('SELECT id FROM users WHERE username=?', (username,))
    if c.fetchone():
        conn.close()
        return None, f'Username "{username}" already exists.'

    pw_hash = hash_password(password)
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    c.execute('''INSERT INTO users(username, password_hash, display_name, role, active, created_at, updated_at)
                 VALUES(?, ?, ?, ?, 1, ?, ?)''', (username, pw_hash, display_name, role, now, now))
    conn.commit()
    new_id = c.lastrowid
    conn.close()
    return get_user_by_id(new_id), None

def update_user(uid, data):
    conn = _get_conn()
    c = conn.cursor()
    c.execute('SELECT id, username, role FROM users WHERE id=?', (uid,))
    existing = c.fetchone()
    if not existing:
        conn.close()
        return None, 'User not found.'

    display_name = data.get('display_name', '').strip()
    role = data.get('role', existing['role'])
    active = data.get('active', 1)

    if role not in ('admin', 'user'):
        role = 'user'

    # Prevent deactivating the last admin
    if existing['role'] == 'admin' and (role != 'admin' or not active):
        c.execute("SELECT COUNT(*) FROM users WHERE role='admin' AND active=1 AND id != ?", (uid,))
        if c.fetchone()[0] == 0:
            conn.close()
            return None, 'Cannot deactivate or demote the last active admin.'

    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    c.execute('''UPDATE users SET display_name=?, role=?, active=?, updated_at=? WHERE id=?''',
              (display_name, role, int(active), now, uid))
    conn.commit()
    conn.close()
    return get_user_by_id(uid), None

def reset_password(uid, new_password):
    if not new_password or len(new_password) < 4:
        return False, 'Password must be at least 4 characters.'
    conn = _get_conn()
    c = conn.cursor()
    c.execute('SELECT id FROM users WHERE id=?', (uid,))
    if not c.fetchone():
        conn.close()
        return False, 'User not found.'
    pw_hash = hash_password(new_password)
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    c.execute('UPDATE users SET password_hash=?, updated_at=? WHERE id=?', (pw_hash, now, uid))
    conn.commit()
    conn.close()
    return True, 'Password updated.'

def change_own_password(uid, current_password, new_password):
    if not new_password or len(new_password) < 4:
        return False, 'New password must be at least 4 characters.'
    conn = _get_conn()
    c = conn.cursor()
    c.execute('SELECT password_hash FROM users WHERE id=?', (uid,))
    row = c.fetchone()
    conn.close()
    if not row:
        return False, 'User not found.'
    if not verify_password(current_password, row['password_hash']):
        return False, 'Current password is incorrect.'
    return reset_password(uid, new_password)

def delete_user(uid):
    conn = _get_conn()
    c = conn.cursor()
    c.execute('SELECT role FROM users WHERE id=?', (uid,))
    row = c.fetchone()
    if not row:
        conn.close()
        return False, 'User not found.'
    if row['role'] == 'admin':
        c.execute("SELECT COUNT(*) FROM users WHERE role='admin' AND active=1 AND id != ?", (uid,))
        if c.fetchone()[0] == 0:
            conn.close()
            return False, 'Cannot delete the last admin.'
    c.execute('DELETE FROM users WHERE id=?', (uid,))
    conn.commit()
    conn.close()
    return True, None
