# HVAC-Vibe Gateway — Installation & Setup Guide

Complete steps to set up the HVAC-Vibe gateway on a Raspberry Pi Zero 2W
from a fresh Raspbian Lite image.

---

## Hardware

- Raspberry Pi Zero 2W
- Waveshare 3.5" RPi LCD (B) — direct HAT mount
- MicroSD card (16GB+)
- Power supply (5V 2.5A)

---

## 1. OS Setup

Flash Raspbian Lite (64-bit) to SD card using Raspberry Pi Imager.

In Imager advanced settings before flashing:
- Set hostname: `hvacvibe`
- Enable SSH
- Set username: `mitkatch`
- Set WiFi credentials

Boot the Pi, then SSH in:

```bash
ssh mitkatch@hvacvibe.local
```

Update the system:

```bash
sudo apt update && sudo apt upgrade -y
```

---

## 2. System Dependencies

```bash
sudo apt install -y \
  python3-pip \
  python3-venv \
  mosquitto \
  mosquitto-clients \
  bluetooth \
  bluez \
  python3-bluez
```

---

## 3. Mosquitto MQTT Broker

Enable external connections (required for laptop debugging):

```bash
sudo nano /etc/mosquitto/mosquitto.conf
```

Add these lines:

```
listener 1883 0.0.0.0
allow_anonymous true
```

Enable and start:

```bash
sudo systemctl enable mosquitto
sudo systemctl start mosquitto
```

Verify:

```bash
mosquitto_sub -h localhost -t "test" -v &
mosquitto_pub -h localhost -t "test" -m "hello"
```

---

## 4. Data Directories

```bash
sudo mkdir -p /var/lib/hvac-vibe
sudo chown mitkatch:mitkatch /var/lib/hvac-vibe
```

---

## 5. HVAC-Vibe Engine

### Deploy files

```bash
mkdir ~/hvac-engine
# copy engine files here:
#   engine_main.py
#   engine_config.py
#   engine_mqtt.py
#   engine_processor.py
#   engine_ble.py
#   engine_store.py
#   engine_heartbeat.py
#   requirements.txt
#   hvac-engine.service
#   config.json
```

### Create virtualenv and install dependencies

```bash
cd ~/hvac-engine
python3 -m venv venv
venv/bin/pip install -r requirements.txt
```

### Configure gateway

```bash
nano ~/hvac-engine/config.json
```

```json
{
  "gateway_name": "your-location-name",
  "wifi_ssid":    "YourWiFiNetwork",
  "wifi_password": "",
  "mqtt_broker":  "localhost",
  "mqtt_port":    1883,
  "db_path":      "/var/lib/hvac-vibe/engine.db",
  "sim_mode":     false
}
```

> **Note:** `gateway_id` is auto-derived as `{gateway_name}-{last-3-bytes-of-MAC}`.
> It will be written to config.json on first run.

### Test run (sim mode first)

Temporarily set `"sim_mode": true` in config.json, then:

```bash
cd ~/hvac-engine
venv/bin/python engine_main.py
```

In a second terminal, verify MQTT traffic:

```bash
mosquitto_sub -h localhost -t "hvac/#" -v
```

You should see topics publishing every 10 seconds.

Set `"sim_mode": false` when done testing.

### Install as systemd service

```bash
# Edit service file — set correct username and paths
nano ~/hvac-engine/hvac-engine.service
# Verify: User=mitkatch, WorkingDirectory and ExecStart point to ~/hvac-engine

sudo cp ~/hvac-engine/hvac-engine.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable hvac-engine
sudo systemctl start hvac-engine
```

Verify:

```bash
systemctl status hvac-engine
journalctl -u hvac-engine -f
```

---

## 6. HVAC-Vibe Display Server

### Deploy files

```bash
mkdir ~/hvac-display
# copy display files here:
#   display_main.py
#   display_state.py
#   display_mqtt.py
#   display_ws.py
#   display_history.py
#   requirements.txt
#   hvac-display.service
```

