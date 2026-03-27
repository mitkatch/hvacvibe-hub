"""
setup_wifi.py — WiFi scanning and credential apply.

Simplified: no backup/rollback. If connection fails, AP restarts and user tries again.
Recovery: use COM port or create /boot/firmware/hvac-restore-wifi on SD card.

Target: Ubuntu cloud-init image with NetworkManager on Pi Zero 2W.
"""

import logging
import os
import re
import shutil
import subprocess
import time

log = logging.getLogger("setup_wifi")

NETWORK_CONFIG         = "/boot/firmware/network-config"
NETWORK_CONFIG_FACTORY = "/boot/firmware/network-config.factory"
RESET_FLAG             = "/boot/firmware/hvac-reset-wifi"
RESTORE_FLAG           = "/boot/firmware/hvac-restore-wifi"
SETUP_FLAG             = "/etc/hvac-vibe/wifi-configured"
IFACE                  = "wlan0"
CONNECT_TIMEOUT        = 30


# ── Setup state ────────────────────────────────────────────────────────────

def needs_setup() -> bool:
    # Restore trigger — silently restore factory config
    if os.path.exists(RESTORE_FLAG):
        log.info("Restore trigger found — restoring factory WiFi")
        os.remove(RESTORE_FLAG)
        _restore_factory()
        ip = _wait_for_ip(timeout=CONNECT_TIMEOUT)
        if ip:
            log.info(f"Restored: {ip}")
            mark_setup_complete()
            return False
        log.warning("Restore failed — entering setup UI")
        _clear_setup_flag()
        return True

    # Reset trigger — force setup UI
    if os.path.exists(RESET_FLAG):
        log.info("Reset trigger — forcing setup")
        os.remove(RESET_FLAG)
        _clear_setup_flag()
        return True

    if not os.path.exists(SETUP_FLAG):
        return True

    return not _has_internet()


def mark_setup_complete():
    os.makedirs(os.path.dirname(SETUP_FLAG), exist_ok=True)
    with open(SETUP_FLAG, "w") as f:
        f.write("configured\n")
    log.info("Setup complete")


def _clear_setup_flag():
    if os.path.exists(SETUP_FLAG):
        os.remove(SETUP_FLAG)


def _restore_factory():
    if os.path.exists(NETWORK_CONFIG_FACTORY):
        shutil.copy2(NETWORK_CONFIG_FACTORY, NETWORK_CONFIG)
        log.info("Restored factory network-config")
    subprocess.run(["nmcli", "con", "reload"], capture_output=True)
    subprocess.run(["nmcli", "dev", "connect", IFACE], capture_output=True)


# ── WiFi scanning ──────────────────────────────────────────────────────────

def scan_networks() -> list[dict]:
    """Scan networks. Call BEFORE AP mode starts."""
    try:
        subprocess.run(["nmcli", "dev", "wifi", "rescan"],
                       capture_output=True, timeout=10)
        time.sleep(2)
        result = subprocess.run(
            ["nmcli", "-t", "-f", "SSID,SIGNAL,SECURITY", "dev", "wifi", "list"],
            capture_output=True, text=True, timeout=15
        )
        networks = _parse_nmcli(result.stdout)
        log.info(f"Scan complete: {len(networks)} networks")
        return networks
    except Exception as e:
        log.error(f"Scan error: {e}")
        return []


def _parse_nmcli(output: str) -> list[dict]:
    networks = []
    seen = set()
    for line in output.splitlines():
        parts = line.split(":")
        if len(parts) < 3:
            continue
        security = parts[-1].strip()
        signal_s = parts[-2].strip()
        ssid     = ":".join(parts[:-2]).strip()
        if not ssid or ssid == "--" or not signal_s.isdigit():
            continue
        if ssid in seen:
            continue
        seen.add(ssid)
        networks.append({
            "ssid":   ssid,
            "signal": int(signal_s),
            "secure": bool(security and security != "--"),
        })
    return sorted(networks, key=lambda n: n["signal"], reverse=True)


# ── Connect ────────────────────────────────────────────────────────────────

