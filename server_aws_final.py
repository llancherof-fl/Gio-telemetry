import socket
import json
import psycopg2
import psycopg2.extras
import threading
import datetime
import os
import ssl
from flask import Flask, jsonify, request

# ==========================================
# CONFIGURATION
# ==========================================
HOST          = '0.0.0.0'
PORT_UDP      = int(os.environ.get('PORT_UDP',  5001))
PORT_WEB      = int(os.environ.get('PORT_WEB',  8080))
PORT_HTTPS    = int(os.environ.get('PORT_HTTPS', 443))
HISTORY_LIMIT = int(os.environ.get('HISTORY_LIMIT', 50))

USE_HTTPS = os.environ.get('USE_HTTPS', 'false').lower() == 'true'
DOMAIN    = os.environ.get('DOMAIN', '')
CERT_FILE = os.environ.get('CERT_FILE', f'/etc/letsencrypt/live/{DOMAIN}/fullchain.pem')
KEY_FILE  = os.environ.get('KEY_FILE',  f'/etc/letsencrypt/live/{DOMAIN}/privkey.pem')
EC2_NAME  = os.environ.get('EC2_NAME', 'gio-server')

DB_CONFIG = {
    'host':     os.environ.get('DB_HOST',     'localhost'),
    'user':     os.environ.get('DB_USER',     'postgres'),
    'password': os.environ.get('DB_PASSWORD', ''),
    'dbname':   os.environ.get('DB_NAME',     'telemetry'),
    'port':     int(os.environ.get('DB_PORT',  5432)),
    'connect_timeout': 5
}

app = Flask(__name__)

# ==========================================
# DATABASE
# ==========================================
def get_db():
    return psycopg2.connect(**DB_CONFIG)

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

def fetch_history_range(start_ts, end_ts, limit=500):
    conn = get_db()
    c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    c.execute(
        '''SELECT timestamp, lat, lon, device FROM coordinates
           WHERE timestamp >= %s AND timestamp <= %s
           ORDER BY timestamp ASC LIMIT %s''',
        (start_ts, end_ts, limit)
    )
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    for r in rows:
        r['timestamp'] = str(r['timestamp'])
    return rows

