#!/usr/bin/env python3
"""
HVAC-Vibe Server  —  FastAPI + WebSocket controller
Serves static/ frontend and pushes live data to all connected clients.
"""
import asyncio
import json
import os
import platform
import sys
from contextlib import asynccontextmanager
from typing import Set

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

# ── Models ────────────────────────────────────────────────────
from models.sensor_model import SENSOR
from models import wifi_model, ble_model, config_model

ON_PI = platform.system() not in ('Windows', 'Darwin')
GPIO_BTN = 26

# ── Connection manager ────────────────────────────────────────
class ConnectionManager:
    def __init__(self):
        self.active: Set[WebSocket] = set()

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active.add(ws)

    def disconnect(self, ws: WebSocket):
        self.active.discard(ws)

    async def broadcast(self, msg: dict):
        if not self.active:
            return
        data = json.dumps(msg)
        dead = set()
        for ws in self.active:
            try:
                await ws.send_text(data)
            except Exception:
                dead.add(ws)
        self.active -= dead

manager = ConnectionManager()

# ── Background tasks ──────────────────────────────────────────
async def sensor_push_loop():
    """Push sensor state to all clients every second."""
    while True:
        SENSOR.tick()
        await manager.broadcast({
            "type": "sensor_update",
            "data": {
                **SENSOR.to_dict(),
                "history": SENSOR.history_list(),
            }
        })
        await asyncio.sleep(1.0)


async def system_status_loop():
    """Push WiFi + BLE config status every 10 seconds."""
    while True:
        wifi  = await wifi_model.get_status()
        paired = ble_model.get_paired()
        await manager.broadcast({
            "type": "system_status",
            "data": {
                "wifi":    wifi,
                "sensors": paired,
            }
        })
        await asyncio.sleep(10.0)


async def gpio_button_loop():
    """Poll GPIO26 and send toggle_view to all clients on press."""
    if not ON_PI:
        return
    import RPi.GPIO as GPIO
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(GPIO_BTN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    last = True
    while True:
        current = GPIO.input(GPIO_BTN)
        if last and not current:          # falling edge = button press
            await manager.broadcast({"type": "toggle_view"})
        last = current
        await asyncio.sleep(0.05)        # 50ms poll = responsive enough


# ── App lifespan ──────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    tasks = [
        asyncio.create_task(sensor_push_loop()),
        asyncio.create_task(system_status_loop()),
        asyncio.create_task(gpio_button_loop()),
    ]
    yield
    for t in tasks:
        t.cancel()

app = FastAPI(lifespan=lifespan)

# Serve static files (index.html, app.js, etc.)
STATIC_DIR = os.path.join(os.path.dirname(__file__), 'static')
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

@app.get("/")
async def root():
    return FileResponse(os.path.join(STATIC_DIR, 'index.html'))


# ── WebSocket endpoint ────────────────────────────────────────
@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await manager.connect(ws)

    # Send initial state immediately on connect
    wifi = await wifi_model.get_status()
    await ws.send_text(json.dumps({
        "type": "system_status",
        "data": {"wifi": wifi, "sensors": ble_model.get_paired()}
    }))
    await ws.send_text(json.dumps({
        "type": "sensor_update",
        "data": {**SENSOR.to_dict(), "history": SENSOR.history_list()}
    }))

    try:
        while True:
            raw = await ws.receive_text()
            msg = json.loads(raw)
            await handle_command(ws, msg)
    except WebSocketDisconnect:
        manager.disconnect(ws)
    except Exception:
        manager.disconnect(ws)


# ── Command handler ───────────────────────────────────────────
async def handle_command(ws: WebSocket, msg: dict):
    cmd = msg.get("cmd")

    if cmd == "wifi_scan":
        await ws.send_text(json.dumps({"type": "cmd_ack", "cmd": "wifi_scan", "status": "scanning"}))
        networks = await wifi_model.scan()
        await ws.send_text(json.dumps({"type": "wifi_scan_result", "data": {"networks": networks}}))

    elif cmd == "wifi_connect":
        ssid = msg.get("ssid", "")
        pwd  = msg.get("password", "")
        await ws.send_text(json.dumps({"type": "cmd_ack", "cmd": "wifi_connect", "status": "connecting"}))
        result = await wifi_model.connect(ssid, pwd)
        await manager.broadcast({"type": "cmd_result", "cmd": "wifi_connect", **result})
        if result["success"]:
            wifi = await wifi_model.get_status()
            await manager.broadcast({"type": "system_status",
                                      "data": {"wifi": wifi, "sensors": ble_model.get_paired()}})

    elif cmd == "ble_scan":
        await ws.send_text(json.dumps({"type": "cmd_ack", "cmd": "ble_scan", "status": "scanning"}))
        devices = await ble_model.scan(duration=5.0)
        await ws.send_text(json.dumps({"type": "ble_scan_result", "data": {"devices": devices}}))

    elif cmd == "ble_pair":
        address = msg.get("address", "")
        name    = msg.get("name", address)
        result  = ble_model.pair(address, name)
        await manager.broadcast({"type": "cmd_result", "cmd": "ble_pair", **result})
        await manager.broadcast({"type": "system_status",
                                  "data": {"wifi": await wifi_model.get_status(),
                                           "sensors": ble_model.get_paired()}})

    elif cmd == "ble_unpair":
        address = msg.get("address", "")
        result  = ble_model.unpair(address)
        await manager.broadcast({"type": "cmd_result", "cmd": "ble_unpair", **result})
        await manager.broadcast({"type": "system_status",
                                  "data": {"wifi": await wifi_model.get_status(),
                                           "sensors": ble_model.get_paired()}})

    elif cmd == "get_status":
        wifi = await wifi_model.get_status()
        await ws.send_text(json.dumps({
            "type": "system_status",
            "data": {"wifi": wifi, "sensors": ble_model.get_paired()}
        }))

    elif cmd == "save_config":
        data = msg.get("data", {})
        c = config_model.load()
        c.update(data)
        ok = config_model.save(c)
        await ws.send_text(json.dumps({"type": "cmd_result", "cmd": "save_config",
                                        "success": ok, "message": "Saved" if ok else "Save failed"}))


# ── Entry point ───────────────────────────────────────────────
if __name__ == "__main__":
    uvicorn.run("server:app", host="0.0.0.0", port=8765, log_level="warning")
