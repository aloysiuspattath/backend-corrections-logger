"""
database.py — DB abstraction layer for SQLite (FTS5) and Oracle DB
"""

import sqlite3
import json
import os
import re
from datetime import datetime, date, timedelta

DB_CONFIG_FILE = 'db_config.json'
DEFAULT_CONFIG = {
    "db_type": "sqlite",
    "sqlite": {"path": "corrections.db"},
    "oracle": {
        "host": "", "port": 1521, "service_name": "", "service_type": "service_name",
        "username": "", "password": "", "schema": ""
    }
}

# ─── CONFIG ────────────────────────────────────────────────────────────────────

def get_config():
    if os.path.exists(DB_CONFIG_FILE):
        with open(DB_CONFIG_FILE, 'r') as f:
            cfg = json.load(f)
            merged = {**DEFAULT_CONFIG, **cfg}
            merged['oracle'] = {**DEFAULT_CONFIG['oracle'], **cfg.get('oracle', {})}
            merged['sqlite'] = {**DEFAULT_CONFIG['sqlite'], **cfg.get('sqlite', {})}
            return merged
    return DEFAULT_CONFIG.copy()

def save_config(config):
    with open(DB_CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=2)

def update_oracle_config(oracle_data):
    config = get_config()
    config['oracle'].update(oracle_data)
    save_config(config)

def is_oracle():
    return get_config().get('db_type') == 'oracle'

# ─── CONNECTIONS ───────────────────────────────────────────────────────────────

def get_sqlite_conn():
    config = get_config()
    db_path = config['sqlite']['path']
    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA cache_size=10000")
    return conn

def get_oracle_conn():
    config = get_config()
    cfg = config['oracle']
    import oracledb
    oracledb.defaults.fetch_lobs = False
    if cfg.get('service_type') == 'sid':
        dsn = oracledb.makedsn(cfg['host'], cfg['port'], sid=cfg['service_name'])
    else:
        dsn = oracledb.makedsn(cfg['host'], cfg['port'], service_name=cfg['service_name'])
    return oracledb.connect(
        user=cfg['username'],
        password=cfg['password'],
        dsn=dsn
    )

# ─── INIT ──────────────────────────────────────────────────────────────────────

def init_db():
    config = get_config()
    if config['db_type'] == 'oracle':
        _init_oracle_tables()
    else:
        _init_sqlite_tables()

