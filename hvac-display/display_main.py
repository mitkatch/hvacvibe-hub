#!/usr/bin/env python3
"""
display_main.py — HVAC-Vibe Display Server.

FastAPI app that:
  1. Subscribes to Mosquitto (MQTT) for live sensor data
  2. Reads engine.db directly for daily chart history
  3. Serves React frontend (dist/) as static files
  4. Pushes live state to browser via WebSocket
  5. Exposes REST endpoints for config + history

Endpoints:
  WS   /ws                         ← live sensor state stream
  GET  /api/state                  ← current snapshot (REST fallback)
  GET  /api/history/{sensor_id}    ← daily chart data
  GET  /api/config                 ← gateway config
  POST /api/config                 ← save WiFi + gateway name
  GET  /*                          ← React static files
"""

import asyncio
import logging
import os
import signal
import sys

from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("display_main")

# ── Config ────────────────────────────────────────────────────
# Reuse engine_config since both processes share config.json
sys.path.insert(0, os.path.join(os.path.dirname(__file__),
                                 "../hvac-engine"))
from engine_config import config as gw_config

from display_state   import state
from display_mqtt    import display_mqtt
from display_ws      import ws_manager
import display_history as history


# ── App lifecycle ─────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("Display server starting...")

    # Give WebSocket manager a reference to the running event loop
    ws_manager.set_loop(asyncio.get_running_loop())

    # Wire state changes → WebSocket broadcast
    state.set_on_change(ws_manager.broadcast_from_thread)

    # Start MQTT subscriber
    display_mqtt.start(gw_config)

    # Open history DB (read-only access to engine.db)
    history.init(gw_config.db_path)

    # Start WebSocket heartbeat
    asyncio.create_task(ws_manager.heartbeat_loop())

    log.info(f"Display server ready — gateway: {gw_config.gateway_id}")
    yield

    # Shutdown
    display_mqtt.stop()
    log.info("Display server stopped.")


app = FastAPI(title="HVAC-Vibe Display", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # kiosk is localhost, open is fine
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── WebSocket ─────────────────────────────────────────────────

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws_manager.connect(ws)
    try:
        while True:
            # Keep connection alive — browser sends pings
            await ws.receive_text()
    except WebSocketDisconnect:
        await ws_manager.disconnect(ws)
    except Exception as e:
        log.warning(f"WS error: {e}")
        await ws_manager.disconnect(ws)


# ── REST: state snapshot ──────────────────────────────────────

@app.get("/api/state")
async def get_state():
    return JSONResponse(state.snapshot())


# ── REST: daily history for chart ─────────────────────────────

@app.get("/api/history/{sensor_id}")
async def get_history(sensor_id: str, date: str = None):
    data = history.get_daily_history(sensor_id, date)
    return JSONResponse({"sensor_id": sensor_id, "date": date, "history": data})


# ── REST: config ──────────────────────────────────────────────

@app.get("/api/config")
async def get_config():
    return JSONResponse({
        "gateway_id":   gw_config.gateway_id,
        "gateway_name": gw_config.gateway_name,
        "mqtt_broker":  gw_config.mqtt_broker,
        "mqtt_port":    gw_config.mqtt_port,
        "sim_mode":     gw_config.sim_mode,
    })


class ConfigUpdate(BaseModel):
    gateway_name:  str | None = None
    wifi_ssid:     str | None = None
    wifi_password: str | None = None


@app.post("/api/config")
async def post_config(body: ConfigUpdate):
    updates = {k: v for k, v in body.dict().items() if v is not None}
    if updates:
        gw_config.save(updates)
        log.info(f"Config updated: {list(updates.keys())}")
    return JSONResponse({"ok": True, "gateway_id": gw_config.gateway_id})


# ── Serve React static files ──────────────────────────────────
# Must be mounted LAST — catches all remaining routes

_dist = os.path.join(os.path.dirname(__file__), "dist")
if os.path.exists(_dist):
    app.mount("/", StaticFiles(directory=_dist, html=True), name="ui")
    log.info(f"Serving React UI from {_dist}")
else:
    log.warning(f"No dist/ found at {_dist} — UI not available yet")

    @app.get("/")
    async def no_ui():
        return JSONResponse({"status": "display server running",
                             "ui": "dist/ not found — build React app first"})


# ── Entry point ───────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "display_main:app",
        host="0.0.0.0",
        port=8000,
        log_level="info",
        reload=False,
    )
