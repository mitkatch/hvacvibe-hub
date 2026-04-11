"""
setup_flask.py — Flask web server for WiFi setup + sensor management portal.

Modes:
  AP mode    (port 80)  — WiFi setup, accessible via 192.168.4.1
  Mgmt mode  (port 8080) — Sensor management, accessible via local WiFi IP

Routes:
  GET  /                    → home: sensor list + system status
  GET  /sensors             → sensor management
  POST /sensors/update      → rename/update sensor profile
  POST /sensors/remove      → soft-delete sensor
  POST /sensors/sync        → send rename to sensor firmware via MQTT
  GET  /wifi                → WiFi settings page
  POST /wifi/connect        → change WiFi (triggers AP mode)
  GET  /status              → JSON system status
  POST /exit                → exit management mode
  Captive portal routes     → redirect to /
"""

import json
import logging
import threading
import time

from flask import Flask, render_template, request, jsonify, redirect

from setup_wifi    import scan_networks, apply_wifi, get_current_ip
from setup_display import (show_connecting_screen, show_success_screen,
                            show_error_screen, show_management_screen)

log = logging.getLogger("setup_flask")

app = Flask(__name__)

# Shared state
_connect_result: dict = {}
_connect_lock = threading.Lock()
_exit_event   = threading.Event()   # set to trigger management mode exit


# ── Captive portal ─────────────────────────────────────────────────────────

@app.route("/hotspot-detect.html")
@app.route("/generate_204")
@app.route("/ncsi.txt")
@app.route("/connecttest.txt")
@app.route("/redirect")
def captive_portal():
    return redirect("/", 302)


# ── Home ───────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    mode     = app.config.get("MODE", "mgmt")   # "setup" or "mgmt"
    networks = app.config.get("CACHED_NETWORKS") or []

    if mode == "setup":
        # WiFi setup mode — show network picker
        if not networks:
            networks = scan_networks()
        return render_template("index.html",
                               mode="setup",
                               networks=networks,
                               current_ip=get_current_ip())
    else:
        # Management mode — show sensor list
        from setup_db import setup_db
        sensors = setup_db.get_all_sensors()
        return render_template("index.html",
                               mode="mgmt",
                               sensors=sensors,
                               current_ip=get_current_ip(),
                               gateway_id=app.config.get("GATEWAY_ID", ""))


# ── Sensor management ──────────────────────────────────────────────────────

@app.route("/sensors/update", methods=["POST"])
def sensors_update():
    from setup_db import setup_db
    data        = request.get_json(silent=True) or {}
    sensor_id   = data.get("sensor_id", "").strip()
    display_name = data.get("display_name", "").strip()
    asset_type  = data.get("asset_type", "").strip()
    location    = data.get("location", "").strip()

    if not sensor_id:
        return jsonify({"success": False, "message": "missing sensor_id"}), 400

    success = setup_db.update_profile(
        sensor_id    = sensor_id,
        display_name = display_name or None,
        asset_type   = asset_type   or None,
        location     = location     or None,
    )
    return jsonify({"success": success})


@app.route("/sensors/remove", methods=["POST"])
def sensors_remove():
    from setup_db import setup_db
    data      = request.get_json(silent=True) or {}
    sensor_id = data.get("sensor_id", "").strip()

    if not sensor_id:
        return jsonify({"success": False, "message": "missing sensor_id"}), 400

    success = setup_db.remove_sensor(sensor_id)
    return jsonify({"success": success})


@app.route("/sensors/sync", methods=["POST"])
def sensors_sync():
    """Send display_name to sensor firmware via engine MQTT command."""
    from setup_db       import setup_db
    from setup_mqtt_cmd import MQTTCommander, get_gateway_id

    data      = request.get_json(silent=True) or {}
    sensor_id = data.get("sensor_id", "").strip()

    if not sensor_id:
        return jsonify({"success": False, "message": "missing sensor_id"}), 400

    profile = setup_db.get_sensor(sensor_id)
    if not profile:
        return jsonify({"success": False, "message": "sensor not found"}), 404

    display_name = profile.get("display_name") or sensor_id

    # Send rename command via MQTT
    gateway_id  = get_gateway_id()
    commander   = MQTTCommander(gateway_id)
    if not commander.start():
        return jsonify({"success": False, "message": "MQTT unavailable"}), 503

    try:
        result = commander.rename_sensor(sensor_id, display_name)
        return jsonify(result)
    finally:
        commander.stop()


# ── WiFi management ────────────────────────────────────────────────────────

@app.route("/wifi/networks")
def wifi_networks():
    """Return cached networks as JSON for management mode WiFi tab."""
    networks = app.config.get("CACHED_NETWORKS") or []
    if not networks:
        networks = scan_networks()
        app.config["CACHED_NETWORKS"] = networks
    return jsonify(networks)


