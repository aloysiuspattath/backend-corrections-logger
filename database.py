import os
import json
import oracledb
from datetime import datetime, date

DB_CONFIG_FILE = 'db_config.json'
pool = None

def get_config():
    if os.path.exists(DB_CONFIG_FILE):
        with open(DB_CONFIG_FILE, 'r') as f:
            return json.load(f)
    return {}

def init_pool():
    global pool
    if pool is not None:
        return
    config = get_config()
    cfg = config.get('oracle', {})
    
    oracledb.defaults.fetch_lobs = False
    
    if cfg.get('service_type') == 'sid':
        dsn = oracledb.makedsn(cfg.get('host', 'localhost'), cfg.get('port', 1521), sid=cfg.get('service_name', 'XE'))
    else:
        dsn = oracledb.makedsn(cfg.get('host', 'localhost'), cfg.get('port', 1521), service_name=cfg.get('service_name', 'XEPDB1'))
    
    pool = oracledb.create_pool(
        user=cfg.get('username', 'appuser'),
        password=cfg.get('password', 'feed#app#123'),
        dsn=dsn,
        min=2,
        max=10,
        increment=1
    )

def get_connection():
    if pool is None:
        init_pool()
    return pool.acquire()

def release_connection(conn):
    if pool and conn:
        pool.release(conn)

def init_tables():
    conn = get_connection()
    cursor = conn.cursor()
    
    # Check if bcp_users exists
    cursor.execute("SELECT count(*) FROM user_tables WHERE table_name = 'BCP_USERS'")
    if cursor.fetchone()[0] == 0:
        cursor.execute("""
            CREATE TABLE bcp_users (
                id NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                username VARCHAR2(50) NOT NULL UNIQUE,
                password_hash VARCHAR2(255),
                display_name VARCHAR2(100) NOT NULL,
                role VARCHAR2(20) DEFAULT 'user' NOT NULL,
                active NUMBER(1) DEFAULT 1 NOT NULL,
                is_external NUMBER(1) DEFAULT 0 NOT NULL,
                auth_source VARCHAR2(50) DEFAULT 'local',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # Insert default admin
        import auth
        pw = auth.hash_password('admin123')
        cursor.execute("""
            INSERT INTO bcp_users (username, password_hash, display_name, role)
            VALUES (:1, :2, :3, :4)
        """, ('admin', pw, 'Administrator', 'admin'))
        conn.commit()
    else:
        # Patch existing table if it doesn't have the new columns
        try:
            cursor.execute("ALTER TABLE bcp_users ADD (is_external NUMBER(1) DEFAULT 0 NOT NULL)")
            cursor.execute("ALTER TABLE bcp_users ADD (auth_source VARCHAR2(50) DEFAULT 'local')")
            # Make password nullable for external users
            cursor.execute("ALTER TABLE bcp_users MODIFY (password_hash NULL)")
        except oracledb.DatabaseError as e:
            pass # Columns likely already exist

    # Check if bcp_corrections exists
    cursor.execute("SELECT count(*) FROM user_tables WHERE table_name = 'BCP_CORRECTIONS'")
    if cursor.fetchone()[0] == 0:
        cursor.execute("""
            CREATE TABLE bcp_corrections (
                id NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                ticket VARCHAR2(100) NOT NULL,
                query CLOB NOT NULL,
                executed_by VARCHAR2(100) NOT NULL,
                date_val DATE NOT NULL,
                status VARCHAR2(50) DEFAULT 'Completed' NOT NULL,
                notes CLOB,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
    
    cursor.close()
    release_connection(conn)

def get_corrections(search='', executed_by='', date_from='', date_to='', status='', page=1, per_page=20, sort_col='date', sort_dir='desc'):
    conn = get_connection()
    cursor = conn.cursor()
    conditions = []
    params = {}

    if search:
        conditions.append("(LOWER(ticket) LIKE LOWER(:search) OR LOWER(query) LIKE LOWER(:search) OR LOWER(notes) LIKE LOWER(:search))")
        params['search'] = f"%{search}%"
    if executed_by:
        conditions.append("executed_by = :executed_by")
        params['executed_by'] = executed_by
    if date_from:
        conditions.append("date_val >= TO_DATE(:df, 'YYYY-MM-DD')")
        params['df'] = date_from
    if date_to:
        conditions.append("date_val <= TO_DATE(:dt, 'YYYY-MM-DD')")
        params['dt'] = date_to
    if status:
        conditions.append("status = :status")
        params['status'] = status

    where = ' AND '.join(conditions) if conditions else '1=1'
    
    valid_sort = {'ticket': 'ticket', 'executed_by': 'executed_by', 'date': 'date_val', 'status': 'status'}
    order_col = valid_sort.get(sort_col, 'date_val')
    order_dir = 'ASC' if sort_dir.lower() == 'asc' else 'DESC'

    cursor.execute(f'SELECT COUNT(*) FROM bcp_corrections WHERE {where}', params)
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
                    FROM bcp_corrections WHERE {where}
                    ORDER BY {order_col} {order_dir}
                ) c WHERE ROWNUM <= :end_row
              ) WHERE rnum > :start_row'''

    cursor.execute(sql, params)
    cols = [d[0].lower() for d in cursor.description]
    rows = [dict(zip(cols, r)) for r in cursor.fetchall()]
    
    cursor.close()
    release_connection(conn)
    return rows, total

def get_correction(cid):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''SELECT id, ticket, query, executed_by, TO_CHAR(date_val,'YYYY-MM-DD') AS "date",
                             status, notes, TO_CHAR(created_at,'YYYY-MM-DD HH24:MI:SS') AS created_at
                      FROM bcp_corrections WHERE id = :id''', {'id': cid})
    cols = [d[0].lower() for d in cursor.description]
    row = cursor.fetchone()
    cursor.close()
    release_connection(conn)
    return dict(zip(cols, row)) if row else None

