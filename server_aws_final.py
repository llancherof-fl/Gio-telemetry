import socket
import json
import psycopg2
import psycopg2.extras
import threading
import datetime
import os
from flask import Flask, jsonify, request

HOST         = '0.0.0.0'
PORT_UDP     = 5001
PORT_WEB     = 8080
HISTORY_LIMIT = 50

DB_CONFIG = {
    'host':     os.environ.get('DB_HOST',     'localhost'),
    'user':     os.environ.get('DB_USER',     'postgres'),
    'password': os.environ.get('DB_PASSWORD', ''),
    'dbname':   os.environ.get('DB_NAME',     'telemetry'),
    'port':     int(os.environ.get('DB_PORT', 5432)),
    'connect_timeout': 5
}

app = Flask(__name__)

def get_db():
    conn = psycopg2.connect(**DB_CONFIG)
    return conn

def init_db():
    conn = get_db()
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
    conn.commit()
    conn.close()
    print("[DB] Tabla 'coordinates' lista.")

def insert_data(lat, lon, device, raw_ts):
    colombia_time = (datetime.datetime.utcfromtimestamp(raw_ts / 1000)
                     - datetime.timedelta(hours=5))
    conn = get_db()
    c = conn.cursor()
    c.execute(
        'INSERT INTO coordinates (timestamp, lat, lon, device, raw_ts) VALUES (%s, %s, %s, %s, %s)',
        (colombia_time, lat, lon, device, raw_ts)
    )
    conn.commit()
    conn.close()

def fetch_latest():
    conn = get_db()
    c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    c.execute('SELECT timestamp, lat, lon, device FROM coordinates ORDER BY id DESC LIMIT 1')
    row = c.fetchone()
    conn.close()
    if row:
        row = dict(row)
        row['timestamp'] = str(row['timestamp'])
        return row
    return None

def fetch_history(limit=HISTORY_LIMIT):
    conn = get_db()
    c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    c.execute(
        'SELECT timestamp, lat, lon, device FROM coordinates ORDER BY id DESC LIMIT %s',
        (limit,)
    )
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    for r in rows:
        r['timestamp'] = str(r['timestamp'])
    return rows

@app.route('/health')
def health():
    return jsonify({
        'status':    'ok',
        'server':    os.environ.get('EC2_NAME', 'servidor-sin-nombre'),
        'timestamp': datetime.datetime.utcnow().isoformat()
    })

@app.route('/test_db')
def test_db():
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute('SELECT NOW() AS db_time')
        db_time = c.fetchone()[0]
        conn.close()
        return jsonify({
            'status':      'ok',
            'db_time':     str(db_time),
            'db_host':     DB_CONFIG['host'],
            'db_name':     DB_CONFIG['dbname'],
            'message':     'Conexion a RDS PostgreSQL exitosa'
        })
    except Exception as e:
        return jsonify({
            'status':  'error',
            'message': str(e),
            'db_host': DB_CONFIG['host']
        }), 500

@app.route('/api/latest')
def api_latest():
    result = fetch_latest()
    if result:
        return jsonify(result)
    return jsonify({'error': 'Sin datos aun'})

@app.route('/api/history')
def api_history():
    limit = request.args.get('limit', HISTORY_LIMIT, type=int)
    limit = min(limit, 500)
    return jsonify(fetch_history(limit))

@app.route('/api/stats')
def api_stats():
    conn = get_db()
    c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    c.execute('SELECT COUNT(*) as total FROM coordinates')
    total = c.fetchone()['total']
    c.execute('SELECT MIN(timestamp) as first_ts, MAX(timestamp) as last_ts FROM coordinates')
    row = dict(c.fetchone())
    conn.close()
    return jsonify({
        'total_records': total,
        'first_record':  str(row['first_ts']) if row['first_ts'] else None,
        'last_record':   str(row['last_ts'])  if row['last_ts']  else None
    })

