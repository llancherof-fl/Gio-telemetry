import datetime
import os
from flask import Flask, jsonify, request

HOST     = '0.0.0.0'
PORT_WEB = 8080
EC2_NAME = 'local-test'

app = Flask(__name__)

# ==========================================
# DATOS FALSOS — solo para probar el frontend
# ==========================================
FAKE_DATA = [
    {"id": i, "timestamp": str(datetime.datetime(2026, 3, 19, 10, i, 0)),
     "lat": 10.9878 + i * 0.001, "lon": -74.7889 + i * 0.001, "device": "GIO-TEST"}
    for i in range(50)
]

@app.route('/health')
def health():
    return jsonify({'status': 'ok', 'server': EC2_NAME})

@app.route('/api/latest')
def api_latest():
    row = FAKE_DATA[-1]
    return jsonify({**row, 'timestamp': str(row['timestamp'])})

@app.route('/api/history')
def api_history():
    limit = request.args.get('limit', 50, type=int)
    rows = FAKE_DATA[-limit:]
    return jsonify([{**r, 'timestamp': str(r['timestamp'])} for r in rows])

@app.route('/api/stats')
def api_stats():
    return jsonify({
        'total_records': len(FAKE_DATA),
        'first_record':  str(FAKE_DATA[0]['timestamp']),
        'last_record':   str(FAKE_DATA[-1]['timestamp'])
    })

