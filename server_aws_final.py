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
        return jsonify({{'status': 'error', 'message': str(e)}}), 500

@app.route('/api/latest')
def api_latest():
    result = fetch_latest()
    if result:
        return jsonify(result)
    return jsonify({{'error': 'Sin datos aun'}})

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
        return jsonify({{'error': 'Se requieren parametros start y end'}}), 400
    try:
        start_dt = datetime.datetime.fromisoformat(start)
        end_dt   = datetime.datetime.fromisoformat(end)
    except ValueError:
        return jsonify({{'error': 'Formato de fecha invalido. Usa ISO 8601'}}), 400
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
    return jsonify({{
        'total_records': total,
        'first_record':  str(row['first_ts']) if row['first_ts'] else None,
        'last_record':   str(row['last_ts'])  if row['last_ts']  else None
    }})

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
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Roboto:wght@300;400;500;700&family=Roboto+Mono:wght@400;500;700&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
    <style>
        /* ── DESIGN TOKENS ── */
        :root {{
            --bg:          #060e0e;
            --bg-subtle:   #091414;
            --surface:     rgba(13, 30, 30, 0.65);
            --surface-solid: #0d1e1e;
            --surface2:    rgba(16, 40, 38, 0.5);
            --glass:       rgba(20, 50, 48, 0.35);
            --glass-hover: rgba(26, 64, 60, 0.5);
            --border:      rgba(45, 100, 95, 0.25);
            --border-strong: rgba(55, 130, 120, 0.35);
            --teal:        #2dd4bf;
            --teal-dim:    rgba(45, 212, 191, 0.15);
            --teal-mid:    rgba(45, 212, 191, 0.25);
            --cyan:        #22d3ee;
            --emerald:     #34d399;
            --emerald-dim: rgba(52, 211, 153, 0.15);
            --amber:       #fbbf24;
            --rose:        #fb7185;
            --text:        #e2f0ee;
            --text-secondary: #8aaba6;
            --text-muted:  #4a6b66;
            --radius:      12px;
            --radius-sm:   8px;
            --radius-lg:   16px;
            --blur:        16px;
            --transition:  0.2s cubic-bezier(0.4, 0, 0.2, 1);
        }}

        *, *::before, *::after {{ margin: 0; padding: 0; box-sizing: border-box; }}
        html, body {{ height: 100%; }}
        body {{
            font-family: 'Roboto', sans-serif;
            background: var(--bg);
            color: var(--text);
            min-height: 100vh;
            overflow-x: hidden;
        }}

        /* ── AMBIENT BACKGROUND ── */
        body::before {{
            content: '';
            position: fixed;
            top: -50%; left: -50%;
            width: 200%; height: 200%;
            background:
                radial-gradient(ellipse at 20% 20%, rgba(45, 212, 191, 0.04) 0%, transparent 50%),
                radial-gradient(ellipse at 80% 80%, rgba(34, 211, 238, 0.03) 0%, transparent 50%),
                radial-gradient(ellipse at 50% 50%, rgba(52, 211, 153, 0.02) 0%, transparent 60%);
            pointer-events: none;
            z-index: 0;
        }}

        /* ── NAVBAR ── */
        nav {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 0 24px;
            height: 56px;
            background: var(--surface);
            border-bottom: 1px solid var(--border);
            position: sticky;
            top: 0;
            z-index: 50;
            backdrop-filter: blur(var(--blur));
            -webkit-backdrop-filter: blur(var(--blur));
        }}
        .nav-brand {{
            display: flex;
            align-items: center;
            gap: 10px;
            font-family: 'Roboto Mono', monospace;
            font-size: 0.85rem;
            font-weight: 700;
            color: var(--teal);
            letter-spacing: 0.06em;
        }}
        .nav-brand .brand-icon {{
            width: 28px; height: 28px;
            border-radius: 8px;
            background: var(--teal-dim);
            border: 1px solid var(--border-strong);
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 14px;
        }}
        .nav-tabs {{
            display: flex;
            gap: 2px;
            background: var(--glass);
            border: 1px solid var(--border);
            border-radius: var(--radius);
            padding: 3px;
            backdrop-filter: blur(8px);
        }}
        .nav-tab {{
            padding: 7px 20px;
            border-radius: calc(var(--radius) - 3px);
            border: none;
            background: transparent;
            color: var(--text-muted);
            font-family: 'Roboto', sans-serif;
            font-size: 0.8rem;
            font-weight: 500;
            cursor: pointer;
            transition: all var(--transition);
            display: flex;
            align-items: center;
            gap: 7px;
            white-space: nowrap;
        }}
        .nav-tab.active {{
            background: var(--teal-dim);
            color: var(--teal);
            border: 1px solid var(--border-strong);
        }}
        .nav-tab:hover:not(.active) {{ color: var(--text-secondary); }}
        .nav-meta {{
            font-family: 'Roboto Mono', monospace;
            font-size: 0.7rem;
            color: var(--text-muted);
            letter-spacing: 0.04em;
        }}
        .dot-live {{
            width: 6px; height: 6px;
            border-radius: 50%;
            background: var(--emerald);
            box-shadow: 0 0 8px rgba(52, 211, 153, 0.6);
            animation: pulse-dot 2s ease-in-out infinite;
        }}
        @keyframes pulse-dot {{
            0%, 100% {{ opacity: 1; box-shadow: 0 0 8px rgba(52, 211, 153, 0.6); }}
            50% {{ opacity: 0.4; box-shadow: 0 0 4px rgba(52, 211, 153, 0.2); }}
        }}

        /* ── VIEWS ── */
        .view {{ display: none; padding: 20px 24px; position: relative; z-index: 1; }}
        .view.active {{ display: block; animation: fadeIn 0.25s ease-out; }}
        @keyframes fadeIn {{ from {{ opacity: 0; transform: translateY(6px); }} to {{ opacity: 1; transform: translateY(0); }} }}

        /* ── STATS BAR ── */
        .stats-bar {{
            display: flex;
            gap: 10px;
            margin-bottom: 16px;
            flex-wrap: wrap;
        }}
        .stat-chip {{
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: var(--radius-sm);
            padding: 10px 16px;
            backdrop-filter: blur(var(--blur));
            flex: 1;
            min-width: 140px;
            transition: border-color var(--transition);
        }}
        .stat-chip:hover {{ border-color: var(--border-strong); }}
        .stat-chip .lbl {{
            font-size: 0.68rem;
            color: var(--text-muted);
            text-transform: uppercase;
            letter-spacing: 0.08em;
            font-weight: 500;
            margin-bottom: 4px;
        }}
        .stat-chip .val {{
            color: var(--teal);
            font-family: 'Roboto Mono', monospace;
            font-size: 0.88rem;
            font-weight: 700;
        }}

        /* ── GRID ── */
        .rt-grid {{
            display: grid;
            grid-template-columns: 1fr 320px;
            grid-template-rows: 400px auto;
            gap: 12px;
        }}
        @media(max-width: 960px) {{
            .rt-grid {{ grid-template-columns: 1fr; }}
        }}

        /* ── GLASS CARD ── */
        .card {{
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: var(--radius);
            overflow: hidden;
            backdrop-filter: blur(var(--blur));
            -webkit-backdrop-filter: blur(var(--blur));
            transition: border-color var(--transition);
        }}
        .card:hover {{ border-color: var(--border-strong); }}
        .card-header {{
            display: flex;
            align-items: center;
            gap: 8px;
            padding: 12px 16px;
            border-bottom: 1px solid var(--border);
            font-size: 0.78rem;
            font-weight: 500;
            color: var(--text-secondary);
        }}

        /* ── BADGES ── */
        .badge {{
            padding: 2px 8px;
            border-radius: 5px;
            font-size: 0.65rem;
            font-weight: 700;
            font-family: 'Roboto Mono', monospace;
            letter-spacing: 0.04em;
            text-transform: uppercase;
        }}
        .badge-teal   {{ background: var(--teal-dim);    color: var(--teal); border: 1px solid rgba(45,212,191,0.2); }}
        .badge-emerald {{ background: var(--emerald-dim); color: var(--emerald); border: 1px solid rgba(52,211,153,0.2); }}
        .badge-cyan    {{ background: rgba(34,211,238,0.12); color: var(--cyan); border: 1px solid rgba(34,211,238,0.2); }}

        /* ── MAP CONTAINERS ── */
        #map-rt, #map-hist {{ width: 100%; height: 100%; }}
        .map-card {{ height: 400px; }}
        .leaflet-container {{ background: #0a1a1a !important; }}
        .leaflet-control-zoom a {{
            background: var(--surface-solid) !important;
            color: var(--teal) !important;
            border-color: var(--border) !important;
        }}
        .leaflet-control-zoom a:hover {{ background: var(--glass-hover) !important; }}
        .leaflet-control-attribution {{ opacity: 0.4; font-size: 9px !important; }}

        /* ── LIVE PANEL ── */
        .live-panel {{
            padding: 16px;
            display: flex;
            flex-direction: column;
            gap: 12px;
        }}
        .live-field {{
            padding: 10px 12px;
            background: var(--glass);
            border-radius: var(--radius-sm);
            border: 1px solid transparent;
            transition: border-color var(--transition);
        }}
        .live-field:hover {{ border-color: var(--border); }}
        .live-field .lbl {{
            font-size: 0.65rem;
            color: var(--text-muted);
            text-transform: uppercase;
            letter-spacing: 0.1em;
            font-weight: 500;
            margin-bottom: 4px;
        }}
        .live-field .val {{
            font-family: 'Roboto Mono', monospace;
            font-size: 0.92rem;
            color: var(--teal);
            font-weight: 700;
        }}
        .live-grid {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 8px;
        }}
        .no-data {{
            color: var(--text-muted);
            font-size: 0.8rem;
            text-align: center;
            padding: 24px 16px;
        }}
        .no-data-icon {{
            font-size: 1.8rem;
            margin-bottom: 8px;
            opacity: 0.5;
        }}

        /* ── HISTÓRICO LAYOUT ── */
        .hist-layout {{
            display: grid;
            grid-template-columns: 1fr 360px;
            gap: 12px;
        }}
        @media(max-width: 960px) {{ .hist-layout {{ grid-template-columns: 1fr; }} }}
        .hist-map-card {{ height: 480px; }}

        /* ── FILTER BAR ── */
        .filter-bar {{
            display: flex;
            align-items: center;
            gap: 8px;
            margin-bottom: 14px;
            flex-wrap: wrap;
        }}
        .filter-bar select,
        .filter-bar input {{
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: var(--radius-sm);
            padding: 8px 14px;
            color: var(--text);
            font-family: 'Roboto', sans-serif;
            font-size: 0.8rem;
            outline: none;
            cursor: pointer;
            backdrop-filter: blur(8px);
            transition: border-color var(--transition);
        }}
        .filter-bar select:focus,
        .filter-bar input:focus {{ border-color: var(--teal); }}
        .filter-bar select option {{ background: var(--surface-solid); color: var(--text); }}

        /* ── BUTTONS ── */
        .btn {{
            padding: 8px 18px;
            border-radius: var(--radius-sm);
            border: none;
            font-family: 'Roboto', sans-serif;
            font-size: 0.8rem;
            font-weight: 500;
            cursor: pointer;
            transition: all var(--transition);
            display: inline-flex;
            align-items: center;
            gap: 6px;
        }}
        .btn-primary {{
            background: var(--teal-mid);
            color: var(--teal);
            border: 1px solid rgba(45, 212, 191, 0.3);
        }}
        .btn-primary:hover {{
            background: rgba(45, 212, 191, 0.35);
            border-color: var(--teal);
            box-shadow: 0 0 20px rgba(45, 212, 191, 0.15);
        }}
        .btn-outline {{
            background: transparent;
            border: 1px solid var(--border);
            color: var(--text-secondary);
        }}
        .btn-outline:hover {{
            border-color: var(--border-strong);
            color: var(--text);
            background: var(--glass);
        }}
        .btn-accent {{
            background: rgba(34, 211, 238, 0.15);
            color: var(--cyan);
            border: 1px solid rgba(34, 211, 238, 0.25);
        }}
        .btn-accent:hover {{
            background: rgba(34, 211, 238, 0.25);
            border-color: var(--cyan);
        }}

        /* ── MODAL — FIXED Z-INDEX ── */
        .modal-overlay {{
            display: none;
            position: fixed;
            inset: 0;
            background: rgba(6, 14, 14, 0.88);
            z-index: 9999;
            align-items: center;
            justify-content: center;
            backdrop-filter: blur(6px);
            -webkit-backdrop-filter: blur(6px);
        }}
        .modal-overlay.open {{ display: flex; }}
        .modal {{
            background: var(--surface-solid);
            border: 1px solid var(--border-strong);
            border-radius: var(--radius-lg);
            padding: 24px;
            width: 400px;
            max-width: 92vw;
            box-shadow:
                0 24px 60px rgba(0, 0, 0, 0.5),
                0 0 60px rgba(45, 212, 191, 0.05);
            animation: modalIn 0.25s ease-out;
            position: relative;
            z-index: 10000;
        }}
        @keyframes modalIn {{
            from {{ opacity: 0; transform: scale(0.95) translateY(10px); }}
            to   {{ opacity: 1; transform: scale(1) translateY(0); }}
        }}
        .modal h3 {{
            font-family: 'Roboto', sans-serif;
            font-size: 0.95rem;
            font-weight: 700;
            color: var(--text);
            margin-bottom: 18px;
            display: flex;
            align-items: center;
            gap: 8px;
        }}
        .modal-field {{
            margin-bottom: 14px;
        }}
        .modal-field label {{
            display: block;
            font-size: 0.7rem;
            color: var(--text-muted);
            margin-bottom: 6px;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            font-weight: 500;
        }}
        .modal-field input {{
            width: 100%;
            background: var(--glass);
            border: 1px solid var(--border);
            border-radius: var(--radius-sm);
            padding: 10px 14px;
            color: var(--text);
            font-family: 'Roboto', sans-serif;
            font-size: 0.85rem;
            outline: none;
            transition: border-color var(--transition);
        }}
        .modal-field input:focus {{ border-color: var(--teal); }}
        /* Fix datetime-local icon color in dark mode */
        .modal-field input::-webkit-calendar-picker-indicator {{
            filter: invert(0.7) sepia(0.3) hue-rotate(130deg);
        }}
        .modal-actions {{
            display: flex;
            gap: 8px;
            justify-content: flex-end;
            margin-top: 18px;
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
            border: 1px solid var(--border);
            background: var(--glass);
            color: var(--text-muted);
            font-size: 0.72rem;
            font-weight: 500;
            cursor: pointer;
            transition: all var(--transition);
        }}
        .quick-btn:hover {{
            border-color: var(--teal);
            color: var(--teal);
            background: var(--teal-dim);
        }}

        /* ── RESULTS PANEL ── */
        .results-panel {{
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: var(--radius);
            overflow: hidden;
            height: 480px;
            display: flex;
            flex-direction: column;
            backdrop-filter: blur(var(--blur));
        }}
        .results-header {{
            padding: 12px 16px;
            border-bottom: 1px solid var(--border);
            display: flex;
            align-items: center;
            justify-content: space-between;
            font-size: 0.78rem;
        }}
        .results-count {{
            font-family: 'Roboto Mono', monospace;
            color: var(--teal);
            font-size: 0.75rem;
            font-weight: 500;
        }}
        .results-list {{
            overflow-y: auto;
            flex: 1;
            padding: 6px;
        }}
        .result-item {{
            display: flex;
            align-items: center;
            gap: 12px;
            padding: 10px 12px;
            border-radius: var(--radius-sm);
            cursor: pointer;
            transition: all var(--transition);
            margin-bottom: 2px;
        }}
        .result-item:hover {{
            background: var(--glass-hover);
        }}
        .result-item:active {{
            transform: scale(0.995);
        }}
        .result-index {{
            width: 26px; height: 26px;
            border-radius: 6px;
            background: var(--teal-dim);
            border: 1px solid rgba(45, 212, 191, 0.15);
            display: flex;
            align-items: center;
            justify-content: center;
            font-family: 'Roboto Mono', monospace;
            font-size: 0.65rem;
            font-weight: 700;
            color: var(--teal);
            flex-shrink: 0;
        }}
        .result-info {{ flex: 1; min-width: 0; }}
        .result-coords {{
            font-family: 'Roboto Mono', monospace;
            font-size: 0.72rem;
            color: var(--text);
            font-weight: 500;
        }}
        .result-device {{
            font-size: 0.68rem;
            color: var(--text-muted);
            margin-top: 1px;
        }}
        .result-time {{
            font-family: 'Roboto Mono', monospace;
            font-size: 0.7rem;
            color: var(--text-secondary);
            flex-shrink: 0;
        }}

        /* ── SCROLLBAR ── */
        ::-webkit-scrollbar {{ width: 4px; }}
        ::-webkit-scrollbar-track {{ background: transparent; }}
        ::-webkit-scrollbar-thumb {{ background: var(--border-strong); border-radius: 4px; }}
        ::-webkit-scrollbar-thumb:hover {{ background: var(--teal-dim); }}

        /* ── FOOTER ── */
        .footer {{
            text-align: center;
            padding: 18px;
            font-size: 0.68rem;
            color: var(--text-muted);
            border-top: 1px solid var(--border);
            margin-top: 12px;
            letter-spacing: 0.02em;
        }}
        .footer span {{ color: var(--teal); font-weight: 500; }}

        /* ── TOAST ── */
        .toast {{
            position: fixed;
            bottom: 20px;
            right: 20px;
            background: var(--surface-solid);
            border: 1px solid var(--border-strong);
            border-radius: var(--radius);
            padding: 12px 20px;
            font-size: 0.8rem;
            color: var(--text);
            z-index: 10001;
            transform: translateY(80px);
            opacity: 0;
            transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
            pointer-events: none;
            display: flex;
            align-items: center;
            gap: 8px;
            box-shadow: 0 8px 30px rgba(0, 0, 0, 0.4);
        }}
        .toast.show {{ transform: translateY(0); opacity: 1; }}

        /* ── LOADING SKELETON ── */
        .skeleton {{
            background: linear-gradient(90deg, var(--glass) 25%, var(--glass-hover) 50%, var(--glass) 75%);
            background-size: 200% 100%;
            animation: shimmer 1.5s infinite;
            border-radius: 4px;
        }}
        @keyframes shimmer {{ 0% {{ background-position: 200% 0; }} 100% {{ background-position: -200% 0; }} }}

        /* ── RESPONSIVE TWEAKS ── */
        @media(max-width: 640px) {{
            nav {{ padding: 0 14px; height: 50px; }}
            .nav-meta {{ display: none; }}
            .view {{ padding: 14px; }}
            .stats-bar {{ gap: 6px; }}
            .stat-chip {{ padding: 8px 12px; min-width: 100px; }}
            .filter-bar {{ gap: 6px; }}
            .btn {{ padding: 7px 14px; font-size: 0.75rem; }}
        }}
    </style>
</head>
<body>

<!-- ── NAVBAR ── -->
<nav>
    <div class="nav-brand">
        <div class="brand-icon">📡</div>
        GIO<span style="color: var(--text-secondary); font-weight: 400; margin-left: 2px;">TELEMETRY</span>
    </div>
    <div class="nav-tabs">
        <button class="nav-tab active" onclick="switchView('realtime')" id="tab-rt">
            <div class="dot-live"></div> Tiempo Real
        </button>
        <button class="nav-tab" onclick="switchView('historical')" id="tab-hist">
            📁 Histórico
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
            <div class="val" id="stat-route-pts">0</div>
        </div>
    </div>

    <div class="rt-grid">
        <!-- Mapa -->
        <div class="card map-card">
            <div class="card-header">
                <span class="badge badge-emerald">LIVE</span>
                Geo-localización en Tiempo Real
            </div>
            <div id="map-rt" style="height:calc(100% - 42px);"></div>
        </div>

        <!-- Panel live -->
        <div class="card" style="grid-row: span 2; display:flex; flex-direction:column;">
            <div class="card-header">
                <span class="badge badge-teal">GPS</span>
                Última Posición
            </div>
            <div class="live-panel" id="live-panel">
                <div class="no-data">
                    <div class="no-data-icon">📍</div>
                    Cargando última posición...
                </div>
            </div>
        </div>

        <!-- Info ruta -->
        <div class="card">
            <div class="card-header">
                <span class="badge badge-cyan">RUTA</span>
                Recorrido de esta sesión
            </div>
            <div class="live-panel" id="route-info">
                <div class="no-data">
                    <div class="no-data-icon">🛣️</div>
                    La polilínea se construye desde que abriste la página
                </div>
            </div>
        </div>
    </div>
</div>

<!-- ── VISTA HISTÓRICO ── -->
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
        <span id="hist-status" style="font-size:0.75rem; color:var(--text-muted); margin-left:2px;"></span>
    </div>

    <div class="hist-layout">
        <!-- Mapa histórico -->
        <div class="card hist-map-card">
            <div class="card-header">
                <span class="badge badge-cyan">HIST</span>
                Recorrido en la ventana seleccionada
            </div>
            <div id="map-hist" style="height:calc(100% - 42px);"></div>
        </div>

        <!-- Lista de resultados -->
        <div class="results-panel">
            <div class="results-header">
                <span style="color:var(--text-secondary); font-weight:500;">Registros</span>
                <span class="results-count" id="results-count">—</span>
            </div>
            <div class="results-list" id="results-list">
                <div class="no-data">
                    <div class="no-data-icon">🔍</div>
                    Selecciona un rango y presiona Buscar
                </div>
            </div>
        </div>
    </div>
</div>

<!-- ── MODAL RANGO PERSONALIZADO ── -->
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

<!-- TOAST -->
<div class="toast" id="toast"></div>

<footer class="footer">
    <span>GIO Telemetry</span> · {EC2_NAME} · PostgreSQL RDS · AWS · Actualización cada 2s
</footer>

<script>
// =============================================
// ESTADO GLOBAL
// =============================================
var mapRT = null;
var mapHist = null;
var markerRT = null;
var routeLineRT = null;
var routeLineHist = null;
var histMarkers = [];
var firstPositionRT = true;
var sessionPoints = [];
var currentRange = {{ start: null, end: null }};
var CACHE_KEY = 'gio_hist_cache';
var CACHE_PTS = 20;

// =============================================
// INIT MAPAS
// =============================================
function initMaps() {{
    var tileUrl = 'https://{{s}}.basemaps.cartocdn.com/dark_all/{{z}}/{{x}}/{{y}}{{r}}.png';
    var tileOpts = {{
        attribution: '&copy; <a href="https://carto.com/">CARTO</a>',
        subdomains: 'abcd',
        maxZoom: 19
    }};

    mapRT = L.map('map-rt', {{ zoomControl: true }}).setView([10.9878, -74.7889], 13);
    L.tileLayer(tileUrl, tileOpts).addTo(mapRT);

    mapHist = L.map('map-hist', {{ zoomControl: true }}).setView([10.9878, -74.7889], 13);
    L.tileLayer(tileUrl, tileOpts).addTo(mapHist);

    loadCachedRoute();
}}

function makeCarIcon() {{
    return L.divIcon({{
        html: '<span style="font-size:24px; filter: hue-rotate(140deg) saturate(3) brightness(1.4);">🚗</span>',
        iconSize: [28, 28],
        className: ''
    }});
}}

// =============================================
// VISTA SWITCHER
// =============================================
function switchView(view) {{
    document.querySelectorAll('.view').forEach(function(v) {{ v.classList.remove('active'); }});
    document.querySelectorAll('.nav-tab').forEach(function(t) {{ t.classList.remove('active'); }});
    document.getElementById('view-' + view).classList.add('active');
    document.getElementById('tab-' + (view === 'realtime' ? 'rt' : 'hist')).classList.add('active');
    setTimeout(function() {{
        if (view === 'realtime' && mapRT) mapRT.invalidateSize();
        if (view === 'historical' && mapHist) mapHist.invalidateSize();
    }}, 80);
}}

// =============================================
// TIEMPO REAL — fetchLatest
// =============================================
var sessionStartTime = new Date().toLocaleTimeString('es-CO');

function fetchLatest() {{
    fetch('/api/latest').then(function(r) {{ return r.json(); }}).then(function(data) {{
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
        document.getElementById('live-panel').innerHTML =
            '<div class="live-grid">' +
                '<div class="live-field">' +
                    '<div class="lbl">Timestamp</div>' +
                    '<div class="val" style="font-size:0.75rem">' + data.timestamp + '</div>' +
                '</div>' +
                '<div class="live-field">' +
                    '<div class="lbl">Dispositivo</div>' +
                    '<div class="val" style="font-size:0.82rem">' + data.device + '</div>' +
                '</div>' +
            '</div>' +
            '<div class="live-grid" style="margin-top:4px">' +
                '<div class="live-field">' +
                    '<div class="lbl">Latitud</div>' +
                    '<div class="val">' + lat.toFixed(6) + '</div>' +
                '</div>' +
                '<div class="live-field">' +
                    '<div class="lbl">Longitud</div>' +
                    '<div class="val">' + lon.toFixed(6) + '</div>' +
                '</div>' +
            '</div>';

        // Info ruta
        document.getElementById('route-info').innerHTML =
            '<div class="live-grid">' +
                '<div class="live-field">' +
                    '<div class="lbl">Puntos trazados</div>' +
                    '<div class="val">' + sessionPoints.length + '</div>' +
                '</div>' +
                '<div class="live-field">' +
                    '<div class="lbl">Inicio sesión</div>' +
                    '<div class="val" style="font-size:0.75rem">' + sessionStartTime + '</div>' +
                '</div>' +
            '</div>' +
            '<p style="font-size:0.7rem; color:var(--text-muted); margin-top:8px; padding: 0 4px;">' +
                'La ruta se reinicia al recargar la página.' +
            '</p>';
    }}).catch(function() {{}});
}}

function drawSessionRoute() {{
    if (sessionPoints.length < 2) return;
    var pts = sessionPoints.length > 25
        ? sessionPoints.filter(function(_, i) {{ return i % Math.ceil(sessionPoints.length / 25) === 0; }})
        : sessionPoints;
    var coords = pts.map(function(p) {{ return p[1] + ',' + p[0]; }}).join(';');
    fetch('https://router.project-osrm.org/route/v1/driving/' + coords + '?overview=full&geometries=geojson')
        .then(function(r) {{ return r.json(); }})
        .then(function(osrm) {{
            if (osrm.code !== 'Ok') {{
                if (routeLineRT) mapRT.removeLayer(routeLineRT);
                routeLineRT = L.polyline(sessionPoints, {{color:'#2dd4bf', weight:3, opacity:0.7}}).addTo(mapRT);
                return;
            }}
            var rc = osrm.routes[0].geometry.coordinates.map(function(c) {{ return [c[1], c[0]]; }});
            if (routeLineRT) mapRT.removeLayer(routeLineRT);
            routeLineRT = L.polyline(rc, {{color:'#2dd4bf', weight:3.5, opacity:0.85}}).addTo(mapRT);
        }}).catch(function() {{
            if (routeLineRT) mapRT.removeLayer(routeLineRT);
            routeLineRT = L.polyline(sessionPoints, {{color:'#2dd4bf', weight:3, opacity:0.7}}).addTo(mapRT);
        }});
}}

// =============================================
// STATS
// =============================================
function fetchStats() {{
    fetch('/api/stats').then(function(r) {{ return r.json(); }}).then(function(data) {{
        document.getElementById('stat-total').textContent = (data.total_records || 0).toLocaleString();
        document.getElementById('stat-first').textContent = data.first_record
            ? data.first_record.substring(0,16)
            : '—';
        document.getElementById('stat-last').textContent = data.last_record
            ? data.last_record.substring(0,16)
            : '—';
    }}).catch(function() {{}});
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
    var pad = function(n) {{ return String(n).padStart(2,'0'); }};
    return d.getFullYear() + '-' + pad(d.getMonth()+1) + '-' + pad(d.getDate()) + 'T' + pad(d.getHours()) + ':' + pad(d.getMinutes()) + ':' + pad(d.getSeconds());
}}

function runHistoricQuery() {{
    if (!currentRange.start || !currentRange.end) {{
        showToast('⚠️ Selecciona un rango de tiempo primero');
        return;
    }}
    var status = document.getElementById('hist-status');
    status.textContent = 'Buscando...';
    status.style.color = 'var(--teal)';
    document.getElementById('results-list').innerHTML =
        '<div class="no-data"><div class="skeleton" style="width:60%;height:12px;margin:8px auto;"></div>' +
        '<div class="skeleton" style="width:40%;height:12px;margin:8px auto;"></div></div>';
    document.getElementById('results-count').textContent = '...';

    var url = '/api/history-range?start=' + encodeURIComponent(currentRange.start) + '&end=' + encodeURIComponent(currentRange.end);
    fetch(url).then(function(r) {{ return r.json(); }}).then(function(data) {{
        status.textContent = '';
        if (!data || data.length === 0) {{
            document.getElementById('results-list').innerHTML =
                '<div class="no-data"><div class="no-data-icon">📭</div>Sin registros en ese período</div>';
            document.getElementById('results-count').textContent = '0';
            return;
        }}
        renderHistoricResults(data);
        drawHistoricRoute(data);
        saveToCache(data);
    }}).catch(function() {{
        status.textContent = 'Error';
        status.style.color = 'var(--rose)';
        showToast('❌ Error al consultar la base de datos');
    }});
}}

function renderHistoricResults(data) {{
    document.getElementById('results-count').textContent = data.length + ' reg.';
    var reversed = data.slice().reverse();
    var html = reversed.map(function(r, i) {{
        return '<div class="result-item" onclick="flyToPoint(' + r.lat + ', ' + r.lon + ')">' +
            '<div class="result-index">' + (data.length - i) + '</div>' +
            '<div class="result-info">' +
                '<div class="result-coords">' + parseFloat(r.lat).toFixed(5) + ', ' + parseFloat(r.lon).toFixed(5) + '</div>' +
                '<div class="result-device">' + r.device + '</div>' +
            '</div>' +
            '<div class="result-time">' + r.timestamp.substring(11,16) + '</div>' +
        '</div>';
    }}).join('');
    document.getElementById('results-list').innerHTML = html;
}}

function flyToPoint(lat, lon) {{
    mapHist.flyTo([lat, lon], 16, {{duration: 0.6}});
}}

function drawHistoricRoute(data) {{
    histMarkers.forEach(function(m) {{ mapHist.removeLayer(m); }});
    histMarkers = [];
    if (routeLineHist) {{ mapHist.removeLayer(routeLineHist); routeLineHist = null; }}

    if (data.length === 0) return;

    var first = data[0];
    var last  = data[data.length - 1];
    var startIcon = L.divIcon({{html:'<span style="font-size:18px">🟢</span>', iconSize:[22,22], className:''}});
    var endIcon   = L.divIcon({{html:'<span style="font-size:18px">🔴</span>', iconSize:[22,22], className:''}});
    histMarkers.push(
        L.marker([first.lat, first.lon], {{icon: startIcon}}).addTo(mapHist)
         .bindPopup('<b>Inicio</b><br>' + first.timestamp.substring(0,16))
    );
    if (data.length > 1) {{
        histMarkers.push(
            L.marker([last.lat, last.lon], {{icon: endIcon}}).addTo(mapHist)
             .bindPopup('<b>Fin</b><br>' + last.timestamp.substring(0,16))
        );
    }}

    var points = data.map(function(r) {{ return [parseFloat(r.lat), parseFloat(r.lon)]; }});
    var sample = points.length > 25
        ? points.filter(function(_, i) {{ return i % Math.ceil(points.length / 25) === 0; }})
        : points;

    var coords = sample.map(function(p) {{ return p[1] + ',' + p[0]; }}).join(';');
    fetch('https://router.project-osrm.org/route/v1/driving/' + coords + '?overview=full&geometries=geojson')
        .then(function(r) {{ return r.json(); }})
        .then(function(osrm) {{
            if (osrm.code !== 'Ok') throw new Error('OSRM error');
            var rc = osrm.routes[0].geometry.coordinates.map(function(c) {{ return [c[1], c[0]]; }});
            routeLineHist = L.polyline(rc, {{color:'#22d3ee', weight:3.5, opacity:0.85}}).addTo(mapHist);
            mapHist.fitBounds(routeLineHist.getBounds(), {{padding:[30,30]}});
        }}).catch(function() {{
            routeLineHist = L.polyline(points, {{color:'#22d3ee', weight:3, opacity:0.7}}).addTo(mapHist);
            mapHist.fitBounds(routeLineHist.getBounds(), {{padding:[30,30]}});
        }});
}}

function clearHistoric() {{
    histMarkers.forEach(function(m) {{ mapHist.removeLayer(m); }});
    histMarkers = [];
    if (routeLineHist) {{ mapHist.removeLayer(routeLineHist); routeLineHist = null; }}
    document.getElementById('results-list').innerHTML =
        '<div class="no-data"><div class="no-data-icon">🔍</div>Selecciona un rango y presiona Buscar</div>';
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
    document.body.style.overflow = 'hidden';
}}
function closeModal() {{
    document.getElementById('modal-overlay').classList.remove('open');
    document.body.style.overflow = '';
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
        var points = cache.points.map(function(r) {{ return [parseFloat(r.lat), parseFloat(r.lon)]; }});
        var cachedLine = L.polyline(points, {{
            color: '#22d3ee',
            weight: 2,
            opacity: 0.3,
            dashArray: '6 4'
        }}).addTo(mapHist);
        mapHist.fitBounds(cachedLine.getBounds(), {{padding:[40,40]}});

        var savedAt = new Date(cache.savedAt).toLocaleString('es-CO');
        document.getElementById('results-list').innerHTML =
            '<div class="no-data" style="padding:16px; font-size:0.78rem;">' +
                '<div class="no-data-icon">📦</div>' +
                'Última búsqueda cargada del caché<br>' +
                '<span style="color:var(--text-muted);font-size:0.72rem">' + savedAt + '</span><br><br>' +
                '<span style="color:var(--text-muted)">Haz una nueva búsqueda para actualizar</span>' +
            '</div>';
        document.getElementById('results-count').textContent = cache.points.length + ' (caché)';
    }} catch(e) {{}}
}}

// =============================================
// TOAST
// =============================================
function showToast(msg) {{
    var t = document.getElementById('toast');
    t.innerHTML = msg;
    t.classList.add('show');
    setTimeout(function() {{ t.classList.remove('show'); }}, 3000);
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