"""
server.py — Backend Corrections Portal
Flask + Flask-SocketIO server with Authentication
Run with: python server.py
"""
import os
import json
import socket
import secrets
from datetime import datetime
from flask import Flask, request, jsonify, send_from_directory, send_file, Response, session
from flask_socketio import SocketIO, emit
from flask_cors import CORS
import database
import excel_handler
import backup_manager
import auth

# ─── APP CONFIG ────────────────────────────────────────────────────────────────
APP_CONFIG_FILE = 'app_config.json'
DEFAULT_APP_CONFIG = {
    'host': '0.0.0.0',
    'port': 5000,
    'shared_excel_path': '',
    'auto_sync_excel': False
}

def load_app_config():
    if os.path.exists(APP_CONFIG_FILE):
        with open(APP_CONFIG_FILE, 'r') as f:
            cfg = json.load(f)
            return {**DEFAULT_APP_CONFIG, **cfg}
    return DEFAULT_APP_CONFIG.copy()

def save_app_config(cfg):
    with open(APP_CONFIG_FILE, 'w') as f:
        json.dump(cfg, f, indent=2)

import threading

def auto_sync_shared_excel():
    """Auto-export to shared Excel file if configured."""
    def run_sync():
        try:
            cfg = load_app_config()
            if cfg.get('auto_sync_excel') and cfg.get('shared_excel_path', '').strip():
                excel_handler.export_to_shared(cfg['shared_excel_path'])
        except Exception as e:
            print(f'[Auto-Sync Warning] {e}')
    
    threading.Thread(target=run_sync, daemon=True).start()

# ─── APP SETUP ─────────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__, static_folder=BASE_DIR, static_url_path='')
app.secret_key = os.environ.get('BCP_SECRET_KEY', secrets.token_hex(32))
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['PERMANENT_SESSION_LIFETIME'] = 86400 * 7  # 7 days
CORS(app, origins='*', supports_credentials=True)
socketio = SocketIO(app, cors_allowed_origins='*', async_mode='gevent',
                    logger=False, engineio_logger=False, manage_session=False)

online_users = {}   # sid -> username

# ─── STATIC FILES ──────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return send_from_directory(BASE_DIR, 'index.html')

@app.route('/<path:filename>')
def static_files(filename):
    return send_from_directory(BASE_DIR, filename)

# ─── AUTH ROUTES ────────────────────────────────────────────────────────────────

@app.route('/api/auth/login', methods=['POST'])
def login():
    data = request.json or {}
    username = data.get('username', '').strip()
    password = data.get('password', '')
    if not username or not password:
        return jsonify({'error': 'Username and password are required.'}), 400
    user, err = auth.authenticate(username, password)
    if not user:
        return jsonify({'error': err}), 401
    session.permanent = True
    session['user_id'] = user['id']
    return jsonify({'user': user, 'message': f'Welcome, {user["display_name"]}!'})

@app.route('/api/auth/logout', methods=['POST'])
def logout():
    session.pop('user_id', None)
    return jsonify({'success': True})

@app.route('/api/auth/me')
def auth_me():
    user = auth.get_current_user()
    if not user:
        return jsonify({'authenticated': False}), 401
    return jsonify({'authenticated': True, 'user': user})

@app.route('/api/auth/change-password', methods=['POST'])
@auth.login_required
def change_password():
    data = request.json or {}
    success, msg = auth.change_own_password(
        request.current_user['id'],
        data.get('current_password', ''),
        data.get('new_password', '')
    )
    if success:
        return jsonify({'success': True, 'message': msg})
    return jsonify({'error': msg}), 400

# ─── USER MANAGEMENT (ADMIN) ───────────────────────────────────────────────────

@app.route('/api/users', methods=['GET'])
@auth.login_required
def list_users():
    include_inactive = request.args.get('all', '0') == '1'
    if include_inactive and request.current_user['role'] != 'admin':
        include_inactive = False
    return jsonify(auth.get_all_users(include_inactive))

@app.route('/api/users', methods=['POST'])
@auth.admin_required
def create_user():
    data = request.json or {}
    user, err = auth.create_user(
        data.get('username', ''), data.get('password', ''),
        data.get('display_name', ''), data.get('role', 'user')
    )
    if not user:
        return jsonify({'error': err}), 400
    return jsonify(user), 201

