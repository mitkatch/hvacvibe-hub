# HVAC-Vibe WiFi Setup — Session Summary

## Goal
Build a captive portal WiFi provisioning system: Pi broadcasts AP → user connects phone → picks network from list → enters password → Pi joins that network → hands off to hvac-engine.

---

## Architecture

```
Boot → hvac-setup.service (runs first)
    → needs_setup()? 
        NO  → show IP on display, exit, hvac-engine starts
        YES → scan WiFi, start AP, start Flask, show QR
             → user picks network + password in browser
             → stop AP, connect via nmcli, mark done
             → hvac-engine starts
```

**Files built:**
- `setup_main.py` — entry point, state machine
- `setup_ap.py` — hostapd + dnsmasq AP control
- `setup_wifi.py` — scan, connect, recovery triggers
- `setup_flask.py` — Flask web server
- `setup_display.py` — Waveshare QR + IP display
- `templates/index.html` — mobile-friendly single page UI
- `hvac-setup.service` — systemd unit
- `install.sh` — installs dependencies and service
- `restore.sh` — manual recovery script

---

## Problems Found & Solutions

### 1. Target image is Ubuntu cloud-init, not Raspbian

**Problem:** Original code used `wpa_supplicant.conf` and `wpa_cli reconfigure` — neither works on Ubuntu with NetworkManager.

**Solution:** Rewrote `setup_wifi.py` entirely for `nmcli` and `/boot/firmware/network-config`.

---

### 2. dnsmasq "Address already in use"

**Problem:** System dnsmasq was already running, blocking our instance from binding port 67.

**Solution:** Added `sudo pkill dnsmasq` before starting AP in `setup_main.py`. Also disabled system dnsmasq in `install.sh`.

---

### 3. HVAC-Vibe-Setup not visible on phone

**Problem:** NetworkManager still owned wlan0 while hostapd tried to broadcast. NM kept wlan0 in client mode, overriding hostapd.

**Solution:** Added `nmcli dev disconnect wlan0` + `nmcli dev set wlan0 managed no` before starting hostapd.

---

### 4. Phone connected to AP but spinner — couldn't join

**Problem:** dnsmasq wasn't running so phone got no DHCP IP. Root cause: dnsmasq started before hostapd fully initialized.

**Solution:** Added `time.sleep(2)` after hostapd starts before launching dnsmasq.

---

### 5. WiFi scan returned 0 networks in AP mode

**Problem:** Once wlan0 switches to AP mode, it can't scan for client networks simultaneously.

**Solution:** Pre-scan networks **before** AP starts (while NM still owns wlan0), cache results, pass to Flask. Browser shows cached list without needing any live scan.

---

### 6. nmcli connect failed: "No network with SSID found"

**Problem:** After AP shuts down, `nmcli dev wifi connect` ran immediately before NM had time to rescan. Scan results were empty.

**Solution:** Added rescan retry loop in `apply_wifi()` — up to 4 attempts with 5s gaps, checking if target SSID is visible before attempting connect.

---

### 7. wlan0 stuck as `unmanaged` after AP stops

**Problem:** After `stop_ap()`, `nmcli dev set wlan0 managed yes` was called but NM hadn't processed it yet. Python immediately proceeded to scan while wlan0 was still `unmanaged`.

**Root cause:** `stop_ap()` was **not being called at all** — it was missing from `_apply()` in `setup_flask.py`.

**Solution (two parts):**
- Added `stop_ap()` as first call in `_apply()` thread in `setup_flask.py`
- Added polling loop in `_release_ap()` — checks `nmcli dev show wlan0` every second for up to 20 seconds, retries `managed yes` every 5 seconds until NM confirms managed state

---

### 8. nmcli connect failed: "key-mgmt property missing"

**Problem:** `nmcli dev wifi connect` couldn't determine security type when no existing profile existed for the SSID.

**Solution:** Switched to `nmcli con add` + `nmcli con up` which explicitly sets `wifi-sec.key-mgmt wpa-psk`. This is more reliable and matches the manual teardown script that worked.

---

### 9. Connection profile deleted on failed attempt

**Problem:** `_delete_existing_connection()` deleted the current working `netplan-wlan0-SmartRG-e2ae` profile before the new connection succeeded. On rollback there was nothing to restore.

**Solution:** Simplified to no-rollback design. Profile names are now prefixed `hvac-setup-{ssid}` so they never conflict with existing profiles. COM port + SD card triggers provide recovery instead.

---

### 10. Flask timeout too short

**Problem:** `t.join(timeout=35)` wasn't enough for `stop_ap()` NM wait (up to 20s) + rescan retries (up to 40s) + connect (up to 35s).

**Solution:** Increased to `t.join(timeout=120)`.

---

## Recovery Mechanisms

| Method | How |
|---|---|
| SD card restore | Create empty `hvac-restore-wifi` on `/boot/firmware` — restores factory WiFi silently |
| SD card reset | Create empty `hvac-reset-wifi` on `/boot/firmware` — forces setup UI |
| COM port | micro USB data port → PuTTY serial 115200 — always available regardless of WiFi |
| `restore.sh` | Manual script on Pi — deletes duplicate profiles, reconnects to known network |

---

## Key Learnings

- Ubuntu cloud-init Pi images use NetworkManager, not wpa_supplicant
- NM and hostapd fight over wlan0 — must explicitly release before AP and verify managed state after
- `nmcli dev wifi connect` is unreliable without existing profiles — `con add` + `con up` is robust
- Scan before AP mode, not after — radio can't be AP and client simultaneously
- Always validate OS-level commands manually with a teardown script before trusting Python to wrap them

---

## Final Connect Sequence (Working)

```
setup_main.py
  1. scan_networks()          ← while NM owns wlan0, before AP
  2. stop hvac-pygame/display/engine
  3. pkill dnsmasq            ← kill any system instance
  4. start_ap()
       nmcli dev disconnect wlan0
       nmcli dev set wlan0 managed no
       ip addr add 192.168.4.1/24
       hostapd -B              ← sleep 2
       dnsmasq
  5. run Flask with cached networks

setup_flask.py /connect
  6. stop_ap() in background thread
       pkill hostapd           ← sleep 2
       pkill dnsmasq
       ip addr flush
       nmcli dev set wlan0 managed yes
       poll until not unmanaged (up to 20s)
  7. apply_wifi()
       sleep 5                 ← radio reinitialize
       rescan loop (4x)        ← until SSID visible
       nmcli con add type wifi wifi-sec.key-mgmt wpa-psk wifi-sec.psk PASSWORD
       nmcli con up
       wait for IP
       write network-config (hashed password)
       mark /etc/hvac-vibe/wifi-configured
  8. Flask returns IP to browser
  9. setup_main.py detects flag → exits
 10. systemd starts hvac-engine
```

---

## Pi Image Notes

- **OS:** Ubuntu cloud-init (not Raspbian)
- **Network manager:** NetworkManager (not wpa_supplicant)
- **WiFi config:** `/boot/firmware/network-config` (netplan format)
- **Boot partition:** `/boot/firmware/` (FAT32, writable from Windows)
- **Netplan files:** `/etc/netplan/90-NM-*.yaml` (auto-generated by NM)
- **Password storage:** WPA PSK hash via `wpa_passphrase ssid password`
