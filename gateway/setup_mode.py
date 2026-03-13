"""
setup_mode.py — Setup mode orchestrator.

Coordinates:
  1. Start WiFi access point
  2. Start Flask setup server
  3. Generate QR code pointing to setup URL
  4. Signal display to show QR screen
  5. Wait for user to submit form
  6. Apply WiFi config + send CHANGE_NAME to sensor via BLE
  7. Tear down AP, restore normal operation

Usage from main.py:
    from setup_mode import enter_setup_mode
    enter_setup_mode(screen_state)
"""

import logging
import os
import time
import threading

log = logging.getLogger("setup_mode")

# State shared with display
_setup_active = False
_qr_data = None       # URL string for QR code
_ap_info = None        # dict with ssid, password, ip
_setup_result = None   # "success" | "error" | None
_setup_event = threading.Event()  # signals when setup form is submitted


def is_active():
    """Check if setup mode is currently running."""
    return _setup_active


def get_qr_data():
    """Get the URL to encode in the QR code."""
    return _qr_data


def get_ap_info():
    """Get AP details for display: {ssid, password, ip}."""
    return _ap_info


def get_result():
    """Get setup result after completion."""
    return _setup_result


def _save_wifi_config(ssid, password):
    """Save WiFi credentials as PENDING — will be tested on next boot."""
    import wifi_manager
    wifi_manager.save_pending(ssid, password)


def _send_sensor_name(name):
    """Send CHANGE_NAME command to connected sensor via BLE NUS."""
    if not name:
        log.info("No sensor name provided, skipping")
        return True, "No name change"

    try:
        import asyncio
        from bleak import BleakClient, BleakScanner

        NUS_RX_UUID = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"
        NUS_TX_UUID = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"
        DEVICE_PREFIX = "HVAC-Vibe"

        response_data = []

        def on_tx(sender, data):
            text = data.decode("utf-8", errors="replace").strip()
            log.info("NUS response: %s", text)
            response_data.append(text)

        async def _do_rename():
            log.info("Scanning for sensor to rename...")
            devices = await BleakScanner.discover(timeout=10.0)
            target = None
            for d in devices:
                if d.name and d.name.startswith(DEVICE_PREFIX):
                    target = d
                    break

            if not target:
                return False, "No HVAC-Vibe sensor found"

            log.info("Found %s (%s), connecting...", target.name, target.address)
            async with BleakClient(target.address, timeout=15.0) as client:
                # Subscribe to NUS TX for response
                await client.start_notify(NUS_TX_UUID, on_tx)
                await asyncio.sleep(0.3)

                # Send command
                cmd = f"CHANGE_NAME:{name}".encode("utf-8")
                log.info("Sending: %s", cmd.decode())
                await client.write_gatt_char(NUS_RX_UUID, cmd,
                                             response=False)

                # Wait for response
                await asyncio.sleep(2.0)

                await client.stop_notify(NUS_TX_UUID)

            if any("OK:NAME=" in r for r in response_data):
                return True, f"Sensor renamed to '{name}'"
            elif any("ERR:" in r for r in response_data):
                err = next(r for r in response_data if "ERR:" in r)
                return False, f"Sensor rejected name: {err}"
            else:
                return True, "Command sent (no confirmation received)"

        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(_do_rename())
        finally:
            loop.close()

    except Exception as e:
        log.exception("Sensor rename failed")
        return False, str(e)


def _on_setup_complete(ssid, wifi_pass, sensor_name):
    """
    Called by Flask when user submits the setup form.
    Returns (ok, message) to the web page.
    """
    global _setup_result

    errors = []

    # 1. Save WiFi config
    try:
        _save_wifi_config(ssid, wifi_pass)
    except Exception as e:
        errors.append(f"WiFi config: {e}")

    # 2. Rename sensor if requested
    if sensor_name:
        ok, msg = _send_sensor_name(sensor_name)
        if not ok:
            errors.append(f"Sensor name: {msg}")
        else:
            log.info("Sensor rename: %s", msg)

    if errors:
        _setup_result = "error"
        _setup_event.set()
        return False, "; ".join(errors)

    _setup_result = "success"
    _setup_event.set()
    return True, "Settings saved! Gateway will restart in a few seconds."


def enter_setup_mode(screen_state):
    """
    Main entry point — run setup mode.

    Blocks until setup is complete or cancelled.
    Called from main thread (via button handler thread).

    Args:
        screen_state: object with .set(name) to switch display screens
    """
    global _setup_active, _qr_data, _ap_info, _setup_result
    import setup_ap
    from setup_server import SetupServer

    if _setup_active:
        log.warning("Setup mode already active")
        return

    _setup_active = True
    _setup_result = None
    _setup_event.clear()

    log.info("═══ Entering setup mode ═══")

    try:
        # 1. Start WiFi AP
        ap_ip = setup_ap.start()
        _ap_info = {
            "ssid": setup_ap.get_ap_ssid(),
            "password": setup_ap.get_ap_password(),
            "ip": ap_ip,
        }

        # 2. Start Flask server
        server = SetupServer(_on_setup_complete, host="0.0.0.0", port=80)
        server.start()

        # 3. Generate QR URL
        _qr_data = f"http://{ap_ip}/setup"
        log.info("Setup URL: %s", _qr_data)

        # 4. Switch display to setup screen
        screen_state.set("setup")

        # 5. Wait for user to complete setup
        log.info("Waiting for setup form submission...")
        _setup_event.wait()

        log.info("Setup form submitted (result: %s)", _setup_result)

        # 6. Brief pause so the web page can show success message
        time.sleep(3.0)

        # 7. Tear down
        server.stop()
        setup_ap.stop()

        # 8. Apply WiFi and restart
        if _setup_result == "success":
            log.info("Setup complete — restarting to apply WiFi...")
            screen_state.set("restarting")
            time.sleep(1.0)
            os.system("sudo reboot")
        else:
            log.warning("Setup had errors — returning to normal mode")
            screen_state.set("dashboard")

    except Exception as e:
        log.exception("Setup mode error: %s", e)
    finally:
        _setup_active = False
        _qr_data = None
        _ap_info = None
        log.info("═══ Exited setup mode ═══")
