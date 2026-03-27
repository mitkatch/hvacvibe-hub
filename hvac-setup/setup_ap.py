"""
setup_ap.py — Start/stop hostapd AP + dnsmasq for WiFi setup mode.

Simplified: no connection saving/restoring.
If setup fails, use COM port or /boot/firmware/hvac-restore-wifi.

AP: HVAC-Vibe-Setup / vibesetup
IP: 192.168.4.1
"""

import logging
import os
import subprocess
import time

log = logging.getLogger("setup_ap")

AP_SSID      = "HVAC-Vibe-Setup"
AP_PASSWORD  = "vibesetup"
AP_IP        = "192.168.4.1"
AP_IFACE     = "wlan0"
HOSTAPD_CONF = "/tmp/hvac-hostapd.conf"
DNSMASQ_CONF = "/tmp/hvac-dnsmasq.conf"
DNSMASQ_PID  = "/tmp/hvac-dnsmasq.pid"


def _write_hostapd_conf():
    conf = f"""interface={AP_IFACE}
driver=nl80211
ssid={AP_SSID}
hw_mode=g
channel=6
wmm_enabled=0
macaddr_acl=0
auth_algs=1
ignore_broadcast_ssid=0
wpa=2
wpa_passphrase={AP_PASSWORD}
wpa_key_mgmt=WPA-PSK
wpa_pairwise=TKIP
rsn_pairwise=CCMP
"""
    with open(HOSTAPD_CONF, "w") as f:
        f.write(conf)


def _write_dnsmasq_conf():
    conf = f"""interface={AP_IFACE}
dhcp-range=192.168.4.2,192.168.4.20,255.255.255.0,24h
address=/#/{AP_IP}
no-resolv
no-poll
"""
    with open(DNSMASQ_CONF, "w") as f:
        f.write(conf)


def start_ap() -> bool:
    """Bring up AP mode on wlan0."""
    log.info(f"Starting AP: {AP_SSID}")

    # Release wlan0 from NM
    log.info("Releasing wlan0 from NetworkManager...")
    try:
        subprocess.run(["nmcli", "dev", "disconnect", AP_IFACE],
                       capture_output=True, timeout=5)
    except subprocess.TimeoutExpired:
        log.warning("nmcli disconnect timed out — continuing")
    try:
        subprocess.run(["nmcli", "dev", "set", AP_IFACE, "managed", "no"],
                       capture_output=True, timeout=5)
    except subprocess.TimeoutExpired:
        log.warning("nmcli set managed no timed out — continuing")
    time.sleep(2)

    # Assign static IP
    subprocess.run(["ip", "link", "set", AP_IFACE, "up"], capture_output=True)
    subprocess.run(["ip", "addr", "flush", "dev", AP_IFACE], capture_output=True)
    result = subprocess.run(
        ["ip", "addr", "add", f"{AP_IP}/24", "dev", AP_IFACE],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        log.error(f"Failed to assign AP IP: {result.stderr}")
        return False

    # Write configs
    _write_hostapd_conf()
    _write_dnsmasq_conf()

    # Start hostapd
    result = subprocess.run(
        ["hostapd", "-B", HOSTAPD_CONF],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        log.error(f"hostapd failed: {result.stderr}")
        _release_ap()
        return False
    log.info("hostapd started")
    time.sleep(2)

    # Start dnsmasq
    result = subprocess.run(
        ["dnsmasq",
         f"--conf-file={DNSMASQ_CONF}",
         f"--pid-file={DNSMASQ_PID}"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        log.error(f"dnsmasq failed: {result.stderr}")
        subprocess.run(["pkill", "-f", "hostapd"], capture_output=True)
        _release_ap()
        return False
    log.info("dnsmasq started")

    log.info(f"AP running: {AP_SSID} @ {AP_IP}")
    return True


def stop_ap():
    """
    Tear down AP and hand wlan0 back to NM.
    Waits until NM actually confirms wlan0 is managed before returning.
    """
    log.info("Stopping AP")

    # Stop hostapd
    subprocess.run(["pkill", "-f", "hostapd"], capture_output=True)
    time.sleep(2)   # wait for radio to fully stop

    # Stop dnsmasq
    if os.path.exists(DNSMASQ_PID):
        try:
            with open(DNSMASQ_PID) as f:
                pid = int(f.read().strip())
            subprocess.run(["kill", str(pid)], capture_output=True)
            os.remove(DNSMASQ_PID)
        except Exception:
            subprocess.run(["pkill", "-f", "dnsmasq"], capture_output=True)

    _release_ap()
    log.info("AP stopped — wlan0 returned to NM")


def _release_ap():
    """
    Flush IP, return wlan0 to NM, and WAIT until NM confirms it's managed.
    This is critical — apply_wifi() must not run until NM owns wlan0.
    """
    # Flush AP IP
    subprocess.run(["ip", "addr", "flush", "dev", AP_IFACE], capture_output=True)
    time.sleep(1)

    # Tell NM to take back control
    subprocess.run(["nmcli", "dev", "set", AP_IFACE, "managed", "yes"],
                   capture_output=True)

    # Wait until NM actually shows wlan0 as managed — not just unmanaged
    log.info("Waiting for NM to take control of wlan0...")
    for i in range(20):
        time.sleep(1)
        result = subprocess.run(
            ["nmcli", "-t", "-f", "GENERAL.STATE", "dev", "show", AP_IFACE],
            capture_output=True, text=True
        )
        state = result.stdout.strip()
        log.info(f"wlan0 state: {state} (attempt {i+1}/20)")

        if state and "unmanaged" not in state:
            log.info(f"wlan0 is now managed by NM: {state}")
            return

        # Retry managed yes every 5 seconds
        if i > 0 and i % 5 == 0:
            log.warning("Still unmanaged — retrying nmcli set managed yes")
            subprocess.run(["nmcli", "dev", "set", AP_IFACE, "managed", "yes"],
                           capture_output=True)

    log.warning("wlan0 still unmanaged after 20s — proceeding anyway")


def is_ap_running() -> bool:
    result = subprocess.run(["pgrep", "-f", "hostapd"], capture_output=True)
    return result.returncode == 0