@app.route('/api/users/<int:uid>', methods=['PUT'])
@auth.admin_required
def update_user(uid):
    user, err = auth.update_user(uid, request.json or {})
    if not user:
        return jsonify({'error': err}), 400
    return jsonify(user)

@app.route('/api/users/<int:uid>/reset-password', methods=['POST'])
@auth.admin_required
def admin_reset_password(uid):
    data = request.json or {}
    success, msg = auth.reset_password(uid, data.get('password', ''))
    if success:
        return jsonify({'success': True, 'message': msg})
    return jsonify({'error': msg}), 400

@app.route('/api/users/<int:uid>', methods=['DELETE'])
@auth.admin_required
def delete_user(uid):
    success, err = auth.delete_user(uid)
    if success:
        return jsonify({'success': True})
    return jsonify({'error': err}), 400

# ─── CORRECTIONS CRUD ──────────────────────────────────────────────────────────

@app.route('/api/corrections', methods=['GET'])
@auth.login_required
def get_corrections():
    try:
        data, total = database.get_corrections(
            search=request.args.get('search', ''),
            executed_by=request.args.get('executed_by', ''),
            date_from=request.args.get('date_from', ''),
            date_to=request.args.get('date_to', ''),
            status=request.args.get('status', ''),
            page=int(request.args.get('page', 1)),
            per_page=int(request.args.get('per_page', 20)),
            sort_col=request.args.get('sort', 'date'),
            sort_dir=request.args.get('dir', 'desc'),
        )
        return jsonify({'data': data, 'total': total,
                        'page': int(request.args.get('page', 1)),
                        'per_page': int(request.args.get('per_page', 20))})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/corrections', methods=['POST'])
@auth.login_required
def add_correction():
    try:
        payload = request.json or {}
        # Auto-set executed_by from logged-in user if not provided
        if not payload.get('executed_by', '').strip():
            payload['executed_by'] = request.current_user['display_name']
        rec = database.add_correction(payload)
        socketio.emit('correction_added', {**rec, '_by': request.current_user['display_name']})
        auto_sync_shared_excel()
        return jsonify(rec), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/corrections/<int:cid>', methods=['GET'])