def _init_sqlite_tables():
    conn = get_sqlite_conn()
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS corrections (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            ticket      TEXT NOT NULL,
            query       TEXT NOT NULL,
            executed_by TEXT NOT NULL,
            date        TEXT NOT NULL,
            status      TEXT DEFAULT 'Completed',
            notes       TEXT DEFAULT '',
            created_at  TEXT DEFAULT (datetime('now','localtime')),
            updated_at  TEXT DEFAULT (datetime('now','localtime'))
        );

        CREATE INDEX IF NOT EXISTS idx_date ON corrections(date);
        CREATE INDEX IF NOT EXISTS idx_ticket ON corrections(ticket);
        CREATE INDEX IF NOT EXISTS idx_exec ON corrections(executed_by);
        CREATE INDEX IF NOT EXISTS idx_status ON corrections(status);

        CREATE VIRTUAL TABLE IF NOT EXISTS corrections_fts USING fts5(
            ticket, query, notes, executed_by,
            content='corrections', content_rowid='id',
            tokenize='unicode61'
        );

        CREATE TRIGGER IF NOT EXISTS corr_ai AFTER INSERT ON corrections BEGIN
            INSERT INTO corrections_fts(rowid, ticket, query, notes, executed_by)
            VALUES (new.id, new.ticket, new.query, COALESCE(new.notes,''), new.executed_by);
        END;

        CREATE TRIGGER IF NOT EXISTS corr_ad AFTER DELETE ON corrections BEGIN
            INSERT INTO corrections_fts(corrections_fts, rowid, ticket, query, notes, executed_by)
            VALUES ('delete', old.id, old.ticket, old.query, COALESCE(old.notes,''), old.executed_by);
        END;

        CREATE TRIGGER IF NOT EXISTS corr_au AFTER UPDATE ON corrections BEGIN
            INSERT INTO corrections_fts(corrections_fts, rowid, ticket, query, notes, executed_by)
            VALUES ('delete', old.id, old.ticket, old.query, COALESCE(old.notes,''), old.executed_by);
            INSERT INTO corrections_fts(rowid, ticket, query, notes, executed_by)
            VALUES (new.id, new.ticket, new.query, COALESCE(new.notes,''), new.executed_by);
        END;
    ''')
    conn.commit()
    conn.close()

def _init_oracle_tables():
    try:
        conn = get_oracle_conn()
        cursor = conn.cursor()
        # Create sequence
        try:
            cursor.execute("CREATE SEQUENCE corrections_seq START WITH 1 INCREMENT BY 1")
        except Exception:
            pass
        # Create table
        try:
            cursor.execute('''
                CREATE TABLE corrections (
                    id          NUMBER PRIMARY KEY,
                    ticket      VARCHAR2(200) NOT NULL,
                    query       CLOB NOT NULL,
                    executed_by VARCHAR2(200) NOT NULL,
                    date_val    DATE NOT NULL,
                    status      VARCHAR2(50) DEFAULT 'Completed',
                    notes       CLOB,
                    created_at  TIMESTAMP DEFAULT SYSTIMESTAMP,
                    updated_at  TIMESTAMP DEFAULT SYSTIMESTAMP
                )
            ''')
        except Exception:
            pass
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[Oracle Init Warning] {e}")

# ─── FTS QUERY BUILDER ─────────────────────────────────────────────────────────

def _build_fts_query(search_term):
    """Build safe FTS5 query from user input with prefix matching."""
    # Remove FTS5 special characters
    clean = re.sub(r'["\(\)\:\^]', ' ', search_term)
    # Handle SQL keywords and operators gracefully
    words = [w.strip() for w in clean.split() if len(w.strip()) >= 1]
    if not words:
        return None
    # Each word as prefix match, implicit AND in FTS5
    terms = []
    for w in words:
        safe_w = re.sub(r'[^a-zA-Z0-9_\-\.]', '', w)
        if safe_w:
            terms.append(f'{safe_w}*')
    return ' '.join(terms) if terms else None

# ─── CORRECTIONS: GET ──────────────────────────────────────────────────────────

def get_corrections(search='', executed_by='', date_from='', date_to='', status='',
                    page=1, per_page=20, sort_col='date', sort_dir='desc'):
    if is_oracle():
        return _get_corrections_oracle(search, executed_by, date_from, date_to, status, page, per_page, sort_col, sort_dir)
    return _get_corrections_sqlite(search, executed_by, date_from, date_to, status, page, per_page, sort_col, sort_dir)

def _get_corrections_sqlite(search, executed_by, date_from, date_to, status, page, per_page, sort_col, sort_dir):
    conn = get_sqlite_conn()
    c = conn.cursor()

    valid_sort = {'ticket': 'c.ticket', 'executed_by': 'c.executed_by',
                  'date': 'c.date', 'status': 'c.status', 'created_at': 'c.created_at'}
    sort_expr = valid_sort.get(sort_col, 'c.date')
    sort_dir_safe = 'ASC' if sort_dir.lower() == 'asc' else 'DESC'

    fts_query = _build_fts_query(search) if search.strip() else None
    extra_conditions = []
    extra_params = []

    if executed_by:
        extra_conditions.append('c.executed_by = ?')
        extra_params.append(executed_by)
    if date_from:
        extra_conditions.append('c.date >= ?')
        extra_params.append(date_from)
    if date_to:
        extra_conditions.append('c.date <= ?')
        extra_params.append(date_to)
    if status:
        extra_conditions.append('c.status = ?')
        extra_params.append(status)

    extra_where = (' AND ' + ' AND '.join(extra_conditions)) if extra_conditions else ''

    try:
        if fts_query:
            base = f'''SELECT c.id,c.ticket,c.query,c.executed_by,c.date,c.status,c.notes,c.created_at,c.updated_at
                       FROM corrections_fts fts JOIN corrections c ON c.id=fts.rowid
                       WHERE corrections_fts MATCH ?{extra_where}'''
            count_sql = f'''SELECT COUNT(*) FROM corrections_fts fts JOIN corrections c ON c.id=fts.rowid
                            WHERE corrections_fts MATCH ?{extra_where}'''
            base_params = [fts_query] + extra_params
        else:
            base = f'''SELECT id,ticket,query,executed_by,date,status,notes,created_at,updated_at
                       FROM corrections c WHERE 1=1{extra_where}'''
            count_sql = f'SELECT COUNT(*) FROM corrections c WHERE 1=1{extra_where}'
            base_params = extra_params

        c.execute(count_sql, base_params)
        total = c.fetchone()[0]

        full_sql = f'{base} ORDER BY {sort_expr} {sort_dir_safe} LIMIT ? OFFSET ?'
        offset = (page - 1) * per_page
        c.execute(full_sql, base_params + [per_page, offset])
        rows = [dict(r) for r in c.fetchall()]

    except Exception as e:
        # Fallback to LIKE search if FTS fails
        like = f'%{search}%'
        base = f'''SELECT id,ticket,query,executed_by,date,status,notes,created_at,updated_at
                   FROM corrections c WHERE (ticket LIKE ? OR query LIKE ? OR executed_by LIKE ? OR notes LIKE ?){extra_where}'''
        count_sql = f'''SELECT COUNT(*) FROM corrections c
                        WHERE (ticket LIKE ? OR query LIKE ? OR executed_by LIKE ? OR notes LIKE ?){extra_where}'''
        base_params = [like, like, like, like] + extra_params
        c.execute(count_sql, base_params)
        total = c.fetchone()[0]
        c.execute(f'{base} ORDER BY {sort_expr} {sort_dir_safe} LIMIT ? OFFSET ?',
                  base_params + [per_page, (page-1)*per_page])
        rows = [dict(r) for r in c.fetchall()]

    conn.close()
    return rows, total

def _get_corrections_oracle(search, executed_by, date_from, date_to, status, page, per_page, sort_col, sort_dir):
    conn = get_oracle_conn()
    cursor = conn.cursor()
    conditions = ['1=1']
    params = {}

    if search:
        conditions.append("(UPPER(ticket) LIKE UPPER(:s1) OR UPPER(query) LIKE UPPER(:s2) OR UPPER(notes) LIKE UPPER(:s3))")
        like = f'%{search}%'
        params['s1'] = like; params['s2'] = like; params['s3'] = like
    if executed_by:
        conditions.append("executed_by = :exec_by")
        params['exec_by'] = executed_by
    if date_from:
        conditions.append("date_val >= TO_DATE(:df,'YYYY-MM-DD')")
        params['df'] = date_from
    if date_to:
        conditions.append("date_val <= TO_DATE(:dt,'YYYY-MM-DD')")
        params['dt'] = date_to
    if status:
        conditions.append("status = :status")
        params['status'] = status

    where = ' AND '.join(conditions)
    valid_sort = {'ticket': 'ticket', 'executed_by': 'executed_by', 'date': 'date_val', 'status': 'status'}
    order_col = valid_sort.get(sort_col, 'date_val')
    order_dir = 'ASC' if sort_dir.lower() == 'asc' else 'DESC'

    cursor.execute(f'SELECT COUNT(*) FROM corrections WHERE {where}', params)
    total = cursor.fetchone()[0]

    offset = (page - 1) * per_page
    params['start_row'] = offset
    params['end_row'] = offset + per_page
    sql = f'''SELECT * FROM (
                SELECT c.*, ROWNUM rnum FROM (
                    SELECT id, ticket, query, executed_by,
                           TO_CHAR(date_val,'YYYY-MM-DD') AS "date", status, notes,
                           TO_CHAR(created_at,'YYYY-MM-DD HH24:MI:SS') AS created_at,
                           TO_CHAR(updated_at,'YYYY-MM-DD HH24:MI:SS') AS updated_at
                    FROM corrections WHERE {where}
                    ORDER BY {order_col} {order_dir}
                ) c WHERE ROWNUM <= :end_row
              ) WHERE rnum > :start_row'''

    cursor.execute(sql, params)
    cols = [d[0].lower() for d in cursor.description]
    rows = [dict(zip(cols, r)) for r in cursor.fetchall()]
    conn.close()
    return rows, total

# ─── CORRECTIONS: ADD ──────────────────────────────────────────────────────────

def add_correction(data):
    if is_oracle():
        return _add_oracle(data)
    return _add_sqlite(data)

def _add_sqlite(data):
    conn = get_sqlite_conn()
    c = conn.cursor()
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    c.execute('''INSERT INTO corrections(ticket,query,executed_by,date,status,notes,created_at,updated_at)
                 VALUES(?,?,?,?,?,?,?,?)''',
              (data.get('ticket','').strip(), data.get('query','').strip(),
               data.get('executed_by','').strip(), data.get('date', date.today().isoformat()),
               data.get('status','Completed'), data.get('notes',''), now, now))
    conn.commit()
    new_id = c.lastrowid
    c.execute('SELECT * FROM corrections WHERE id=?', (new_id,))
    row = dict(c.fetchone())
    conn.close()
    return row

def _add_oracle(data):
    conn = get_oracle_conn()
    cursor = conn.cursor()
    new_id = cursor.var(int)
    cursor.execute('''INSERT INTO corrections(id,ticket,query,executed_by,date_val,status,notes)
                      VALUES(corrections_seq.NEXTVAL,:t,:q,:e,TO_DATE(:d,'YYYY-MM-DD'),:s,:n)
                      RETURNING id INTO :nid''',
                   {'t': data.get('ticket',''), 'q': data.get('query',''),
                    'e': data.get('executed_by',''), 'd': data.get('date', date.today().isoformat()),
                    's': data.get('status','Completed'), 'n': data.get('notes',''), 'nid': new_id})
    conn.commit()
    rid = new_id.getvalue()[0]
    cursor.execute('''SELECT id,ticket,query,executed_by,TO_CHAR(date_val,'YYYY-MM-DD') AS "date",
                             status,notes,TO_CHAR(created_at,'YYYY-MM-DD HH24:MI:SS') AS created_at
                      FROM corrections WHERE id=:id''', {'id': rid})
    cols = [d[0].lower() for d in cursor.description]
    row = dict(zip(cols, cursor.fetchone()))
    conn.close()
    return row

# ─── CORRECTIONS: UPDATE ───────────────────────────────────────────────────────

def update_correction(cid, data):
    if is_oracle():
        return _update_oracle(cid, data)
    return _update_sqlite(cid, data)

def _update_sqlite(cid, data):
    conn = get_sqlite_conn()
    c = conn.cursor()
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    c.execute('''UPDATE corrections SET ticket=?,query=?,executed_by=?,date=?,status=?,notes=?,updated_at=?
                 WHERE id=?''',
              (data.get('ticket','').strip(), data.get('query','').strip(),
               data.get('executed_by','').strip(), data.get('date'),
               data.get('status','Completed'), data.get('notes',''), now, cid))
    conn.commit()
    if c.rowcount == 0:
        conn.close(); return None
    c.execute('SELECT * FROM corrections WHERE id=?', (cid,))
    row = dict(c.fetchone())
    conn.close()
    return row

def _update_oracle(cid, data):
    conn = get_oracle_conn()
    cursor = conn.cursor()
    cursor.execute('''UPDATE corrections SET ticket=:t,query=:q,executed_by=:e,
                             date_val=TO_DATE(:d,'YYYY-MM-DD'),status=:s,notes=:n,updated_at=SYSTIMESTAMP
                      WHERE id=:id''',
                   {'t': data.get('ticket',''), 'q': data.get('query',''),
                    'e': data.get('executed_by',''), 'd': data.get('date'),
                    's': data.get('status',''), 'n': data.get('notes',''), 'id': cid})
    conn.commit()
    if cursor.rowcount == 0:
        conn.close(); return None
    cursor.execute('''SELECT id,ticket,query,executed_by,TO_CHAR(date_val,'YYYY-MM-DD') AS "date",
                             status,notes FROM corrections WHERE id=:id''', {'id': cid})
    cols = [d[0].lower() for d in cursor.description]
    row = dict(zip(cols, cursor.fetchone()))
    conn.close()
    return row

# ─── CORRECTIONS: DELETE ───────────────────────────────────────────────────────

def delete_correction(cid):
    if is_oracle():
        conn = get_oracle_conn()
        cursor = conn.cursor()
        cursor.execute('DELETE FROM corrections WHERE id=:id', {'id': cid})
        conn.commit(); affected = cursor.rowcount; conn.close()
        return affected > 0
    conn = get_sqlite_conn()
    c = conn.cursor()
    c.execute('DELETE FROM corrections WHERE id=?', (cid,))
    conn.commit(); affected = c.rowcount; conn.close()
    return affected > 0

# ─── STATS ─────────────────────────────────────────────────────────────────────

def get_stats():
    if is_oracle():
        conn = get_oracle_conn()
        cursor = conn.cursor()
        cursor.execute('''SELECT COUNT(*),
                                 SUM(CASE WHEN TRUNC(date_val)=TRUNC(SYSDATE) THEN 1 ELSE 0 END),
                                 SUM(CASE WHEN date_val>=TRUNC(SYSDATE,'IW') THEN 1 ELSE 0 END),
                                 SUM(CASE WHEN date_val>=TRUNC(SYSDATE,'MM') THEN 1 ELSE 0 END)
                          FROM corrections''')
        r = cursor.fetchone(); conn.close()
        return {'total': r[0], 'today': r[1] or 0, 'week': r[2] or 0, 'month': r[3] or 0}

    conn = get_sqlite_conn()
    c = conn.cursor()
    today_dt = date.today()
    today = today_dt.isoformat()
    week_start = (today_dt - timedelta(days=today_dt.weekday())).isoformat()
    month_start = today_dt.replace(day=1).isoformat()
    c.execute('SELECT COUNT(*) FROM corrections'); total = c.fetchone()[0]
    c.execute('SELECT COUNT(*) FROM corrections WHERE date=?', (today,)); t = c.fetchone()[0]
    c.execute('SELECT COUNT(*) FROM corrections WHERE date>=?', (week_start,)); w = c.fetchone()[0]
    c.execute('SELECT COUNT(*) FROM corrections WHERE date>=?', (month_start,)); m = c.fetchone()[0]
    conn.close()
    return {'total': total, 'today': t, 'week': w, 'month': m}

def get_executors():
    if is_oracle():
        conn = get_oracle_conn()
        cursor = conn.cursor()
        cursor.execute('SELECT DISTINCT executed_by FROM corrections ORDER BY executed_by')
        result = [r[0] for r in cursor.fetchall()]; conn.close(); return result
    conn = get_sqlite_conn()
    c = conn.cursor()
    c.execute('SELECT DISTINCT executed_by FROM corrections ORDER BY executed_by')
    result = [r[0] for r in c.fetchall()]; conn.close(); return result

def get_activity(days=14):
    if is_oracle():
        conn = get_oracle_conn()
        cursor = conn.cursor()
        cursor.execute('''SELECT TO_CHAR(date_val,'YYYY-MM-DD') AS d, COUNT(*) AS cnt
                          FROM corrections WHERE date_val >= SYSDATE - :days
                          GROUP BY TO_CHAR(date_val,'YYYY-MM-DD') ORDER BY d''', {'days': days})
        result = [{'date': r[0], 'count': r[1]} for r in cursor.fetchall()]
        conn.close(); return result
    conn = get_sqlite_conn()
    c = conn.cursor()
    c.execute('''SELECT date, COUNT(*) FROM corrections
                 WHERE date >= date('now', ? || ' days')
                 GROUP BY date ORDER BY date''', (f'-{days}',))
    result = [{'date': r[0], 'count': r[1]} for r in c.fetchall()]
    conn.close(); return result

# ─── FULL-TEXT SEARCH ──────────────────────────────────────────────────────────

def full_text_search(query, limit=100, executed_by='', status='', date_from='', date_to=''):
    if is_oracle():
        conn = get_oracle_conn()
        cursor = conn.cursor()
        like = f'%{query}%'
        conditions = ['(UPPER(ticket) LIKE UPPER(:l1) OR UPPER(query) LIKE UPPER(:l2) OR UPPER(notes) LIKE UPPER(:l3) OR UPPER(executed_by) LIKE UPPER(:l4))']
        params = {'l1': like, 'l2': like, 'l3': like, 'l4': like, 'lim': limit}
        if executed_by:
            conditions.append('executed_by = :exec_by')
            params['exec_by'] = executed_by
        if status:
            conditions.append('status = :status')
            params['status'] = status
        if date_from:
            conditions.append("date_val >= TO_DATE(:df,'YYYY-MM-DD')")
            params['df'] = date_from
        if date_to:
            conditions.append("date_val <= TO_DATE(:dt,'YYYY-MM-DD')")
            params['dt'] = date_to
        where = ' AND '.join(conditions)
        cursor.execute(f'''SELECT id,ticket,query,executed_by,TO_CHAR(date_val,'YYYY-MM-DD') AS "date",
                                 status,notes,TO_CHAR(created_at,'YYYY-MM-DD HH24:MI:SS') AS created_at
                          FROM corrections
                          WHERE {where}
                          ORDER BY date_val DESC FETCH FIRST :lim ROWS ONLY''', params)
        cols = [d[0].lower() for d in cursor.description]
        rows = [dict(zip(cols, r)) for r in cursor.fetchall()]
        conn.close(); return rows, len(rows)

    conn = get_sqlite_conn()
    c = conn.cursor()
    fts_query = _build_fts_query(query)

    extra_conditions = []
    extra_params = []
    if executed_by:
        extra_conditions.append('c.executed_by = ?')
        extra_params.append(executed_by)
    if status:
        extra_conditions.append('c.status = ?')
        extra_params.append(status)
    if date_from:
        extra_conditions.append('c.date >= ?')
        extra_params.append(date_from)
    if date_to:
        extra_conditions.append('c.date <= ?')
        extra_params.append(date_to)
    extra_where = (' AND ' + ' AND '.join(extra_conditions)) if extra_conditions else ''

    try:
        if fts_query:
            c.execute(f'''SELECT c.id,c.ticket,c.query,c.executed_by,c.date,c.status,c.notes,c.created_at
                         FROM corrections_fts fts JOIN corrections c ON c.id=fts.rowid
                         WHERE corrections_fts MATCH ?{extra_where}
                         ORDER BY rank LIMIT ?''', [fts_query] + extra_params + [limit])
        else:
            raise ValueError("Empty FTS query")
    except Exception:
        like = f'%{query}%'
        c.execute(f'''SELECT id,ticket,query,executed_by,date,status,notes,created_at FROM corrections c
                     WHERE (ticket LIKE ? OR query LIKE ? OR notes LIKE ? OR executed_by LIKE ?){extra_where}
                     ORDER BY date DESC LIMIT ?''', [like, like, like, like] + extra_params + [limit])
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows, len(rows)

# ─── EXPORT ────────────────────────────────────────────────────────────────────

def get_all_for_export():
    if is_oracle():
        conn = get_oracle_conn()
        cursor = conn.cursor()
        cursor.execute('''SELECT id,ticket,query,executed_by,TO_CHAR(date_val,'YYYY-MM-DD') AS "date",
                                 status,notes,TO_CHAR(created_at,'YYYY-MM-DD HH24:MI:SS') AS created_at
                          FROM corrections ORDER BY date_val DESC, id DESC''')
        cols = [d[0].lower() for d in cursor.description]
        rows = [dict(zip(cols, r)) for r in cursor.fetchall()]
        conn.close(); return rows
    conn = get_sqlite_conn()
    c = conn.cursor()
    c.execute('SELECT id,ticket,query,executed_by,date,status,notes,created_at FROM corrections ORDER BY date DESC,id DESC')
    rows = [dict(r) for r in c.fetchall()]
    conn.close(); return rows

def bulk_insert(records):
    if is_oracle():
        conn = get_oracle_conn(); cursor = conn.cursor(); inserted = 0
        for rec in records:
            try:
                cursor.execute('''INSERT INTO corrections(id,ticket,query,executed_by,date_val,status,notes)
                                  VALUES(corrections_seq.NEXTVAL,:t,:q,:e,TO_DATE(:d,'YYYY-MM-DD'),:s,:n)''',
                               {'t': rec.get('ticket',''), 'q': rec.get('query',''),
                                'e': rec.get('executed_by','Imported'), 'd': rec.get('date', date.today().isoformat()),
                                's': rec.get('status','Completed'), 'n': rec.get('notes','')})
                inserted += 1
            except Exception: pass
        conn.commit(); conn.close(); return inserted

    conn = get_sqlite_conn(); c = conn.cursor(); inserted = 0
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    for rec in records:
        try:
            c.execute('''INSERT INTO corrections(ticket,query,executed_by,date,status,notes,created_at,updated_at)
                         VALUES(?,?,?,?,?,?,?,?)''',
                      (rec.get('ticket','').strip(), rec.get('query','').strip(),
                       rec.get('executed_by','Imported').strip(), rec.get('date', date.today().isoformat()),
                       rec.get('status','Completed'), rec.get('notes',''), now, now))
            inserted += 1
        except Exception: pass
    conn.commit(); conn.close(); return inserted

def get_tickets_set():
    """Return set of (ticket, date) tuples for duplicate detection."""
    if is_oracle():
        conn = get_oracle_conn(); cursor = conn.cursor()
        cursor.execute("SELECT ticket, TO_CHAR(date_val,'YYYY-MM-DD') FROM corrections")
        result = {(r[0], r[1]) for r in cursor.fetchall()}; conn.close(); return result
    conn = get_sqlite_conn(); c = conn.cursor()
    c.execute('SELECT ticket, date FROM corrections')
    result = {(r[0], r[1]) for r in c.fetchall()}; conn.close(); return result

# ─── ORACLE MIGRATION ──────────────────────────────────────────────────────────

def test_oracle_connection(oracle_cfg):
    try:
        import oracledb
        if oracle_cfg.get('service_type') == 'sid':
            dsn = oracledb.makedsn(oracle_cfg.get('host'), oracle_cfg.get('port', 1521), sid=oracle_cfg.get('service_name'))
        else:
            dsn = oracledb.makedsn(oracle_cfg.get('host'), oracle_cfg.get('port', 1521), service_name=oracle_cfg.get('service_name'))
        conn = oracledb.connect(
            user=oracle_cfg.get('username'),
            password=oracle_cfg.get('password'),
            dsn=dsn
        )
        cursor = conn.cursor()
        cursor.execute('SELECT 1 FROM DUAL')
        conn.close()
        return {'success': True, 'message': 'Connection successful! Oracle DB is reachable.'}
    except Exception as e:
        return {'success': False, 'error': str(e)}

def migrate_to_oracle():
    """Copy all SQLite data to Oracle and switch the active database."""
    try:
        # Read all SQLite records first
        old_config = get_config()
        conn_s = sqlite3.connect(old_config['sqlite']['path'])
        conn_s.row_factory = sqlite3.Row
        records = [dict(r) for r in conn_s.execute('SELECT * FROM corrections').fetchall()]
        conn_s.close()

        # Create Oracle tables
        _init_oracle_tables()

        # Insert all records
        conn_o = get_oracle_conn()
        cursor = conn_o.cursor()
        for rec in records:
            cursor.execute('''INSERT INTO corrections(id,ticket,query,executed_by,date_val,status,notes)
                              VALUES(corrections_seq.NEXTVAL,:t,:q,:e,TO_DATE(:d,'YYYY-MM-DD'),:s,:n)''',
                           {'t': rec['ticket'], 'q': rec['query'], 'e': rec['executed_by'],
                            'd': rec['date'], 's': rec['status'], 'n': rec.get('notes','')})
        conn_o.commit(); conn_o.close()

        # Switch config
        config = get_config()
        config['db_type'] = 'oracle'
        save_config(config)
        return {'success': True, 'migrated': len(records), 'message': f'Migrated {len(records)} records to Oracle DB.'}
    except Exception as e:
        return {'success': False, 'error': str(e)}

def migrate_to_sqlite():
    """Copy all Oracle data to SQLite and switch back."""
    try:
        records, _ = _get_corrections_oracle('','','','','',1,100000,'date','desc')
        config = get_config()
        config['db_type'] = 'sqlite'
        save_config(config)
        _init_sqlite_tables()
        inserted = bulk_insert(records)
        return {'success': True, 'migrated': inserted}
    except Exception as e:
        config = get_config(); config['db_type'] = 'oracle'; save_config(config)
        return {'success': False, 'error': str(e)}