@app.route("/wifi")
def wifi_page():
    return render_template("index.html",
                           mode="wifi",
                           current_ip=get_current_ip(),
                           networks=app.config.get("CACHED_NETWORKS") or [])


@app.route("/wifi/connect", methods=["POST"])
def wifi_connect():
    """Change WiFi — triggers AP mode from management mode."""
    from setup_ap import stop_ap, start_ap

    data     = request.get_json(silent=True) or {}
    ssid     = data.get("ssid", "").strip()
    password = data.get("password", "")

    if not ssid:
        return jsonify({"success": False, "message": "missing_ssid"}), 400

    log.info(f"WiFi change request: SSID={ssid}")

    with _connect_lock:
        _connect_result.clear()

    try:
        show_connecting_screen(ssid)
    except Exception:
        pass

    def _apply():
        stop_ap()
        success, result = apply_wifi(ssid, password)

        with _connect_lock:
            _connect_result["success"] = success
            _connect_result["ip"]      = result if success else None
            _connect_result["message"] = result if not success else None

        if success:
            try:
                show_success_screen(result)
            except Exception:
                pass
            # Update management screen with new IP
            try:
                show_management_screen(result, app.config.get("GATEWAY_ID", ""))
            except Exception:
                pass
        else:
            try:
                show_error_screen("Wrong password or network unreachable")
            except Exception:
                pass
            start_ap()

    t = threading.Thread(target=_apply, daemon=True, name="wifi-change")
    t.start()
    t.join(timeout=120)

    with _connect_lock:
        if _connect_result.get("success"):
            return jsonify({"success": True, "ip": _connect_result["ip"]})
        elif "success" in _connect_result:
            return jsonify({"success": False,
                            "message": _connect_result.get("message", "failed")})
        else:
            return jsonify({"success": False, "message": "timeout"})


# ── Setup WiFi connect (AP mode) ───────────────────────────────────────────

@app.route("/connect", methods=["POST"])
def connect():
    """Original WiFi setup connect — used in AP mode."""
    from setup_ap import stop_ap, start_ap

    data     = request.get_json(silent=True) or {}
    ssid     = data.get("ssid", "").strip()
    password = data.get("password", "")

    if not ssid:
        return jsonify({"success": False, "message": "missing_ssid"}), 400

    log.info(f"Connect request: SSID={ssid}")

    with _connect_lock:
        _connect_result.clear()

    try:
        show_connecting_screen(ssid)
    except Exception:
        pass

    def _apply():
        log.info("Stopping AP before connect attempt...")
        stop_ap()
        success, result = apply_wifi(ssid, password)

        with _connect_lock:
            _connect_result["success"] = success
            _connect_result["ip"]      = result if success else None
            _connect_result["message"] = result if not success else None

        if success:
            log.info(f"Connected: {result}")
            try:
                show_success_screen(result)
            except Exception:
                pass
        else:
            log.warning(f"Connection failed ({result}) — restarting AP")
            try:
                show_error_screen("Wrong password or network unreachable")
            except Exception:
                pass
            start_ap()

    t = threading.Thread(target=_apply, daemon=True, name="wifi-connect")
    t.start()
    t.join(timeout=120)

    with _connect_lock:
        if _connect_result.get("success"):
            return jsonify({"success": True, "ip": _connect_result["ip"]})
        elif "success" in _connect_result:
            return jsonify({"success": False,
                            "message": _connect_result.get("message", "failed")})
        else:
            return jsonify({"success": False, "message": "timeout"})


# ── Status + Exit ──────────────────────────────────────────────────────────

@app.route("/status")
def status():
    ip        = get_current_ip()
    connected = ip is not None and not ip.startswith("192.168.4")
    from setup_db import setup_db
    try:
        sensors = setup_db.get_all_sensors()
        sensor_count = len(sensors)
    except Exception:
        sensor_count = 0
    return jsonify({
        "connected":    connected,
        "ip":           ip,
        "mode":         app.config.get("MODE", "mgmt"),
        "sensor_count": sensor_count,
    })


@app.route("/exit", methods=["POST"])
def exit_mgmt():
    """Signal management mode to shut down."""
    log.info("Exit requested via UI")
    _exit_event.set()
    return jsonify({"success": True})


def get_exit_event() -> threading.Event:
    return _exit_event


# ── Runner ─────────────────────────────────────────────────────────────────

def run_server(host="0.0.0.0", port=80, networks=None,
               mode="setup", gateway_id=""):
    """
    Start Flask server.
    mode: "setup" (AP, port 80) or "mgmt" (local WiFi, port 8080)
    """
    app.config["CACHED_NETWORKS"] = networks or []
    app.config["MODE"]            = mode
    app.config["GATEWAY_ID"]      = gateway_id
    _exit_event.clear()

    log.info(f"Flask starting: mode={mode} port={port} "
             f"networks={len(app.config['CACHED_NETWORKS'])}")
    app.run(host=host, port=port, debug=False,
            use_reloader=False, threaded=True)
