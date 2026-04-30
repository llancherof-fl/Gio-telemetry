"""
GIO Telemetry — Centralized Configuration
All environment variables are read here and nowhere else.
"""
import os


class Config:
    # ── Server ──
    HOST = '0.0.0.0'
    PORT_UDP = int(os.environ.get('PORT_UDP', 5001))
    PORT_WEB = int(os.environ.get('PORT_WEB', 8080))
    PORT_HTTPS = int(os.environ.get('PORT_HTTPS', 443))

    USE_HTTPS = os.environ.get('USE_HTTPS', 'false').lower() == 'true'
    DOMAIN = os.environ.get('DOMAIN', '')
    CERT_FILE = os.environ.get('CERT_FILE', f'/etc/letsencrypt/live/{os.environ.get("DOMAIN", "")}/fullchain.pem')
    KEY_FILE = os.environ.get('KEY_FILE', f'/etc/letsencrypt/live/{os.environ.get("DOMAIN", "")}/privkey.pem')
    EC2_NAME = os.environ.get('EC2_NAME', 'gio-server')

    # ── Database ──
    DB_HOST = os.environ.get('DB_HOST', 'localhost')
    DB_USER = os.environ.get('DB_USER', 'postgres')
    DB_PASSWORD = os.environ.get('DB_PASSWORD', '')
    DB_NAME = os.environ.get('DB_NAME', 'telemetry')
    DB_PORT = int(os.environ.get('DB_PORT', 5432))
    DB_POOL_MIN = int(os.environ.get('DB_POOL_MIN', 2))
    DB_POOL_MAX = int(os.environ.get('DB_POOL_MAX', 10))

    DB_CONFIG = {
        'host': DB_HOST,
        'user': DB_USER,
        'password': DB_PASSWORD,
        'dbname': DB_NAME,
        'port': DB_PORT,
        'connect_timeout': 5,
    }

    # ── OSRM ──
    OSRM_URL = os.environ.get('OSRM_URL', 'https://router.project-osrm.org')
    OSRM_CACHE_TTL = int(os.environ.get('OSRM_CACHE_TTL', 300))  # 5 minutes

    # ── Admin / Flush ──
    ADMIN_SECRET = os.environ.get('ADMIN_SECRET', '')

    # ── Limits ──
    HISTORY_LIMIT = int(os.environ.get('HISTORY_LIMIT', 50))
    HISTORY_RANGE_MAX = int(os.environ.get('HISTORY_RANGE_MAX', 5000))
    HISTORY_SAMPLE_MINUTES_DEFAULT = int(os.environ.get('HISTORY_SAMPLE_MINUTES_DEFAULT', 3))
    HISTORY_SAMPLE_MINUTES_MAX = int(os.environ.get('HISTORY_SAMPLE_MINUTES_MAX', 60))
    HISTORY_OUTLIER_MAX_SPEED_KMH = float(os.environ.get('HISTORY_OUTLIER_MAX_SPEED_KMH', 240))
    HISTORY_OUTLIER_MIN_JUMP_KM = float(os.environ.get('HISTORY_OUTLIER_MIN_JUMP_KM', 5))
    DEVICES_CACHE_TTL = int(os.environ.get('DEVICES_CACHE_TTL', 45))
    STATS_CACHE_INTERVAL = 30  # seconds
    SENSOR_BRAKE_AX_G = float(os.environ.get('SENSOR_BRAKE_AX_G', 0.45))
    SENSOR_TURN_GZ_DPS = float(os.environ.get('SENSOR_TURN_GZ_DPS', 45.0))

    # ── UDP ingestion (queue + batch write) ──
    UDP_QUEUE_MAX = int(os.environ.get('UDP_QUEUE_MAX', 20000))
    UDP_BATCH_SIZE = int(os.environ.get('UDP_BATCH_SIZE', 120))
    UDP_FLUSH_MS = int(os.environ.get('UDP_FLUSH_MS', 200))
    UDP_LOG_EVERY = int(os.environ.get('UDP_LOG_EVERY', 500))