@auth.login_required
def get_one(cid):
    try:
        conn = database.get_sqlite_conn() if not database.is_oracle() else None
        if conn:
            import sqlite3
            conn.row_factory = sqlite3.Row
            c = conn.cursor()
            c.execute('SELECT * FROM corrections WHERE id=?', (cid,))
            row = c.fetchone()
            conn.close()
            if not row:
                return jsonify({'error': 'Not found'}), 404
            return jsonify(dict(row))
        return jsonify({'error': 'Not supported'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/corrections/<int:cid>', methods=['PUT'])
@auth.login_required
def update_correction(cid):
    try:
        # Basic users can only edit their own corrections
        if request.current_user['role'] != 'admin':
            conn = database.get_sqlite_conn()
            c = conn.cursor()
            c.execute('SELECT executed_by FROM corrections WHERE id=?', (cid,))
            row = c.fetchone()
            conn.close()
            if row and row['executed_by'] != request.current_user['display_name']:
                return jsonify({'error': 'You can only edit your own corrections.'}), 403

        rec = database.update_correction(cid, request.json or {})
        if rec:
            socketio.emit('correction_updated', {**rec, '_by': request.current_user['display_name']})
            auto_sync_shared_excel()
            return jsonify(rec)
        return jsonify({'error': 'Not found'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/corrections/<int:cid>', methods=['DELETE'])
@auth.admin_required
def delete_correction(cid):
    try:
        success = database.delete_correction(cid)
        if success:
            socketio.emit('correction_deleted', {'id': cid, '_by': request.current_user['display_name']})
            auto_sync_shared_excel()
            return jsonify({'success': True})
        return jsonify({'error': 'Not found'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ─── STATS & METADATA ──────────────────────────────────────────────────────────

@app.route('/api/stats')
@auth.login_required
def get_stats():
    try:
        s = database.get_stats()
        s['db_engine'] = 'Oracle Database' if database.is_oracle() else 'SQLite (FTS5)'
        return jsonify(s)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/executors')
@auth.login_required
def get_executors():
    try:
        return jsonify(database.get_executors())
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/activity')
@auth.login_required
def get_activity():
    try:
        days = int(request.args.get('days', 14))
        return jsonify(database.get_activity(days))
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ─── SEARCH ────────────────────────────────────────────────────────────────────

@app.route('/api/search')
@auth.login_required
def search():
    q = request.args.get('q', '').strip()
    if not q:
        return jsonify({'data': [], 'total': 0, 'query': q})
    try:
        data, total = database.full_text_search(
            q,
            executed_by=request.args.get('executed_by', ''),
            status=request.args.get('status', ''),
            date_from=request.args.get('date_from', ''),
            date_to=request.args.get('date_to', '')
        )
        return jsonify({'data': data, 'total': total, 'query': q})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ─── EXCEL IMPORT ──────────────────────────────────────────────────────────────

@app.route('/api/import/headers', methods=['POST'])
@auth.admin_required
def get_import_headers():
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    try:
        result = excel_handler.get_file_headers(request.files['file'])
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/import/excel', methods=['POST'])
@auth.admin_required
def import_excel():
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    mode = request.form.get('mode', 'skip')
    col_map_json = request.form.get('column_mapping', '')
    col_map = None
    if col_map_json:
        try:
            col_map = json.loads(col_map_json)
        except:
            pass
    try:
        result = excel_handler.import_from_excel(request.files['file'], mode, column_mapping=col_map)
        if result.get('imported', 0) > 0:
            socketio.emit('data_imported', {'count': result['imported']})
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/sync/preview', methods=['POST'])
@auth.admin_required
def sync_preview():
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    try:
        return jsonify(excel_handler.preview_sync(request.files['file']))
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ─── EXPORT ────────────────────────────────────────────────────────────────────

@app.route('/api/export/excel')
@auth.admin_required
def export_excel():
    try:
        filepath = excel_handler.export_to_excel()
        fname = f'corrections_{datetime.now().strftime("%Y%m%d_%H%M%S")}.xlsx'
        return send_file(filepath, as_attachment=True, download_name=fname,
                         mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/export/csv')
@auth.admin_required
def export_csv():
    try:
        data = excel_handler.export_to_csv()
        fname = f'corrections_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
        return Response(data, mimetype='text/csv',
                        headers={'Content-Disposition': f'attachment; filename={fname}'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ─── BACKUPS ───────────────────────────────────────────────────────────────────

@app.route('/api/backups', methods=['GET'])
@auth.admin_required
def list_backups():
    try:
        return jsonify(backup_manager.list_backups())
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/backups', methods=['POST'])
@auth.admin_required
def create_backup():
    label = (request.json or {}).get('label', '')
    try:
        result = backup_manager.create_backup(label)
        return jsonify(result), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/backups/<filename>/download')
@auth.admin_required
def download_backup(filename):
    try:
        fpath = backup_manager.get_backup_path(filename)
        return send_file(fpath, as_attachment=True, download_name=filename)
    except Exception as e:
        return jsonify({'error': str(e)}), 404

@app.route('/api/backups/<filename>', methods=['DELETE'])
@auth.admin_required
def delete_backup(filename):
    try:
        backup_manager.delete_backup(filename)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ─── DB CONFIG / MIGRATION ─────────────────────────────────────────────────────

@app.route('/api/db/config', methods=['GET'])
@auth.admin_required
def get_db_config():
    try:
        config = database.get_config()
        safe = {**config}
        if 'oracle' in safe:
            safe['oracle'] = {k: ('' if k == 'password' else v)
                              for k, v in safe['oracle'].items()}
        return jsonify(safe)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/db/config', methods=['POST'])
@auth.admin_required
def save_db_config():
    try:
        database.update_oracle_config(request.json or {})
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/db/test-oracle', methods=['POST'])
@auth.admin_required
def test_oracle():
    try:
        result = database.test_oracle_connection(request.json or {})
        return jsonify(result)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/db/migrate-to-oracle', methods=['POST'])
@auth.admin_required
def migrate_to_oracle():
    try:
        result = database.migrate_to_oracle()
        if result.get('success'):
            socketio.emit('db_switched', {'db_type': 'oracle'})
        return jsonify(result)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/db/migrate-to-sqlite', methods=['POST'])
@auth.admin_required
def migrate_to_sqlite():
    try:
        result = database.migrate_to_sqlite()
        if result.get('success'):
            socketio.emit('db_switched', {'db_type': 'sqlite'})
        return jsonify(result)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# ─── ORACLE CX STUB ────────────────────────────────────────────────────────────

@app.route('/api/cx/ticket/<ticket_no>')
@auth.login_required
def cx_ticket(ticket_no):
    return jsonify({
        'configured': False,
        'ticket_no':  ticket_no,
        'message':    'Oracle CX integration is not yet configured. '
                      'Go to Settings to enable this feature.',
        'data':       None
    }), 501

# ─── APP CONFIG API ────────────────────────────────────────────────────────────

@app.route('/api/app-config', methods=['GET'])
@auth.admin_required
def get_app_config():
    try:
        return jsonify(load_app_config())
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/app-config', methods=['POST'])
@auth.admin_required
def save_app_config_api():
    try:
        data = request.json or {}
        cfg = load_app_config()
        if 'host' in data: cfg['host'] = str(data['host']).strip() or '0.0.0.0'
        if 'port' in data:
            try: cfg['port'] = int(data['port'])
            except: cfg['port'] = 5000
        if 'shared_excel_path' in data: cfg['shared_excel_path'] = str(data['shared_excel_path']).strip()
        if 'auto_sync_excel' in data: cfg['auto_sync_excel'] = bool(data['auto_sync_excel'])
        save_app_config(cfg)
        return jsonify({'success': True, 'config': cfg, 'message': 'Settings saved. Restart the server for host/port changes to take effect.'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/shared-excel/sync', methods=['POST'])
@auth.admin_required
def sync_shared_excel():
    """Manual sync: export all data to the shared Excel file."""
    try:
        cfg = load_app_config()
        path = cfg.get('shared_excel_path', '').strip()
        if not path:
            return jsonify({'error': 'Shared Excel path is not configured.'}), 400
        excel_handler.export_to_shared(path)
        return jsonify({'success': True, 'message': f'Data synced to {path}'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/shared-excel/import', methods=['POST'])
@auth.admin_required
def import_from_shared_excel():
    """Import new entries from the shared Excel file into the portal."""
    try:
        cfg = load_app_config()
        path = cfg.get('shared_excel_path', '').strip()
        if not path:
            return jsonify({'error': 'Shared Excel path is not configured.'}), 400
        if not os.path.exists(path):
            return jsonify({'error': f'File not found: {path}'}), 404
        with open(path, 'rb') as f:
            result = excel_handler.import_from_excel(f, mode='skip')
        if result.get('imported', 0) > 0:
            socketio.emit('data_imported', {'count': result['imported']})
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ─── WEBSOCKET EVENTS ──────────────────────────────────────────────────────────

@socketio.on('connect')
def on_connect():
    pass

@socketio.on('user_join')
def on_user_join(data):
    username = str(data.get('username', 'Anonymous'))[:50]
    online_users[request.sid] = username
    socketio.emit('users_online', list(set(online_users.values())))

@socketio.on('disconnect')
def on_disconnect():
    online_users.pop(request.sid, None)
    socketio.emit('users_online', list(set(online_users.values())))

# ─── ENTRY POINT ───────────────────────────────────────────────────────────────

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return 'your-ip'

if __name__ == '__main__':
    os.makedirs('backups', exist_ok=True)
    os.makedirs('uploads', exist_ok=True)
    database.init_db()
    auth.init_users_table()
    app_cfg = load_app_config()
    host = app_cfg.get('host', '0.0.0.0')
    port = app_cfg.get('port', 5000)
    local_ip = get_local_ip()
    print('\n' + '='*54)
    print('   ____   ____  ____  ')
    print('  | __ ) / ___||  _ \\ ')
    print('  |  _ \\| |    | |_) |')
    print('  | |_) | |___ |  __/ ')
    print('  |____/ \\____||_|    ')
    print('')
    print('  Backend Corrections Portal')
    print('='*54)
    print(f'  Local:   http://localhost:{port}')
    print(f'  Network: http://{local_ip}:{port}')
    print('  Default:  admin / admin123')
    if app_cfg.get('shared_excel_path'):
        print(f'  Excel:   {app_cfg["shared_excel_path"]}')
        print(f'  Sync:    {"Auto" if app_cfg.get("auto_sync_excel") else "Manual"}')
    print('  Press Ctrl+C to stop')
    print('='*54 + '\n')
    socketio.run(app, host=host, port=port, debug=False)