@app.route('/')
def index():
    server_name = os.environ.get('EC2_NAME', 'GIO Server')
    html = f"""
    <!DOCTYPE html>
    <html lang="es">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>{server_name} - GIO Dashboard</title>
        <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
        <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
        <style>
            * {{ margin: 0; padding: 0; box-sizing: border-box; }}
            body {{
                font-family: 'Courier New', Courier, monospace;
                background-color: #0e0b14;
                color: #d9c9e8;
                padding: 20px 30px;
            }}
            .header {{ border-bottom: 1px solid #3b2d52; padding-bottom: 14px; margin-bottom: 20px; }}
            .header h1 {{ color: #c084c8; font-size: 1.4rem; margin-bottom: 5px; }}
            .header .meta {{ color: #8b7a9e; font-size: 0.82rem; }}
            .status-bar {{ display: flex; gap: 14px; margin-bottom: 20px; flex-wrap: wrap; }}
            .status-item {{
                background: #1a1225; border: 1px solid #3b2d52;
                border-radius: 6px; padding: 10px 16px; font-size: 0.82rem;
            }}
            .status-item .label {{ color: #8b7a9e; }}
            .status-item .value {{ color: #e89bcf; font-weight: bold; }}
            .status-item .value.warning {{ color: #c9a0dc; }}
            .main-grid {{
                display: grid; grid-template-columns: 1fr 1fr;
                grid-template-rows: 420px auto; gap: 18px; margin-bottom: 20px;
            }}
            @media (max-width: 900px) {{ .main-grid {{ grid-template-columns: 1fr; }} }}
            .card {{
                border: 1px solid #3b2d52; background: #1a1225;
                padding: 16px; border-radius: 6px; overflow: hidden;
            }}
            .card h2 {{ color: #c084c8; font-size: 0.95rem; margin-bottom: 12px; }}
            .badge {{
                display: inline-block; padding: 2px 7px; border-radius: 4px;
                font-weight: bold; font-size: 0.7rem; margin-right: 6px;
            }}
            .badge-udp  {{ background: #6b2d6b; color: #f0c0f0; }}
            .badge-live {{ background: #7a2d5a; color: #f0c0d8; animation: pulse 2s infinite; }}
            .badge-map  {{ background: #4a2070; color: #d4a8f0; }}
            @keyframes pulse {{ 0%,100%{{opacity:1}} 50%{{opacity:.5}} }}
            #map {{ width: 100%; height: 340px; border-radius: 4px; border: 1px solid #3b2d52; }}
            .rt-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }}
            .rt-field .label {{ color: #8b7a9e; font-size: 0.78rem; margin-bottom: 2px; }}
            .rt-field .value {{ color: #e89bcf; font-size: 1rem; font-weight: bold; }}
            .table-wrap {{ height: 340px; overflow-y: auto; border: 1px solid #3b2d52; border-radius: 4px; }}
            table {{ width: 100%; border-collapse: collapse; font-size: 0.8rem; }}
            thead th {{
                background: #251835; color: #c084c8; padding: 7px 9px;
                text-align: left; position: sticky; top: 0;
                border-bottom: 1px solid #3b2d52;
            }}
            tbody tr {{ border-bottom: 1px solid #1e1428; }}
            tbody tr:hover {{ background: #1e1428; }}
            td {{ padding: 6px 9px; color: #d9c9e8; }}
            td.coord {{ color: #d4a8f0; }}
            .no-data {{ color: #8b7a9e; text-align: center; padding: 20px; }}
            .footer {{ color: #8b7a9e; font-size: 0.75rem; text-align: center; margin-top: 10px; }}
        </style>
    </head>
    <body>
        <div class="header">
            <h1>&#x1F4E1; GIO Telemetry Dashboard</h1>
            <div class="meta">Servidor: <strong>{server_name}</strong> &mdash; PostgreSQL RDS &mdash; AWS</div>
        </div>

        <div class="status-bar">
            <div class="status-item">
                <span class="label">Registros totales: </span>
                <span class="value" id="stat-total">...</span>
            </div>
            <div class="status-item">
                <span class="label">Primer registro: </span>
                <span class="value warning" id="stat-first">...</span>
            </div>
            <div class="status-item">
                <span class="label">Ultimo registro: </span>
                <span class="value" id="stat-last">...</span>
            </div>
        </div>

        <div class="main-grid">
            <div class="card">
                <h2><span class="badge badge-map">&#x1F5FA; MAPA</span>Geo-localizacion en Tiempo Real</h2>
                <div id="map"></div>
            </div>
            <div class="card" style="grid-row: span 2;">
                <h2><span class="badge badge-udp">UDP</span>Historial de Posiciones (ultimos 50)</h2>
                <div class="table-wrap">
                    <table>
                        <thead>
                            <tr><th>#</th><th>Timestamp</th><th>Latitud</th><th>Longitud</th><th>Device</th></tr>
                        </thead>
                        <tbody id="history-body">
                            <tr><td colspan="5" class="no-data">Cargando...</td></tr>
                        </tbody>
                    </table>
                </div>
            </div>
            <div class="card">
                <h2><span class="badge badge-live">&#x25CF; LIVE</span>Ultima Posicion Recibida</h2>
                <div id="realtime-container">
                    <p class="no-data">Esperando telemetria UDP...</p>
                </div>
            </div>
        </div>

        <div class="footer">GIO Telemetry System &mdash; AWS Cloud &mdash; PostgreSQL RDS &mdash; Actualizando cada 2s</div>

        <script>
            var map = L.map('map').setView([4.6097, -74.0817], 13);
            L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
                attribution: '© OpenStreetMap contributors'
            }}).addTo(map);

            var vehicleIcon = L.divIcon({{
                html: '<span style="font-size:26px;filter:hue-rotate(300deg) saturate(4) brightness(1.3)">&#x1F697;</span>',
                iconSize: [30, 30],
                className: ''
            }});

            var marker = null;
            var routeLine = null;
            var firstPosition = true;

            function fetchLatest() {{
                fetch('/api/latest').then(r => r.json()).then(data => {{
                    if (data.error) return;
                    var lat = parseFloat(data.lat), lon = parseFloat(data.lon);
                    if (marker === null) {{
                        marker = L.marker([lat, lon], {{icon: vehicleIcon}}).addTo(map);
                    }} else {{ marker.setLatLng([lat, lon]); }}
                    if (firstPosition) {{ map.setView([lat, lon], 15); firstPosition = false; }}
                    document.getElementById('realtime-container').innerHTML = `
                        <div class="rt-grid">
                            <div class="rt-field"><div class="label">Timestamp</div><div class="value">${{data.timestamp}}</div></div>
                            <div class="rt-field"><div class="label">Dispositivo</div><div class="value">${{data.device}}</div></div>
                            <div class="rt-field"><div class="label">Latitud</div><div class="value">${{data.lat}}</div></div>
                            <div class="rt-field"><div class="label">Longitud</div><div class="value">${{data.lon}}</div></div>
                        </div>`;
                }}).catch(err => console.error(err));
            }}

            function fetchHistory() {{
                fetch('/api/history?limit=50').then(r => r.json()).then(data => {{
                    const tbody = document.getElementById('history-body');
                    if (!data || data.length === 0) {{
                        tbody.innerHTML = '<tr><td colspan="5" class="no-data">Sin registros aun</td></tr>'; return;
                    }}
                    tbody.innerHTML = data.map((row, i) => `
                        <tr>
                            <td>${{i+1}}</td><td>${{row.timestamp}}</td>
                            <td class="coord">${{row.lat}}</td><td class="coord">${{row.lon}}</td>
                            <td>${{row.device}}</td>
                        </tr>`).join('');

                    var points = data.slice().reverse().map(r => [parseFloat(r.lat), parseFloat(r.lon)]);
                    if (points.length >= 2) {{
                        var coords = points.map(p => p[1] + ',' + p[0]).join(';');
                        fetch('https://router.project-osrm.org/route/v1/driving/' + coords + '?overview=full&geometries=geojson')
                            .then(r => r.json())
                            .then(osrm => {{
                                if (osrm.code !== 'Ok') return;
                                var routeCoords = osrm.routes[0].geometry.coordinates.map(c => [c[1], c[0]]);
                                if (routeLine) {{ map.removeLayer(routeLine); }}
                                routeLine = L.polyline(routeCoords, {{
                                    color: '#e879a0',
                                    weight: 4,
                                    opacity: 0.85,
                                    smoothFactor: 1
                                }}).addTo(map);
                            }})
                            .catch(err => console.error('OSRM error:', err));
                    }}
                }});
            }}

            function fetchStats() {{
                fetch('/api/stats').then(r => r.json()).then(data => {{
                    document.getElementById('stat-total').textContent = data.total_records.toLocaleString();
                    document.getElementById('stat-first').textContent = data.first_record || '---';
                    document.getElementById('stat-last').textContent  = data.last_record  || '---';
                }});
            }}

            function updateAll() {{ fetchLatest(); fetchHistory(); fetchStats(); }}
            window.onload = updateAll;
            setInterval(updateAll, 2000);
        </script>
    </body>
    </html>
    """
    return html

