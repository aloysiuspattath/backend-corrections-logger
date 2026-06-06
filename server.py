import os
from flask import Flask, request, jsonify, session, send_file
from flask_socketio import SocketIO
from datetime import timedelta
import tempfile
import csv

import database
import auth

app = Flask(__name__, static_url_path='', static_folder='.')
app.secret_key = 'bcp-super-secret-key' # Use a static key or env var for session persistence
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)

socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# Initialize DB
database.init_tables()

# ─── MIDDLEWARE ────────────────────────────────────────────────────────────────
@app.before_request
def make_session_permanent():
    session.permanent = True

# ─── AUTHENTICATION ────────────────────────────────────────────────────────────
@app.route('/api/auth/login', methods=['POST'])
def login():
    data = request.json or {}
    username = data.get('username', '').strip()
    password = data.get('password', '')

    user, err = auth.authenticate_user(username, password)
    if not user:
        return jsonify({'authenticated': False, 'error': err}), 401

    session['user_id'] = user['id']
    return jsonify({'authenticated': True, 'user': user})

@app.route('/api/auth/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({'success': True})

@app.route('/api/auth/me', methods=['GET'])
def get_me():
    user = auth.get_current_user()
    if user:
        return jsonify({'authenticated': True, 'user': user})
    return jsonify({'authenticated': False}), 401

@app.route('/api/auth/password', methods=['PUT'])
@auth.login_required
def change_password():
    if request.current_user.get('is_external'):
        return jsonify({'error': 'Password must be changed through your Active Directory or External system.'}), 403
    data = request.json or {}
    success, msg = auth.update_password(
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

# ─── CORRECTIONS ───────────────────────────────────────────────────────────────
@app.route('/api/corrections', methods=['GET'])
@auth.login_required
def list_corrections():
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
            sort_dir=request.args.get('dir', 'desc')
        )
        return jsonify({
            'data': data, 
            'total': total,
            'page': int(request.args.get('page', 1)),
            'per_page': int(request.args.get('per_page', 20))
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/corrections', methods=['POST'])
@auth.login_required
def add_correction():
    try:
        payload = request.json or {}
        if not payload.get('executed_by', '').strip():
            payload['executed_by'] = request.current_user['display_name']
        rec = database.add_correction(payload)
        socketio.emit('correction_added', {**rec, '_by': request.current_user['display_name']})
        return jsonify(rec), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/corrections/<int:cid>', methods=['GET'])
@auth.login_required
def get_correction(cid):
    try:
        row = database.get_correction(cid)
        if not row:
            return jsonify({'error': 'Not found'}), 404
        return jsonify(row)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/corrections/<int:cid>', methods=['PUT'])
@auth.login_required
def update_correction(cid):
    try:
        payload = request.json or {}
        rec = database.update_correction(cid, payload)
        if not rec:
            return jsonify({'error': 'Not found'}), 404
        socketio.emit('correction_updated', {**rec, '_by': request.current_user['display_name']})
        return jsonify(rec)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/corrections/<int:cid>', methods=['DELETE'])
@auth.admin_required
def delete_correction(cid):
    try:
        success = database.delete_correction(cid)
        if not success:
            return jsonify({'error': 'Not found'}), 404
        socketio.emit('correction_deleted', {'id': cid, '_by': request.current_user['display_name']})
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ─── STATS & METADATA ──────────────────────────────────────────────────────────
@app.route('/api/stats')
@auth.login_required
def get_stats():
    try:
        s = database.get_stats()
        s['db_engine'] = 'Oracle Database'
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

# ─── EXPORT ────────────────────────────────────────────────────────────────────
@app.route('/api/export/csv')
@auth.login_required
def export_csv():
    try:
        data, _ = database.get_corrections(per_page=100000) # Get all essentially
        fd, path = tempfile.mkstemp(suffix='.csv')
        with os.fdopen(fd, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['ID', 'Ticket', 'Query', 'Executed By', 'Date', 'Status', 'Notes', 'Created At'])
            for r in data:
                writer.writerow([r['id'], r['ticket'], r['query'], r['executed_by'], r['date'], r['status'], r['notes'], r['created_at']])
        return send_file(path, as_attachment=True, download_name='corrections_export.csv', mimetype='text/csv')
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ─── SOCKET.IO EVENTS ──────────────────────────────────────────────────────────
@socketio.on('connect')
def handle_connect():
    pass

@socketio.on('disconnect')
def handle_disconnect():
    pass

@app.route('/')
def index():
    return app.send_static_file('index.html')

if __name__ == '__main__':
    cfg = database.get_config().get('app', {})
    port = cfg.get('port', 5000)
    print(f"[*] Starting Backend Corrections Portal on port {port}")
    socketio.run(app, host='0.0.0.0', port=port, debug=False, allow_unsafe_werkzeug=True)
