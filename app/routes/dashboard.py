"""
GIO Telemetry — Dashboard Route
Serves the main dashboard HTML page.
"""
from flask import Blueprint, render_template

from app.config import Config

dashboard_bp = Blueprint('dashboard', __name__)


@dashboard_bp.route('/')
def index():
    """Serve the main telemetry dashboard."""
    return render_template(
        'index.html',
        ec2_name=Config.EC2_NAME,
        osrm_url=Config.OSRM_URL,
    )
