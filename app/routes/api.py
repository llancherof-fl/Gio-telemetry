"""
GIO Telemetry — API Endpoints
/api/latest, /api/history, /api/history-range, /api/devices, /api/stats, /api/osrm-proxy, /health, /test_db
"""
import datetime

from flask import Blueprint, jsonify, request, current_app

from app.config import Config
from app.database import fetch_latest, fetch_history, fetch_history_range, fetch_devices

api_bp = Blueprint('api', __name__)


def _clamp(value, minimum, maximum):
    return max(minimum, min(value, maximum))


def _downsample_rows(rows, sample_minutes):
    """
    Downsample by keeping the latest point per N-minute bucket (per device).
    This reduces map noise and payload size for historical rendering.
    """
    if sample_minutes < 2 or len(rows) < 3:
        return rows

    bucketed = {}
    for row in rows:
        try:
            ts = datetime.datetime.fromisoformat(row['timestamp'])
        except (ValueError, TypeError):
            continue

        minute_bucket = (ts.minute // sample_minutes) * sample_minutes
        bucket_ts = ts.replace(minute=minute_bucket, second=0, microsecond=0)
        device_key = row.get('device', '') or ''
        bucketed[(device_key, bucket_ts.isoformat())] = row

    sampled = list(bucketed.values())
    sampled.sort(key=lambda r: r.get('timestamp', ''))
    return sampled


# ══════════════════════════════════════════
#  HEALTH & DIAGNOSTICS
# ══════════════════════════════════════════

@api_bp.route('/health')
def health():
    return jsonify({
        'status': 'ok',
        'server': Config.EC2_NAME,
        'domain': Config.DOMAIN,
        'https': Config.USE_HTTPS,
        'timestamp': datetime.datetime.utcnow().isoformat(),
    })


@api_bp.route('/test_db')
def test_db():
    try:
        from app.database import get_conn, release_conn
        conn = get_conn()
        c = conn.cursor()
        c.execute('SELECT NOW() AS db_time')
        db_time = c.fetchone()[0]
        release_conn(conn)
        return jsonify({
            'status': 'ok',
            'db_time': str(db_time),
            'db_host': Config.DB_HOST,
            'db_name': Config.DB_NAME,
            'message': 'Conexion a RDS PostgreSQL exitosa',
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


# ══════════════════════════════════════════
#  TELEMETRY DATA
# ══════════════════════════════════════════

@api_bp.route('/api/latest')
def api_latest():
    device = (request.args.get('device') or '').strip() or None
    result = fetch_latest(device=device)
    if result:
        return jsonify(result)
    return jsonify({'error': 'Sin datos aun'})


@api_bp.route('/api/history')
def api_history():
    limit = request.args.get('limit', Config.HISTORY_LIMIT, type=int)
    limit = min(limit, 500)
    return jsonify(fetch_history(limit))


@api_bp.route('/api/history-range')
def api_history_range():
    start = request.args.get('start')
    end = request.args.get('end')
    limit = request.args.get('limit', 1200, type=int)
    offset = request.args.get('offset', 0, type=int)
    device = (request.args.get('device') or '').strip() or None
    sample_minutes = request.args.get(
        'sample_minutes',
        Config.HISTORY_SAMPLE_MINUTES_DEFAULT,
        type=int,
    )

    if not start or not end:
        return jsonify({'error': 'Se requieren parametros start y end'}), 400

    if limit is None:
        limit = 1200
    if offset is None:
        offset = 0
    if sample_minutes is None:
        sample_minutes = Config.HISTORY_SAMPLE_MINUTES_DEFAULT

    safe_limit = _clamp(limit, 1, Config.HISTORY_RANGE_MAX)
    safe_offset = max(0, offset)
    safe_sample_minutes = _clamp(sample_minutes, 0, Config.HISTORY_SAMPLE_MINUTES_MAX)

    # Parse dates
    try:
        start_dt = datetime.datetime.fromisoformat(start)
        end_dt = datetime.datetime.fromisoformat(end)
    except ValueError:
        return jsonify({'error': 'Formato de fecha invalido. Usa ISO 8601'}), 400

    # ── Validation: start must be before end ──
    if start_dt >= end_dt:
        return jsonify({
            'error': 'Rango invalido: la fecha de inicio debe ser anterior a la fecha fin',
            'code': 'INVALID_RANGE',
        }), 400

    # ── Clamp end to now (Colombia time = UTC-5) ──
    now_colombia = datetime.datetime.utcnow() - datetime.timedelta(hours=5)
    clamped = False
    if end_dt > now_colombia:
        end_dt = now_colombia
        clamped = True

    rows = fetch_history_range(
        start_dt,
        end_dt,
        safe_limit,
        offset=safe_offset,
        device=device,
    )
    raw_count = len(rows)
    sampled_rows = _downsample_rows(rows, safe_sample_minutes)

    return jsonify({
        'data': sampled_rows,
        'meta': {
            'count': len(sampled_rows),
            'raw_count': raw_count,
            'start': start_dt.isoformat(),
            'end': end_dt.isoformat(),
            'clamped': clamped,
            'limit': safe_limit,
            'offset': safe_offset,
            'sample_minutes': safe_sample_minutes,
            'sampled': safe_sample_minutes >= 2,
            'device': device,
            'has_more': raw_count == safe_limit,
        },
    })


# ══════════════════════════════════════════
#  FILTER OPTIONS
# ══════════════════════════════════════════

@api_bp.route('/api/devices')
def api_devices():
    devices = fetch_devices(limit=200)
    return jsonify({
        'devices': devices,
        'count': len(devices),
    })


# ══════════════════════════════════════════
#  STATS (cached)
# ══════════════════════════════════════════

@api_bp.route('/api/stats')
def api_stats():
    return jsonify(current_app.stats_cache.get())


# ══════════════════════════════════════════
#  OSRM PROXY (cached)
# ══════════════════════════════════════════

@api_bp.route('/api/osrm-proxy')
def osrm_proxy():
    """
    Proxy OSRM route requests through our backend.
    This avoids CORS issues and adds server-side caching.
    Query param: coords=lon1,lat1;lon2,lat2;...
    """
    coords = request.args.get('coords', '')
    if not coords or ';' not in coords:
        return jsonify({'error': 'Se requiere parametro coords con al menos 2 puntos'}), 400

    result = current_app.osrm_proxy.get_route(coords)

    if result:
        # Extract just what the frontend needs
        route = result['routes'][0]
        return jsonify({
            'ok': True,
            'geometry': route['geometry'],
            'distance': route.get('distance', 0),
            'duration': route.get('duration', 0),
            'cache_size': current_app.osrm_proxy.cache_size,
        })

    return jsonify({'ok': False, 'fallback': True})
