"""
display_ws.py — WebSocket connection manager.

Maintains set of active browser connections.
Broadcasts full state snapshot to all clients on every state change.
Also sends a heartbeat every 5s to keep connections alive.
"""

import asyncio
import json
import logging
import time

from fastapi import WebSocket

log = logging.getLogger("display_ws")


class WSManager:
    def __init__(self):
        self._clients:  set[WebSocket] = set()
        self._loop:     asyncio.AbstractEventLoop | None = None
        self._pending:  bool = False   # debounce rapid MQTT bursts

    def set_loop(self, loop: asyncio.AbstractEventLoop):
        """Called once FastAPI starts — stores the running event loop."""
        self._loop = loop

    # ── Connection lifecycle ──────────────────────────────────

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self._clients.add(ws)
        log.info(f"WS client connected — total: {len(self._clients)}")

        # Send current state immediately on connect
        from display_state import state
        await self._send_one(ws, state.snapshot())

    async def disconnect(self, ws: WebSocket):
        self._clients.discard(ws)
        log.info(f"WS client disconnected — total: {len(self._clients)}")

    # ── Broadcast ─────────────────────────────────────────────

    async def broadcast(self, data: dict):
        """Send data to all connected clients."""
        if not self._clients:
            return
        msg  = json.dumps(data, separators=(",", ":"))
        dead = set()
        for ws in self._clients:
            try:
                await ws.send_text(msg)
            except Exception:
                dead.add(ws)
        self._clients -= dead

    def broadcast_from_thread(self):
        """
        Called from MQTT thread (non-async context).
        Debounced — coalesces rapid FFT axis messages into one broadcast.
        """
        if self._loop is None or self._loop.is_closed():
            return
        if self._pending:
            return   # already scheduled
        self._pending = True

        async def _do():
            # Small delay to coalesce x/y/z FFT messages arriving together
            await asyncio.sleep(0.05)
            self._pending = False
            from display_state import state
            await self.broadcast(state.snapshot())

        asyncio.run_coroutine_threadsafe(_do(), self._loop)

    # ── Heartbeat ─────────────────────────────────────────────

    async def heartbeat_loop(self):
        """Keep-alive ping every 5s. Run as FastAPI background task."""
        while True:
            await asyncio.sleep(5)
            if self._clients:
                from display_state import state
                await self.broadcast({
                    "ts":   int(time.time()),
                    "type": "heartbeat",
                    "sensors": [
                        {"sensor_id": s.sensor_id,
                         "connected": s.connected,
                         "vib_rms":   s.vib_rms,
                         "alarm":     s.alarm,
                         "warn":      s.warn}
                        for s in state.get_all()
                    ],
                })

    # ── Internal ──────────────────────────────────────────────

    async def _send_one(self, ws: WebSocket, data: dict):
        try:
            await ws.send_text(json.dumps(data, separators=(",", ":")))
        except Exception as e:
            log.warning(f"WS send error: {e}")
            self._clients.discard(ws)


# Module-level singleton
ws_manager = WSManager()
