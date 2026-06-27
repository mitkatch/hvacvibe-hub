"""
engine_thread.py — Thread/CoAP UDP receiver.

Drop-in replacement for engine_ble.py.
Listens on UDP port 5683 for CoAP NON POST packets from sensor nodes.
Reuses all packet parsing and MQTT publishing from engine_ble.py.

Packet format (firmware analysis.h / thread.c):
  The firmware sends 3 separate CoAP NON POST packets per burst:

    PKT_TYPE_TIME_STATS (0x01): burst_header_t (10B) + time_stats_t (36B)
    PKT_TYPE_FFT_STATS  (0x04): burst_header_t (10B) + fft_stats_t  (60B)
    PKT_TYPE_ENV        (0x03): burst_header_t (10B) + env           (8B)

  All packets in a burst share the same (seq, timestamp_ms).
  This receiver reassembles them by (sensor_id, seq) before publishing.

  burst_header_t wire layout (little-endian, 10 bytes):
    [0]     uint8   type          PKT_TYPE_*
    [1]     uint8   reserved
    [2..3]  uint16  seq           monotonic burst counter
    [4..5]  uint16  sample_count  samples analysed
    [6..9]  uint32  timestamp_ms  k_uptime_get_32()

Sensor identification:
  Source address is the sensor's Thread RLOC (not ML-EID), so the IID
  encodes the RLOC16 rather than the EUI-64.  Sensor IDs are therefore
  derived from the RLOC16 suffix (e.g. "thread-9801") and will change
  on each rejoin.  To map stable names, configure a seq-based or
  topic-level alias in the backend, or extend burst_header_t with the
  EUI-64 in a future firmware revision.

config.json format (optional name override by RLOC suffix):
  "thread_sensors": {
    "9801": "hvac-vibe-basement"
  }

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
COAP_PORT = 5683

# burst_header_t: type(1) + reserved(1) + seq(2) + sample_count(2) + timestamp_ms(4) + name(16)
HEADER_SIZE = 26
HEADER_FMT  = "<BBHHI16s"

PKT_TYPE_TIME_STATS = 0x01
PKT_TYPE_ENV        = 0x03
PKT_TYPE_FFT_STATS  = 0x04
PKT_TYPE_SPECTRUM   = 0x05

TIME_STATS_SIZE  = 36
FFT_STATS_SIZE   = 60
ENV_SIZE         = 8
SPECTRUM_BINS    = 76    # bins 1-76 → 3.1-237 Hz at 3.125 Hz/bin (1600 Hz / 512 pt FFT)
SPECTRUM_HZ_PER_BIN = 1600 / 512   # 3.125 Hz

# Incomplete bursts are discarded after this many seconds
BURST_TIMEOUT_S = 2.0

# ── Reuse all parsing from engine_ble ────────────────────────────────────
from engine_ble import (
    SensorSession,
    _parse_time_stats,
    _parse_fft_stats,
    _parse_env,
)


def _rloc16_from_ipv6(addr: str) -> str:
    """
    Extract the RLOC16 suffix from a Thread RLOC IPv6 address.

    Thread RLOC IID format: 0000:00ff:fe00:<rloc16>
    e.g. fd42:46fb:fcc2:f867:0:ff:fe00:9801  ->  "9801"

    Used as a fallback sensor identifier when no name map is configured.
    """
    try:
        import ipaddress
        ip = ipaddress.IPv6Address(addr)
        # RLOC16 is the last 2 bytes of the 16-byte address
        return f"{ip.packed[14]:02x}{ip.packed[15]:02x}"
    except Exception:
        return addr.replace(":", "")[-4:].lower()


def _sensor_id_from_rloc16(rloc16: str) -> str:
    return f"thread-{rloc16}"


def _strip_coap_header(data: bytes) -> bytes | None:
    """
    Strip CoAP fixed header + token + options to get the raw payload.
    CoAP payload starts after the 0xFF payload marker byte.
    Returns None if no payload marker found.

    Must search only from after the fixed 4-byte CoAP header + token bytes.
    Bytes 2-3 of the fixed header are the message ID (big-endian), which can
    contain 0xFF when the ID counter is in the 0xFF00-0xFFFF range.  Searching
    from byte 0 finds that false 0xFF and returns the wrong slice.
    """
    if len(data) < 4:
        return None
    tkl = data[0] & 0x0F          # token length from low nibble of first byte
    options_start = 4 + tkl       # skip fixed header + token
    if len(data) <= options_start:
        return None
    marker = data.find(b'\xff', options_start)
    if marker < 0:
        return None
    return data[marker + 1:]


def _parse_packet(payload: bytes) -> dict | None:
    """
    Parse one CoAP payload (a single burst packet of any type).

    Returns a dict with keys: type, seq, sample_count, timestamp_ms,
    plus one of: time_stats, fft_stats, env.
    Returns None on any parse error.
    """
    if len(payload) < HEADER_SIZE:
        log.warning(f"Payload too short for header: {len(payload)} bytes")
        return None

    pkt_type, _reserved, seq, sample_count, timestamp_ms, name_raw = struct.unpack_from(
        HEADER_FMT, payload, 0
    )
    body = payload[HEADER_SIZE:]

    sensor_name = name_raw.rstrip(b'\x00').decode('ascii', errors='replace').strip()

    result = {
        "type":         pkt_type,
        "seq":          seq,
        "sample_count": sample_count,
        "timestamp_ms": timestamp_ms,
        "sensor_name":  sensor_name,
    }

    if pkt_type == PKT_TYPE_TIME_STATS:
        if len(body) < TIME_STATS_SIZE:
            log.warning(f"TIME_STATS body too short: {len(body)} bytes")
            return None
        ts = _parse_time_stats(body[:TIME_STATS_SIZE])
        if not ts:
            return None
        ts["seq"]          = seq
        ts["timestamp_ms"] = timestamp_ms
        result["time_stats"] = ts

    elif pkt_type == PKT_TYPE_FFT_STATS:
        if len(body) < FFT_STATS_SIZE:
            log.warning(f"FFT_STATS body too short: {len(body)} bytes")
            return None
        fs = _parse_fft_stats(body[:FFT_STATS_SIZE])
        if not fs:
            return None
        fs["seq"] = seq
        result["fft_stats"] = fs

    elif pkt_type == PKT_TYPE_ENV:
        if len(body) < ENV_SIZE:
            log.warning(f"ENV body too short: {len(body)} bytes")
            return None
        result["env"] = _parse_env(body[:ENV_SIZE])

    elif pkt_type == PKT_TYPE_SPECTRUM:
        if len(body) < SPECTRUM_BINS:
            log.warning(f"SPECTRUM body too short: {len(body)} bytes")
            return None
        raw = body[:SPECTRUM_BINS]
        # Firmware sends uint8 magnitudes normalised to peak (peak=255, DC=0)
        # Reconstruct frequency axis: bin k → k * 1600/512 Hz
        result["spectrum"] = {
            "freq_hz":   [round(k * SPECTRUM_HZ_PER_BIN, 1) for k in range(SPECTRUM_BINS)],
            "amplitude": [b / 255.0 for b in raw],
        }

    else:
        log.warning(f"Unknown pkt_type=0x{pkt_type:02x} — dropping")
        return None

    return result


# ── Burst reassembly ──────────────────────────────────────────────────────
#
# The firmware sends 3 separate CoAP packets per burst, all with the same
# seq and timestamp_ms.  We buffer them by (sensor_id, seq) and publish
# as soon as TIME_STATS + FFT_STATS have both arrived.  ENV is optional.

_bursts: dict[tuple, dict] = {}
_bursts_lock = threading.Lock()


def _assemble_and_maybe_publish(sensor_id: str, parsed: dict, session) -> bool:
    """
    Route one parsed packet.

    ENV (0x03) is published immediately — it arrives after TIME+FFT and is
    independent of vibration data, so buffering it alongside the burst would
    cause it to be silently dropped (the burst entry is deleted as soon as
    TIME_STATS+FFT_STATS complete, before ENV arrives).

    TIME_STATS (0x01) and FFT_STATS (0x04) are buffered by (sensor_id, seq)
    and published together as soon as both halves arrive.
    """
    # ENV and SPECTRUM are independent — publish directly, no burst buffering.
    # Both arrive after TIME_STATS+FFT_STATS so the burst entry is already gone.
    if parsed["type"] == PKT_TYPE_ENV:
        env = parsed.get("env")
        if env:
            session._last_env = env
            session._publish_environment()
        return True

    if parsed["type"] == PKT_TYPE_SPECTRUM:
        spec = parsed.get("spectrum")
        if spec:
            import time as _time
            session._mqtt.publish(
                topic=session._config.topic(session.sensor_id, "vibration", "spectrum"),
                payload={
                    "ts":        int(_time.time()),
                    "sensor_id": session.sensor_id,
                    "freq_hz":   spec["freq_hz"],
                    "amplitude": spec["amplitude"],
                },
                qos=0,
            )
        return True

    key = (sensor_id, parsed["seq"])

    with _bursts_lock:
        # Lazy cleanup of timed-out incomplete bursts
        now   = time.monotonic()
        stale = [k for k, v in _bursts.items()
                 if now - v["arrived"] > BURST_TIMEOUT_S]
        for k in stale:
            log.debug(f"Discarding incomplete burst key={k}")
            del _bursts[k]

        if key not in _bursts:
            _bursts[key] = {"arrived": now}

        burst    = _bursts[key]
        pkt_type = parsed["type"]

        if pkt_type == PKT_TYPE_TIME_STATS:
            burst["time_stats"]   = parsed["time_stats"]
            burst["timestamp_ms"] = parsed["timestamp_ms"]
        elif pkt_type == PKT_TYPE_FFT_STATS:
            burst["fft_stats"] = parsed["fft_stats"]

        if "time_stats" not in burst or "fft_stats" not in burst:
            return False

        # Both halves present — extract and remove before releasing lock
        time_stats = burst["time_stats"]
        fft_stats  = burst["fft_stats"]
        del _bursts[key]

    # Publish outside the lock
    session._publish_time_stats(time_stats)
    session._publish_fft_stats(fft_stats)

    return True


# ── Session registry ──────────────────────────────────────────────────────

_sessions: dict[str, SensorSession] = {}
_sessions_lock = threading.Lock()


def _get_or_create_session(sensor_id: str, rloc16: str, src_addr: str,
                            config, store, mqtt_client) -> SensorSession:
    with _sessions_lock:
        if sensor_id not in _sessions:
            session = SensorSession(
                address=src_addr,
                name=sensor_id,
                sensor_id=sensor_id,
                config=config,
                store=store,
                mqtt_client=mqtt_client,
            )
            _sessions[sensor_id] = session
            log.info(f"New Thread sensor: {sensor_id} rloc16={rloc16} addr={src_addr}")
            session._publish_status(connected=True)
        return _sessions[sensor_id]


# ── UDP listener ──────────────────────────────────────────────────────────

def _udp_listener(config, store, mqtt_client, stop_event: threading.Event):
    """
    Main UDP receive loop.
    Binds to :: (all interfaces) on port 5683.
    """
    sock = socket.socket(socket.AF_INET6, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.settimeout(1.0)

    try:
        sock.bind(('::', COAP_PORT))
        log.info(f"Thread listener: UDP [::] port {COAP_PORT}")
    except OSError as e:
        log.error(f"Failed to bind UDP port {COAP_PORT}: {e}")
        return

    # Optional: RLOC16-suffix → sensor_id name map from config
    sensor_map: dict[str, str] = getattr(config, 'THREAD_SENSORS', {})
    if sensor_map:
        log.info(f"Thread sensor map (RLOC16-based): {sensor_map}")

    while not stop_event.is_set():
        try:
            data, addr_info = sock.recvfrom(512)
            src_addr = addr_info[0]

            # Strip IPv6 scope ID if present (e.g. "fe80::1%eth0")
            if '%' in src_addr:
                src_addr = src_addr.split('%')[0]

            # Only process mesh-local (fd prefix) — skip link-local MLE traffic
            if src_addr.startswith('fe80'):
                continue

            rloc16 = _rloc16_from_ipv6(src_addr)

            payload = _strip_coap_header(data)
            if payload is None:
                log.warning(f"No CoAP payload marker from {src_addr}")
                continue

            parsed = _parse_packet(payload)
            if parsed is None:
                continue

            # Prefer name embedded in packet; fall back to config map, then RLOC16
            sensor_id = (parsed.get("sensor_name")
                         or sensor_map.get(rloc16)
                         or _sensor_id_from_rloc16(rloc16))

            session = _get_or_create_session(
                sensor_id, rloc16, src_addr, config, store, mqtt_client
            )

            published = _assemble_and_maybe_publish(sensor_id, parsed, session)
            if published:
                log.debug(
                    f"{sensor_id} rloc={rloc16}: seq={parsed['seq']} "
                    f"ts={parsed['timestamp_ms']}ms burst complete"
                )

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