def udp_sniffer():
    print(f"[*] Iniciando Sniffer UDP en puerto {PORT_UDP}...")
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind((HOST, PORT_UDP))
        while True:
            try:
                data, addr = s.recvfrom(1024)
                try:
                    payload = json.loads(data.decode('utf-8'))
                    lat    = payload.get('lat', 0.0)
                    lon    = payload.get('long', 0.0)
                    device = payload.get('device', 'Desconocido')
                    raw_ts = payload.get('timestamp', 0)
                    print(f"[UDP] {addr[0]}: Lat {lat}, Lon {lon} -> PostgreSQL RDS")
                    insert_data(lat, lon, device, raw_ts)
                except json.JSONDecodeError:
                    pass
            except Exception:
                pass

if __name__ == '__main__':
    print("[*] Verificando conexion a base de datos...")
    try:
        init_db()
    except Exception as e:
        print(f"[ERROR] No se pudo conectar a la BD: {e}")
        print("[!] Revisa tus variables de entorno DB_HOST, DB_USER, DB_PASSWORD, DB_NAME")
        exit(1)

    threading.Thread(target=udp_sniffer, daemon=True).start()
    ec2_name = os.environ.get('EC2_NAME', 'servidor')
    print(f"[*] Servidor '{ec2_name}' corriendo en puerto {PORT_WEB}")
    print(f"[*] Dashboard: http://0.0.0.0:{PORT_WEB}")
    print(f"[*] Health:    http://0.0.0.0:{PORT_WEB}/health")
    print(f"[*] Test DB:   http://0.0.0.0:{PORT_WEB}/test_db")
    app.run(host='0.0.0.0', port=PORT_WEB, debug=False, use_reloader=False)
