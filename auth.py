import hashlib
import secrets
from functools import wraps
from flask import request, jsonify, session

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

def authenticate_user(username, password):
    import database
    conn = database.get_connection()
    cursor = conn.cursor()
    cursor.execute('''SELECT id, username, display_name, role, active, password_hash 
                      FROM bcp_users WHERE LOWER(username) = LOWER(:u)''', {'u': username})
    cols = [d[0].lower() for d in cursor.description]
    row = cursor.fetchone()
    cursor.close()
    database.release_connection(conn)

    if not row:
        return None, 'Invalid username or password.'
    r = dict(zip(cols, row))
    if not r['active']:
        return None, 'Account is deactivated. Contact an administrator.'
    if not verify_password(password, r['password_hash']):
        return None, 'Invalid username or password.'

    return {
        'id': r['id'],
        'username': r['username'],
        'display_name': r['display_name'],
        'role': r['role'],
    }, None

def get_current_user():
    user_id = session.get('user_id')
    if not user_id:
        return None
    import database
    conn = database.get_connection()
    cursor = conn.cursor()
    cursor.execute('''SELECT id, username, display_name, role, active 
                      FROM bcp_users WHERE id = :id AND active = 1''', {'id': user_id})
    cols = [d[0].lower() for d in cursor.description]
    row = cursor.fetchone()
    cursor.close()
    database.release_connection(conn)
    
    if not row:
        return None
    r = dict(zip(cols, row))
    return {
        'id': r['id'],
        'username': r['username'],
        'display_name': r['display_name'],
        'role': r['role'],
    }

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        user = get_current_user()
        if not user:
            return jsonify({'auth_required': True}), 401
        request.current_user = user
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        user = get_current_user()
        if not user or user.get('role') != 'admin':
            return jsonify({'error': 'Unauthorized. Admins only.'}), 403
        request.current_user = user
        return f(*args, **kwargs)
    return decorated

def get_all_users(include_inactive=False):
    import database
    conn = database.get_connection()
    cursor = conn.cursor()
    sql = 'SELECT id, username, display_name, role, active FROM bcp_users'
    if not include_inactive:
        sql += ' WHERE active=1'
    cursor.execute(sql)
    cols = [d[0].lower() for d in cursor.description]
    rows = [dict(zip(cols, r)) for r in cursor.fetchall()]
    cursor.close()
    database.release_connection(conn)
    return rows

def create_user(username, password, display_name, role='user'):
    import database
    conn = database.get_connection()
    cursor = conn.cursor()
    # Check if exists
    cursor.execute('SELECT COUNT(*) FROM bcp_users WHERE LOWER(username) = LOWER(:u)', {'u': username})
    if cursor.fetchone()[0] > 0:
        cursor.close(); database.release_connection(conn)
        return None, 'Username already exists.'

    pw = hash_password(password)
    new_id = cursor.var(int)
    cursor.execute('''INSERT INTO bcp_users(username, password_hash, display_name, role)
                      VALUES(:u, :p, :d, :r) RETURNING id INTO :nid''',
                   {'u': username, 'p': pw, 'd': display_name, 'r': role, 'nid': new_id})
    conn.commit()
    uid = new_id.getvalue()[0]
    cursor.close()
    database.release_connection(conn)
    return {'id': uid, 'username': username, 'display_name': display_name, 'role': role}, None

def update_user(uid, data):
    import database
    conn = database.get_connection()
    cursor = conn.cursor()
    fields = []
    params = {'id': uid}
    if 'display_name' in data and data['display_name'].strip():
        fields.append('display_name = :d')
        params['d'] = data['display_name'].strip()
    if 'role' in data and data['role'] in ['admin','user']:
        fields.append('role = :r')
        params['r'] = data['role']
    if 'active' in data:
        fields.append('active = :a')
        params['a'] = 1 if data['active'] else 0
    if 'password' in data and data['password']:
        fields.append('password_hash = :p')
        params['p'] = hash_password(data['password'])
        
    if not fields:
        cursor.close(); database.release_connection(conn)
        return None, 'No valid fields provided.'

    fields.append('updated_at = CURRENT_TIMESTAMP')
    sql = f"UPDATE bcp_users SET {', '.join(fields)} WHERE id = :id"
    cursor.execute(sql, params)
    conn.commit()
    affected = cursor.rowcount
    cursor.close()
    database.release_connection(conn)

    if affected == 0:
        return None, 'User not found.'

    # Fetch updated user
    return get_user_by_id(uid), None

def get_user_by_id(uid):
    import database
    conn = database.get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT id, username, display_name, role, active FROM bcp_users WHERE id = :id', {'id': uid})
    cols = [d[0].lower() for d in cursor.description]
    row = cursor.fetchone()
    cursor.close()
    database.release_connection(conn)
    if not row:
        return None
    return dict(zip(cols, row))

def update_password(uid, current_pw, new_pw):
    import database
    conn = database.get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT password_hash FROM bcp_users WHERE id = :id', {'id': uid})
    row = cursor.fetchone()
    if not row:
        cursor.close(); database.release_connection(conn)
        return False, 'User not found.'

    if not verify_password(current_pw, row[0]):
        cursor.close(); database.release_connection(conn)
        return False, 'Incorrect current password.'

    cursor.execute('UPDATE bcp_users SET password_hash = :p, updated_at = CURRENT_TIMESTAMP WHERE id = :id',
                   {'p': hash_password(new_pw), 'id': uid})
    conn.commit()
    cursor.close()
    database.release_connection(conn)
    return True, 'Password updated successfully.'
