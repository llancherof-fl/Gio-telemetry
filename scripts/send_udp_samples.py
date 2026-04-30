#!/usr/bin/env python3
"""
Send UDP sample payloads to validate ingestion:
1) GPS/trip payload
2) GPS + sensor payload (MPU6050 fields)
"""
import argparse
import json
import socket
import time


def build_samples(device: str):
    now_ms = int(time.time() * 1000)
    trip_id = f"trip-{device.lower()}-{now_ms}"

    gps_only = {
        "lat": 10.9878,
        "long": -74.7889,
        "timestamp": now_ms,
        "device": device,
        "trip_id": trip_id,
        "event_id": f"start-{now_ms}",
        "event_type": "trip_start",
        "trip_state": "active",
        "seq": 1,
        "client_ts_ms": now_ms,
    }

    with_sensor = {
        "lat": 10.9881,
        "long": -74.7894,
        "timestamp": now_ms + 2000,
        "device": device,
        "trip_id": trip_id,
        "event_id": f"pos-{now_ms + 2000}",
        "event_type": "position",
        "trip_state": "active",
        "seq": 2,
        "client_ts_ms": now_ms + 2000,
        "sensor_ts_ms": now_ms + 1900,
        "sensor_source": "ble",
        "ax": 0.62,
        "ay": 0.08,
        "az": 0.94,
        "gx": 12.7,
        "gy": -3.1,
        "gz": 51.2,
    }
    return gps_only, with_sensor


def send_udp(host: str, port: int, payload: dict):
    raw = json.dumps(payload).encode("utf-8")
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.sendto(raw, (host, port))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5001)
    parser.add_argument("--device", default="GIO-android")
    args = parser.parse_args()

    p1, p2 = build_samples(args.device)
    send_udp(args.host, args.port, p1)
    print("Sent GPS sample")
    send_udp(args.host, args.port, p2)
    print("Sent GPS+sensor sample")


if __name__ == "__main__":
    main()