def add_correction(data):
    conn = get_connection()
    cursor = conn.cursor()
    new_id = cursor.var(int)
    cursor.execute('''INSERT INTO bcp_corrections(ticket, query, executed_by, date_val, status, notes)
                      VALUES(:t, :q, :e, TO_DATE(:d,'YYYY-MM-DD'), :s, :n)
                      RETURNING id INTO :nid''',
                   {'t': data.get('ticket','').strip(), 'q': data.get('query','').strip(),
                    'e': data.get('executed_by','').strip(), 'd': data.get('date', date.today().isoformat()),
                    's': data.get('status','Completed'), 'n': data.get('notes',''), 'nid': new_id})
    conn.commit()
    rid = new_id.getvalue()[0]
    cursor.execute('''SELECT id, ticket, query, executed_by, TO_CHAR(date_val,'YYYY-MM-DD') AS "date",
                             status, notes, TO_CHAR(created_at,'YYYY-MM-DD HH24:MI:SS') AS created_at
                      FROM bcp_corrections WHERE id = :id''', {'id': rid})
    cols = [d[0].lower() for d in cursor.description]
    row = dict(zip(cols, cursor.fetchone()))
    cursor.close()
    release_connection(conn)
    return row

def update_correction(cid, data):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''UPDATE bcp_corrections 
                      SET ticket=:t, query=:q, executed_by=:e, date_val=TO_DATE(:d,'YYYY-MM-DD'), 
                          status=:s, notes=:n, updated_at=CURRENT_TIMESTAMP
                      WHERE id=:id''',
                   {'t': data.get('ticket','').strip(), 'q': data.get('query','').strip(),
                    'e': data.get('executed_by','').strip(), 'd': data.get('date'),
                    's': data.get('status','Completed'), 'n': data.get('notes',''), 'id': cid})
    conn.commit()
    affected = cursor.rowcount
    if affected == 0:
        cursor.close()
        release_connection(conn)
        return None
        
    cursor.execute('''SELECT id, ticket, query, executed_by, TO_CHAR(date_val,'YYYY-MM-DD') AS "date",
                             status, notes FROM bcp_corrections WHERE id=:id''', {'id': cid})
    cols = [d[0].lower() for d in cursor.description]
    row = dict(zip(cols, cursor.fetchone()))
    cursor.close()
    release_connection(conn)
    return row

def delete_correction(cid):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM bcp_corrections WHERE id=:id', {'id': cid})
    conn.commit()
    affected = cursor.rowcount
    cursor.close()
    release_connection(conn)
    return affected > 0

def get_stats():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''SELECT COUNT(*),
                             SUM(CASE WHEN TRUNC(date_val)=TRUNC(SYSDATE) THEN 1 ELSE 0 END),
                             SUM(CASE WHEN date_val>=TRUNC(SYSDATE,'IW') THEN 1 ELSE 0 END),
                             SUM(CASE WHEN date_val>=TRUNC(SYSDATE,'MM') THEN 1 ELSE 0 END)
                      FROM bcp_corrections''')
    r = cursor.fetchone()
    cursor.close()
    release_connection(conn)
    return {'total': r[0], 'today': r[1] or 0, 'week': r[2] or 0, 'month': r[3] or 0}

def get_executors():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT DISTINCT executed_by FROM bcp_corrections ORDER BY executed_by')
    result = [r[0] for r in cursor.fetchall()]
    cursor.close()
    release_connection(conn)
    return result

def get_activity(days=14):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        WITH dates AS (
            SELECT TRUNC(SYSDATE) - LEVEL + 1 AS d 
            FROM DUAL CONNECT BY LEVEL <= :days
        )
        SELECT TO_CHAR(d.d, 'YYYY-MM-DD'), COUNT(c.id)
        FROM dates d
        LEFT JOIN bcp_corrections c ON TRUNC(c.date_val) = d.d
        GROUP BY d.d
        ORDER BY d.d ASC
    ''', {'days': days})
    rows = [{'date': r[0], 'count': r[1]} for r in cursor.fetchall()]
    cursor.close()
    release_connection(conn)
    return rows
