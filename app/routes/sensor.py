"""
GIO Telemetry — Sensor API Endpoints (P3-S1: MPU6050)
POST /api/sensor          — Receive sensor data from ESP32
GET  /api/sensor/latest   — Last sensor reading
GET  /api/sensor/history  — Sensor history
GET  /api/sensor/events   — Only braking/turning events
"""
from flask import Blueprint, jsonify, request

from app.database import (
    insert_sensor_data,
    fetch_sensor_latest,
    fetch_sensor_history,
    fetch_sensor_events,
)

sensor_bp = Blueprint('sensor', __name__)


# ══════════════════════════════════════════
#  POST /api/sensor — Receive ESP32 data
# ══════════════════════════════════════════

@sensor_bp.route('/api/sensor', methods=['POST'])
def receive_sensor_data():
    """
    Receive MPU6050 sensor data from the ESP32 via HTTP POST.

    Expected JSON payload:
    {
        "vehicle_id": "taxi1",
        "ax": 0.02,    // Acceleration X in g
        "ay": -0.01,   // Acceleration Y in g
        "az": 0.98,    // Acceleration Z in g
        "gx": 1.5,     // Gyroscope X in deg/s (optional)
        "gy": -0.8,    // Gyroscope Y in deg/s (optional)
        "gz": 0.2      // Gyroscope Z in deg/s (optional)
    }
    """
    try:
        data = request.get_json()

        if not data:
            return jsonify({'error': 'No se recibieron datos JSON'}), 400

        vehicle_id = data.get('vehicle_id', 'unknown')
        ax = float(data.get('ax', 0))
        ay = float(data.get('ay', 0))
        az = float(data.get('az', 0))
        gx = float(data.get('gx', 0))
        gy = float(data.get('gy', 0))
        gz = float(data.get('gz', 0))

        # Detect events based on thresholds
        # Hard braking: acceleration X > 0.5g (strong deceleration)
        evento_frenada = abs(ax) > 0.5
        # Sharp turn: angular velocity Z > 50 deg/s
        evento_giro = abs(gz) > 50

        timestamp = insert_sensor_data(
            vehicle_id, ax, ay, az, gx, gy, gz, evento_frenada, evento_giro
        )

        # Console log for monitoring
        status_str = ""
        if evento_frenada:
            status_str += " ⚠️FRENADA"
        if evento_giro:
            status_str += " ⚠️GIRO"
        print(f"[SENSOR] {vehicle_id}: ax={ax:.3f} ay={ay:.3f} az={az:.3f}{status_str}")

        return jsonify({
            'status': 'ok',
            'vehicle_id': vehicle_id,
            'evento_frenada': evento_frenada,
            'evento_giro': evento_giro,
            'timestamp': timestamp,
        }), 200

    except ValueError as e:
        print(f"[SENSOR ERROR] Datos inválidos: {e}")
        return jsonify({'error': f'Datos numéricos inválidos: {str(e)}'}), 400
    except Exception as e:
        print(f"[SENSOR ERROR] {e}")
        return jsonify({'error': str(e)}), 500


# ══════════════════════════════════════════
#  GET /api/sensor/latest
# ══════════════════════════════════════════

@sensor_bp.route('/api/sensor/latest')
def api_sensor_latest():
    """Return the most recent sensor reading, optionally filtered by vehicle_id."""
    vehicle_id = request.args.get('vehicle_id')
    row = fetch_sensor_latest(vehicle_id=vehicle_id)

    if row:
        return jsonify(row)

    return jsonify({'error': 'Sin datos del sensor aún'}), 404


# ══════════════════════════════════════════
#  GET /api/sensor/history
# ══════════════════════════════════════════

@sensor_bp.route('/api/sensor/history')
def api_sensor_history():
    """Return sensor history with configurable limit."""
    vehicle_id = request.args.get('vehicle_id')
    limit = request.args.get('limit', 100, type=int)
    rows = fetch_sensor_history(vehicle_id=vehicle_id, limit=limit)
    return jsonify(rows)


# ══════════════════════════════════════════
#  GET /api/sensor/events
# ══════════════════════════════════════════

@sensor_bp.route('/api/sensor/events')
def api_sensor_events():
    """Return only records where a braking or turning event was detected."""
    vehicle_id = request.args.get('vehicle_id')
    limit = request.args.get('limit', 50, type=int)
    rows = fetch_sensor_events(vehicle_id=vehicle_id, limit=limit)
    return jsonify({
        'count': len(rows),
        'events': rows,
    })
