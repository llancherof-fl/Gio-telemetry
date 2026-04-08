"""
GIO Telemetry — Server Entry Point
Creates the Flask app, starts the UDP sniffer, and runs the server.
"""
import os
import sys
import json
import socket
import ssl
import threading
import time
from queue import Queue, Empty, Full

# Load .env file if python-dotenv is available (local dev convenience).
# On EC2, start.sh already exports vars via 'source ~/.env', so this is optional.
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # Not installed — env vars already loaded by start.sh

from app import create_app
from app.config import Config
from app.database import insert_data_batch


_ingest_queue = Queue(maxsize=max(1000, Config.UDP_QUEUE_MAX))
_ingest_stats = {
    'received': 0,
    'queued': 0,
    'dropped': 0,
    'inserted': 0,
}


def _enqueue_packet(lat, lon, device, raw_ts):
    try:
        _ingest_queue.put_nowait((lat, lon, device, raw_ts))
        _ingest_stats['queued'] += 1
    except Full:
        _ingest_stats['dropped'] += 1


def db_writer():
    """Consume UDP queue and persist to DB in batches."""
    batch_size = max(20, Config.UDP_BATCH_SIZE)
    flush_seconds = max(0.05, Config.UDP_FLUSH_MS / 1000.0)
    log_every = max(100, Config.UDP_LOG_EVERY)

    pending = []
    last_flush = time.monotonic()

    print(f"[*] DB writer activo (batch={batch_size}, flush={int(flush_seconds * 1000)}ms)")

    while True:
        try:
            item = _ingest_queue.get(timeout=flush_seconds)
            pending.append(item)
        except Empty:
            item = None

        while len(pending) < batch_size:
            try:
                pending.append(_ingest_queue.get_nowait())
            except Empty:
                break

        now = time.monotonic()
        if not pending:
            continue

        should_flush = (
            len(pending) >= batch_size
            or item is None
            or (now - last_flush) >= flush_seconds
        )

        if not should_flush:
            continue

        try:
            inserted = insert_data_batch(pending)
            _ingest_stats['inserted'] += inserted
        except Exception as e:
            print(f"[DB-WRITER] Error insertando batch: {e}")
        finally:
            pending = []
            last_flush = now

        if (_ingest_stats['received'] % log_every) == 0 and _ingest_stats['received'] > 0:
            print(
                "[INGEST] recv={received} queued={queued} inserted={inserted} "
                "drop={dropped} qsize={qsize}".format(
                    received=_ingest_stats['received'],
                    queued=_ingest_stats['queued'],
                    inserted=_ingest_stats['inserted'],
                    dropped=_ingest_stats['dropped'],
                    qsize=_ingest_queue.qsize(),
                )
            )


# ══════════════════════════════════════════
#  UDP SNIFFER
# ══════════════════════════════════════════

def udp_sniffer():
    """Listen for UDP telemetry packets and insert into the database."""
    print(f"[*] Iniciando Sniffer UDP en puerto {Config.PORT_UDP}...")
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind((Config.HOST, Config.PORT_UDP))
        while True:
            try:
                data, addr = s.recvfrom(1024)
                try:
                    payload = json.loads(data.decode('utf-8'))
                    lat = payload.get('lat', 0.0)
                    lon = payload.get('long', payload.get('lon', 0.0))
                    device = payload.get('device', 'Desconocido')
                    raw_ts = payload.get('timestamp', 0)
                    _ingest_stats['received'] += 1
                    _enqueue_packet(lat, lon, device, raw_ts)
                except json.JSONDecodeError:
                    pass
            except Exception:
                pass


# ══════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════

if __name__ == '__main__':
    print(f"[*] GIO Telemetry — Initializing...")

    try:
        flask_app = create_app()
    except Exception as e:
        print(f"[ERROR] No se pudo inicializar la app: {e}")
        print("[!] Revisa tus variables de entorno DB_HOST, DB_USER, DB_PASSWORD, DB_NAME")
        sys.exit(1)

    # Start DB writer + UDP sniffer in background threads
    threading.Thread(target=db_writer, daemon=True).start()
    threading.Thread(target=udp_sniffer, daemon=True).start()

    # Run Flask
    if Config.USE_HTTPS:
        if not Config.DOMAIN:
            print("[ERROR] USE_HTTPS=true pero DOMAIN no esta definido.")
            sys.exit(1)
        if not os.path.exists(Config.CERT_FILE):
            print(f"[ERROR] Certificado no encontrado: {Config.CERT_FILE}")
            sys.exit(1)
        ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ssl_context.load_cert_chain(Config.CERT_FILE, Config.KEY_FILE)
        print(f"[*] Servidor '{Config.EC2_NAME}' corriendo en HTTPS puerto {Config.PORT_HTTPS}")
        print(f"[*] Dashboard: https://{Config.DOMAIN}")
        print(f"[*] Admin:     https://{Config.DOMAIN}/admin")
        flask_app.run(host=Config.HOST, port=Config.PORT_HTTPS, debug=False, use_reloader=False, ssl_context=ssl_context)
    else:
        print(f"[*] Servidor '{Config.EC2_NAME}' corriendo en HTTP puerto {Config.PORT_WEB}")
        print(f"[*] Dashboard: http://0.0.0.0:{Config.PORT_WEB}")
        print(f"[*] Admin:     http://0.0.0.0:{Config.PORT_WEB}/admin")
        flask_app.run(host=Config.HOST, port=Config.PORT_WEB, debug=False, use_reloader=False)
