"""
setup_flask.py — Flask web server for WiFi setup UI.

Routes:
  GET  /          — scan networks, render setup page
  POST /connect   — apply credentials, return JSON result
  GET  /status    — return current connection status (for JS polling)
  GET  /hotspot-detect.html  — Android captive portal detection
  GET  /generate_204         — Android captive portal detection
  GET  /ncsi.txt             — Windows captive portal detection
  GET  /connecttest.txt      — Windows captive portal detection
"""

import logging
import threading

from flask import Flask, render_template, request, jsonify, redirect

from setup_wifi import scan_networks, apply_wifi, get_current_ip
from setup_display import show_connecting_screen, show_success_screen, show_error_screen

log = logging.getLogger("setup_flask")

app = Flask(__name__)

# Shared state between Flask and main thread
_connect_result: dict = {}
_connect_lock = threading.Lock()


# ── Captive portal detection endpoints ────────────────────────────────────
# These make iOS/Android/Windows show the "Sign in to network" popup

@app.route("/hotspot-detect.html")
@app.route("/generate_204")
@app.route("/ncsi.txt")
@app.route("/connecttest.txt")
@app.route("/redirect")
def captive_portal():
    """Redirect all captive portal checks to setup page."""
    return redirect("/", 302)


# ── Main setup page ────────────────────────────────────────────────────────

@app.route("/")
def index():
    # Use cached networks from pre-AP scan — reliable
    # Fall back to live scan only if cache is empty
    networks = app.config.get("CACHED_NETWORKS") or []
    if not networks:
        log.info("No cached networks — attempting live scan")
        networks = scan_networks()
    log.info(f"Serving {len(networks)} networks")
    return render_template("index.html", networks=networks)


# ── Connect endpoint ───────────────────────────────────────────────────────

@app.route("/connect", methods=["POST"])
def connect():
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
        # ── Step 1: Stop AP so wlan0 is free for NM ───────────────────────
        log.info("Stopping AP before connect attempt...")
        stop_ap()

        # ── Step 2: Attempt WiFi connection ───────────────────────────────
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
            # ── Step 3: Restart AP so user can try again ──────────────────
            log.warning(f"Connection failed ({result}) — restarting AP")
            try:
                show_error_screen("Wrong password or network unreachable")
            except Exception:
                pass
            start_ap()

    t = threading.Thread(target=_apply, daemon=True, name="wifi-connect")
    t.start()
    t.join(timeout=120)   # enough for stop_ap wait + rescan + connect

    with _connect_lock:
        if _connect_result.get("success"):
            return jsonify({
                "success": True,
                "ip":      _connect_result["ip"],
            })
        elif "success" in _connect_result:
            return jsonify({
                "success": False,
                "message": _connect_result.get("message", "connection_failed"),
            })
        else:
            return jsonify({
                "success": False,
                "message": "timeout",
            })


# ── Status polling endpoint ────────────────────────────────────────────────

@app.route("/status")
def status():
    ip = get_current_ip()
    connected = ip is not None and not ip.startswith("192.168.4")
    return jsonify({
        "connected": connected,
        "ip":        ip,
    })


# ── Runner ─────────────────────────────────────────────────────────────────

def run_server(host="0.0.0.0", port=80, networks=None):
    """
    Start Flask setup server.
    networks: pre-scanned list from before AP mode started.
              If None, will attempt live scan (may be unreliable in AP mode).
    """
    # Store cached networks as app config so routes can access them
    app.config["CACHED_NETWORKS"] = networks or []
    log.info(f"Flask setup server starting on {host}:{port} "
             f"({len(app.config['CACHED_NETWORKS'])} cached networks)")
    app.run(host=host, port=port, debug=False, use_reloader=False, threaded=True)
