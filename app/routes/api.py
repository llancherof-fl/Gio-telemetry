"""
GIO Telemetry — API Endpoints
/api/latest, /api/history, /api/history-range, /api/trips-range, /api/trip-points,
/api/devices, /api/stats, /api/osrm-proxy, /health, /test_db
"""
import datetime
import math
import time

from flask import Blueprint, jsonify, request, current_app

from app.config import Config
from app.database import (
    fetch_latest,
    fetch_history,
    fetch_history_range,
    fetch_trip_summaries,
    fetch_trip_points,
    fetch_devices,
)

api_bp = Blueprint('api', __name__)
_devices_cache = {
    'data': [],
    'expires_at': 0.0,
}


def _clamp(value, minimum, maximum):
    return max(minimum, min(value, maximum))


def _parse_ts(value):
    if isinstance(value, datetime.datetime):
        return value
    if value is None:
        return None
    try:
        return datetime.datetime.fromisoformat(str(value))
    except (ValueError, TypeError):
        return None


def _is_valid_latlon(lat, lon):
    return (-90.0 <= lat <= 90.0) and (-180.0 <= lon <= 180.0)


def _haversine_km(lat1, lon1, lat2, lon2):
    radius_km = 6371.0088
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = (
        math.sin(d_lat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(d_lon / 2) ** 2
    )
    return 2 * radius_km * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _sanitize_history_rows(rows, max_speed_kmh, min_jump_km):
    """
    Drop clearly invalid coordinates and impossible "teleport" jumps per device.
    This prevents transoceanic artifacts and OSRM failures in historical routes.
    """
    if len(rows) < 2:
        return rows, {'dropped_invalid': 0, 'dropped_outliers': 0}

    prev_by_device = {}
    cleaned = []
    dropped_invalid = 0
    dropped_outliers = 0

    for row in rows:
        try:
            lat = float(row.get('lat'))
            lon = float(row.get('lon'))
        except (ValueError, TypeError):
            dropped_invalid += 1
            continue

        if not _is_valid_latlon(lat, lon):
            dropped_invalid += 1
            continue

        device_key = (row.get('device') or '').strip() or '__unknown__'
        ts = _parse_ts(row.get('timestamp'))
        prev = prev_by_device.get(device_key)

        if prev:
            dist_km = _haversine_km(prev['lat'], prev['lon'], lat, lon)
            if dist_km >= min_jump_km:
                should_drop = False
                prev_ts = prev['ts']

                if prev_ts and ts:
                    delta_seconds = (ts - prev_ts).total_seconds()
                    if delta_seconds <= 0:
                        should_drop = True
                    else:
                        speed_kmh = dist_km / (delta_seconds / 3600.0)
                        if speed_kmh > max_speed_kmh:
                            should_drop = True

                if should_drop:
                    dropped_outliers += 1
                    continue

        clean_row = dict(row)
        clean_row['lat'] = lat
        clean_row['lon'] = lon
        if ts:
            clean_row['timestamp'] = ts.isoformat(sep=' ')

        cleaned.append(clean_row)
        prev_by_device[device_key] = {'lat': lat, 'lon': lon, 'ts': ts}

    return cleaned, {
        'dropped_invalid': dropped_invalid,
        'dropped_outliers': dropped_outliers,
    }


def _downsample_rows(rows, sample_minutes):
    """
    Downsample by keeping the latest point per N-minute bucket (per device),
    while preserving first and last point per device for route consistency.
    This reduces map noise and payload size for historical rendering.
    """
    if sample_minutes < 2 or len(rows) < 3:
        return rows

    bucketed = {}
    first_by_device = {}
    last_by_device = {}

    for row in rows:
        device_key = row.get('device', '') or ''
        if device_key not in first_by_device:
            first_by_device[device_key] = row
        last_by_device[device_key] = row

        ts = _parse_ts(row.get('timestamp'))
        if not ts:
            continue

        minute_bucket = (ts.minute // sample_minutes) * sample_minutes
        bucket_ts = ts.replace(minute=minute_bucket, second=0, microsecond=0)
        key = (device_key, bucket_ts.isoformat())
        prev = bucketed.get(key)
        if not prev:
            bucketed[key] = row
            continue

        prev_ts = _parse_ts(prev.get('timestamp'))
        if not prev_ts or ts >= prev_ts:
            bucketed[key] = row

    sampled = list(bucketed.values())
    sampled.extend(first_by_device.values())
    sampled.extend(last_by_device.values())

    deduped = []
    seen = set()
    for row in sampled:
        key = (
            row.get('device', '') or '',
            str(row.get('timestamp', '')),
            row.get('lat'),
            row.get('lon'),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)

    deduped.sort(key=lambda r: r.get('timestamp', ''))
    return deduped


def _merge_line_coords(lines):
    merged = []
    for line in lines:
        if not line or len(line) < 2:
            continue
        if not merged:
            merged.extend(line)
            continue
        if merged[-1] == line[0]:
            merged.extend(line[1:])
        else:
            merged.extend(line)
    return merged


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
    max_speed_kmh = max(30.0, float(getattr(Config, 'HISTORY_OUTLIER_MAX_SPEED_KMH', 240)))
    min_jump_km = max(1.0, float(getattr(Config, 'HISTORY_OUTLIER_MIN_JUMP_KM', 5)))

    cleaned_rows, sanitize_meta = _sanitize_history_rows(
        rows,
        max_speed_kmh=max_speed_kmh,
        min_jump_km=min_jump_km,
    )
    sampled_rows = _downsample_rows(cleaned_rows, safe_sample_minutes)

    return jsonify({
        'data': sampled_rows,
        'meta': {
            'count': len(sampled_rows),
            'raw_count': raw_count,
            'clean_count': len(cleaned_rows),
            'start': start_dt.isoformat(),
            'end': end_dt.isoformat(),
            'clamped': clamped,
            'limit': safe_limit,
            'offset': safe_offset,
            'sample_minutes': safe_sample_minutes,
            'sampled': safe_sample_minutes >= 2,
            'device': device,
            'has_more': raw_count == safe_limit,
            'dropped_invalid': sanitize_meta['dropped_invalid'],
            'dropped_outliers': sanitize_meta['dropped_outliers'],
        },
    })


@api_bp.route('/api/trips-range')
def api_trips_range():
    """
    Return trip sessions grouped by trip_id inside a time range.
    Useful for dashboard trip list (started/ended/open).
    """
    start = request.args.get('start')
    end = request.args.get('end')
    device = (request.args.get('device') or '').strip() or None
    limit = request.args.get('limit', 200, type=int)
    offset = request.args.get('offset', 0, type=int)

    if not start or not end:
        return jsonify({'error': 'Se requieren parametros start y end'}), 400

    if limit is None:
        limit = 200
    if offset is None:
        offset = 0

    safe_limit = _clamp(limit, 1, 500)
    safe_offset = max(0, offset)

    try:
        start_dt = datetime.datetime.fromisoformat(start)
        end_dt = datetime.datetime.fromisoformat(end)
    except ValueError:
        return jsonify({'error': 'Formato de fecha invalido. Usa ISO 8601'}), 400

    if start_dt >= end_dt:
        return jsonify({
            'error': 'Rango invalido: la fecha de inicio debe ser anterior a la fecha fin',
            'code': 'INVALID_RANGE',
        }), 400

    rows = fetch_trip_summaries(
        start_dt,
        end_dt,
        device=device,
        limit=safe_limit,
        offset=safe_offset,
    )

    return jsonify({
        'data': rows,
        'meta': {
            'count': len(rows),
            'start': start_dt.isoformat(),
            'end': end_dt.isoformat(),
            'limit': safe_limit,
            'offset': safe_offset,
            'device': device,
            'has_more': len(rows) == safe_limit,
        },
    })


@api_bp.route('/api/trip-points')
def api_trip_points():
    """Return ordered points for a single trip_id."""
    trip_id = (request.args.get('trip_id') or '').strip()
    limit = request.args.get('limit', 5000, type=int)
    offset = request.args.get('offset', 0, type=int)

    if not trip_id:
        return jsonify({'error': 'Se requiere parametro trip_id'}), 400

    if limit is None:
        limit = 5000
    if offset is None:
        offset = 0

    safe_limit = _clamp(limit, 1, 10000)
    safe_offset = max(0, offset)

    rows = fetch_trip_points(trip_id, limit=safe_limit, offset=safe_offset)
    raw_count = len(rows)
    max_speed_kmh = max(30.0, float(getattr(Config, 'HISTORY_OUTLIER_MAX_SPEED_KMH', 240)))
    min_jump_km = max(1.0, float(getattr(Config, 'HISTORY_OUTLIER_MIN_JUMP_KM', 5)))
    cleaned_rows, sanitize_meta = _sanitize_history_rows(
        rows,
        max_speed_kmh=max_speed_kmh,
        min_jump_km=min_jump_km,
    )

    return jsonify({
        'data': cleaned_rows,
        'meta': {
            'trip_id': trip_id,
            'count': len(cleaned_rows),
            'raw_count': raw_count,
            'clean_count': len(cleaned_rows),
            'limit': safe_limit,
            'offset': safe_offset,
            'has_more': raw_count == safe_limit,
            'dropped_invalid': sanitize_meta['dropped_invalid'],
            'dropped_outliers': sanitize_meta['dropped_outliers'],
        },
    })


# ══════════════════════════════════════════
#  FILTER OPTIONS
# ══════════════════════════════════════════

@api_bp.route('/api/devices')
def api_devices():
    now = time.time()
    if _devices_cache['expires_at'] > now:
        return jsonify({
            'devices': _devices_cache['data'],
            'count': len(_devices_cache['data']),
            'cached': True,
        })

    devices = fetch_devices(limit=200)
    _devices_cache['data'] = devices
    _devices_cache['expires_at'] = now + max(5, Config.DEVICES_CACHE_TTL)

    return jsonify({
        'devices': devices,
        'count': len(devices),
        'cached': False,
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
    Proxy OSRM route/match requests through our backend.
    This avoids CORS issues and adds server-side caching.
    Query param: coords=lon1,lat1;lon2,lat2;...
    Optional: method=route|match
    """
    coords = request.args.get('coords', '')
    method = (request.args.get('method') or 'route').strip().lower()
    if method not in ('route', 'match'):
        return jsonify({'error': 'Metodo invalido. Usa route o match'}), 400

    if not coords or ';' not in coords:
        return jsonify({'error': 'Se requiere parametro coords con al menos 2 puntos'}), 400

    result = current_app.osrm_proxy.get_route(coords, method=method)

    if result:
        if method == 'match':
            matchings = result.get('matchings') or []
            lines = []
            distance = 0.0
            duration = 0.0
            for matching in matchings:
                geometry = matching.get('geometry') or {}
                coords_line = geometry.get('coordinates') or []
                if len(coords_line) > 1:
                    lines.append(coords_line)
                distance += float(matching.get('distance') or 0.0)
                duration += float(matching.get('duration') or 0.0)

            merged = _merge_line_coords(lines)
            if len(merged) > 1:
                return jsonify({
                    'ok': True,
                    'geometry': {
                        'type': 'LineString',
                        'coordinates': merged,
                    },
                    'distance': distance,
                    'duration': duration,
                    'method': method,
                    'cache_size': current_app.osrm_proxy.cache_size,
                })
        else:
            routes = result.get('routes') or []
            if routes:
                route = routes[0]
                return jsonify({
                    'ok': True,
                    'geometry': route.get('geometry'),
                    'distance': route.get('distance', 0),
                    'duration': route.get('duration', 0),
                    'method': method,
                    'cache_size': current_app.osrm_proxy.cache_size,
                })

    return jsonify({'ok': False, 'fallback': True, 'method': method})
