"""
wifi_manager.py — Safe WiFi credential management.

Implements a two-stage WiFi config strategy:

  ACTIVE config:   /home/mitkatch/gateway/wifi.conf
                   Known-good credentials (last successful connection)

  PENDING config:  /home/mitkatch/gateway/wifi_pending.conf
                   New credentials from setup page (unverified)

Boot sequence (run_boot_wifi_check):
  1. If pending config exists → try it
     a. Connected within timeout → promote to active, delete pending
     b. Failed → delete pending, fall back to active
  2. If active config exists → try it (should just work)
  3. If nothing exists → signal "needs setup"

The setup page writes to PENDING only — never touches ACTIVE.
ACTIVE is only written by this module after a successful connection.
"""

import logging
import os
import shutil
import subprocess
import time

log = logging.getLogger("wifi_manager")

GATEWAY_DIR   = "/home/mitkatch/gateway"
ACTIVE_CONF   = os.path.join(GATEWAY_DIR, "wifi.conf")
PENDING_CONF  = os.path.join(GATEWAY_DIR, "wifi_pending.conf")
WPA_CONF      = "/etc/wpa_supplicant/wpa_supplicant.conf"
INTERFACE      = "wlan0"
CONNECT_TIMEOUT = 45  # seconds to wait for DHCP


def _run(cmd):
    log.debug("$ %s", cmd)
    return subprocess.run(cmd, shell=True, capture_output=True, text=True)


def _is_connected():
    """Check if wlan0 has a routable IP (not 169.254.x.x, not AP address)."""
    result = _run(f"ip -4 addr show {INTERFACE}")
    if result.returncode != 0:
        return False
    output = result.stdout
    # Has an inet address that isn't link-local or our AP address
    for line in output.splitlines():
        line = line.strip()
        if line.startswith("inet "):
            addr = line.split()[1].split("/")[0]
            if not addr.startswith("169.254.") and not addr.startswith("192.168.4."):
                log.info("Connected with IP: %s", addr)
                return True
    return False


def _apply_config(conf_path):
    """Copy a wifi conf to wpa_supplicant and restart networking."""
    if not os.path.exists(conf_path):
        return False

    log.info("Applying WiFi config: %s", conf_path)
    _run(f"sudo cp {conf_path} {WPA_CONF}")
    _run(f"sudo wpa_cli -i {INTERFACE} reconfigure")
    # Also restart dhcpcd to get a fresh lease
    _run(f"sudo dhcpcd --release {INTERFACE} 2>/dev/null")
    _run(f"sudo dhcpcd {INTERFACE} 2>/dev/null")
    return True


def _wait_for_connection(timeout):
    """Wait up to timeout seconds for wlan0 to get an IP."""
    log.info("Waiting up to %ds for WiFi connection...", timeout)
    start = time.time()
    while time.time() - start < timeout:
        if _is_connected():
            elapsed = time.time() - start
            log.info("WiFi connected in %.1fs", elapsed)
            return True
        time.sleep(2.0)
    log.warning("WiFi connection timed out after %ds", timeout)
    return False


def save_pending(ssid, password):
    """
    Save new WiFi credentials as PENDING (called by setup page).
    Does NOT touch the active config.
    """
    os.makedirs(GATEWAY_DIR, exist_ok=True)

    conf = f"""country=CA
ctrl_interface=DIR=/var/run/wpa_supplicant GROUP=netdev
update_config=1

network={{
    ssid="{ssid}"
    {'psk="' + password + '"' if password else 'key_mgmt=NONE'}
    scan_ssid=1
}}
"""
    with open(PENDING_CONF, "w") as f:
        f.write(conf)

    log.info("Saved pending WiFi config: SSID=%s", ssid)


def _promote_pending():
    """Pending config worked — make it the active config."""
    shutil.copy2(PENDING_CONF, ACTIVE_CONF)
    os.remove(PENDING_CONF)
    log.info("Promoted pending config to active")


def _discard_pending():
    """Pending config failed — delete it."""
    if os.path.exists(PENDING_CONF):
        os.remove(PENDING_CONF)
        log.warning("Discarded failed pending config")


def run_boot_wifi_check():
    """
    Boot-time WiFi check. Call this early in main.py before
    starting the gateway.

    Returns:
        "connected"   — WiFi is up (using active or newly promoted config)
        "needs_setup" — no config exists, user must run setup
    """
    has_pending = os.path.exists(PENDING_CONF)
    has_active  = os.path.exists(ACTIVE_CONF)

    log.info("Boot WiFi check: pending=%s active=%s", has_pending, has_active)

    # ── Step 1: Try pending config if it exists ────────────────
    if has_pending:
        log.info("Trying pending WiFi config...")
        _apply_config(PENDING_CONF)

        if _wait_for_connection(CONNECT_TIMEOUT):
            _promote_pending()
            return "connected"
        else:
            log.warning("Pending config failed, falling back to active")
            _discard_pending()
            # Fall through to try active

    # ── Step 2: Try active (known-good) config ─────────────────
    if has_active:
        # Check if already connected (e.g. system auto-connected)
        if _is_connected():
            log.info("Already connected using active config")
            return "connected"

        log.info("Applying active WiFi config...")
        _apply_config(ACTIVE_CONF)

        if _wait_for_connection(CONNECT_TIMEOUT):
            return "connected"
        else:
            log.error("Active config also failed — network may be down")
            # Don't delete active — it was good before, network might
            # just be temporarily unavailable
            return "connected"  # optimistic — gateway should still run

    # ── Step 3: No config at all ───────────────────────────────
    log.warning("No WiFi config found — setup required")
    return "needs_setup"


def clear_all():
    """Factory reset — delete both configs."""
    for f in (ACTIVE_CONF, PENDING_CONF):
        if os.path.exists(f):
            os.remove(f)
            log.info("Deleted %s", f)
