"""
setup_flask.py — Flask web server for hvac-setup.

Two completely separate interfaces, no links between them:

  WiFi Setup  (AP mode, port 80)
    GET  /                → wifi_setup.html  — network picker
    POST /connect         → apply WiFi credentials
    GET  /status          → JSON connection status

  Management  (local WiFi, port 8080)
    GET  /                → management.html  — sensor list + system info
    POST /sensors/update  → rename/update sensor profile
    POST /sensors/remove  → soft-delete sensor
    POST /sensors/sync    → send rename to firmware via MQTT
    GET  /status          → JSON status
    POST /exit            → exit management mode

  Captive portal routes (both modes)
    /hotspot-detect.html, /generate_204, /ncsi.txt, /connecttest.txt
"""

import logging
import threading

from flask import Flask, render_template, request, jsonify, redirect

log = logging.getLogger("setup_flask")

app  = Flask(__name__)
_exit_event   = threading.Event()
_connect_result: dict = {}
_connect_lock = threading.Lock()


# ── Captive portal ─────────────────────────────────────────────────────────

@app.route("/hotspot-detect.html")
@app.route("/generate_204")
@app.route("/ncsi.txt")
@app.route("/connecttest.txt")
@app.route("/redirect")
def captive_portal():
    return redirect("/", 302)


# ── Home — mode-aware ──────────────────────────────────────────────────────

@app.route("/")
def index():
    mode = app.config.get("MODE", "wifi")

    if mode == "wifi":
        from setup_wifi import scan_networks
        networks = app.config.get("CACHED_NETWORKS") or []
        if not networks:
            networks = scan_networks()
        return render_template("wifi_setup.html", networks=networks)

    else:  # mgmt
        from setup_db import setup_db
        sensors    = setup_db.get_all_sensors()
        current_ip = app.config.get("CURRENT_IP", "")
        gateway_id = app.config.get("GATEWAY_ID", "")
        return render_template("management.html",
                               sensors=sensors,
                               current_ip=current_ip,
                               gateway_id=gateway_id)


# ── WiFi setup routes (AP mode) ────────────────────────────────────────────

@app.route("/connect", methods=["POST"])
def connect():
    from setup_ap  import stop_ap, start_ap
    from setup_wifi import apply_wifi

    data     = request.get_json(silent=True) or {}
    ssid     = data.get("ssid", "").strip()
    password = data.get("password", "")

    if not ssid:
        return jsonify({"success": False, "message": "missing_ssid"}), 400

    log.info(f"WiFi connect request: SSID={ssid}")

    with _connect_lock:
        _connect_result.clear()

    try:
        from setup_display import show_connecting_screen
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
                from setup_display import show_success_screen
                show_success_screen(result)
            except Exception:
                pass
        else:
            log.warning(f"Connection failed ({result}) — restarting AP")
            try:
                from setup_display import show_error_screen
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


# ── Management routes (local WiFi) ─────────────────────────────────────────

@app.route("/sensors/update", methods=["POST"])
def sensors_update():
    from setup_db import setup_db
    data         = request.get_json(silent=True) or {}
    sensor_id    = data.get("sensor_id", "").strip()
    display_name = data.get("display_name", "").strip()
    asset_type   = data.get("asset_type",   "").strip()
    location     = data.get("location",     "").strip()

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
    return jsonify({"success": setup_db.remove_sensor(sensor_id)})


@app.route("/sensors/sync", methods=["POST"])
def sensors_sync():
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
    gateway_id   = get_gateway_id()
    commander    = MQTTCommander(gateway_id)

    if not commander.start():
        return jsonify({"success": False, "message": "MQTT unavailable"}), 503

    try:
        result = commander.rename_sensor(sensor_id, display_name)
        return jsonify(result)
    finally:
        commander.stop()


# ── Shared routes ──────────────────────────────────────────────────────────

@app.route("/status")
def status():
    from setup_wifi import get_current_ip
    ip        = get_current_ip()
    connected = ip is not None and not ip.startswith("192.168.4")
    return jsonify({"connected": connected, "ip": ip,
                    "mode": app.config.get("MODE", "wifi")})


@app.route("/exit", methods=["POST"])
def exit_mgmt():
    log.info("Exit requested")
    _exit_event.set()
    return jsonify({"success": True})


def get_exit_event() -> threading.Event:
    return _exit_event


# ── Runner ─────────────────────────────────────────────────────────────────

def run_server(host="0.0.0.0", port=80, networks=None,
               mode="wifi", gateway_id="", current_ip=""):
    app.config["CACHED_NETWORKS"] = networks or []
    app.config["MODE"]            = mode
    app.config["GATEWAY_ID"]      = gateway_id
    app.config["CURRENT_IP"]      = current_ip
    _exit_event.clear()

    log.info(f"Flask: mode={mode} port={port} "
             f"networks={len(app.config['CACHED_NETWORKS'])}")
    app.run(host=host, port=port, debug=False,
            use_reloader=False, threaded=True)
