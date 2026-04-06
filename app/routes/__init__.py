"""
GIO Telemetry — Blueprint Registration
"""
from flask import Flask


def register_blueprints(app: Flask):
    """Register all route blueprints."""
    from app.routes.api import api_bp
    from app.routes.admin import admin_bp
    from app.routes.dashboard import dashboard_bp

    app.register_blueprint(api_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(dashboard_bp)