# ==========================================
# API ENDPOINTS
# ==========================================
@app.route('/health')
def health():
    return jsonify({
        'status':    'ok',
        'server':    EC2_NAME,
        'domain':    DOMAIN,
        'https':     USE_HTTPS,
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
            'status':  'ok',
            'db_time': str(db_time),
            'db_host': DB_CONFIG['host'],
            'db_name': DB_CONFIG['dbname'],
            'message': 'Conexion a RDS PostgreSQL exitosa'
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

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

@app.route('/api/history-range')
def api_history_range():
    start = request.args.get('start')
    end   = request.args.get('end')
    limit = request.args.get('limit', 500, type=int)
    if not start or not end:
        return jsonify({'error': 'Se requieren parametros start y end'}), 400
    try:
        start_dt = datetime.datetime.fromisoformat(start)
        end_dt   = datetime.datetime.fromisoformat(end)
    except ValueError:
        return jsonify({'error': 'Formato de fecha invalido. Usa ISO 8601'}), 400
    rows = fetch_history_range(start_dt, end_dt, min(limit, 1000))
    return jsonify(rows)

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

# ==========================================
# WEB DASHBOARD
# ==========================================
@app.route('/')
def index():
    html = f"""<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{EC2_NAME} · GIO Telemetry</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link href="https://fonts.googleapis.com/css2?family=Space+Mono:wght@400;700&family=DM+Sans:wght@300;400;500;600&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
    <style>
        :root {{
            --bg:        #080612;
            --surface:   #110e1e;
            --surface2:  #1a1530;
            --border:    #2a2240;
            --border2:   #3d3060;
            --pink:      #e879a0;
            --pink-dim:  #9d3d62;
            --purple:    #b06ef3;
            --purple-dim:#5c3585;
            --lavender:  #c4a8ff;
            --text:      #e8deff;
            --text-dim:  #8b7aaa;
            --text-faint:#4a3d6a;
            --green:     #4ade80;
            --radius:    10px;
        }}
        *, *::before, *::after {{ margin:0; padding:0; box-sizing:border-box; }}
        html, body {{ height:100%; }}
        body {{
            font-family: 'DM Sans', sans-serif;
            background: var(--bg);
            color: var(--text);
            min-height: 100vh;
            overflow-x: hidden;
        }}

        /* ── NAVBAR ── */
        nav {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 0 28px;
            height: 58px;
            background: var(--surface);
            border-bottom: 1px solid var(--border);
            position: sticky;
            top: 0;
            z-index: 100;
            backdrop-filter: blur(10px);
        }}
        .nav-brand {{
            display: flex;
            align-items: center;
            gap: 10px;
            font-family: 'Space Mono', monospace;
            font-size: 0.9rem;
            color: var(--purple);
            letter-spacing: 0.04em;
        }}
        .nav-brand span {{ color: var(--pink); }}
        .nav-tabs {{
            display: flex;
            gap: 4px;
            background: var(--surface2);
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 4px;
        }}
        .nav-tab {{
            padding: 7px 20px;
            border-radius: 6px;
            border: none;
            background: transparent;
            color: var(--text-dim);
            font-family: 'DM Sans', sans-serif;
            font-size: 0.82rem;
            font-weight: 500;
            cursor: pointer;
            transition: all 0.2s;
            display: flex;
            align-items: center;
            gap: 6px;
        }}
        .nav-tab.active {{
            background: var(--purple-dim);
            color: var(--lavender);
        }}
        .nav-tab:hover:not(.active) {{ color: var(--text); }}
        .nav-meta {{
            font-family: 'Space Mono', monospace;
            font-size: 0.72rem;
            color: var(--text-faint);
        }}
        .dot-live {{
            width: 7px; height: 7px;
            border-radius: 50%;
            background: var(--green);
            animation: blink 1.4s ease-in-out infinite;
        }}
        @keyframes blink {{ 0%,100%{{opacity:1}} 50%{{opacity:0.2}} }}

        /* ── VIEWS ── */
        .view {{ display: none; padding: 24px 28px; }}
        .view.active {{ display: block; }}

        /* ── STATS BAR ── */
        .stats-bar {{
            display: flex;
            gap: 12px;
            margin-bottom: 20px;
            flex-wrap: wrap;
        }}
        .stat-chip {{
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: var(--radius);
            padding: 10px 18px;
            font-size: 0.8rem;
        }}
        .stat-chip .lbl {{ color: var(--text-dim); margin-bottom: 2px; }}
        .stat-chip .val {{
            color: var(--pink);
            font-family: 'Space Mono', monospace;
            font-size: 0.9rem;
            font-weight: 700;
        }}

        /* ── GRID ── */
        .rt-grid {{
            display: grid;
            grid-template-columns: 1fr 340px;
            grid-template-rows: 420px auto;
            gap: 16px;
        }}
        @media(max-width:900px) {{ .rt-grid {{ grid-template-columns: 1fr; }} }}

        .card {{
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: var(--radius);
            overflow: hidden;
        }}
        .card-header {{
            display: flex;
            align-items: center;
            gap: 8px;
            padding: 14px 18px;
            border-bottom: 1px solid var(--border);
            font-size: 0.82rem;
            font-weight: 600;
            color: var(--lavender);
        }}
        .badge {{
            padding: 2px 8px;
            border-radius: 4px;
            font-size: 0.68rem;
            font-weight: 700;
            font-family: 'Space Mono', monospace;
        }}
        .badge-pink  {{ background: var(--pink-dim);   color: #ffc6d9; }}
        .badge-purple{{ background: var(--purple-dim); color: var(--lavender); }}
        .badge-green {{ background: #1a4a2a; color: var(--green); }}

        #map-rt, #map-hist {{
            width: 100%;
            height: 100%;
        }}
        .map-card {{ height: 420px; }}

        /* ── LIVE PANEL ── */
        .live-panel {{
            padding: 18px;
            display: flex;
            flex-direction: column;
            gap: 14px;
        }}
        .live-field .lbl {{
            font-size: 0.72rem;
            color: var(--text-dim);
            text-transform: uppercase;
            letter-spacing: 0.08em;
            margin-bottom: 4px;
        }}
        .live-field .val {{
            font-family: 'Space Mono', monospace;
            font-size: 1rem;
            color: var(--pink);
            font-weight: 700;
        }}
        .live-grid {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 12px;
        }}
        .no-data {{
            color: var(--text-faint);
            font-size: 0.82rem;
            text-align: center;
            padding: 24px;
            font-style: italic;
        }}

        /* ── HISTÓRICO ── */
        .hist-layout {{
            display: grid;
            grid-template-columns: 1fr 380px;
            gap: 16px;
        }}
        @media(max-width:900px) {{ .hist-layout {{ grid-template-columns: 1fr; }} }}

        .hist-map-card {{ height: 500px; }}

        .filter-bar {{
            display: flex;
            align-items: center;
            gap: 10px;
            margin-bottom: 16px;
            flex-wrap: wrap;
        }}
        .filter-bar select, .filter-bar input {{
            background: var(--surface);
            border: 1px solid var(--border2);
            border-radius: 8px;
            padding: 8px 14px;
            color: var(--text);
            font-family: 'DM Sans', sans-serif;
            font-size: 0.82rem;
            outline: none;
            cursor: pointer;
        }}
        .filter-bar select:focus, .filter-bar input:focus {{
            border-color: var(--purple);
        }}
        .btn {{
            padding: 8px 18px;
            border-radius: 8px;
            border: none;
            font-family: 'DM Sans', sans-serif;
            font-size: 0.82rem;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.18s;
        }}
        .btn-primary {{
            background: var(--purple-dim);
            color: var(--lavender);
        }}
        .btn-primary:hover {{ background: #7a4ab0; }}
        .btn-outline {{
            background: transparent;
            border: 1px solid var(--border2);
            color: var(--text-dim);
        }}
        .btn-outline:hover {{ border-color: var(--purple); color: var(--text); }}
        .btn-pink {{
            background: var(--pink-dim);
            color: #ffc6d9;
        }}
        .btn-pink:hover {{ background: #b84070; }}

        /* ── MODAL ── */
        .modal-overlay {{
            display: none;
            position: fixed;
            inset: 0;
            background: rgba(8,6,18,0.85);
            z-index: 200;
            align-items: center;
            justify-content: center;
            backdrop-filter: blur(4px);
        }}
        .modal-overlay.open {{ display: flex; }}
        .modal {{
            background: var(--surface);
            border: 1px solid var(--border2);
            border-radius: 14px;
            padding: 28px;
            width: 420px;
            max-width: 95vw;
            box-shadow: 0 24px 60px rgba(0,0,0,0.6);
        }}
        .modal h3 {{
            font-family: 'Space Mono', monospace;
            font-size: 1rem;
            color: var(--lavender);
            margin-bottom: 20px;
        }}
        .modal-field {{
            margin-bottom: 16px;
        }}
        .modal-field label {{
            display: block;
            font-size: 0.78rem;
            color: var(--text-dim);
            margin-bottom: 6px;
            text-transform: uppercase;
            letter-spacing: 0.06em;
        }}
        .modal-field input {{
            width: 100%;
            background: var(--surface2);
            border: 1px solid var(--border2);
            border-radius: 8px;
            padding: 10px 14px;
            color: var(--text);
            font-family: 'DM Sans', sans-serif;
            font-size: 0.88rem;
            outline: none;
        }}
        .modal-field input:focus {{ border-color: var(--purple); }}
        .modal-actions {{
            display: flex;
            gap: 10px;
            justify-content: flex-end;
            margin-top: 20px;
        }}
        .quick-ranges {{
            display: flex;
            gap: 6px;
            flex-wrap: wrap;
            margin-bottom: 16px;
        }}
        .quick-btn {{
            padding: 5px 12px;
            border-radius: 6px;
            border: 1px solid var(--border2);
            background: var(--surface2);
            color: var(--text-dim);
            font-size: 0.75rem;
            cursor: pointer;
            transition: all 0.15s;
        }}
        .quick-btn:hover {{ border-color: var(--purple); color: var(--lavender); }}

        /* ── RESULTS PANEL ── */
        .results-panel {{
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: var(--radius);
            overflow: hidden;
            height: 500px;
            display: flex;
            flex-direction: column;
        }}
        .results-header {{
            padding: 14px 18px;
            border-bottom: 1px solid var(--border);
            display: flex;
            align-items: center;
            justify-content: space-between;
            font-size: 0.82rem;
        }}
        .results-count {{
            font-family: 'Space Mono', monospace;
            color: var(--pink);
            font-size: 0.78rem;
        }}
        .results-list {{
            overflow-y: auto;
            flex: 1;
            padding: 8px;
        }}
        .result-item {{
            display: flex;
            align-items: center;
            gap: 12px;
            padding: 10px 12px;
            border-radius: 8px;
            cursor: pointer;
            transition: background 0.15s;
            border-bottom: 1px solid var(--border);
        }}
        .result-item:last-child {{ border-bottom: none; }}
        .result-item:hover {{ background: var(--surface2); }}
        .result-dot {{
            width: 8px; height: 8px;
            border-radius: 50%;
            background: var(--pink);
            flex-shrink: 0;
        }}
        .result-coords {{
            font-family: 'Space Mono', monospace;
            font-size: 0.72rem;
            color: var(--lavender);
        }}
        .result-time {{
            font-size: 0.72rem;
            color: var(--text-dim);
            margin-left: auto;
        }}
        .result-device {{
            font-size: 0.7rem;
            color: var(--text-faint);
        }}

        /* ── SCROLLBAR ── */
        ::-webkit-scrollbar {{ width: 4px; }}
        ::-webkit-scrollbar-track {{ background: var(--surface); }}
        ::-webkit-scrollbar-thumb {{ background: var(--border2); border-radius: 4px; }}

        /* ── FOOTER ── */
        .footer {{
            text-align: center;
            padding: 20px;
            font-family: 'Space Mono', monospace;
            font-size: 0.68rem;
            color: var(--text-faint);
            border-top: 1px solid var(--border);
            margin-top: 12px;
        }}

        /* ── TOAST ── */
        .toast {{
            position: fixed;
            bottom: 24px;
            right: 24px;
            background: var(--surface2);
            border: 1px solid var(--border2);
            border-radius: 10px;
            padding: 12px 20px;
            font-size: 0.82rem;
            color: var(--text);
            z-index: 300;
            transform: translateY(80px);
            opacity: 0;
            transition: all 0.3s;
            pointer-events: none;
        }}
        .toast.show {{ transform: translateY(0); opacity: 1; }}
        .leaflet-container {{ background: #1a1530 !important; }}
    </style>
</head>
<body>

<!-- NAVBAR -->
<nav>
    <div class="nav-brand">
        📡 <span>GIO GRUPO 2=)</span>&nbsp;TELEMETRY
    </div>
    <div class="nav-tabs">
        <button class="nav-tab active" onclick="switchView('realtime')" id="tab-rt">
            <div class="dot-live"></div> Tiempo Real
        </button>
        <button class="nav-tab" onclick="switchView('historical')" id="tab-hist">
            🗂 Histórico
        </button>
    </div>
    <div class="nav-meta">{EC2_NAME}</div>
</nav>

<!-- ── VISTA TIEMPO REAL ── -->
<div class="view active" id="view-realtime">
    <div class="stats-bar">
        <div class="stat-chip">
            <div class="lbl">Total registros</div>
            <div class="val" id="stat-total">—</div>
        </div>
        <div class="stat-chip">
            <div class="lbl">Primer registro</div>
            <div class="val" id="stat-first">—</div>
        </div>
        <div class="stat-chip">
            <div class="lbl">Último registro</div>
            <div class="val" id="stat-last">—</div>
        </div>
        <div class="stat-chip">
            <div class="lbl">Puntos en ruta</div>
            <div class="val" id="stat-route-pts">—</div>
        </div>
    </div>

    <div class="rt-grid">
        <!-- Mapa -->
        <div class="card map-card">
            <div class="card-header">
                <span class="badge badge-pink">LIVE</span>
                Geo-localización en Tiempo Real
            </div>
            <div id="map-rt" style="height:calc(100% - 45px);"></div>
        </div>

        <!-- Panel live -->
        <div class="card" style="grid-row: span 2; display:flex; flex-direction:column;">
            <div class="card-header">
                <span class="badge badge-green">●</span>
                Última Posición
            </div>
            <div class="live-panel" id="live-panel">
                <p class="no-data">Cargando última posición...</p>
            </div>
        </div>

        <!-- Info ruta -->
        <div class="card">
            <div class="card-header">
                <span class="badge badge-purple">RUTA</span>
                Recorrido desde este refresh
            </div>
            <div class="live-panel" id="route-info">
                <p class="no-data">La polilínea se construye desde que abriste la página</p>
            </div>
        </div>
    </div>
</div>

<!-- ── VISTA HISTÓRICO ── -->
<div class="view" id="view-historical">
    <div class="filter-bar">
        <select id="quick-select" onchange="applyQuickRange(this.value)">
            <option value="">— Rango rápido —</option>
            <option value="30m">Últimos 30 min</option>
            <option value="1h">Última hora</option>
            <option value="3h">Últimas 3 horas</option>
            <option value="6h">Últimas 6 horas</option>
            <option value="today">Hoy</option>
            <option value="yesterday">Ayer</option>
            <option value="week">Esta semana</option>
        </select>
        <button class="btn btn-outline" onclick="openModal()">📅 Rango personalizado</button>
        <button class="btn btn-primary" onclick="runHistoricQuery()">Buscar</button>
        <button class="btn btn-outline" onclick="clearHistoric()">Limpiar</button>
        <span id="hist-status" style="font-size:0.78rem; color:var(--text-dim); margin-left:4px;"></span>
    </div>

    <div class="hist-layout">
        <!-- Mapa histórico -->
        <div class="card hist-map-card">
            <div class="card-header">
                <span class="badge badge-purple">HIST</span>
                Recorrido en la ventana seleccionada
            </div>
            <div id="map-hist" style="height:calc(100% - 45px);"></div>
        </div>

        <!-- Lista de resultados -->
        <div class="results-panel">
            <div class="results-header">
                <span style="color:var(--lavender); font-weight:600;">Registros encontrados</span>
                <span class="results-count" id="results-count">—</span>
            </div>
            <div class="results-list" id="results-list">
                <p class="no-data">Selecciona un rango y presiona Buscar</p>
            </div>
        </div>
    </div>
</div>

<!-- MODAL RANGO PERSONALIZADO -->
<div class="modal-overlay" id="modal-overlay" onclick="closeModalOutside(event)">
    <div class="modal">
        <h3>📅 Rango personalizado</h3>
        <div class="quick-ranges">
            <button class="quick-btn" onclick="setQuick('30m')">30 min</button>
            <button class="quick-btn" onclick="setQuick('1h')">1 hora</button>
            <button class="quick-btn" onclick="setQuick('3h')">3 horas</button>
            <button class="quick-btn" onclick="setQuick('6h')">6 horas</button>
            <button class="quick-btn" onclick="setQuick('today')">Hoy</button>
            <button class="quick-btn" onclick="setQuick('yesterday')">Ayer</button>
        </div>
        <div class="modal-field">
            <label>Desde</label>
            <input type="datetime-local" id="modal-start">
        </div>
        <div class="modal-field">
            <label>Hasta</label>
            <input type="datetime-local" id="modal-end">
        </div>
        <div class="modal-actions">
            <button class="btn btn-outline" onclick="closeModal()">Cancelar</button>
            <button class="btn btn-pink" onclick="applyModal()">Aplicar</button>
        </div>
    </div>
</div>

<!-- TOAST -->
<div class="toast" id="toast"></div>

<footer class="footer">
    GIO Telemetry · {EC2_NAME} · PostgreSQL RDS · AWS · Actualización cada 2s
</footer>

<script>
// =============================================
// ESTADO GLOBAL
// =============================================
var mapRT   = null;
var mapHist = null;
var markerRT    = null;
var routeLineRT = null;
var routeLineHist = null;
var histMarkers = [];
var firstPositionRT = true;
var sessionPoints = [];  // puntos desde este refresh
var currentRange  = {{ start: null, end: null }};
var CACHE_KEY = 'gio_hist_cache';
var CACHE_PTS  = 20; // puntos a guardar en localStorage

// =============================================
// INIT MAPAS
// =============================================
function initMaps() {{
    var tileUrl = 'https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png';
    var tileOpts = {{ attribution: '© OpenStreetMap' }};

    mapRT = L.map('map-rt').setView([10.9878, -74.7889], 13);
    L.tileLayer(tileUrl, tileOpts).addTo(mapRT);

    mapHist = L.map('map-hist').setView([10.9878, -74.7889], 13);
    L.tileLayer(tileUrl, tileOpts).addTo(mapHist);

    // Cargar cache de localStorage en mapa histórico al inicio
    loadCachedRoute();
}}

function makeCarIcon() {{
    return L.divIcon({{
        html: '<span style="font-size:26px;filter:hue-rotate(300deg) saturate(4) brightness(1.3)">🚗</span>',
        iconSize: [30, 30],
        className: ''
    }});
}}

// =============================================
// VISTA SWITCHER
// =============================================
function switchView(view) {{
    document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
    document.querySelectorAll('.nav-tab').forEach(t => t.classList.remove('active'));
    document.getElementById('view-' + view).classList.add('active');
    document.getElementById('tab-' + (view === 'realtime' ? 'rt' : 'hist')).classList.add('active');
    // Forzar resize del mapa activo
    setTimeout(() => {{
        if (view === 'realtime' && mapRT) mapRT.invalidateSize();
        if (view === 'historical' && mapHist) mapHist.invalidateSize();
    }}, 50);
}}

// =============================================
// TIEMPO REAL — fetchLatest
// =============================================
function fetchLatest() {{
    fetch('/api/latest').then(r => r.json()).then(data => {{
        if (data.error) return;
        var lat = parseFloat(data.lat);
        var lon = parseFloat(data.lon);

        // Marcador
        if (!markerRT) {{
            markerRT = L.marker([lat, lon], {{icon: makeCarIcon()}}).addTo(mapRT);
        }} else {{
            markerRT.setLatLng([lat, lon]);
        }}
        if (firstPositionRT) {{
            mapRT.setView([lat, lon], 15);
            firstPositionRT = false;
        }}

        // Agregar punto a la sesión actual
        var lastPt = sessionPoints[sessionPoints.length - 1];
        if (!lastPt || lastPt[0] !== lat || lastPt[1] !== lon) {{
            sessionPoints.push([lat, lon]);
            document.getElementById('stat-route-pts').textContent = sessionPoints.length;
            drawSessionRoute();
        }}

        // Panel live
        document.getElementById('live-panel').innerHTML = `
            <div class="live-grid">
                <div class="live-field">
                    <div class="lbl">Timestamp</div>
                    <div class="val" style="font-size:0.78rem">${{data.timestamp}}</div>
                </div>
                <div class="live-field">
                    <div class="lbl">Dispositivo</div>
                    <div class="val" style="font-size:0.85rem">${{data.device}}</div>
                </div>
                <div class="live-field">
                    <div class="lbl">Latitud</div>
                    <div class="val">${{parseFloat(data.lat).toFixed(6)}}</div>
                </div>
                <div class="live-field">
                    <div class="lbl">Longitud</div>
                    <div class="val">${{parseFloat(data.lon).toFixed(6)}}</div>
                </div>
            </div>
        `;

        // Info ruta
        document.getElementById('route-info').innerHTML = `
            <div class="live-grid">
                <div class="live-field">
                    <div class="lbl">Puntos trazados</div>
                    <div class="val">${{sessionPoints.length}}</div>
                </div>
                <div class="live-field">
                    <div class="lbl">Inicio sesión</div>
                    <div class="val" style="font-size:0.72rem">${{sessionStartTime}}</div>
                </div>
            </div>
            <p style="font-size:0.72rem; color:var(--text-faint); margin-top:8px;">
                La ruta se reinicia al recargar la página
            </p>
        `;
    }}).catch(() => {{}});
}}

var sessionStartTime = new Date().toLocaleTimeString('es-CO');

function drawSessionRoute() {{
    if (sessionPoints.length < 2) return;
    // Limitar a 25 puntos para OSRM
    var pts = sessionPoints.length > 25
        ? sessionPoints.filter((_, i) => i % Math.ceil(sessionPoints.length / 25) === 0)
        : sessionPoints;
    var coords = pts.map(p => p[1] + ',' + p[0]).join(';');
    fetch('https://router.project-osrm.org/route/v1/driving/' + coords + '?overview=full&geometries=geojson')
        .then(r => r.json())
        .then(osrm => {{
            if (osrm.code !== 'Ok') {{
                // Fallback: línea recta
                if (routeLineRT) mapRT.removeLayer(routeLineRT);
                routeLineRT = L.polyline(sessionPoints, {{color:'#e879a0', weight:3, opacity:0.7}}).addTo(mapRT);
                return;
            }}
            var rc = osrm.routes[0].geometry.coordinates.map(c => [c[1], c[0]]);
            if (routeLineRT) mapRT.removeLayer(routeLineRT);
            routeLineRT = L.polyline(rc, {{color:'#e879a0', weight:4, opacity:0.85}}).addTo(mapRT);
        }}).catch(() => {{
            if (routeLineRT) mapRT.removeLayer(routeLineRT);
            routeLineRT = L.polyline(sessionPoints, {{color:'#e879a0', weight:3, opacity:0.7}}).addTo(mapRT);
        }});
}}

// =============================================
// STATS
// =============================================
function fetchStats() {{
    fetch('/api/stats').then(r => r.json()).then(data => {{
        document.getElementById('stat-total').textContent = (data.total_records || 0).toLocaleString();
        document.getElementById('stat-first').textContent = data.first_record
            ? data.first_record.substring(0,16)
            : '—';
        document.getElementById('stat-last').textContent = data.last_record
            ? data.last_record.substring(0,16)
            : '—';
    }}).catch(() => {{}});
}}

// =============================================
// HISTÓRICO — QUERY
// =============================================
function applyQuickRange(val) {{
    if (!val) return;
    var now = new Date();
    var start;
    if (val === '30m')       start = new Date(now - 30*60*1000);
    else if (val === '1h')   start = new Date(now - 60*60*1000);
    else if (val === '3h')   start = new Date(now - 3*60*60*1000);
    else if (val === '6h')   start = new Date(now - 6*60*60*1000);
    else if (val === 'today') {{
        start = new Date(now); start.setHours(0,0,0,0);
    }}
    else if (val === 'yesterday') {{
        start = new Date(now); start.setDate(start.getDate()-1); start.setHours(0,0,0,0);
        now   = new Date(start); now.setHours(23,59,59,999);
    }}
    else if (val === 'week') {{
        start = new Date(now); start.setDate(start.getDate()-7);
    }}
    currentRange.start = toLocalISO(start);
    currentRange.end   = toLocalISO(val === 'yesterday' ? now : new Date());
}}

function toLocalISO(d) {{
    var pad = n => String(n).padStart(2,'0');
    return `${{d.getFullYear()}}-${{pad(d.getMonth()+1)}}-${{pad(d.getDate())}}T${{pad(d.getHours())}}:${{pad(d.getMinutes())}}:${{pad(d.getSeconds())}}`;
}}

function runHistoricQuery() {{
    if (!currentRange.start || !currentRange.end) {{
        showToast('Selecciona un rango de tiempo primero');
        return;
    }}
    var status = document.getElementById('hist-status');
    status.textContent = 'Buscando...';
    document.getElementById('results-list').innerHTML = '<p class="no-data">Cargando...</p>';
    document.getElementById('results-count').textContent = '—';

    var url = `/api/history-range?start=${{encodeURIComponent(currentRange.start)}}&end=${{encodeURIComponent(currentRange.end)}}`;
    fetch(url).then(r => r.json()).then(data => {{
        status.textContent = '';
        if (!data || data.length === 0) {{
            document.getElementById('results-list').innerHTML = '<p class="no-data">Sin registros en ese período</p>';
            document.getElementById('results-count').textContent = '0';
            return;
        }}
        renderHistoricResults(data);
        drawHistoricRoute(data);
        saveToCache(data);
    }}).catch(err => {{
        status.textContent = 'Error al buscar';
        showToast('Error al consultar la base de datos');
    }});
}}

function renderHistoricResults(data) {{
    document.getElementById('results-count').textContent = data.length + ' registros';
    var html = data.slice().reverse().map((r, i) => `
        <div class="result-item" onclick="flyToPoint(${{r.lat}}, ${{r.lon}})">
            <div class="result-dot"></div>
            <div>
                <div class="result-coords">${{parseFloat(r.lat).toFixed(5)}}, ${{parseFloat(r.lon).toFixed(5)}}</div>
                <div class="result-device">${{r.device}}</div>
            </div>
            <div class="result-time">${{r.timestamp.substring(11,16)}}</div>
        </div>
    `).join('');
    document.getElementById('results-list').innerHTML = html;
}}

function flyToPoint(lat, lon) {{
    mapHist.flyTo([lat, lon], 16, {{duration: 0.8}});
}}

function drawHistoricRoute(data) {{
    // Limpiar marcadores anteriores
    histMarkers.forEach(m => mapHist.removeLayer(m));
    histMarkers = [];
    if (routeLineHist) {{ mapHist.removeLayer(routeLineHist); routeLineHist = null; }}

    if (data.length === 0) return;

    // Marcador inicio y fin
    var first = data[0];
    var last  = data[data.length - 1];
    var startIcon = L.divIcon({{html:'<span style="font-size:20px">🟢</span>', iconSize:[24,24], className:''}});
    var endIcon   = L.divIcon({{html:'<span style="font-size:20px">🔴</span>', iconSize:[24,24], className:''}});
    histMarkers.push(L.marker([first.lat, first.lon], {{icon: startIcon}}).addTo(mapHist).bindPopup('Inicio: ' + first.timestamp.substring(0,16)));
    if (data.length > 1) {{
        histMarkers.push(L.marker([last.lat, last.lon], {{icon: endIcon}}).addTo(mapHist).bindPopup('Fin: ' + last.timestamp.substring(0,16)));
    }}

    // Dibujar ruta con OSRM (máx 25 puntos)
    var points = data.map(r => [parseFloat(r.lat), parseFloat(r.lon)]);
    var sample = points.length > 25
        ? points.filter((_, i) => i % Math.ceil(points.length / 25) === 0)
        : points;

    var coords = sample.map(p => p[1] + ',' + p[0]).join(';');
    fetch('https://router.project-osrm.org/route/v1/driving/' + coords + '?overview=full&geometries=geojson')
        .then(r => r.json())
        .then(osrm => {{
            if (osrm.code !== 'Ok') throw new Error('OSRM error');
            var rc = osrm.routes[0].geometry.coordinates.map(c => [c[1], c[0]]);
            routeLineHist = L.polyline(rc, {{color:'#b06ef3', weight:4, opacity:0.85}}).addTo(mapHist);
            mapHist.fitBounds(routeLineHist.getBounds(), {{padding:[30,30]}});
        }}).catch(() => {{
            routeLineHist = L.polyline(points, {{color:'#b06ef3', weight:3, opacity:0.7}}).addTo(mapHist);
            mapHist.fitBounds(routeLineHist.getBounds(), {{padding:[30,30]}});
        }});
}}

function clearHistoric() {{
    histMarkers.forEach(m => mapHist.removeLayer(m));
    histMarkers = [];
    if (routeLineHist) {{ mapHist.removeLayer(routeLineHist); routeLineHist = null; }}
    document.getElementById('results-list').innerHTML = '<p class="no-data">Selecciona un rango y presiona Buscar</p>';
    document.getElementById('results-count').textContent = '—';
    document.getElementById('hist-status').textContent = '';
    document.getElementById('quick-select').value = '';
    currentRange = {{ start: null, end: null }};
}}

// =============================================
// MODAL
// =============================================
function openModal() {{
    var now = new Date();
    var oneHourAgo = new Date(now - 60*60*1000);
    document.getElementById('modal-start').value = toLocalISO(oneHourAgo);
    document.getElementById('modal-end').value   = toLocalISO(now);
    document.getElementById('modal-overlay').classList.add('open');
}}
function closeModal() {{
    document.getElementById('modal-overlay').classList.remove('open');
}}
function closeModalOutside(e) {{
    if (e.target === document.getElementById('modal-overlay')) closeModal();
}}
function setQuick(val) {{
    applyQuickRange(val);
    document.getElementById('modal-start').value = currentRange.start;
    document.getElementById('modal-end').value   = currentRange.end;
}}
function applyModal() {{
    currentRange.start = document.getElementById('modal-start').value;
    currentRange.end   = document.getElementById('modal-end').value;
    closeModal();
    runHistoricQuery();
}}

// =============================================
// CACHE localStorage
// =============================================
function saveToCache(data) {{
    try {{
        var toSave = data.slice(-CACHE_PTS);
        localStorage.setItem(CACHE_KEY, JSON.stringify({{
            savedAt: new Date().toISOString(),
            points:  toSave
        }}));
    }} catch(e) {{}}
}}

function loadCachedRoute() {{
    try {{
        var raw = localStorage.getItem(CACHE_KEY);
        if (!raw) return;
        var cache = JSON.parse(raw);
        if (!cache.points || cache.points.length < 2) return;
        var points = cache.points.map(r => [parseFloat(r.lat), parseFloat(r.lon)]);
        var cachedLine = L.polyline(points, {{
            color: '#b06ef3',
            weight: 2,
            opacity: 0.35,
            dashArray: '6 4'
        }}).addTo(mapHist);
        mapHist.fitBounds(cachedLine.getBounds(), {{padding:[40,40]}});

        // Mostrar aviso en lista
        var savedAt = new Date(cache.savedAt).toLocaleString('es-CO');
        document.getElementById('results-list').innerHTML = `
            <p class="no-data" style="padding:16px; font-size:0.78rem;">
                📦 Última búsqueda cargada del caché<br>
                <span style="color:var(--text-faint)">${{savedAt}}</span><br><br>
                Haz una nueva búsqueda para actualizar.
            </p>
        `;
        document.getElementById('results-count').textContent = cache.points.length + ' (caché)';
    }} catch(e) {{}}
}}

// =============================================
// TOAST
// =============================================
function showToast(msg) {{
    var t = document.getElementById('toast');
    t.textContent = msg;
    t.classList.add('show');
    setTimeout(() => t.classList.remove('show'), 3000);
}}

// =============================================
// LOOP PRINCIPAL
// =============================================
function updateRT() {{
    fetchLatest();
    fetchStats();
}}

// INIT
initMaps();
updateRT();
setInterval(updateRT, 2000);
</script>
</body>
</html>"""
    return html

# ==========================================
# UDP SNIFFER
# ==========================================
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

# ==========================================
# MAIN
# ==========================================
if __name__ == '__main__':
    print("[*] Verificando conexion a base de datos...")
    try:
        init_db()
    except Exception as e:
        print(f"[ERROR] No se pudo conectar a la BD: {e}")
        print("[!] Revisa tus variables de entorno DB_HOST, DB_USER, DB_PASSWORD, DB_NAME")
        exit(1)

    threading.Thread(target=udp_sniffer, daemon=True).start()

    if USE_HTTPS:
        if not DOMAIN:
            print("[ERROR] USE_HTTPS=true pero DOMAIN no esta definido.")
            exit(1)
        if not os.path.exists(CERT_FILE):
            print(f"[ERROR] Certificado no encontrado: {CERT_FILE}")
            exit(1)
        ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ssl_context.load_cert_chain(CERT_FILE, KEY_FILE)
        print(f"[*] Servidor '{EC2_NAME}' corriendo en HTTPS puerto {PORT_HTTPS}")
        print(f"[*] Dashboard: https://{DOMAIN}")
        app.run(host=HOST, port=PORT_HTTPS, debug=False, use_reloader=False, ssl_context=ssl_context)
    else:
        print(f"[*] Servidor '{EC2_NAME}' corriendo en HTTP puerto {PORT_WEB}")
        print(f"[*] Dashboard: http://0.0.0.0:{PORT_WEB}")
        app.run(host=HOST, port=PORT_WEB, debug=False, use_reloader=False)
