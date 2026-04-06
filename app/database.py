"""
GIO Telemetry — Database Layer
Connection pool, schema initialization, and all CRUD operations.
"""
import datetime

import psycopg2
import psycopg2.extras
import psycopg2.pool

from app.config import Config

# ── Connection Pool ──
_pool = None


def init_db():
    """Create the coordinates table and indexes if they don't exist."""
    conn = psycopg2.connect(**Config.DB_CONFIG)
    try:
        c = conn.cursor()
        c.execute('''
            CREATE TABLE IF NOT EXISTS coordinates (
                id        SERIAL PRIMARY KEY,
                timestamp TIMESTAMP,
                lat       DOUBLE PRECISION,
                lon       DOUBLE PRECISION,
                device    VARCHAR(100),
                raw_ts    BIGINT
            )
        ''')
        c.execute('CREATE INDEX IF NOT EXISTS idx_coordinates_ts ON coordinates(timestamp)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_coordinates_device ON coordinates(device)')
        conn.commit()
        print("[DB] Tabla 'coordinates' lista.")
    finally:
        conn.close()


def init_pool():
    """Initialize the threaded connection pool."""
    global _pool
    _pool = psycopg2.pool.ThreadedConnectionPool(2, 10, **Config.DB_CONFIG)
    print("[DB] Pool de conexiones inicializado.")


def get_conn():
    """Get a connection from the pool."""
    return _pool.getconn()


def release_conn(conn):
    """Return a connection to the pool."""
    _pool.putconn(conn)


# ══════════════════════════════════════════
#  DATA OPERATIONS
# ══════════════════════════════════════════

def insert_data(lat, lon, device, raw_ts):
    """Insert a new GPS coordinate into the database."""
    colombia_time = (
        datetime.datetime.utcfromtimestamp(raw_ts / 1000)
        - datetime.timedelta(hours=5)
    )
    conn = get_conn()
    try:
        c = conn.cursor()
        c.execute(
            'INSERT INTO coordinates (timestamp, lat, lon, device, raw_ts) VALUES (%s, %s, %s, %s, %s)',
            (colombia_time, lat, lon, device, raw_ts),
        )
        conn.commit()
    finally:
        release_conn(conn)


def fetch_latest():
    """Fetch the most recent coordinate."""
    conn = get_conn()
    try:
        c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        c.execute('SELECT id, timestamp, lat, lon, device FROM coordinates ORDER BY id DESC LIMIT 1')
        row = c.fetchone()
        if row:
            row = dict(row)
            row['timestamp'] = str(row['timestamp'])
            return row
        return None
    finally:
        release_conn(conn)


def fetch_history(limit=None):
    """Fetch the N most recent coordinates."""
    limit = limit or Config.HISTORY_LIMIT
    conn = get_conn()
    try:
        c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        c.execute(
            'SELECT timestamp, lat, lon, device FROM coordinates ORDER BY id DESC LIMIT %s',
            (limit,),
        )
        rows = [dict(r) for r in c.fetchall()]
        for r in rows:
            r['timestamp'] = str(r['timestamp'])
        return rows
    finally:
        release_conn(conn)


def fetch_history_range(start_ts, end_ts, limit=500):
    """Fetch coordinates within a time range."""
    conn = get_conn()
    try:
        c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        c.execute(
            '''SELECT timestamp, lat, lon, device FROM coordinates
               WHERE timestamp >= %s AND timestamp <= %s
               ORDER BY timestamp ASC LIMIT %s''',
            (start_ts, end_ts, limit),
        )
        rows = [dict(r) for r in c.fetchall()]
        for r in rows:
            r['timestamp'] = str(r['timestamp'])
        return rows
    finally:
        release_conn(conn)


def fetch_stats():
    """Fetch aggregate statistics (total, first, last)."""
    conn = get_conn()
    try:
        c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        c.execute('SELECT COUNT(*) as total FROM coordinates')
        total = c.fetchone()['total']
        c.execute('SELECT MIN(timestamp) as first_ts, MAX(timestamp) as last_ts FROM coordinates')
        row = dict(c.fetchone())
        return {
            'total_records': total,
            'first_record': str(row['first_ts']) if row['first_ts'] else None,
            'last_record': str(row['last_ts']) if row['last_ts'] else None,
        }
    finally:
        release_conn(conn)


# ══════════════════════════════════════════
#  FLUSH OPERATIONS
# ══════════════════════════════════════════

def count_records_for_flush(mode, start=None, end=None, days=None):
    """Count how many records would be deleted — preview without deleting."""
    conn = get_conn()
    try:
        c = conn.cursor()
        if mode == 'all':
            c.execute('SELECT COUNT(*) FROM coordinates')
        elif mode == 'range':
            c.execute(
                'SELECT COUNT(*) FROM coordinates WHERE timestamp >= %s AND timestamp <= %s',
                (start, end),
            )
        elif mode == 'older_than':
            cutoff = datetime.datetime.utcnow() - datetime.timedelta(hours=5) - datetime.timedelta(days=days)
            c.execute('SELECT COUNT(*) FROM coordinates WHERE timestamp < %s', (cutoff,))
        else:
            return 0
        return c.fetchone()[0]
    finally:
        release_conn(conn)


def flush_data(mode, start=None, end=None, days=None):
    """Delete records based on mode. Returns number of deleted rows."""
    conn = get_conn()
    try:
        c = conn.cursor()
        if mode == 'all':
            c.execute('DELETE FROM coordinates')
        elif mode == 'range':
            c.execute(
                'DELETE FROM coordinates WHERE timestamp >= %s AND timestamp <= %s',
                (start, end),
            )
        elif mode == 'older_than':
            cutoff = datetime.datetime.utcnow() - datetime.timedelta(hours=5) - datetime.timedelta(days=days)
            c.execute('DELETE FROM coordinates WHERE timestamp < %s', (cutoff,))
        else:
            return 0
        deleted = c.rowcount
        conn.commit()
        return deleted
    finally:
        release_conn(conn)


def count_total():
    """Quick total record count."""
    conn = get_conn()
    try:
        c = conn.cursor()
        c.execute('SELECT COUNT(*) FROM coordinates')
        return c.fetchone()[0]
    finally:
        release_conn(conn)
