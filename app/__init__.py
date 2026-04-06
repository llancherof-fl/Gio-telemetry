"""
GIO Telemetry — Flask Application Factory
"""
from flask import Flask

from app.config import Config


def create_app():
    """Create and configure the Flask application."""
    flask_app = Flask(
        __name__,
        static_folder='static',
        template_folder='templates',
    )
    flask_app.config.from_object(Config)

    # ── Database ──
    from app.database import init_db, init_pool
    init_db()
    init_pool()

    # ── Services (background threads) ──
    from app.services.stats import StatsCache
    flask_app.stats_cache = StatsCache()
    flask_app.stats_cache.start()

    from app.services.osrm import OSRMProxy
    flask_app.osrm_proxy = OSRMProxy(
        base_url=Config.OSRM_URL,
        cache_ttl=Config.OSRM_CACHE_TTL,
    )

    # ── Blueprints ──
    from app.routes import register_blueprints
    register_blueprints(flask_app)

    return flask_app
