"""
setup_server.py — Flask web server for HVAC-Vibe gateway setup.

Serves a single-page setup form at /setup:
  - WiFi SSID + password
  - Sensor display name (sent to nRF via BLE CHANGE_NAME: command)

Runs on a background thread, started/stopped by setup_mode.py.
"""

import logging
import threading
from flask import Flask, request, jsonify, render_template_string
from werkzeug.serving import make_server

log = logging.getLogger("setup_server")

SETUP_PORT = 80  # Port 80 so captive portal detection works


# ──────────────────────────────────────────────
# HTML Template
# ──────────────────────────────────────────────

SETUP_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>HVAC-Vibe Setup</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;700&display=swap');

  * { margin: 0; padding: 0; box-sizing: border-box; }

  :root {
    --bg: #0f1117;
    --card: #1a1d27;
    --border: #2a2d3a;
    --accent: #3b82f6;
    --accent-hover: #2563eb;
    --success: #22c55e;
    --text: #e2e8f0;
    --text-dim: #94a3b8;
    --input-bg: #0f1117;
    --danger: #ef4444;
  }

  body {
    font-family: 'DM Sans', system-ui, sans-serif;
    background: var(--bg);
    color: var(--text);
    min-height: 100vh;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 1rem;
  }

  .card {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 16px;
    padding: 2rem;
    width: 100%;
    max-width: 400px;
  }

  .logo {
    text-align: center;
    margin-bottom: 1.5rem;
  }
  .logo h1 {
    font-size: 1.4rem;
    font-weight: 700;
    letter-spacing: -0.02em;
  }
  .logo span {
    color: var(--accent);
  }
  .logo p {
    color: var(--text-dim);
    font-size: 0.85rem;
    margin-top: 0.25rem;
  }

  .section {
    margin-bottom: 1.5rem;
  }
  .section-title {
    font-size: 0.75rem;
    font-weight: 500;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--text-dim);
    margin-bottom: 0.75rem;
  }

  .field {
    margin-bottom: 0.75rem;
  }
  .field label {
    display: block;
    font-size: 0.85rem;
    font-weight: 500;
    margin-bottom: 0.3rem;
    color: var(--text);
  }
  .field input {
    width: 100%;
    padding: 0.6rem 0.75rem;
    background: var(--input-bg);
    border: 1px solid var(--border);
    border-radius: 8px;
    color: var(--text);
    font-family: inherit;
    font-size: 0.9rem;
    outline: none;
    transition: border-color 0.2s;
  }
  .field input:focus {
    border-color: var(--accent);
  }
  .field input::placeholder {
    color: var(--text-dim);
    opacity: 0.6;
  }
  .field .hint {
    font-size: 0.75rem;
    color: var(--text-dim);
    margin-top: 0.2rem;
  }

  .btn {
    width: 100%;
    padding: 0.7rem;
    background: var(--accent);
    color: white;
    border: none;
    border-radius: 8px;
    font-family: inherit;
    font-size: 0.95rem;
    font-weight: 600;
    cursor: pointer;
    transition: background 0.2s, transform 0.1s;
  }
  .btn:hover { background: var(--accent-hover); }
  .btn:active { transform: scale(0.98); }
  .btn:disabled {
    opacity: 0.5;
    cursor: not-allowed;
    transform: none;
  }

  .status {
    text-align: center;
    padding: 0.6rem;
    border-radius: 8px;
    font-size: 0.85rem;
    margin-top: 1rem;
    display: none;
  }
  .status.ok {
    display: block;
    background: rgba(34,197,94,0.12);
    color: var(--success);
    border: 1px solid rgba(34,197,94,0.25);
  }
  .status.err {
    display: block;
    background: rgba(239,68,68,0.12);
    color: var(--danger);
    border: 1px solid rgba(239,68,68,0.25);
  }
  .status.working {
    display: block;
    background: rgba(59,130,246,0.12);
    color: var(--accent);
    border: 1px solid rgba(59,130,246,0.25);
  }