@app.route('/')
def index():
    html = f"""
    <!DOCTYPE html>
    <html lang="es">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>{EC2_NAME} - GIO Dashboard</title>
        <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
        <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
        <style>
            * {{ margin: 0; padding: 0; box-sizing: border-box; }}
            body {{ font-family: 'Courier New', Courier, monospace; background-color: #0d1117; color: #c9d1d9; padding: 20px 30px; }}
            .header {{ border-bottom: 1px solid #21362a; padding-bottom: 14px; margin-bottom: 20px; }}
            .header h1 {{ color: #58a6ff; font-size: 1.4rem; margin-bottom: 5px; }}
            .header .meta {{ color: #7d8590; font-size: 0.82rem; }}
            .status-bar {{ display: flex; gap: 14px; margin-bottom: 20px; flex-wrap: wrap; }}
            .status-item {{ background: #161b22; border: 1px solid #21362a; border-radius: 6px; padding: 10px 16px; font-size: 0.82rem; }}
            .status-item .label {{ color: #7d8590; }}
            .status-item .value {{ color: #3fb950; font-weight: bold; }}
            .status-item .value.warning {{ color: #3fb950; }}
            .main-grid {{ display: grid; grid-template-columns: 1fr 1fr; grid-template-rows: 420px auto; gap: 18px; margin-bottom: 20px; }}
            @media (max-width: 900px) {{ .main-grid {{ grid-template-columns: 1fr; }} }}
            .card {{ border: 1px solid #21362a; background: #161b22; padding: 16px; border-radius: 6px; overflow: hidden; }}
            .card h2 {{ color: #58a6ff; font-size: 0.95rem; margin-bottom: 12px; }}
            .badge {{ display: inline-block; padding: 2px 7px; border-radius: 4px; font-weight: bold; font-size: 0.7rem; margin-right: 6px; }}
            .badge-udp  {{ background: #1f4d2e; color: #56d364; }}
            .badge-live {{ background: #1b3a5c; color: #79c0ff; animation: pulse 2s infinite; }}
            .badge-map  {{ background: #1f4d2e; color: #56d364; }}
            @keyframes pulse {{ 0%,100%{{opacity:1}} 50%{{opacity:.5}} }}
            #map {{ width: 100%; height: 340px; border-radius: 4px; border: 1px solid #21362a; }}
            .rt-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }}
            .rt-field .label {{ color: #7d8590; font-size: 0.78rem; margin-bottom: 2px; }}
            .rt-field .value {{ color: #58a6ff; font-size: 1rem; font-weight: bold; }}
            .table-wrap {{ height: 340px; overflow-y: auto; border: 1px solid #21362a; border-radius: 4px; }}
            table {{ width: 100%; border-collapse: collapse; font-size: 0.8rem; }}
            thead th {{ background: #161b22; color: #58a6ff; padding: 7px 9px; text-align: left; position: sticky; top: 0; border-bottom: 1px solid #21362a; }}
            tbody tr {{ border-bottom: 1px solid #1c2128; }}
            tbody tr:hover {{ background: #1c2128; }}
            td {{ padding: 6px 9px; color: #c9d1d9; }}
            td.coord {{ color: #79c0ff; }}
            .no-data {{ color: #7d8590; text-align: center; padding: 20px; }}
            .footer {{ color: #7d8590; font-size: 0.75rem; text-align: center; margin-top: 10px; }}
        </style>
    </head>
    <body>
        <div class="header">
            <h1>&#x1F4E1; GIOOOOOOO grupo 2 — TEST LOCAL</h1>
            <div class="meta">Servidor: <strong>{EC2_NAME}</strong> &mdash; Datos de prueba</div>
        </div>
        <div class="status-bar">
            <div class="status-item"><span class="label">Registros totales: </span><span class="value" id="stat-total">...</span></div>
            <div class="status-item"><span class="label">Primer registro: </span><span class="value warning" id="stat-first">...</span></div>
            <div class="status-item"><span class="label">Ultimo registro: </span><span class="value" id="stat-last">...</span></div>
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
                        <thead><tr><th>#</th><th>Timestamp</th><th>Latitud</th><th>Longitud</th><th>Device</th></tr></thead>
                        <tbody id="history-body"><tr><td colspan="5" class="no-data">Cargando...</td></tr></tbody>
                    </table>
                </div>
            </div>
            <div class="card">
                <h2><span class="badge badge-live">&#x25CF; LIVE</span>Ultima Posicion Recibida</h2>
                <div id="realtime-container"><p class="no-data">Esperando telemetria...</p></div>
            </div>
        </div>
        <div class="footer">GIO Telemetry System &mdash; TEST LOCAL &mdash; Actualizando cada 2s</div>
        <script>
            var map = L.map('map').setView([10.9878, -74.7889], 15);
            L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{attribution: '&copy; OpenStreetMap contributors'}}).addTo(map);
            var vehicleIcon = L.divIcon({{html: '<span style="font-size:26px;filter:hue-rotate(300deg) saturate(4) brightness(1.3)">&#x1F697;</span>', iconSize: [30, 30], className: ''}});
            var marker = null, routeLine = null, firstPosition = true;
            function fetchLatest() {{
                fetch('/api/latest').then(r => r.json()).then(data => {{
                    if (data.error) return;
                    var lat = parseFloat(data.lat), lon = parseFloat(data.lon);
                    if (marker === null) {{ marker = L.marker([lat, lon], {{icon: vehicleIcon}}).addTo(map); }}
                    else {{ marker.setLatLng([lat, lon]); }}
                    if (firstPosition) {{ map.setView([lat, lon], 15); firstPosition = false; }}
                    document.getElementById('realtime-container').innerHTML = `<div class="rt-grid"><div class="rt-field"><div class="label">Timestamp</div><div class="value">${{data.timestamp}}</div></div><div class="rt-field"><div class="label">Dispositivo</div><div class="value">${{data.device}}</div></div><div class="rt-field"><div class="label">Latitud</div><div class="value">${{data.lat}}</div></div><div class="rt-field"><div class="label">Longitud</div><div class="value">${{data.lon}}</div></div></div>`;
                }}).catch(err => console.error(err));
            }}
            function fetchHistory() {{
                fetch('/api/history?limit=50').then(r => r.json()).then(data => {{
                    const tbody = document.getElementById('history-body');
                    if (!data || data.length === 0) {{ tbody.innerHTML = '<tr><td colspan="5" class="no-data">Sin registros aun</td></tr>'; return; }}
                    tbody.innerHTML = data.map((row, i) => `<tr><td>${{i+1}}</td><td>${{row.timestamp}}</td><td class="coord">${{row.lat}}</td><td class="coord">${{row.lon}}</td><td>${{row.device}}</td></tr>`).join('');
                    var points = data.slice().reverse().map(r => [parseFloat(r.lat), parseFloat(r.lon)]);
                    if (points.length >= 2) {{
                        var coords = points.map(p => p[1] + ',' + p[0]).join(';');
                        fetch('https://router.project-osrm.org/route/v1/driving/' + coords + '?overview=full&geometries=geojson')
                            .then(r => r.json()).then(osrm => {{
                                if (osrm.code !== 'Ok') return;
                                var routeCoords = osrm.routes[0].geometry.coordinates.map(c => [c[1], c[0]]);
                                if (routeLine) {{ map.removeLayer(routeLine); }}
                                routeLine = L.polyline(routeCoords, {{color: '#58a6ff', weight: 4, opacity: 0.85, smoothFactor: 1}}).addTo(map);
                            }}).catch(err => console.error('OSRM error:', err));
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

if __name__ == '__main__':
    print(f"[*] Servidor de prueba corriendo en http://localhost:{PORT_WEB}")
    print(f"[*] Abre tu navegador en: http://localhost:8080")
    app.run(host=HOST, port=PORT_WEB, debug=False, use_reloader=False)
