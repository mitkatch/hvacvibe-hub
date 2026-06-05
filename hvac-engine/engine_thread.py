"""
engine_thread.py — Thread/CoAP UDP receiver.

Drop-in replacement for engine_ble.py.
Listens on UDP port 5683 for CoAP NON POST packets from sensor nodes.
Reuses all packet parsing and MQTT publishing from engine_ble.py.

Packet format (from firmware thread.c):
  CoAP NON POST → /telemetry
  Payload: burst_header_t (8B) + time_stats_t (36B) + fft_stats_t (60B) + optional env (8B)
  type = PKT_TYPE_THREAD_TELEMETRY (0x10)

Sensor identification:
  Sensors are identified by their Thread IPv6 source address.
  Address is mapped to sensor_id via THREAD_SENSORS in config.json.
  Unknown sensors are auto-registered as "thread-<addr_suffix>".

Interface (matches engine_ble.py BLEScanner):
  thread_scanner.start(config, store, mqtt_client)
  thread_scanner.stop()
"""

import logging
import socket
import struct
import threading
import time

log = logging.getLogger("engine_thread")

# ── CoAP / packet constants ───────────────────────────────────────────────
COAP_PORT            = 5683
PKT_TYPE_THREAD_TEL  = 0x10   # thread.c PKT_TYPE_THREAD_TELEMETRY

# Offsets inside CoAP payload (after CoAP header is stripped)
HEADER_SIZE          = 8      # burst_header_t
TIME_STATS_SIZE      = 36     # time_stats_t
FFT_STATS_SIZE       = 60     # fft_stats_t
ENV_SIZE             = 8      # optional env block

PAYLOAD_MIN          = HEADER_SIZE + TIME_STATS_SIZE + FFT_STATS_SIZE   # 104 bytes
PAYLOAD_WITH_ENV     = PAYLOAD_MIN + ENV_SIZE                            # 112 bytes

# ── Reuse all parsing from engine_ble ────────────────────────────────────
from engine_ble import (
    SensorSession,
    _parse_time_stats,
    _parse_fft_stats,
    _parse_env,
    PKT_TYPE_TIME_STATS,
    PKT_TYPE_FFT_STATS,
    PKT_TYPE_ENV,
)

import math


def _sensor_id_from_addr(addr: str) -> str:
    """
    Derive a sensor_id from a Thread IPv6 address.
    Uses last 4 hex chars of the address as suffix.
    e.g. fd54:b06a:fe40:1:603b:9690:f851:ec4d → thread-ec4d
    """
    suffix = addr.replace(":", "")[-4:].lower()
    return f"thread-{suffix}"


def _strip_coap_header(data: bytes) -> bytes | None:
    """
    Strip CoAP fixed header + token + options to get the raw payload.
    CoAP payload starts after the 0xFF payload marker byte.
    Returns None if no payload marker found.
    """
    marker = data.find(b'\xff')
    if marker < 0:
        return None
    return data[marker + 1:]


def _parse_thread_telemetry(payload: bytes) -> tuple[dict, dict, dict | None] | None:
    """
    Parse the combined Thread telemetry payload:
      burst_header_t (8B) + time_stats_t (36B) + fft_stats_t (60B) [+ env (8B)]

    Returns (time_stats, fft_stats, env_or_None) or None on error.
    """
    if len(payload) < PAYLOAD_MIN:
        log.warning(f"Payload too short: {len(payload)} bytes (need {PAYLOAD_MIN})")
        return None

    # Parse burst header
    pkt_type, _reserved, seq, sample_count, chunk_index = struct.unpack_from(
        "<BBHHh", payload, 0
    )

    if pkt_type != PKT_TYPE_THREAD_TEL:
        log.warning(f"Unexpected pkt_type=0x{pkt_type:02x} (expected 0x10)")
        return None

    # Parse time_stats
    ts_payload = payload[HEADER_SIZE : HEADER_SIZE + TIME_STATS_SIZE]
    time_stats = _parse_time_stats(ts_payload)
    if not time_stats:
        return None
    time_stats["seq"] = seq

    # Parse fft_stats
    fft_offset = HEADER_SIZE + TIME_STATS_SIZE
    fft_payload = payload[fft_offset : fft_offset + FFT_STATS_SIZE]
    fft_stats = _parse_fft_stats(fft_payload)
    if not fft_stats:
        return None
    fft_stats["seq"] = seq

    # Parse optional env block
    env = None
    if len(payload) >= PAYLOAD_WITH_ENV:
        env_payload = payload[PAYLOAD_MIN : PAYLOAD_MIN + ENV_SIZE]
        env = _parse_env(env_payload)

    return time_stats, fft_stats, env


