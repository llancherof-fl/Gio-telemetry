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

# Load .env file before importing app
from dotenv import load_dotenv
load_dotenv()

from app import create_app
from app.config import Config
from app.database import insert_data


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
                    lon = payload.get('long', 0.0)
                    device = payload.get('device', 'Desconocido')
                    raw_ts = payload.get('timestamp', 0)
                    print(f"[UDP] {addr[0]}: Lat {lat}, Lon {lon} -> PostgreSQL RDS")
                    insert_data(lat, lon, device, raw_ts)
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

    # Start UDP sniffer in background thread
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
