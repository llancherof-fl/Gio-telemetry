"""
GIO Telemetry — Servidor de prueba local v3
Sirve el dashboard REAL (app/templates/index.html + static/) con datos
falsos en memoria. No necesita PostgreSQL ni variables de entorno.

Uso:
    cd Gio-telemetry
    pip install flask
    python3 server_test_local_v3.py
    Abre: http://localhost:8080
"""

import datetime
import math
import os
from flask import Flask, jsonify, request, render_template

# ── App con los templates y static REALES ──────────────────────────────────
BASE = os.path.dirname(os.path.abspath(__file__))
app = Flask(
    __name__,
    template_folder=os.path.join(BASE, 'app', 'templates'),
    static_folder=os.path.join(BASE, 'app', 'static'),
)

HOST     = '0.0.0.0'
PORT_WEB = 8080
EC2_NAME = 'local-dev'

# ══════════════════════════════════════════
#  DATOS FALSOS — trayecto simulado en Barranquilla
#  Ruta: zona norte del campus, ~50 puntos
# ══════════════════════════════════════════

BASE_LAT = 10.9878
BASE_LON = -74.7889
BASE_TS  = datetime.datetime(2026, 4, 16, 9, 0, 0)

FAKE_POINTS = []
for i in range(60):
    angle = i * 0.12          # curva suave
    lat = BASE_LAT + math.sin(angle) * 0.004 + i * 0.00015
    lon = BASE_LON + math.cos(angle) * 0.003 + i * 0.00010
    ts  = BASE_TS + datetime.timedelta(minutes=i * 2)
    FAKE_POINTS.append({
        'id':        i + 1,
        'seq':       i,
        'timestamp': str(ts),
        'lat':       round(lat, 6),
        'lon':       round(lon, 6),
        'device':    'GIO-TEST',
        'trip_id':   'trip-2026-0001',
        'event_type': None,
    })

FAKE_TRIP = {
    'trip_id':         'trip-2026-0001',
    'device':          'GIO-TEST',
    'start_ts':        str(FAKE_POINTS[0]['timestamp']),
    'end_ts':          str(FAKE_POINTS[-1]['timestamp']),
    'duration_seconds': 60 * 2 * len(FAKE_POINTS),
    'point_count':     len(FAKE_POINTS),
    'status':          'closed',
}

def haversine(lat1, lon1, lat2, lon2):
    R = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlam/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# ══════════════════════════════════════════
#  DASHBOARD
# ══════════════════════════════════════════

@app.route('/')
def index():
    return render_template('index.html', ec2_name=EC2_NAME)


# ══════════════════════════════════════════
#  REAL-TIME
# ══════════════════════════════════════════

@app.route('/api/latest')
def api_latest():
    p = FAKE_POINTS[-1]
    return jsonify({**p, 'timestamp': str(p['timestamp'])})

@app.route('/api/devices')
def api_devices():
    return jsonify({'devices': ['GIO-TEST']})

@app.route('/api/stats')
def api_stats():
    return jsonify({
        'total_records': len(FAKE_POINTS),
        'first_record':  str(FAKE_POINTS[0]['timestamp']),
        'last_record':   str(FAKE_POINTS[-1]['timestamp']),
    })


# ══════════════════════════════════════════
#  HISTÓRICO — puntos crudos
# ══════════════════════════════════════════

@app.route('/api/history-range')
def api_history_range():
    limit = request.args.get('limit', 2500, type=int)
    pts   = FAKE_POINTS[:limit]
    return jsonify({
        'data': pts,
        'meta': {
            'count':            len(pts),
            'has_more':         False,
            'dropped_outliers': 0,
            'dropped_invalid':  0,
            'clamped':          False,
        }
    })


# ══════════════════════════════════════════
#  HISTÓRICO — trayectos
# ══════════════════════════════════════════

@app.route('/api/trips-range')
def api_trips_range():
    return jsonify({
        'data': [FAKE_TRIP],
        'meta': {'has_more': False, 'count': 1}
    })

@app.route('/api/trip-points')
def api_trip_points():
    sample = request.args.get('sample_minutes', 3, type=int)
    if sample < 1: sample = 1
    # tomar un punto cada N según sample_minutes (cada punto = 2 min reales)
    step  = max(1, round(sample / 2))
    pts   = FAKE_POINTS[::step]
    return jsonify({
        'data': pts,
        'meta': {'count': len(pts), 'dropped_outliers': 0, 'dropped_invalid': 0}
    })


# ══════════════════════════════════════════
#  FEATURE — ¿Cuándo pasó?
# ══════════════════════════════════════════

@app.route('/api/nearest-point')
def api_nearest_point():
    try:
        lat = float(request.args.get('lat'))
        lon = float(request.args.get('lon'))
    except (TypeError, ValueError):
        return jsonify({'error': 'lat/lon requeridos'}), 400

    best     = None
    best_d   = float('inf')
    for p in FAKE_POINTS:
        d = haversine(lat, lon, p['lat'], p['lon'])
        if d < best_d:
            best_d = d
            best   = p

    if best is None or best_d > 1500:
        return jsonify({'found': False})

    return jsonify({
        'found':      True,
        'timestamp':  str(best['timestamp']),
        'lat':        best['lat'],
        'lon':        best['lon'],
        'distance_m': round(best_d, 1),
        'device':     best['device'],
        'trip_id':    best['trip_id'],
        'seq':        best['seq'],
    })


# ══════════════════════════════════════════
#  OSRM PROXY — devuelve ruta directa sin llamar OSRM
#  (el frontend cae en el spline fallback si falla, igual sirve)
# ══════════════════════════════════════════

@app.route('/api/osrm-proxy')
def api_osrm_proxy():
    # Devuelve vacío para forzar el fallback a spline local — sin internet needed
    return jsonify({'code': 'Error', 'message': 'proxy disabled in local-dev'}), 503


# ══════════════════════════════════════════
#  HEALTH
# ══════════════════════════════════════════

@app.route('/health')
def health():
    return jsonify({'status': 'ok', 'server': EC2_NAME, 'mode': 'local-dev'})


if __name__ == '__main__':
    print()
    print('  GIO Telemetry — servidor de prueba local v3')
    print(f'  Dashboard real en: http://localhost:{PORT_WEB}')
    print()
    print('  Datos simulados: 60 puntos, 1 trayecto (trip-2026-0001)')
    print('  Para probar ¿Cuándo pasó?: Histórico -> Buscar -> botón mira -> click mapa')
    print('  El OSRM proxy está desactivado — el frontend usa spline fallback')
    print()
    app.run(host=HOST, port=PORT_WEB, debug=True, use_reloader=True)