def apply_wifi(ssid: str, password: str) -> tuple[bool, str]:
    """
    Connect to WiFi via nmcli.
    AP must be stopped before calling this — wlan0 must be free.
    Returns (success, ip_or_error_message).
    """
    log.info(f"Connecting to: {ssid}")

    # Wait for NM to reinitialize radio after AP shutdown
    log.info("Waiting for radio to reinitialize...")
    time.sleep(5)

    # Rescan with retry until target SSID is visible
    visible = []
    for attempt in range(1, 5):
        log.info(f"Rescan attempt {attempt}/4...")
        try:
            subprocess.run(["nmcli", "dev", "wifi", "rescan"],
                           capture_output=True, timeout=10)
            time.sleep(4)
        except subprocess.TimeoutExpired:
            log.warning("Rescan timed out")

        result = subprocess.run(
            ["nmcli", "-t", "-f", "SSID", "dev", "wifi", "list"],
            capture_output=True, text=True
        )
        visible = [l.strip() for l in result.stdout.splitlines()
                   if l.strip() and l.strip() != "--"]
        log.info(f"Visible: {visible}")

        if ssid in visible:
            log.info(f"Found '{ssid}' on attempt {attempt}")
            break
        if attempt < 4:
            log.warning(f"'{ssid}' not visible — retrying in 5s...")
            time.sleep(5)

    if ssid not in visible:
        log.warning(f"'{ssid}' not found after 4 attempts")
        return False, "network_not_found"

    # Delete any stale profile for this SSID
    conn_name = f"hvac-setup-{ssid}"
    subprocess.run(["nmcli", "con", "delete", conn_name], capture_output=True)
    # Also clean up any old netplan-style profiles
    subprocess.run(["nmcli", "con", "delete", f"netplan-wlan0-{ssid}"],
                   capture_output=True)
    subprocess.run(["nmcli", "con", "delete", ssid], capture_output=True)

    # Create NM profile explicitly with security type
    # nmcli dev wifi connect is unreliable — con add + con up is robust
    log.info(f"Creating NM profile: {conn_name}")
    result = subprocess.run(
        ["nmcli", "con", "add",
         "type", "wifi",
         "ifname", IFACE,
         "con-name", conn_name,
         "ssid", ssid,
         "wifi-sec.key-mgmt", "wpa-psk",
         "wifi-sec.psk", password],
        capture_output=True, text=True
    )
    log.info(f"con add rc={result.returncode} stdout={result.stdout.strip()!r}")
    if result.stderr.strip():
        log.warning(f"con add stderr: {result.stderr.strip()}")
    if result.returncode != 0:
        log.warning("nmcli con add failed")
        return False, "connection_failed"

    # Activate the connection
    log.info(f"Activating: {conn_name}")
    result = subprocess.run(
        ["nmcli", "con", "up", conn_name],
        capture_output=True, text=True, timeout=35
    )
    log.info(f"con up rc={result.returncode} stdout={result.stdout.strip()!r}")
    if result.stderr.strip():
        log.warning(f"con up stderr: {result.stderr.strip()}")
    if result.returncode != 0:
        subprocess.run(["nmcli", "con", "delete", conn_name], capture_output=True)
        return False, "connection_failed"

    # Wait for IP
    ip = _wait_for_ip(timeout=CONNECT_TIMEOUT)
    if not ip:
        return False, "connection_failed"

    # Save hashed credentials to network-config
    _write_network_config(ssid, password)
    mark_setup_complete()
    log.info(f"Connected: {ip}")
    return True, ip


def _hash_password(ssid: str, password: str) -> str:
    try:
        result = subprocess.run(
            ["wpa_passphrase", ssid, password],
            capture_output=True, text=True, timeout=5
        )
        for line in result.stdout.splitlines():
            line = line.strip()
            if line.startswith("psk=") and not line.startswith("#"):
                return line.split("=", 1)[1].strip()
    except Exception as e:
        log.warning(f"wpa_passphrase failed: {e}")
    return password


def _write_network_config(ssid: str, password: str):
    psk = _hash_password(ssid, password)
    conf = f"""network:
  version: 2
  ethernets:
    eth0:
      dhcp4: true
      dhcp6: true
      optional: true
  wifis:
    wlan0:
      dhcp4: true
      regulatory-domain: "CA"
      optional: true
      access-points:
        "{ssid}":
          password: "{psk}"
"""
    with open(NETWORK_CONFIG, "w") as f:
        f.write(conf)
    log.info("Updated network-config")


def _wait_for_ip(timeout: int) -> str | None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        ip = _get_wlan_ip()
        if ip and not ip.startswith("192.168.4"):
            return ip
        time.sleep(1)
    return None


def _get_wlan_ip() -> str | None:
    try:
        result = subprocess.run(
            ["ip", "-4", "addr", "show", IFACE],
            capture_output=True, text=True
        )
        m = re.search(r"inet (\d+\.\d+\.\d+\.\d+)", result.stdout)
        return m.group(1) if m else None
    except Exception:
        return None


def _has_internet() -> bool:
    result = subprocess.run(
        ["ping", "-c", "1", "-W", "3", "8.8.8.8"],
        capture_output=True
    )
    return result.returncode == 0


def get_current_ip() -> str | None:
    return _get_wlan_ip()
