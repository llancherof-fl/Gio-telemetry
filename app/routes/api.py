"""
GIO Telemetry — API Endpoints
/api/latest, /api/history, /api/history-range, /api/stats, /api/osrm-proxy, /health, /test_db
"""
import datetime

from flask import Blueprint, jsonify, request, current_app

from app.config import Config
from app.database import fetch_latest, fetch_history, fetch_history_range

api_bp = Blueprint('api', __name__)


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
    result = fetch_latest()
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
    limit = request.args.get('limit', 500, type=int)

    if not start or not end:
        return jsonify({'error': 'Se requieren parametros start y end'}), 400

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

    safe_limit = min(limit, Config.HISTORY_RANGE_MAX)
    rows = fetch_history_range(start_dt, end_dt, safe_limit)

    return jsonify({
        'data': rows,
        'meta': {
            'count': len(rows),
            'start': start_dt.isoformat(),
            'end': end_dt.isoformat(),
            'clamped': clamped,
            'limit': safe_limit,
        },
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