# ── Session registry ──────────────────────────────────────────────────────

_sessions: dict[str, SensorSession] = {}
_sessions_lock = threading.Lock()


def _get_or_create_session(sensor_id: str, addr: str,
                            config, store, mqtt_client) -> SensorSession:
    with _sessions_lock:
        if sensor_id not in _sessions:
            # Use IPv6 address as the "address" field (replaces MAC)
            session = SensorSession(
                address=addr,
                name=sensor_id,
                sensor_id=sensor_id,
                config=config,
                store=store,
                mqtt_client=mqtt_client,
            )
            _sessions[sensor_id] = session
            log.info(f"New Thread sensor: {sensor_id} @ {addr}")
            # Publish connected status
            session._publish_status(connected=True)
        return _sessions[sensor_id]


# ── UDP listener ──────────────────────────────────────────────────────────

def _udp_listener(config, store, mqtt_client, stop_event: threading.Event):
    """
    Main UDP receive loop.
    Binds to :: (all interfaces) on port 5683 to receive Thread multicast CoAP.
    """
    sock = socket.socket(socket.AF_INET6, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.settimeout(1.0)   # allows checking stop_event

    try:
        sock.bind(('::', COAP_PORT))
        log.info(f"Thread listener: UDP [::] port {COAP_PORT}")
    except OSError as e:
        log.error(f"Failed to bind UDP port {COAP_PORT}: {e}")
        return

    # Check config for sensor address map
    sensor_map: dict[str, str] = getattr(config, 'THREAD_SENSORS', {})
    if sensor_map:
        log.info(f"Thread sensor map: {sensor_map}")

    while not stop_event.is_set():
        try:
            data, addr_info = sock.recvfrom(512)
            src_addr = addr_info[0]

            # Strip IPv6 scope ID if present (e.g. "fe80::1%eth0")
            if '%' in src_addr:
                src_addr = src_addr.split('%')[0]

            # Resolve sensor_id
            sensor_id = sensor_map.get(src_addr) or _sensor_id_from_addr(src_addr)

            # Strip CoAP header to get raw payload
            payload = _strip_coap_header(data)
            if payload is None:
                log.warning(f"No CoAP payload marker from {src_addr}")
                continue

            result = _parse_thread_telemetry(payload)
            if result is None:
                continue

            time_stats, fft_stats, env = result

            session = _get_or_create_session(
                sensor_id, src_addr, config, store, mqtt_client
            )

            # Feed into the same publish pipeline as BLE
            session._publish_time_stats(time_stats)
            session._publish_fft_stats(fft_stats)

            if env:
                session._last_env = env
                session._publish_environment()

            log.debug(f"{sensor_id}: seq={time_stats['seq']} "
                      f"rms=[{time_stats['rms_x_mg']},{time_stats['rms_y_mg']},"
                      f"{time_stats['rms_z_mg']}]mg "
                      f"dom_x={fft_stats['x']['dominant_hz']}Hz")

        except socket.timeout:
            continue
        except Exception as e:
            log.error(f"Thread listener error: {e}", exc_info=True)
            time.sleep(1.0)

    sock.close()
    log.info("Thread listener stopped")


# ── Public API ────────────────────────────────────────────────────────────

class ThreadScanner:
    """
    Drop-in replacement for BLEScanner.
    Same start()/stop() interface — engine_main.py needs no structural changes.
    """

    def __init__(self):
        self._thread     = None
        self._stop_event = threading.Event()

    def start(self, config, store, mqtt_client):
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=_udp_listener,
            args=(config, store, mqtt_client, self._stop_event),
            name="thread-listener",
            daemon=True,
        )
        self._thread.start()
        log.info("Thread scanner started")

    def stop(self):
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=3.0)
        log.info("Thread scanner stopped")


thread_scanner = ThreadScanner()
