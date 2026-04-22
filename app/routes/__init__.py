"""
GIO Telemetry — Blueprint Registration
"""
from flask import Flask


def register_blueprints(app: Flask):
    """Register all route blueprints."""
    from app.routes.api import api_bp
    from app.routes.admin import admin_bp
    from app.routes.dashboard import dashboard_bp
    from app.routes.sensor import sensor_bp  # P3-S1: MPU6050 sensor endpoints

    app.register_blueprint(api_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(sensor_bp)