### Create virtualenv and install dependencies

```bash
cd ~/hvac-display
python3 -m venv venv
venv/bin/pip install -r requirements.txt
```

Verify all packages installed:

```bash
venv/bin/python -c "import fastapi, uvicorn, paho.mqtt, pydantic; print('all ok')"
```

### Test run

```bash
cd ~/hvac-display
venv/bin/python display_main.py
```

From laptop, verify API:

```bash
curl http://hvacvibe.local:8000/api/state
```

Should return JSON with sensor data.

### Install as systemd service

```bash
nano ~/hvac-display/hvac-display.service
# Verify: User=mitkatch, WorkingDirectory and ExecStart point to ~/hvac-display

sudo cp ~/hvac-display/hvac-display.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable hvac-display
sudo systemctl start hvac-display
```

Verify:

```bash
systemctl status hvac-display
journalctl -u hvac-display -f
```

---

## 7. Verify Both Services on Reboot

```bash
sudo reboot
```

After reboot:

```bash
systemctl is-enabled hvac-engine    # should print: enabled
systemctl is-enabled hvac-display   # should print: enabled
systemctl status hvac-engine
systemctl status hvac-display
curl http://hvacvibe.local:8000/api/state
```

---

## 8. React UI (built on laptop)

```bash
# On laptop
cd ~/git/hvacvibe-hub
npm create vite@latest hvac-ui -- --template react
cd hvac-ui
npm install
npm install recharts

# Build
npm run build

# Deploy to Pi
scp -r dist/ mitkatch@hvacvibe.local:~/hvac-display/dist/
```

After deploying, Chromium kiosk:

```bash
# On Pi
chromium-browser \
  --kiosk \
  --noerrdialogs \
  --disable-infobars \
  --no-first-run \
  http://localhost:8000
```

---

## Service Management Reference

```bash
# Engine
sudo systemctl start|stop|restart|status hvac-engine
journalctl -u hvac-engine -f

# Display
sudo systemctl start|stop|restart|status hvac-display
journalctl -u hvac-display -f

# MQTT broker
sudo systemctl start|stop|restart|status mosquitto

# Watch all MQTT traffic (from laptop)
mosquitto_sub -h hvacvibe.local -t "hvac/#" -v

# Clear retained MQTT messages for a sensor
mosquitto_pub -h localhost -t "hvac/{gateway_id}/{sensor_id}/status" -r -n
```

---

## Directory Structure

```
/home/mitkatch/
  ├── hvac-engine/
  │     ├── engine_main.py
  │     ├── engine_config.py
  │     ├── engine_mqtt.py
  │     ├── engine_processor.py
  │     ├── engine_ble.py
  │     ├── engine_store.py
  │     ├── engine_heartbeat.py
  │     ├── requirements.txt
  │     ├── hvac-engine.service
  │     ├── config.json
  │     └── venv/
  │
  └── hvac-display/
        ├── display_main.py
        ├── display_state.py
        ├── display_mqtt.py
        ├── display_ws.py
        ├── display_history.py
        ├── requirements.txt
        ├── hvac-display.service
        ├── venv/
        └── dist/               ← React build output

/var/lib/hvac-vibe/
  └── engine.db                 ← SQLite (auto-created)

/etc/systemd/system/
  ├── hvac-engine.service
  └── hvac-display.service
```

---

## MQTT Topic Reference

```
hvac/{gateway_id}/{sensor_id}/status
hvac/{gateway_id}/{sensor_id}/vibration/fft
hvac/{gateway_id}/{sensor_id}/vibration/features
hvac/{gateway_id}/{sensor_id}/environment
hvac/{gateway_id}/{sensor_id}/alert
hvac/{gateway_id}/gateway/status
```

Gateway ID format: `{location-name}-{last-3-bytes-of-wlan0-MAC}`
Example: `roof-unit-a4b2c3`
