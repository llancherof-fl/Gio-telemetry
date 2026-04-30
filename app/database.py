"""
GIO Telemetry — Database Layer
Connection pool, schema initialization, and all CRUD operations.
"""
import datetime
import math

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
                raw_ts    BIGINT,
                trip_id   VARCHAR(96),
                event_id  VARCHAR(96),
                event_type VARCHAR(24),
                trip_state VARCHAR(24),
                seq        INTEGER,
                reason     VARCHAR(48),
                client_ts_ms BIGINT
            )
        ''')
        c.execute('ALTER TABLE coordinates ADD COLUMN IF NOT EXISTS trip_id VARCHAR(96)')
        c.execute('ALTER TABLE coordinates ADD COLUMN IF NOT EXISTS event_id VARCHAR(96)')
        c.execute('ALTER TABLE coordinates ADD COLUMN IF NOT EXISTS event_type VARCHAR(24)')
        c.execute('ALTER TABLE coordinates ADD COLUMN IF NOT EXISTS trip_state VARCHAR(24)')
        c.execute('ALTER TABLE coordinates ADD COLUMN IF NOT EXISTS seq INTEGER')
        c.execute('ALTER TABLE coordinates ADD COLUMN IF NOT EXISTS reason VARCHAR(48)')
        c.execute('ALTER TABLE coordinates ADD COLUMN IF NOT EXISTS client_ts_ms BIGINT')
        c.execute('CREATE INDEX IF NOT EXISTS idx_coordinates_ts ON coordinates(timestamp)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_coordinates_device ON coordinates(device)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_coordinates_device_ts ON coordinates(device, timestamp)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_coordinates_trip_id_ts ON coordinates(trip_id, timestamp)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_coordinates_event_type_ts ON coordinates(event_type, timestamp)')
        # === P3-S1: Tabla para datos del sensor MPU6050 ===
        c.execute('''
            CREATE TABLE IF NOT EXISTS sensor_data (
                id SERIAL PRIMARY KEY,
                vehicle_id VARCHAR(50) NOT NULL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                ax DECIMAL(10, 6),
                ay DECIMAL(10, 6),
                az DECIMAL(10, 6),
                gx DECIMAL(10, 6),
                gy DECIMAL(10, 6),
                gz DECIMAL(10, 6),
                lat DOUBLE PRECISION,
                lon DOUBLE PRECISION,
                acc_mag DECIMAL(10, 6),
                trip_id VARCHAR(96),
                event_id VARCHAR(96),
                seq INTEGER,
                client_ts_ms BIGINT,
                sensor_source VARCHAR(24),
                evento_frenada BOOLEAN DEFAULT FALSE,
                evento_giro BOOLEAN DEFAULT FALSE
            )
        ''')
        c.execute('ALTER TABLE sensor_data ADD COLUMN IF NOT EXISTS lat DOUBLE PRECISION')
        c.execute('ALTER TABLE sensor_data ADD COLUMN IF NOT EXISTS lon DOUBLE PRECISION')
        c.execute('ALTER TABLE sensor_data ADD COLUMN IF NOT EXISTS acc_mag DECIMAL(10, 6)')
        c.execute('ALTER TABLE sensor_data ADD COLUMN IF NOT EXISTS trip_id VARCHAR(96)')
        c.execute('ALTER TABLE sensor_data ADD COLUMN IF NOT EXISTS event_id VARCHAR(96)')
        c.execute('ALTER TABLE sensor_data ADD COLUMN IF NOT EXISTS seq INTEGER')
        c.execute('ALTER TABLE sensor_data ADD COLUMN IF NOT EXISTS client_ts_ms BIGINT')
        c.execute('ALTER TABLE sensor_data ADD COLUMN IF NOT EXISTS sensor_source VARCHAR(24)')
        c.execute('''
            CREATE INDEX IF NOT EXISTS idx_sensor_vehicle_time
            ON sensor_data(vehicle_id, timestamp)
        ''')
        c.execute('''
            CREATE INDEX IF NOT EXISTS idx_sensor_trip_time
            ON sensor_data(trip_id, timestamp)
        ''')
        c.execute('''
            CREATE INDEX IF NOT EXISTS idx_sensor_event_flags_time
            ON sensor_data(evento_frenada, evento_giro, timestamp)
        ''')

        conn.commit()
        print("[DB] Tabla 'coordinates' lista.")
        print("[DB] Tabla 'sensor_data' lista.")
    finally:
        conn.close()


def init_pool():
    """Initialize the threaded connection pool."""
    global _pool
    min_conn = max(1, Config.DB_POOL_MIN)
    max_conn = max(min_conn, Config.DB_POOL_MAX)
    _pool = psycopg2.pool.ThreadedConnectionPool(min_conn, max_conn, **Config.DB_CONFIG)
    print("[DB] Pool de conexiones inicializado.")


def get_conn():
    """Get a connection from the pool."""
    return _pool.getconn()


def release_conn(conn):
    """Return a connection to the pool."""
    _pool.putconn(conn)


def _to_colombia_time(raw_ts):
    """Convert raw timestamp millis to UTC-5 naive datetime, with safe fallback."""
    try:
        ts_ms = int(raw_ts)
        if ts_ms <= 0:
            raise ValueError()
        return datetime.datetime.utcfromtimestamp(ts_ms / 1000) - datetime.timedelta(hours=5)
    except (ValueError, TypeError, OverflowError):
        return datetime.datetime.utcnow() - datetime.timedelta(hours=5)


# ══════════════════════════════════════════
#  DATA OPERATIONS
# ══════════════════════════════════════════

def insert_data(
    lat,
    lon,
    device,
    raw_ts,
    trip_id=None,
    event_id=None,
    event_type=None,
    trip_state=None,
    seq=None,
    reason=None,
    client_ts_ms=None,
):
    """Insert a new GPS coordinate into the database."""
    colombia_time = _to_colombia_time(raw_ts)
    conn = get_conn()
    try:
        c = conn.cursor()
        c.execute(
            '''INSERT INTO coordinates (
                   timestamp, lat, lon, device, raw_ts,
                   trip_id, event_id, event_type, trip_state, seq, reason, client_ts_ms
               ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)''',
            (
                colombia_time, lat, lon, device, raw_ts,
                trip_id, event_id, event_type, trip_state, seq, reason, client_ts_ms,
            ),
        )
        conn.commit()
    finally:
        release_conn(conn)


def insert_data_batch(rows):
    """Insert many GPS rows in a single transaction. Returns inserted count."""
    if not rows:
        return 0

    values = []
    for row in rows:
        if isinstance(row, dict):
            lat = row.get('lat')
            lon = row.get('lon')
            device = row.get('device')
            raw_ts = row.get('raw_ts')
            trip_id = row.get('trip_id')
            event_id = row.get('event_id')
            event_type = row.get('event_type')
            trip_state = row.get('trip_state')
            seq = row.get('seq')
            reason = row.get('reason')
            client_ts_ms = row.get('client_ts_ms')
        else:
            try:
                lat, lon, device, raw_ts = row
            except (ValueError, TypeError):
                continue
            trip_id = None
            event_id = None
            event_type = None
            trip_state = None
            seq = None
            reason = None
            client_ts_ms = None

        try:
            lat_f = float(lat)
            lon_f = float(lon)
        except (ValueError, TypeError):
            continue

        try:
            raw_ts_i = int(raw_ts)
        except (ValueError, TypeError):
            raw_ts_i = 0

        try:
            seq_i = int(seq) if seq is not None else None
        except (ValueError, TypeError):
            seq_i = None

        try:
            client_ts_i = int(client_ts_ms) if client_ts_ms is not None else None
        except (ValueError, TypeError):
            client_ts_i = None

        trip_id_s = (str(trip_id).strip()[:96] if trip_id else None)
        event_id_s = (str(event_id).strip()[:96] if event_id else None)
        event_type_s = (str(event_type).strip()[:24] if event_type else None)
        trip_state_s = (str(trip_state).strip()[:24] if trip_state else None)
        reason_s = (str(reason).strip()[:48] if reason else None)

        values.append((
            _to_colombia_time(raw_ts_i),
            lat_f,
            lon_f,
            (device or 'Desconocido')[:100],
            raw_ts_i,
            trip_id_s,
            event_id_s,
            event_type_s,
            trip_state_s,
            seq_i,
            reason_s,
            client_ts_i,
        ))

    if not values:
        return 0

    conn = get_conn()
    try:
        c = conn.cursor()
        psycopg2.extras.execute_values(
            c,
            '''INSERT INTO coordinates (
                   timestamp, lat, lon, device, raw_ts,
                   trip_id, event_id, event_type, trip_state, seq, reason, client_ts_ms
               )
               VALUES %s''',
            values,
            template='(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)',
            page_size=1000,
        )
        conn.commit()
        return len(values)
    finally:
        release_conn(conn)


def fetch_latest(device=None):
    """Fetch the most recent coordinate, optionally filtered by device."""
    conn = get_conn()
    try:
        c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        if device:
            c.execute(
                '''SELECT id, timestamp, lat, lon, device
                   , trip_id, event_id, event_type, trip_state, seq, reason, client_ts_ms
                   FROM coordinates
                   WHERE device = %s
                   ORDER BY id DESC
                   LIMIT 1''',
                (device,),
            )
        else:
            c.execute(
                '''SELECT id, timestamp, lat, lon, device
                   , trip_id, event_id, event_type, trip_state, seq, reason, client_ts_ms
                   FROM coordinates
                   ORDER BY id DESC
                   LIMIT 1'''
            )
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
            '''SELECT timestamp, lat, lon, device
               , trip_id, event_id, event_type, trip_state, seq, reason, client_ts_ms
               FROM coordinates
               ORDER BY id DESC
               LIMIT %s''',
            (limit,),
        )
        rows = [dict(r) for r in c.fetchall()]
        for r in rows:
            r['timestamp'] = str(r['timestamp'])
        return rows
    finally:
        release_conn(conn)


def fetch_history_range(start_ts, end_ts, limit=500, offset=0, device=None):
    """Fetch coordinates within a time range, optionally filtered by device."""
    conn = get_conn()
    try:
        c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        if device:
            c.execute(
                '''SELECT timestamp, lat, lon, device
                   , trip_id, event_id, event_type, trip_state, seq, reason, client_ts_ms
                   FROM coordinates
                   WHERE timestamp >= %s
                     AND timestamp <= %s
                     AND device = %s
                   ORDER BY timestamp ASC
                   LIMIT %s OFFSET %s''',
                (start_ts, end_ts, device, limit, offset),
            )
        else:
            c.execute(
                '''SELECT timestamp, lat, lon, device
                   , trip_id, event_id, event_type, trip_state, seq, reason, client_ts_ms
                   FROM coordinates
                   WHERE timestamp >= %s
                     AND timestamp <= %s
                   ORDER BY timestamp ASC
                   LIMIT %s OFFSET %s''',
                (start_ts, end_ts, limit, offset),
            )
        rows = [dict(r) for r in c.fetchall()]
        for r in rows:
            r['timestamp'] = str(r['timestamp'])
        return rows
    finally:
        release_conn(conn)


def fetch_trip_summaries(start_ts, end_ts, device=None, limit=200, offset=0):
    """
    Fetch trip sessions grouped by trip_id for a time range.
    A trip is considered closed when it has at least one trip_end event.
    """
    conn = get_conn()
    try:
        c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        if device:
            c.execute(
                '''SELECT
                       trip_id,
                       MIN(timestamp) AS start_ts,
                       MAX(timestamp) AS end_ts,
                       MAX(device) AS device,
                       COUNT(*) AS point_count,
                       SUM(CASE WHEN event_type = 'trip_start' THEN 1 ELSE 0 END) AS start_events,
                       SUM(CASE WHEN event_type = 'trip_end' THEN 1 ELSE 0 END) AS end_events
                   FROM coordinates
                   WHERE timestamp >= %s
                     AND timestamp <= %s
                     AND device = %s
                     AND trip_id IS NOT NULL
                     AND trip_id <> ''
                   GROUP BY trip_id
                   ORDER BY MAX(timestamp) DESC
                   LIMIT %s OFFSET %s''',
                (start_ts, end_ts, device, limit, offset),
            )
        else:
            c.execute(
                '''SELECT
                       trip_id,
                       MIN(timestamp) AS start_ts,
                       MAX(timestamp) AS end_ts,
                       MAX(device) AS device,
                       COUNT(*) AS point_count,
                       SUM(CASE WHEN event_type = 'trip_start' THEN 1 ELSE 0 END) AS start_events,
                       SUM(CASE WHEN event_type = 'trip_end' THEN 1 ELSE 0 END) AS end_events
                   FROM coordinates
                   WHERE timestamp >= %s
                     AND timestamp <= %s
                     AND trip_id IS NOT NULL
                     AND trip_id <> ''
                   GROUP BY trip_id
                   ORDER BY MAX(timestamp) DESC
                   LIMIT %s OFFSET %s''',
                (start_ts, end_ts, limit, offset),
            )

        rows = [dict(r) for r in c.fetchall()]
        for row in rows:
            start_dt = row.get('start_ts')
            end_dt = row.get('end_ts')
            row['start_ts'] = str(start_dt) if start_dt else None
            row['end_ts'] = str(end_dt) if end_dt else None
            row['point_count'] = int(row.get('point_count') or 0)
            row['start_events'] = int(row.get('start_events') or 0)
            row['end_events'] = int(row.get('end_events') or 0)
            row['status'] = 'closed' if row['end_events'] > 0 else 'open'
            if start_dt and end_dt:
                row['duration_seconds'] = max(0, int((end_dt - start_dt).total_seconds()))
            else:
                row['duration_seconds'] = 0
        return rows
    finally:
        release_conn(conn)


def fetch_trip_points(trip_id, limit=5000, offset=0):
    """Fetch all points for a specific trip_id ordered by timestamp ASC."""
    conn = get_conn()
    try:
        c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        c.execute(
            '''SELECT timestamp, lat, lon, device,
                      trip_id, event_id, event_type, trip_state, seq, reason, client_ts_ms
               FROM coordinates
               WHERE trip_id = %s
               ORDER BY timestamp ASC
               LIMIT %s OFFSET %s''',
            (trip_id, limit, offset),
        )
        rows = [dict(r) for r in c.fetchall()]
        for r in rows:
            r['timestamp'] = str(r['timestamp'])
        return rows
    finally:
        release_conn(conn)


def fetch_nearest_point(lat, lon, start_ts, end_ts, delta_deg, device=None):
    """
    Return up to 300 rows inside a bounding box around (lat, lon) for a time range.
    The caller selects the exact nearest point via Haversine to avoid a full-table
    scan. Uses the existing (device, timestamp) or timestamp B-tree index as a
    range prefilter — no spatial index required.
    """
    conn = get_conn()
    try:
        c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        lat_min = lat - delta_deg
        lat_max = lat + delta_deg
        lon_min = lon - delta_deg
        lon_max = lon + delta_deg

        if device:
            c.execute(
                '''SELECT timestamp, lat, lon, device, trip_id, seq
                   FROM coordinates
                   WHERE timestamp >= %s
                     AND timestamp <= %s
                     AND device = %s
                     AND lat  BETWEEN %s AND %s
                     AND lon  BETWEEN %s AND %s
                   ORDER BY timestamp ASC
                   LIMIT 300''',
                (start_ts, end_ts, device,
                 lat_min, lat_max, lon_min, lon_max),
            )
        else:
            c.execute(
                '''SELECT timestamp, lat, lon, device, trip_id, seq
                   FROM coordinates
                   WHERE timestamp >= %s
                     AND timestamp <= %s
                     AND lat  BETWEEN %s AND %s
                     AND lon  BETWEEN %s AND %s
                   ORDER BY timestamp ASC
                   LIMIT 300''',
                (start_ts, end_ts,
                 lat_min, lat_max, lon_min, lon_max),
            )

        rows = [dict(r) for r in c.fetchall()]
        for r in rows:
            r['timestamp'] = str(r['timestamp'])
        return rows
    finally:
        release_conn(conn)


def fetch_devices(limit=200):
    """Fetch distinct device names for UI filters."""
    conn = get_conn()
    try:
        c = conn.cursor()
        c.execute(
            '''SELECT DISTINCT device
               FROM coordinates
               WHERE device IS NOT NULL
                 AND device <> ''
               ORDER BY device ASC
               LIMIT %s''',
            (limit,),
        )
        return [row[0] for row in c.fetchall()]
    finally:
        release_conn(conn)


def fetch_stats():
    """Fetch lightweight aggregate statistics (estimated total, first, last)."""
    conn = get_conn()
    try:
        c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        # reltuples provides an approximate row count from planner stats (fast, non-blocking).
        c.execute(
            '''SELECT COALESCE(reltuples::BIGINT, 0) AS total_est
               FROM pg_class
               WHERE oid = 'coordinates'::regclass'''
        )
        total = c.fetchone()['total_est']

        c.execute('SELECT timestamp FROM coordinates ORDER BY timestamp ASC LIMIT 1')
        first_row = c.fetchone()
        c.execute('SELECT timestamp FROM coordinates ORDER BY timestamp DESC LIMIT 1')
        last_row = c.fetchone()

        return {
            'total_records': total,
            'first_record': str(first_row['timestamp']) if first_row else None,
            'last_record': str(last_row['timestamp']) if last_row else None,
        }
    finally:
        release_conn(conn)


# ══════════════════════════════════════════
#  SENSOR DATA OPERATIONS (P3-S2: BLE + MPU6050)
# ══════════════════════════════════════════

def _to_float_or_none(value):
    try:
        if value is None:
            return None
        out = float(value)
        if math.isfinite(out):
            return out
        return None
    except (ValueError, TypeError):
        return None


def _to_int_or_none(value):
    try:
        if value is None:
            return None
        return int(value)
    except (ValueError, TypeError):
        return None


def _to_bool(value, default=False):
    if value is None:
        return bool(default)
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    safe = str(value).strip().lower()
    if safe in ('true', '1', 'yes', 'y', 'on'):
        return True
    if safe in ('false', '0', 'no', 'n', 'off'):
        return False
    return bool(default)


def _normalize_sensor_record(row):
    row = dict(row)
    row['timestamp'] = str(row['timestamp']) if row.get('timestamp') else None
    for key in ('ax', 'ay', 'az', 'gx', 'gy', 'gz', 'lat', 'lon', 'acc_mag'):
        if row.get(key) is not None:
            row[key] = float(row[key])
    return row


def _build_sensor_where(vehicle_id=None, trip_id=None, start=None, end=None, events_only=False):
    clauses = []
    params = []
    if events_only:
        clauses.append('(evento_frenada = TRUE OR evento_giro = TRUE)')
    if vehicle_id:
        clauses.append('vehicle_id = %s')
        params.append(vehicle_id)
    if trip_id:
        clauses.append('trip_id = %s')
        params.append(trip_id)
    if start:
        clauses.append('timestamp >= %s')
        params.append(start)
    if end:
        clauses.append('timestamp <= %s')
        params.append(end)
    where_sql = (' WHERE ' + ' AND '.join(clauses)) if clauses else ''
    return where_sql, params


def insert_sensor_data(
    vehicle_id,
    ax,
    ay,
    az,
    gx,
    gy,
    gz,
    evento_frenada,
    evento_giro,
    lat=None,
    lon=None,
    acc_mag=None,
    trip_id=None,
    event_id=None,
    seq=None,
    client_ts_ms=None,
    sensor_source='ble',
    timestamp=None,
):
    """Insert a single sensor reading and return the generated timestamp."""
    sensor_ts = timestamp
    if not sensor_ts:
        sensor_ts = _to_colombia_time(client_ts_ms) if client_ts_ms else (datetime.datetime.utcnow() - datetime.timedelta(hours=5))

    conn = get_conn()
    try:
        c = conn.cursor()
        c.execute(
            '''INSERT INTO sensor_data (
                   vehicle_id, timestamp, ax, ay, az, gx, gy, gz,
                   lat, lon, acc_mag, trip_id, event_id, seq, client_ts_ms, sensor_source,
                   evento_frenada, evento_giro
               )
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
               RETURNING timestamp''',
            (
                (vehicle_id or 'unknown')[:50],
                sensor_ts,
                _to_float_or_none(ax),
                _to_float_or_none(ay),
                _to_float_or_none(az),
                _to_float_or_none(gx),
                _to_float_or_none(gy),
                _to_float_or_none(gz),
                _to_float_or_none(lat),
                _to_float_or_none(lon),
                _to_float_or_none(acc_mag),
                (str(trip_id).strip()[:96] if trip_id else None),
                (str(event_id).strip()[:96] if event_id else None),
                _to_int_or_none(seq),
                _to_int_or_none(client_ts_ms),
                (str(sensor_source).strip()[:24] if sensor_source else None),
                _to_bool(evento_frenada),
                _to_bool(evento_giro),
            ),
        )
        result = c.fetchone()
        conn.commit()
        return str(result[0]) if result else None
    finally:
        release_conn(conn)


def insert_sensor_batch(rows):
    """Insert many sensor rows in one transaction. Returns inserted count."""
    if not rows:
        return 0

    brake_thr = max(0.0, float(Config.SENSOR_BRAKE_AX_G))
    turn_thr = max(0.0, float(Config.SENSOR_TURN_GZ_DPS))
    values = []

    for row in rows:
        if not isinstance(row, dict):
            continue

        ax = _to_float_or_none(row.get('ax'))
        ay = _to_float_or_none(row.get('ay'))
        az = _to_float_or_none(row.get('az'))
        gx = _to_float_or_none(row.get('gx'))
        gy = _to_float_or_none(row.get('gy'))
        gz = _to_float_or_none(row.get('gz'))
        if ax is None or ay is None or az is None:
            continue
        if gx is None:
            gx = 0.0
        if gy is None:
            gy = 0.0
        if gz is None:
            gz = 0.0

        raw_sensor_ts = _to_int_or_none(row.get('sensor_ts_ms'))
        raw_client_ts = _to_int_or_none(row.get('client_ts_ms'))
        sensor_ts = raw_sensor_ts or raw_client_ts
        timestamp = _to_colombia_time(sensor_ts) if sensor_ts else (datetime.datetime.utcnow() - datetime.timedelta(hours=5))

        lat = _to_float_or_none(row.get('lat'))
        lon = _to_float_or_none(row.get('lon'))
        acc_mag = _to_float_or_none(row.get('acc_mag'))
        if acc_mag is None:
            acc_mag = math.sqrt((ax * ax) + (ay * ay) + (az * az))

        evento_frenada = _to_bool(row.get('evento_frenada'), default=(abs(ax) >= brake_thr))
        evento_giro = _to_bool(row.get('evento_giro'), default=(abs(gz) >= turn_thr))

        values.append((
            (str(row.get('device') or row.get('vehicle_id') or 'unknown').strip()[:50]),
            timestamp,
            ax,
            ay,
            az,
            gx,
            gy,
            gz,
            lat,
            lon,
            acc_mag,
            (str(row.get('trip_id')).strip()[:96] if row.get('trip_id') else None),
            (str(row.get('event_id')).strip()[:96] if row.get('event_id') else None),
            _to_int_or_none(row.get('seq')),
            raw_client_ts,
            (str(row.get('sensor_source')).strip()[:24] if row.get('sensor_source') else 'ble'),
            evento_frenada,
            evento_giro,
        ))

    if not values:
        return 0

    conn = get_conn()
    try:
        c = conn.cursor()
        psycopg2.extras.execute_values(
            c,
            '''INSERT INTO sensor_data (
                   vehicle_id, timestamp, ax, ay, az, gx, gy, gz,
                   lat, lon, acc_mag, trip_id, event_id, seq, client_ts_ms, sensor_source,
                   evento_frenada, evento_giro
               ) VALUES %s''',
            values,
            template='(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)',
            page_size=500,
        )
        conn.commit()
        return len(values)
    finally:
        release_conn(conn)


def fetch_sensor_latest(vehicle_id=None, trip_id=None):
    """Fetch the latest sensor reading, optionally filtered by vehicle and/or trip."""
    conn = get_conn()
    try:
        c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        where_sql, params = _build_sensor_where(vehicle_id=vehicle_id, trip_id=trip_id)
        c.execute(f'SELECT * FROM sensor_data{where_sql} ORDER BY id DESC LIMIT 1', tuple(params))
        row = c.fetchone()
        return _normalize_sensor_record(row) if row else None
    finally:
        release_conn(conn)


def fetch_sensor_history(vehicle_id=None, trip_id=None, start=None, end=None, limit=100):
    """Fetch sensor history with optional filters."""
    limit = min(max(int(limit or 100), 1), 1000)
    conn = get_conn()
    try:
        c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        where_sql, params = _build_sensor_where(vehicle_id=vehicle_id, trip_id=trip_id, start=start, end=end)
        params.append(limit)
        c.execute(
            f'''SELECT * FROM sensor_data
                {where_sql}
                ORDER BY id DESC
                LIMIT %s''',
            tuple(params),
        )
        return [_normalize_sensor_record(r) for r in c.fetchall()]
    finally:
        release_conn(conn)


def fetch_sensor_events(vehicle_id=None, trip_id=None, start=None, end=None, limit=50):
    """Fetch event rows (frenada/giro) with optional filters."""
    limit = min(max(int(limit or 50), 1), 1000)
    conn = get_conn()
    try:
        c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        where_sql, params = _build_sensor_where(
            vehicle_id=vehicle_id,
            trip_id=trip_id,
            start=start,
            end=end,
            events_only=True,
        )
        params.append(limit)
        c.execute(
            f'''SELECT * FROM sensor_data
                {where_sql}
                ORDER BY id DESC
                LIMIT %s''',
            tuple(params),
        )
        return [_normalize_sensor_record(r) for r in c.fetchall()]
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
