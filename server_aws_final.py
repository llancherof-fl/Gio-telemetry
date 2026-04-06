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
    html = """<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>""" + EC2_NAME + """ · GIO Telemetry</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Roboto:wght@300;400;500;700&family=Roboto+Mono:wght@400;500;700&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
    <style>
        /* ═══════════════════════════════════════════
           BLUE TERMINAL PALETTE — GIO TELEMETRY
           ═══════════════════════════════════════════ */
        :root {
            --bg:            #0a0e1a;
            --bg-card:       #0f1525;
            --bg-card-hover: #141c30;
            --bg-input:      #111827;
            --border:        #1e2a4a;
            --border-hover:  #2d3f6e;
            --border-accent: #3b5bdb;

            /* Blues */
            --blue-bright:   #4dabf7;
            --blue-light:    #74c0fc;
            --blue-medium:   #339af0;
            --blue-dim:      rgba(77, 171, 247, 0.12);
            --blue-glow:     rgba(77, 171, 247, 0.08);

            /* Green accents — active states */
            --green:         #51cf66;
            --green-dim:     rgba(81, 207, 102, 0.12);
            --green-border:  rgba(81, 207, 102, 0.3);

            /* Orange for highlights */
            --orange:        #ffa94d;
            --orange-dim:    rgba(255, 169, 77, 0.12);

            /* Text hierarchy */
            --text:          #e1e8f5;
            --text-secondary:#8da0c2;
            --text-muted:    #4a5e85;

            /* Route colors */
            --route-live:    #4dabf7;
            --route-hist:    #748ffc;

            --radius:      10px;
            --radius-sm:   7px;
            --radius-lg:   14px;
            --transition:  0.2s ease;
        }

        *, *::before, *::after { margin:0; padding:0; box-sizing:border-box; }
        html, body { height:100%; }
        body {
            font-family: 'Roboto', sans-serif;
            background: var(--bg);
            color: var(--text);
            min-height: 100vh;
            overflow-x: hidden;
        }

        /* ── NAVBAR ── */
        nav {
            display:flex; align-items:center; justify-content:space-between;
            padding:0 24px; height:54px;
            background: var(--bg-card);
            border-bottom:1px solid var(--border);
            position:sticky; top:0; z-index:50;
        }
        .nav-brand {
            display:flex; align-items:center; gap:10px;
            font-family:'Roboto Mono',monospace;
            font-size:0.88rem; font-weight:700;
            color:var(--blue-bright);
            letter-spacing:0.05em;
        }
        .nav-brand .brand-icon {
            font-size:18px;
        }
        .nav-brand .brand-sub {
            color:var(--text-secondary);
            font-weight:400;
        }
        .nav-tabs {
            display:flex; gap:2px;
            background:var(--bg-input);
            border:1px solid var(--border);
            border-radius:var(--radius); padding:3px;
        }
        .nav-tab {
            padding:7px 20px;
            border-radius:calc(var(--radius) - 3px);
            border:none; background:transparent;
            color:var(--text-muted);
            font-family:'Roboto',sans-serif;
            font-size:0.8rem; font-weight:500;
            cursor:pointer; transition:all var(--transition);
            display:flex; align-items:center; gap:7px;
            white-space:nowrap;
        }
        .nav-tab.active {
            background:var(--blue-dim);
            color:var(--blue-bright);
            border:1px solid rgba(77,171,247,0.2);
        }
        .nav-tab:hover:not(.active) { color:var(--text-secondary); }
        .nav-meta {
            font-family:'Roboto Mono',monospace;
            font-size:0.7rem; color:var(--text-muted);
        }
        .dot-live {
            width:6px; height:6px; border-radius:50%;
            background:var(--green);
            box-shadow:0 0 8px rgba(81,207,102,0.6);
            animation:pulse-dot 2s ease-in-out infinite;
        }
        @keyframes pulse-dot {
            0%,100% { opacity:1; box-shadow:0 0 8px rgba(81,207,102,0.6); }
            50% { opacity:0.35; box-shadow:0 0 3px rgba(81,207,102,0.2); }
        }

        /* ── VIEWS ── */
        .view { display:none; padding:20px 24px; }
        .view.active { display:block; animation:fadeIn 0.2s ease-out; }
        @keyframes fadeIn { from{opacity:0;transform:translateY(4px)} to{opacity:1;transform:translateY(0)} }

        /* ── STATS BAR ── */
        .stats-bar { display:flex; gap:10px; margin-bottom:16px; flex-wrap:wrap; }
        .stat-chip {
            background:var(--bg-card); border:1px solid var(--border);
            border-radius:var(--radius-sm); padding:10px 16px;
            flex:1; min-width:140px;
            transition:border-color var(--transition);
        }
        .stat-chip:hover { border-color:var(--border-hover); }
        .stat-chip .lbl {
            font-size:0.68rem; color:var(--text-muted);
            text-transform:uppercase; letter-spacing:0.08em;
            font-weight:500; margin-bottom:4px;
        }
        .stat-chip .val {
            color:var(--blue-bright);
            font-family:'Roboto Mono',monospace;
            font-size:0.88rem; font-weight:700;
        }

        /* ── GRID ── */
        .rt-grid {
            display:grid;
            grid-template-columns:1fr 320px;
            grid-template-rows:400px auto;
            gap:12px;
        }
        @media(max-width:960px) { .rt-grid { grid-template-columns:1fr; } }

        /* ── CARD ── */
        .card {
            background:var(--bg-card); border:1px solid var(--border);
            border-radius:var(--radius); overflow:hidden;
            transition:border-color var(--transition);
        }
        .card:hover { border-color:var(--border-hover); }
        .card-header {
            display:flex; align-items:center; gap:8px;
            padding:12px 16px; border-bottom:1px solid var(--border);
            font-size:0.78rem; font-weight:500; color:var(--text-secondary);
        }

        /* ── BADGES ── */
        .badge {
            padding:2px 8px; border-radius:5px;
            font-size:0.65rem; font-weight:700;
            font-family:'Roboto Mono',monospace;
            letter-spacing:0.04em; text-transform:uppercase;
        }
        .badge-live {
            background:var(--green-dim); color:var(--green);
            border:1px solid var(--green-border);
        }
        .badge-blue {
            background:var(--blue-dim); color:var(--blue-bright);
            border:1px solid rgba(77,171,247,0.2);
        }
        .badge-orange {
            background:var(--orange-dim); color:var(--orange);
            border:1px solid rgba(255,169,77,0.2);
        }

        /* ── MAP — CLASSIC WHITE OSM ── */
        #map-rt, #map-hist { width:100%; height:100%; }
        .map-card { height:400px; }
        .leaflet-container { background:#e8ecf1 !important; }
        /* NO filter on tiles — classic white OpenStreetMap */
        .leaflet-control-zoom a {
            background:var(--bg-card) !important;
            color:var(--blue-bright) !important;
            border-color:var(--border) !important;
        }
        .leaflet-control-zoom a:hover { background:var(--bg-card-hover) !important; }
        .leaflet-control-attribution { font-size:9px !important; }
        .leaflet-popup-content-wrapper {
            background:var(--bg-card) !important;
            color:var(--text) !important;
            border:1px solid var(--border-hover) !important;
            border-radius:var(--radius-sm) !important;
            box-shadow:0 8px 24px rgba(0,0,0,0.4) !important;
        }
        .leaflet-popup-tip { background:var(--bg-card) !important; }
        .leaflet-popup-content { font-family:'Roboto',sans-serif !important; font-size:0.8rem !important; }

        /* ── LIVE PANEL ── */
        .live-panel { padding:16px; display:flex; flex-direction:column; gap:12px; }
        .live-field {
            padding:10px 12px;
            background:var(--bg-input);
            border-radius:var(--radius-sm);
            border:1px solid transparent;
            transition:border-color var(--transition);
        }
        .live-field:hover { border-color:var(--border); }
        .live-field .lbl {
            font-size:0.65rem; color:var(--text-muted);
            text-transform:uppercase; letter-spacing:0.1em;
            font-weight:500; margin-bottom:4px;
        }
        .live-field .val {
            font-family:'Roboto Mono',monospace;
            font-size:0.92rem; color:var(--blue-bright); font-weight:700;
        }
        .live-grid { display:grid; grid-template-columns:1fr 1fr; gap:8px; }
        .no-data {
            color:var(--text-muted); font-size:0.8rem;
            text-align:center; padding:24px 16px;
        }
        .no-data-icon { font-size:1.6rem; margin-bottom:8px; opacity:0.5; }

        /* ── HISTÓRICO LAYOUT ── */
        .hist-layout { display:grid; grid-template-columns:1fr 360px; gap:12px; }
        @media(max-width:960px) { .hist-layout { grid-template-columns:1fr; } }
        .hist-map-card { height:480px; }

        /* ── FILTER BAR ── */
        .filter-bar {
            display:flex; align-items:center;
            gap:8px; margin-bottom:14px; flex-wrap:wrap;
        }
        .filter-bar select, .filter-bar input {
            background:var(--bg-card); border:1px solid var(--border);
            border-radius:var(--radius-sm); padding:8px 14px;
            color:var(--text); font-family:'Roboto',sans-serif;
            font-size:0.8rem; outline:none; cursor:pointer;
            transition:border-color var(--transition);
        }
        .filter-bar select:focus, .filter-bar input:focus { border-color:var(--blue-medium); }
        .filter-bar select option { background:var(--bg-card); color:var(--text); }

        /* ── BUTTONS ── */
        .btn {
            padding:8px 18px; border-radius:var(--radius-sm);
            border:none; font-family:'Roboto',sans-serif;
            font-size:0.8rem; font-weight:500; cursor:pointer;
            transition:all var(--transition);
            display:inline-flex; align-items:center; gap:6px;
        }
        .btn-primary {
            background:rgba(77,171,247,0.15); color:var(--blue-bright);
            border:1px solid rgba(77,171,247,0.3);
        }
        .btn-primary:hover {
            background:rgba(77,171,247,0.25);
            border-color:var(--blue-bright);
            box-shadow:0 0 16px rgba(77,171,247,0.12);
        }
        .btn-outline {
            background:transparent; border:1px solid var(--border);
            color:var(--text-secondary);
        }
        .btn-outline:hover {
            border-color:var(--border-hover); color:var(--text);
            background:var(--bg-card-hover);
        }

        /* ── MODAL ── */
        .modal-overlay {
            display:none; position:fixed; inset:0;
            background:rgba(10,14,26,0.9);
            z-index:9999; align-items:center; justify-content:center;
            backdrop-filter:blur(4px);
        }
        .modal-overlay.open { display:flex; }
        .modal {
            background:var(--bg-card);
            border:1px solid var(--border-hover);
            border-radius:var(--radius-lg);
            padding:24px; width:400px; max-width:92vw;
            box-shadow:0 24px 60px rgba(0,0,0,0.6);
            animation:modalIn 0.25s ease-out;
            position:relative; z-index:10000;
        }
        @keyframes modalIn {
            from{opacity:0;transform:scale(0.95) translateY(10px)}
            to{opacity:1;transform:scale(1) translateY(0)}
        }
        .modal h3 {
            font-family:'Roboto',sans-serif;
            font-size:0.95rem; font-weight:700;
            color:var(--text); margin-bottom:18px;
            display:flex; align-items:center; gap:8px;
        }
        .modal-field { margin-bottom:14px; }
        .modal-field label {
            display:block; font-size:0.7rem;
            color:var(--text-muted); margin-bottom:6px;
            text-transform:uppercase; letter-spacing:0.08em; font-weight:500;
        }
        .modal-field input {
            width:100%; background:var(--bg-input);
            border:1px solid var(--border);
            border-radius:var(--radius-sm);
            padding:10px 14px; color:var(--text);
            font-family:'Roboto',sans-serif;
            font-size:0.85rem; outline:none;
            transition:border-color var(--transition);
        }
        .modal-field input:focus { border-color:var(--blue-medium); }
        .modal-field input::-webkit-calendar-picker-indicator {
            filter:invert(0.6) sepia(0.2) hue-rotate(190deg);
        }
        .modal-actions { display:flex; gap:8px; justify-content:flex-end; margin-top:18px; }
        .quick-ranges { display:flex; gap:6px; flex-wrap:wrap; margin-bottom:16px; }
        .quick-btn {
            padding:5px 12px; border-radius:6px;
            border:1px solid var(--border);
            background:var(--bg-input); color:var(--text-muted);
            font-size:0.72rem; font-weight:500;
            cursor:pointer; transition:all var(--transition);
        }
        .quick-btn:hover {
            border-color:var(--blue-medium); color:var(--blue-bright);
            background:var(--blue-dim);
        }

        /* ── RESULTS PANEL ── */
        .results-panel {
            background:var(--bg-card); border:1px solid var(--border);
            border-radius:var(--radius); overflow:hidden;
            height:480px; display:flex; flex-direction:column;
        }
        .results-header {
            padding:12px 16px; border-bottom:1px solid var(--border);
            display:flex; align-items:center;
            justify-content:space-between; font-size:0.78rem;
        }
        .results-count {
            font-family:'Roboto Mono',monospace;
            color:var(--blue-bright); font-size:0.75rem; font-weight:500;
        }
        .results-list { overflow-y:auto; flex:1; padding:6px; }
        .result-item {
            display:flex; align-items:center; gap:12px;
            padding:10px 12px; border-radius:var(--radius-sm);
            cursor:pointer; transition:all var(--transition); margin-bottom:2px;
        }
        .result-item:hover { background:var(--bg-card-hover); }
        .result-item:active { transform:scale(0.997); }
        .result-index {
            width:26px; height:26px; border-radius:6px;
            background:var(--blue-dim);
            border:1px solid rgba(77,171,247,0.15);
            display:flex; align-items:center; justify-content:center;
            font-family:'Roboto Mono',monospace;
            font-size:0.65rem; font-weight:700;
            color:var(--blue-bright); flex-shrink:0;
        }
        .result-info { flex:1; min-width:0; }
        .result-coords {
            font-family:'Roboto Mono',monospace;
            font-size:0.72rem; color:var(--text); font-weight:500;
        }
        .result-device { font-size:0.68rem; color:var(--text-muted); margin-top:1px; }
        .result-time {
            font-family:'Roboto Mono',monospace;
            font-size:0.7rem; color:var(--text-secondary); flex-shrink:0;
        }

        /* ── SCROLLBAR ── */
        ::-webkit-scrollbar { width:4px; }
        ::-webkit-scrollbar-track { background:transparent; }
        ::-webkit-scrollbar-thumb { background:var(--border-hover); border-radius:4px; }

        /* ── FOOTER ── */
        .footer {
            text-align:center; padding:18px;
            font-size:0.68rem; color:var(--text-muted);
            border-top:1px solid var(--border); margin-top:12px;
            font-family:'Roboto Mono',monospace;
        }
        .footer span { color:var(--blue-bright); font-weight:500; }

        /* ── TOAST ── */
        .toast {
            position:fixed; bottom:20px; right:20px;
            background:var(--bg-card);
            border:1px solid var(--border-hover);
            border-radius:var(--radius); padding:12px 20px;
            font-size:0.8rem; color:var(--text);
            z-index:10001;
            transform:translateY(80px); opacity:0;
            transition:all 0.3s ease;
            pointer-events:none;
            box-shadow:0 8px 30px rgba(0,0,0,0.5);
        }
        .toast.show { transform:translateY(0); opacity:1; }

        .skeleton {
            background:linear-gradient(90deg, var(--bg-input) 25%, var(--bg-card-hover) 50%, var(--bg-input) 75%);
            background-size:200% 100%;
            animation:shimmer 1.5s infinite; border-radius:4px;
        }
        @keyframes shimmer { 0%{background-position:200% 0} 100%{background-position:-200% 0} }

        @media(max-width:640px) {
            nav { padding:0 14px; height:50px; }
            .nav-meta { display:none; }
            .view { padding:14px; }
            .stat-chip { padding:8px 12px; min-width:100px; }
        }
    </style>
</head>
<body>

<nav>
    <div class="nav-brand">
        <span class="brand-icon">📡</span>
        GIO <span class="brand-sub">TELEMETRY</span>
    </div>
    <div class="nav-tabs">
        <button class="nav-tab active" onclick="switchView('realtime')" id="tab-rt">
            <div class="dot-live"></div> Tiempo Real
        </button>
        <button class="nav-tab" onclick="switchView('historical')" id="tab-hist">
            📁 Histórico
        </button>
    </div>
    <div class="nav-meta">""" + EC2_NAME + """</div>
</nav>

<!-- VISTA TIEMPO REAL -->
<div class="view active" id="view-realtime">
    <div class="stats-bar">
        <div class="stat-chip">
            <div class="lbl">Total registros</div>
            <div class="val" id="stat-total">&mdash;</div>
        </div>
        <div class="stat-chip">
            <div class="lbl">Primer registro</div>
            <div class="val" id="stat-first">&mdash;</div>
        </div>
        <div class="stat-chip">
            <div class="lbl">Último registro</div>
            <div class="val" id="stat-last">&mdash;</div>
        </div>
        <div class="stat-chip">
            <div class="lbl">Puntos en ruta</div>
            <div class="val" id="stat-route-pts">0</div>
        </div>
    </div>
    <div class="rt-grid">
        <div class="card map-card">
            <div class="card-header">
                <span class="badge badge-live">● LIVE</span>
                Geo-localización en Tiempo Real
            </div>
            <div id="map-rt" style="height:calc(100% - 42px);"></div>
        </div>
        <div class="card" style="grid-row:span 2;display:flex;flex-direction:column;">
            <div class="card-header">
                <span class="badge badge-blue">GPS</span>
                Última Posición
            </div>
            <div class="live-panel" id="live-panel">
                <div class="no-data"><div class="no-data-icon">📍</div>Cargando última posición...</div>
            </div>
        </div>
        <div class="card">
            <div class="card-header">
                <span class="badge badge-orange">RUTA</span>
                Recorrido de esta sesión
            </div>
            <div class="live-panel" id="route-info">
                <div class="no-data"><div class="no-data-icon">🛣️</div>La polilínea se construye desde que abriste la página</div>
            </div>
        </div>
    </div>
</div>

<!-- VISTA HISTÓRICO -->
<div class="view" id="view-historical">
    <div class="filter-bar">
        <select id="quick-select" onchange="applyQuickRange(this.value)">
            <option value="">Rango rápido</option>
            <option value="30m">30 min</option>
            <option value="1h">1 hora</option>
            <option value="3h">3 horas</option>
            <option value="6h">6 horas</option>
            <option value="today">Hoy</option>
            <option value="yesterday">Ayer</option>
            <option value="week">Esta semana</option>
        </select>
        <button class="btn btn-outline" onclick="openModal()">📅 Personalizado</button>
        <button class="btn btn-primary" onclick="runHistoricQuery()">Buscar</button>
        <button class="btn btn-outline" onclick="clearHistoric()">Limpiar</button>
        <span id="hist-status" style="font-size:0.75rem;color:var(--text-muted);margin-left:2px;"></span>
    </div>
    <div class="hist-layout">
        <div class="card hist-map-card">
            <div class="card-header">
                <span class="badge badge-blue">HIST</span>
                Recorrido en la ventana seleccionada
            </div>
            <div id="map-hist" style="height:calc(100% - 42px);"></div>
        </div>
        <div class="results-panel">
            <div class="results-header">
                <span style="color:var(--text-secondary);font-weight:500;">Registros</span>
                <span class="results-count" id="results-count">&mdash;</span>
            </div>
            <div class="results-list" id="results-list">
                <div class="no-data"><div class="no-data-icon">🔍</div>Selecciona un rango y presiona Buscar</div>
            </div>
        </div>
    </div>
</div>

<!-- MODAL -->
<div class="modal-overlay" id="modal-overlay" onclick="closeModalOutside(event)">
    <div class="modal" onclick="event.stopPropagation()">
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
            <button class="btn btn-primary" onclick="applyModal()">Aplicar</button>
        </div>
    </div>
</div>

<div class="toast" id="toast"></div>

<footer class="footer">
    <span>GIO Telemetry</span> &mdash; """ + EC2_NAME + """ &mdash; PostgreSQL RDS &mdash; AWS &mdash; Actualización cada 2s
</footer>

<script>
var mapRT=null,mapHist=null;
var markerRT=null,routeLineRT=null,routeLineHist=null;
var histMarkers=[];
var firstPositionRT=true;
var sessionPoints=[];
var currentRange={start:null,end:null};
var CACHE_KEY='gio_hist_cache';
var CACHE_PTS=20;
var sessionStartTime=new Date().toLocaleTimeString('es-CO');

function initMaps(){
    // CLASSIC WHITE OpenStreetMap — no filters
    var tileUrl='https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png';
    var tileOpts={attribution:'&copy; OpenStreetMap',maxZoom:19};
    mapRT=L.map('map-rt').setView([10.9878,-74.7889],13);
    L.tileLayer(tileUrl,tileOpts).addTo(mapRT);
    mapHist=L.map('map-hist').setView([10.9878,-74.7889],13);
    L.tileLayer(tileUrl,tileOpts).addTo(mapHist);
    loadCachedRoute();
}

function makeCarIcon(){
    return L.divIcon({
        html:'<svg width="32" height="32" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">'
            +'<rect x="3" y="8" width="18" height="9" rx="3" fill="#339af0" stroke="#0a0e1a" stroke-width="1.2"/>'
            +'<rect x="5" y="4.5" width="14" height="7" rx="2.5" fill="#4dabf7" stroke="#0a0e1a" stroke-width="1.2"/>'
            +'<circle cx="7" cy="17.5" r="2.2" fill="#0a0e1a" stroke="#4dabf7" stroke-width="1.5"/>'
            +'<circle cx="17" cy="17.5" r="2.2" fill="#0a0e1a" stroke="#4dabf7" stroke-width="1.5"/>'
            +'<rect x="7" y="6" width="4" height="3.5" rx="0.8" fill="rgba(255,255,255,0.4)"/>'
            +'<rect x="13" y="6" width="4" height="3.5" rx="0.8" fill="rgba(255,255,255,0.4)"/>'
            +'<circle cx="12" cy="11" r="1" fill="#ffa94d"/>'
            +'</svg>',
        iconSize:[32,32],
        iconAnchor:[16,22],
        className:''
    });
}

function switchView(view){
    document.querySelectorAll('.view').forEach(function(v){v.classList.remove('active')});
    document.querySelectorAll('.nav-tab').forEach(function(t){t.classList.remove('active')});
    document.getElementById('view-'+view).classList.add('active');
    document.getElementById('tab-'+(view==='realtime'?'rt':'hist')).classList.add('active');
    setTimeout(function(){
        if(view==='realtime'&&mapRT) mapRT.invalidateSize();
        if(view==='historical'&&mapHist) mapHist.invalidateSize();
    },80);
}

function fetchLatest(){
    fetch('/api/latest').then(function(r){return r.json()}).then(function(data){
        if(data.error) return;
        var lat=parseFloat(data.lat);
        var lon=parseFloat(data.lon);
        if(!markerRT){
            markerRT=L.marker([lat,lon],{icon:makeCarIcon()}).addTo(mapRT);
        }else{
            markerRT.setLatLng([lat,lon]);
        }
        if(firstPositionRT){
            mapRT.setView([lat,lon],15);
            firstPositionRT=false;
        }
        var lastPt=sessionPoints[sessionPoints.length-1];
        if(!lastPt||lastPt[0]!==lat||lastPt[1]!==lon){
            sessionPoints.push([lat,lon]);
            document.getElementById('stat-route-pts').textContent=sessionPoints.length;
            drawSessionRoute();
        }
        document.getElementById('live-panel').innerHTML=
            '<div class="live-grid">'+
                '<div class="live-field"><div class="lbl">Timestamp</div><div class="val" style="font-size:0.75rem">'+data.timestamp+'</div></div>'+
                '<div class="live-field"><div class="lbl">Dispositivo</div><div class="val" style="font-size:0.82rem">'+data.device+'</div></div>'+
            '</div>'+
            '<div class="live-grid" style="margin-top:4px">'+
                '<div class="live-field"><div class="lbl">Latitud</div><div class="val">'+lat.toFixed(6)+'</div></div>'+
                '<div class="live-field"><div class="lbl">Longitud</div><div class="val">'+lon.toFixed(6)+'</div></div>'+
            '</div>';
        document.getElementById('route-info').innerHTML=
            '<div class="live-grid">'+
                '<div class="live-field"><div class="lbl">Puntos trazados</div><div class="val">'+sessionPoints.length+'</div></div>'+
                '<div class="live-field"><div class="lbl">Inicio sesión</div><div class="val" style="font-size:0.75rem">'+sessionStartTime+'</div></div>'+
            '</div>'+
            '<p style="font-size:0.7rem;color:var(--text-muted);margin-top:8px;padding:0 4px">La ruta se reinicia al recargar la página.</p>';
    }).catch(function(){});
}

function drawSessionRoute(){
    if(sessionPoints.length<2) return;
    drawInterimRoute();
    if(osrmState.timer) clearTimeout(osrmState.timer);
    osrmState.timer=setTimeout(executeSessionOSRM,osrmState.DEBOUNCE);
}

function drawInterimRoute(){
    if(routeLineRT) mapRT.removeLayer(routeLineRT);
    if(osrmState.cachedRoute&&osrmState.cachedRoute.length>1){
        var latest=sessionPoints[sessionPoints.length-1];
        var combined=osrmState.cachedRoute.concat([latest]);
        routeLineRT=L.polyline(combined,{color:'#4dabf7',weight:3.5,opacity:0.85}).addTo(mapRT);
    }else{
        routeLineRT=L.polyline(sessionPoints,{color:'#4dabf7',weight:3,opacity:0.7}).addTo(mapRT);
    }
}

function executeSessionOSRM(){
    if(osrmState.inFlight) return;
    if(sessionPoints.length<2) return;
    var pts=sessionPoints;
    if(pts.length>25){
        var step=Math.ceil(pts.length/23);
        var sampled=[pts[0]];
        for(var i=step;i<pts.length-1;i+=step) sampled.push(pts[i]);
        sampled.push(pts[pts.length-1]);
        pts=sampled;
    }
    var coords=pts.map(function(p){return p[1]+','+p[0]}).join(';');
    fetch('https://router.project-osrm.org/route/v1/driving/'+coords+'?overview=full&geometries=geojson')
        .then(function(r){return r.json()})
        .then(function(osrm){
            if(osrm.code!=='Ok'){
                if(routeLineRT) mapRT.removeLayer(routeLineRT);
                routeLineRT=L.polyline(sessionPoints,{color:'#4dabf7',weight:3,opacity:0.7}).addTo(mapRT);
                return;
            }
            var rc=osrm.routes[0].geometry.coordinates.map(function(c){return [c[1],c[0]]});
            if(routeLineRT) mapRT.removeLayer(routeLineRT);
            routeLineRT=L.polyline(rc,{color:'#4dabf7',weight:3.5,opacity:0.85}).addTo(mapRT);
        }).catch(function(){
            osrmState.inFlight=false;
        });
}

function fetchStats(){
    fetch('/api/stats').then(function(r){return r.json()}).then(function(data){
        document.getElementById('stat-total').textContent=(data.total_records||0).toLocaleString();
        document.getElementById('stat-first').textContent=data.first_record?data.first_record.substring(0,16):'—';
        document.getElementById('stat-last').textContent=data.last_record?data.last_record.substring(0,16):'—';
    }).catch(function(){});
}

function applyQuickRange(val){
    if(!val) return;
    var now=new Date();
    var start;
    if(val==='30m') start=new Date(now-30*60*1000);
    else if(val==='1h') start=new Date(now-60*60*1000);
    else if(val==='3h') start=new Date(now-3*60*60*1000);
    else if(val==='6h') start=new Date(now-6*60*60*1000);
    else if(val==='today'){start=new Date(now);start.setHours(0,0,0,0);}
    else if(val==='yesterday'){
        start=new Date(now);start.setDate(start.getDate()-1);start.setHours(0,0,0,0);
        now=new Date(start);now.setHours(23,59,59,999);
    }
    else if(val==='week'){start=new Date(now);start.setDate(start.getDate()-7);}
    currentRange.start=toLocalISO(start);
    currentRange.end=toLocalISO(val==='yesterday'?now:new Date());
}

function toLocalISO(d){
    var pad=function(n){return String(n).padStart(2,'0')};
    return d.getFullYear()+'-'+pad(d.getMonth()+1)+'-'+pad(d.getDate())+'T'+pad(d.getHours())+':'+pad(d.getMinutes())+':'+pad(d.getSeconds());
}

function runHistoricQuery(){
    if(!currentRange.start||!currentRange.end){
        showToast('Selecciona un rango de tiempo primero');
        return;
    }
    var status=document.getElementById('hist-status');
    status.textContent='Buscando...';
    status.style.color='var(--blue-bright)';
    document.getElementById('results-list').innerHTML=
        '<div class="no-data"><div class="skeleton" style="width:60%;height:12px;margin:8px auto"></div><div class="skeleton" style="width:40%;height:12px;margin:8px auto"></div></div>';
    document.getElementById('results-count').textContent='...';
    var url='/api/history-range?start='+encodeURIComponent(currentRange.start)+'&end='+encodeURIComponent(currentRange.end);
    fetch(url).then(function(r){return r.json()}).then(function(data){
        status.textContent='';
        if(!data||data.length===0){
            document.getElementById('results-list').innerHTML=
                '<div class="no-data"><div class="no-data-icon">📭</div>Sin registros en ese período</div>';
            document.getElementById('results-count').textContent='0';
            return;
        }
        renderHistoricResults(data);
        drawHistoricRoute(data);
        saveToCache(data);
    }).catch(function(){
        status.textContent='Error';
        status.style.color='#ff6b6b';
        showToast('Error al consultar la base de datos');
    });
}

function renderHistoricResults(data){
    document.getElementById('results-count').textContent=data.length+' reg.';
    var reversed=data.slice().reverse();
    var html=reversed.map(function(r,i){
        return '<div class="result-item" onclick="flyToPoint('+r.lat+','+r.lon+')">'+
            '<div class="result-index">'+(data.length-i)+'</div>'+
            '<div class="result-info">'+
                '<div class="result-coords">'+parseFloat(r.lat).toFixed(5)+', '+parseFloat(r.lon).toFixed(5)+'</div>'+
                '<div class="result-device">'+r.device+'</div>'+
            '</div>'+
            '<div class="result-time">'+r.timestamp.substring(11,16)+'</div>'+
        '</div>';
    }).join('');
    document.getElementById('results-list').innerHTML=html;
}

function flyToPoint(lat,lon){mapHist.flyTo([lat,lon],16,{duration:0.6});}

function drawHistoricRoute(data){
    histMarkers.forEach(function(m){mapHist.removeLayer(m)});
    histMarkers=[];
    if(routeLineHist){mapHist.removeLayer(routeLineHist);routeLineHist=null;}
    if(data.length===0) return;

    var first=data[0];
    var last=data[data.length-1];
    var startIcon=L.divIcon({html:'<span style="font-size:18px">🟢</span>',iconSize:[22,22],className:''});
    var endIcon=L.divIcon({html:'<span style="font-size:18px">🔴</span>',iconSize:[22,22],className:''});
    histMarkers.push(L.marker([first.lat,first.lon],{icon:startIcon}).addTo(mapHist).bindPopup('<b>Inicio</b><br>'+first.timestamp.substring(0,16)));
    if(data.length>1){
        histMarkers.push(L.marker([last.lat,last.lon],{icon:endIcon}).addTo(mapHist).bindPopup('<b>Fin</b><br>'+last.timestamp.substring(0,16)));
    }

    var points=data.map(function(r){return [parseFloat(r.lat),parseFloat(r.lon)]});

    routeLineHist=L.polyline(points,{color:'#748ffc',weight:3,opacity:0.5,dashArray:'6 4'}).addTo(mapHist);
    mapHist.fitBounds(routeLineHist.getBounds(),{padding:[30,30]});

    var sample;
    if(points.length>25){
        var step=Math.ceil(points.length/23);
        sample=[points[0]];
        for(var i=step;i<points.length-1;i+=step) sample.push(points[i]);
        sample.push(points[points.length-1]);
    }else{
        sample=points;
    }

    var status=document.getElementById('hist-status');
    status.textContent='Calculando ruta...';
    status.style.color='var(--blue-bright)';

    var coords=sample.map(function(p){return p[1]+','+p[0]}).join(';');
    fetch('https://router.project-osrm.org/route/v1/driving/'+coords+'?overview=full&geometries=geojson')
        .then(function(r){return r.json()})
        .then(function(osrm){
            status.textContent='';
            if(osrm.code!=='Ok') throw new Error();
            var rc=osrm.routes[0].geometry.coordinates.map(function(c){return [c[1],c[0]]});
            if(routeLineHist) mapHist.removeLayer(routeLineHist);
            routeLineHist=L.polyline(rc,{color:'#748ffc',weight:3.5,opacity:0.85}).addTo(mapHist);
            mapHist.fitBounds(routeLineHist.getBounds(),{padding:[30,30]});
        }).catch(function(){
            status.textContent='';
            if(routeLineHist){
                routeLineHist.setStyle({opacity:0.7,dashArray:null});
            }
        });
}

function clearHistoric(){
    histMarkers.forEach(function(m){mapHist.removeLayer(m)});
    histMarkers=[];
    if(routeLineHist){mapHist.removeLayer(routeLineHist);routeLineHist=null;}
    document.getElementById('results-list').innerHTML=
        '<div class="no-data"><div class="no-data-icon">🔍</div>Selecciona un rango y presiona Buscar</div>';
    document.getElementById('results-count').textContent='—';
    document.getElementById('hist-status').textContent='';
    document.getElementById('quick-select').value='';
    currentRange={start:null,end:null};
}

function openModal(){
    var now=new Date();
    var oneHourAgo=new Date(now-60*60*1000);
    document.getElementById('modal-start').value=toLocalISO(oneHourAgo);
    document.getElementById('modal-end').value=toLocalISO(now);
    document.getElementById('modal-overlay').classList.add('open');
    document.body.style.overflow='hidden';
}
function closeModal(){
    document.getElementById('modal-overlay').classList.remove('open');
    document.body.style.overflow='';
}
function closeModalOutside(e){
    if(e.target===document.getElementById('modal-overlay')) closeModal();
}
function setQuick(val){
    applyQuickRange(val);
    document.getElementById('modal-start').value=currentRange.start;
    document.getElementById('modal-end').value=currentRange.end;
}
function applyModal(){
    currentRange.start=document.getElementById('modal-start').value;
    currentRange.end=document.getElementById('modal-end').value;
    closeModal();
    runHistoricQuery();
}

function saveToCache(data){
    try{
        localStorage.setItem(CACHE_KEY,JSON.stringify({
            savedAt:new Date().toISOString(),
            points:data.slice(-CACHE_PTS)
        }));
    }catch(e){}
}

function loadCachedRoute(){
    try{
        var raw=localStorage.getItem(CACHE_KEY);
        if(!raw) return;
        var cache=JSON.parse(raw);
        if(!cache.points||cache.points.length<2) return;
        var points=cache.points.map(function(r){return [parseFloat(r.lat),parseFloat(r.lon)]});
        var cachedLine=L.polyline(points,{color:'#748ffc',weight:2,opacity:0.3,dashArray:'6 4'}).addTo(mapHist);
        mapHist.fitBounds(cachedLine.getBounds(),{padding:[40,40]});
        var savedAt=new Date(cache.savedAt).toLocaleString('es-CO');
        document.getElementById('results-list').innerHTML=
            '<div class="no-data" style="padding:16px;font-size:0.78rem">'+
                '<div class="no-data-icon">📦</div>'+
                'Última búsqueda del caché<br>'+
                '<span style="color:var(--text-muted);font-size:0.72rem">'+savedAt+'</span><br><br>'+
                '<span style="color:var(--text-muted)">Haz una nueva búsqueda para actualizar</span>'+
            '</div>';
        document.getElementById('results-count').textContent=cache.points.length+' (caché)';
    }catch(e){}
}

function showToast(msg){
    var t=document.getElementById('toast');
    t.innerHTML=msg;
    t.classList.add('show');
    setTimeout(function(){t.classList.remove('show')},3000);
}

function updateRT(){fetchLatest();fetchStats();}

initMaps();
updateRT();
setInterval(updateRT,2000);
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
