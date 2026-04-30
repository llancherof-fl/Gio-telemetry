"""
GIO Telemetry — Sensor API Endpoints (P3-S1: MPU6050)
POST /api/sensor          — Receive sensor data from ESP32
GET  /api/sensor/latest   — Last sensor reading
GET  /api/sensor/history  — Sensor history
GET  /api/sensor/events   — Only braking/turning events
"""
import datetime
import math

from flask import Blueprint, jsonify, request

from app.config import Config
from app.database import (
    insert_sensor_data,
    fetch_sensor_latest,
    fetch_sensor_history,
    fetch_sensor_events,
)

sensor_bp = Blueprint('sensor', __name__)


def _parse_iso_dt(value):
    if not value:
        return None
    try:
        return datetime.datetime.fromisoformat(str(value).replace('Z', '+00:00')).replace(tzinfo=None)
    except (ValueError, TypeError):
        return None


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

        vehicle_id = data.get('vehicle_id') or data.get('device') or 'unknown'
        ax = float(data.get('ax'))
        ay = float(data.get('ay'))
        az = float(data.get('az'))
        gx = float(data.get('gx', 0))
        gy = float(data.get('gy', 0))
        gz = float(data.get('gz', 0))
        lat = float(data.get('lat')) if data.get('lat') is not None else None
        lon = float(data.get('lon', data.get('long'))) if data.get('lon', data.get('long')) is not None else None
        acc_mag = math.sqrt((ax * ax) + (ay * ay) + (az * az))
        trip_id = data.get('trip_id')
        event_id = data.get('event_id')
        seq = data.get('seq')
        sensor_ts_ms = data.get('sensor_ts_ms')
        client_ts_ms = data.get('client_ts_ms')
        sample_ts_ms = sensor_ts_ms if sensor_ts_ms is not None else client_ts_ms
        sensor_source = data.get('sensor_source') or 'ble'

        # Detect events based on configurable thresholds
        evento_frenada = abs(ax) >= max(0.0, float(Config.SENSOR_BRAKE_AX_G))
        evento_giro = abs(gz) >= max(0.0, float(Config.SENSOR_TURN_GZ_DPS))

        timestamp = insert_sensor_data(
            vehicle_id, ax, ay, az, gx, gy, gz, evento_frenada, evento_giro,
            lat=lat,
            lon=lon,
            acc_mag=acc_mag,
            trip_id=trip_id,
            event_id=event_id,
            seq=seq,
            client_ts_ms=sample_ts_ms,
            sensor_source=sensor_source,
        )

        # Console log for monitoring
        status_str = ""
        if evento_frenada:
            status_str += " [FRENADA]"
        if evento_giro:
            status_str += " [GIRO]"
        print(f"[SENSOR] {vehicle_id}: ax={ax:.3f} ay={ay:.3f} az={az:.3f} |mag={acc_mag:.3f}{status_str}")

        return jsonify({
            'status': 'ok',
            'vehicle_id': vehicle_id,
            'evento_frenada': evento_frenada,
            'evento_giro': evento_giro,
            'acc_mag': round(acc_mag, 6),
            'sensor_ts_ms': sample_ts_ms,
            'timestamp': timestamp,
        }), 200

    except (TypeError, ValueError) as e:
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
    trip_id = request.args.get('trip_id')
    row = fetch_sensor_latest(vehicle_id=vehicle_id, trip_id=trip_id)

    if row:
        return jsonify(row)

    return jsonify({'error': 'Sin datos del sensor aún'}), 404


# ══════════════════════════════════════════
#  GET /api/sensor/history
# ══════════════════════════════════════════

@sensor_bp.route('/api/sensor/history')
def api_sensor_history():
    """Return sensor history with optional filters."""
    vehicle_id = request.args.get('vehicle_id')
    trip_id = request.args.get('trip_id')
    start = _parse_iso_dt(request.args.get('start'))
    end = _parse_iso_dt(request.args.get('end'))
    limit = request.args.get('limit', 100, type=int) or 100
    rows = fetch_sensor_history(
        vehicle_id=vehicle_id,
        trip_id=trip_id,
        start=start,
        end=end,
        limit=limit,
    )
    return jsonify({
        'data': rows,
        'meta': {
            'count': len(rows),
            'vehicle_id': vehicle_id,
            'trip_id': trip_id,
        },
    })


# ══════════════════════════════════════════
#  GET /api/sensor/events
# ══════════════════════════════════════════

@sensor_bp.route('/api/sensor/events')
def api_sensor_events():
    """Return only records where a braking or turning event was detected."""
    vehicle_id = request.args.get('vehicle_id')
    trip_id = request.args.get('trip_id')
    start = _parse_iso_dt(request.args.get('start'))
    end = _parse_iso_dt(request.args.get('end'))
    limit = request.args.get('limit', 50, type=int) or 50
    rows = fetch_sensor_events(
        vehicle_id=vehicle_id,
        trip_id=trip_id,
        start=start,
        end=end,
        limit=limit,
    )
    return jsonify({
        'count': len(rows),
        'vehicle_id': vehicle_id,
        'trip_id': trip_id,
        'events': rows,
    })