</style>
</head>
<body>
<div class="card">
  <div class="logo">
    <h1>HVAC<span>-Vibe</span></h1>
    <p>Gateway Setup</p>
  </div>

  <form id="setupForm" onsubmit="return doSubmit(event)">
    <div class="section">
      <div class="section-title">WiFi Network</div>
      <div class="field">
        <label for="ssid">SSID</label>
        <input type="text" id="ssid" name="ssid"
               placeholder="Your WiFi network name" required>
      </div>
      <div class="field">
        <label for="wifi_pass">Password</label>
        <input type="password" id="wifi_pass" name="wifi_pass"
               placeholder="WiFi password">
        <div class="hint">Leave blank for open networks</div>
      </div>
    </div>

    <div class="section">
      <div class="section-title">Sensor Name</div>
      <div class="field">
        <label for="sensor_name">Display Name</label>
        <input type="text" id="sensor_name" name="sensor_name"
               placeholder="e.g. AHU-Lobby-3" maxlength="20"
               pattern="[\\x20-\\x7E]+"
               title="ASCII characters only, max 20">
        <div class="hint">Optional — leave blank to keep current name</div>
      </div>
    </div>

    <button type="submit" class="btn" id="submitBtn">Save &amp; Connect</button>
  </form>

  <div class="status" id="status"></div>
</div>

<script>
async function doSubmit(e) {
  e.preventDefault();
  const btn = document.getElementById('submitBtn');
  const status = document.getElementById('status');

  btn.disabled = true;
  btn.textContent = 'Saving...';
  status.className = 'status working';
  status.textContent = 'Applying settings...';

  const data = {
    ssid:        document.getElementById('ssid').value.trim(),
    wifi_pass:   document.getElementById('wifi_pass').value,
    sensor_name: document.getElementById('sensor_name').value.trim(),
  };

  try {
    const resp = await fetch('/api/setup', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(data),
    });
    const result = await resp.json();

    if (result.ok) {
      status.className = 'status ok';
      status.textContent = result.message || 'Settings saved! Gateway is restarting...';
      btn.textContent = 'Done!';
    } else {
      status.className = 'status err';
      status.textContent = result.error || 'Something went wrong';
      btn.disabled = false;
      btn.textContent = 'Save & Connect';
    }
  } catch (err) {
    status.className = 'status err';
    status.textContent = 'Connection lost — settings may have been applied';
    btn.disabled = false;
    btn.textContent = 'Retry';
  }
}
</script>
</body>
</html>"""


# ──────────────────────────────────────────────
# Flask App
# ──────────────────────────────────────────────

def create_app(on_setup_complete):
    """
    Create Flask app.

    Args:
        on_setup_complete: callback(ssid, wifi_pass, sensor_name)
                           called when user submits the form.
                           Should return (ok: bool, message: str).
    """
    app = Flask(__name__)
    app.logger.setLevel(logging.WARNING)  # Quiet Flask logs

    @app.route("/")
    @app.route("/setup")
    @app.route("/generate_204")       # Android captive portal
    @app.route("/hotspot-detect.html")  # Apple captive portal
    @app.route("/connecttest.txt")      # Windows captive portal
    def setup_page():
        return render_template_string(SETUP_HTML)

    @app.route("/api/setup", methods=["POST"])
    def api_setup():
        data = request.get_json(silent=True) or {}

        ssid = data.get("ssid", "").strip()
        wifi_pass = data.get("wifi_pass", "")
        sensor_name = data.get("sensor_name", "").strip()

        if not ssid:
            return jsonify(ok=False, error="WiFi SSID is required"), 400

        # Validate sensor name (ASCII printable, max 20)
        if sensor_name:
            if len(sensor_name) > 20:
                return jsonify(ok=False,
                               error="Sensor name too long (max 20 chars)"), 400
            if not all(0x20 <= ord(c) <= 0x7E for c in sensor_name):
                return jsonify(ok=False,
                               error="Sensor name must be ASCII only"), 400

        try:
            ok, message = on_setup_complete(ssid, wifi_pass, sensor_name)
            if ok:
                return jsonify(ok=True, message=message)
            else:
                return jsonify(ok=False, error=message), 500
        except Exception as e:
            log.exception("Setup handler error")
            return jsonify(ok=False, error=str(e)), 500

    return app


# ──────────────────────────────────────────────
# Server Lifecycle
# ──────────────────────────────────────────────

class SetupServer:
    """Runs Flask in a background thread with clean shutdown."""

    def __init__(self, on_setup_complete, host="0.0.0.0", port=SETUP_PORT):
        self._app = create_app(on_setup_complete)
        self._server = make_server(host, port, self._app)
        self._thread = None

    def start(self):
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="setup-server",
            daemon=True,
        )
        self._thread.start()
        log.info("Setup server started on port %d", self._server.port)

    def stop(self):
        self._server.shutdown()
        if self._thread:
            self._thread.join(timeout=3.0)
        log.info("Setup server stopped")
