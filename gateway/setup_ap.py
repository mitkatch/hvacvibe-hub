"""
setup_ap.py — WiFi Access Point management for setup mode.

Starts a temporary hotspot on wlan0 so a phone can connect
and access the setup web page.  Tears down cleanly on exit.

Requires (install once):
  sudo apt install hostapd dnsmasq

AP config:
  SSID:      HVAC-Vibe-Setup
  Password:  vibesetup
  IP:        192.168.4.1
  DHCP:      192.168.4.10 — 192.168.4.50
"""

import logging
import os
import subprocess
import time

log = logging.getLogger("setup_ap")

AP_INTERFACE = "wlan0"
AP_IP        = "192.168.4.1"
AP_NETMASK   = "255.255.255.0"
AP_SSID      = "HVAC-Vibe-Setup"
AP_PASSWORD  = "vibesetup"
AP_CHANNEL   = 6

DHCP_RANGE_START = "192.168.4.10"
DHCP_RANGE_END   = "192.168.4.50"
DHCP_LEASE_TIME  = "1h"

# Temp config files
HOSTAPD_CONF = "/tmp/hvac_hostapd.conf"
DNSMASQ_CONF = "/tmp/hvac_dnsmasq.conf"

_original_state = {}


def _run(cmd, check=False):
    """Run shell command, log errors but don't crash."""
    log.debug(f"$ {cmd}")
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if result.returncode != 0 and check:
        log.error(f"Command failed: {cmd}\n{result.stderr}")
    return result


def _save_network_state():
    """Save current network state so we can restore later."""
    global _original_state

    # Check if wlan0 is managed by NetworkManager or wpa_supplicant
    result = _run("systemctl is-active NetworkManager")
    _original_state["nm_active"] = result.returncode == 0

    result = _run("systemctl is-active wpa_supplicant")
    _original_state["wpa_active"] = result.returncode == 0

    log.info("Saved network state: NM=%s wpa=%s",
             _original_state["nm_active"],
             _original_state["wpa_active"])


def _write_hostapd_conf():
    conf = f"""interface={AP_INTERFACE}
driver=nl80211
ssid={AP_SSID}
hw_mode=g
channel={AP_CHANNEL}
wmm_enabled=0
macaddr_acl=0
auth_algs=1
wpa=2
wpa_passphrase={AP_PASSWORD}
wpa_key_mgmt=WPA-PSK
rsn_pairwise=CCMP
"""
    with open(HOSTAPD_CONF, "w") as f:
        f.write(conf)
    log.debug(f"Wrote {HOSTAPD_CONF}")


def _write_dnsmasq_conf():
    conf = f"""interface={AP_INTERFACE}
bind-interfaces
dhcp-range={DHCP_RANGE_START},{DHCP_RANGE_END},{AP_NETMASK},{DHCP_LEASE_TIME}
# Redirect all DNS to ourselves (captive portal)
address=/#/{AP_IP}
"""
    with open(DNSMASQ_CONF, "w") as f:
        f.write(conf)
    log.debug(f"Wrote {DNSMASQ_CONF}")


def start():
    """Start the WiFi access point. Returns AP_IP on success."""
    log.info("Starting WiFi AP: %s (password: %s)", AP_SSID, AP_PASSWORD)

    _save_network_state()

    # Stop services that might conflict
    _run("sudo systemctl stop NetworkManager 2>/dev/null")
    _run("sudo systemctl stop wpa_supplicant 2>/dev/null")
    _run("sudo killall hostapd 2>/dev/null")
    _run("sudo killall dnsmasq 2>/dev/null")

    # Configure interface
    _run(f"sudo ip link set {AP_INTERFACE} down")
    _run(f"sudo ip addr flush dev {AP_INTERFACE}")
    _run(f"sudo ip addr add {AP_IP}/{AP_NETMASK} dev {AP_INTERFACE}")
    _run(f"sudo ip link set {AP_INTERFACE} up")
    time.sleep(0.5)

    # Write configs and start services
    _write_hostapd_conf()
    _write_dnsmasq_conf()

    _run(f"sudo hostapd -B {HOSTAPD_CONF}", check=True)
    time.sleep(1.0)
    _run(f"sudo dnsmasq -C {DNSMASQ_CONF}", check=True)

    log.info("AP started — SSID: %s  IP: %s", AP_SSID, AP_IP)
    return AP_IP


def stop():
    """Tear down the access point and restore network."""
    log.info("Stopping WiFi AP...")

    _run("sudo killall hostapd 2>/dev/null")
    _run("sudo killall dnsmasq 2>/dev/null")

    # Clean up temp files
    for f in (HOSTAPD_CONF, DNSMASQ_CONF):
        if os.path.exists(f):
            os.remove(f)

    # Flush AP address
    _run(f"sudo ip addr flush dev {AP_INTERFACE}")
    _run(f"sudo ip link set {AP_INTERFACE} down")

    # Restore previous network services
    if _original_state.get("wpa_active"):
        _run("sudo systemctl start wpa_supplicant")
        time.sleep(1.0)

    if _original_state.get("nm_active"):
        _run("sudo systemctl start NetworkManager")
        time.sleep(1.0)
    else:
        # If not using NM, bring interface back up for dhcpcd/systemd-networkd
        _run(f"sudo ip link set {AP_INTERFACE} up")
        _run(f"sudo dhcpcd {AP_INTERFACE} 2>/dev/null")

    log.info("AP stopped, network restored")


def get_ap_ip():
    return AP_IP


def get_ap_ssid():
    return AP_SSID


def get_ap_password():
    return AP_PASSWORD
