"""
engine_ble.py — BLE scanner and sensor connection manager.

Handles the new framed BLE packet protocol from nRF52840 firmware:
  PKT_TYPE_TIME_STATS (0x01)  8-byte header + 36-byte time_stats_t
  PKT_TYPE_RAW        (0x02)  8-byte header + raw accel chunks
  PKT_TYPE_ENV        (0x03)  8-byte header + 8-byte env payload
  PKT_TYPE_FFT_STATS  (0x04)  8-byte header + 60-byte fft_stats_t

All arrive on BURST_DATA_UUID (0x...ef1) except ENV which uses ENV_DATA_UUID (0x...ef2).

Packet accumulation strategy:
  - Stats packets (type 01, 04) are complete in one notification → process immediately.
  - Raw packets (type 02) are accumulated by (seq, chunk_index) until all chunks
    arrive, then assembled and forwarded to the FFT pipeline.
  - ENV packets (type 03) on the env characteristic are always single-packet.

Legacy support:
  If the first notification on a connection is NOT header-framed (old firmware),
  we fall back to the old 3072-byte accumulation mode automatically.
"""

import asyncio
import logging
import math
import struct
import threading
import time

log = logging.getLogger("engine_ble")

# ── Packet type constants (must match firmware analysis.h) ────────────────
PKT_TYPE_TIME_STATS = 0x01
PKT_TYPE_RAW        = 0x02
PKT_TYPE_ENV        = 0x03
PKT_TYPE_FFT_STATS  = 0x04

HEADER_SIZE       = 8      # burst_header_t: type(1) + reserved(1) + seq(2) + count(2) + chunk(2)
BYTES_PER_SAMPLE  = 6      # accel_sample_t: int16 x3
LEGACY_BURST_BYTES = 512 * BYTES_PER_SAMPLE   # 3072 — old firmware

# ── ADXL343 scale factors (match firmware) ────────────────────────────────
LSB_MG_NUM = 39    # 3.9 mg per LSB × 10
LSB_MG_DEN = 10


def _parse_header(data: bytes) -> dict | None:
    """
    Attempt to parse an 8-byte burst_header_t from the start of data.
    Returns None if data is too short or type byte is not a known type.
    """
    if len(data) < HEADER_SIZE:
        return None
    pkt_type, _reserved, seq, sample_count, chunk_index = struct.unpack_from("<BBHHh", data, 0)
    if pkt_type not in (PKT_TYPE_TIME_STATS, PKT_TYPE_RAW, PKT_TYPE_ENV, PKT_TYPE_FFT_STATS):
        return None
    return {
        "type":         pkt_type,
        "seq":          seq,
        "sample_count": sample_count,
        "chunk_index":  chunk_index,
        "payload":      data[HEADER_SIZE:],
    }


def _parse_time_stats(payload: bytes) -> dict | None:
    """
    Decode 36-byte time_stats_t payload.
    Returns dict with all fields in engineering units.
    """
    if len(payload) < 36:
        log.warning(f"time_stats payload too short: {len(payload)} bytes")
        return None

    (rms_x, rms_y, rms_z,
     peak_x, peak_y, peak_z,
     crest_x, crest_y, crest_z,
     kurt_x, kurt_y, kurt_z,
     var_x, var_y, var_z,
     _reserved, sample_count) = struct.unpack_from("<HHHhhhHHHhhhHHHHI", payload, 0)

    # Convert raw counts to engineering units
    # RMS: already in mg from firmware
    # Peak: raw counts → mg (× 3.9)
    peak_x_mg = (abs(peak_x) * LSB_MG_NUM) / (LSB_MG_DEN * 1000.0)   # mg → g
    peak_y_mg = (abs(peak_y) * LSB_MG_NUM) / (LSB_MG_DEN * 1000.0)
    peak_z_mg = (abs(peak_z) * LSB_MG_NUM) / (LSB_MG_DEN * 1000.0)

    return {
        # RMS per axis in g (firmware sends mg)
        "rms_x_g":     round(rms_x / 1000.0, 5),
        "rms_y_g":     round(rms_y / 1000.0, 5),
        "rms_z_g":     round(rms_z / 1000.0, 5),
        "rms_x_mg":    rms_x,
        "rms_y_mg":    rms_y,
        "rms_z_mg":    rms_z,
        # Peak in g
        "peak_x_g":    round(peak_x_mg, 5),
        "peak_y_g":    round(peak_y_mg, 5),
        "peak_z_g":    round(peak_z_mg, 5),
        "peak_x_raw":  peak_x,
        "peak_y_raw":  peak_y,
        "peak_z_raw":  peak_z,
        # Crest factor (dimensionless, ×100 from firmware)
        "crest_x":     round(crest_x / 100.0, 2),
        "crest_y":     round(crest_y / 100.0, 2),
        "crest_z":     round(crest_z / 100.0, 2),
        # Kurtosis (×100 from firmware; Gaussian ≈ 3.0)
        "kurtosis_x":  round(kurt_x / 100.0, 2),
        "kurtosis_y":  round(kurt_y / 100.0, 2),
        "kurtosis_z":  round(kurt_z / 100.0, 2),
        # Variance in mg²
        "variance_x_mg2": var_x,
        "variance_y_mg2": var_y,
        "variance_z_mg2": var_z,
        # Vector RMS across all axes (3D magnitude)
        "vector_rms_g": round(
            math.sqrt((rms_x**2 + rms_y**2 + rms_z**2) / 3) / 1000.0, 5
        ),
        "sample_count": sample_count,
    }


def _parse_fft_stats(payload: bytes) -> dict | None:
    """
    Decode 60-byte fft_stats_t payload (3 × 20-byte axis_fft_stats_t).
    """
    if len(payload) < 60:
        log.warning(f"fft_stats payload too short: {len(payload)} bytes")
        return None

    def _decode_axis(data: bytes, offset: int) -> dict:
        (dom_freq_hz, dom_mag, total_power,
         bpfo_energy, bpfi_energy, bsf_energy, ftf_energy,
         noise_floor, snr_bpfo, _reserved) = struct.unpack_from("<HHHHHHHHHH", data, offset)
        return {
            "dominant_hz":   dom_freq_hz,
            "dominant_mag":  dom_mag,
            "total_power":   total_power,
            "bpfo_energy":   bpfo_energy,
            "bpfi_energy":   bpfi_energy,
            "bsf_energy":    bsf_energy,
            "ftf_energy":    ftf_energy,
            "noise_floor":   noise_floor,
            "snr_bpfo":      round(snr_bpfo / 100.0, 2),   # firmware stores ×100
        }

    return {
        "x": _decode_axis(payload, 0),
        "y": _decode_axis(payload, 20),
        "z": _decode_axis(payload, 40),
    }


def _parse_env(payload: bytes) -> dict | None:
    """
    Decode 8-byte env payload: temp(int16 LE) + hum(uint16 LE) + pressure(uint32 LE).
    Fixed vs old 6-byte format — pressure is now 4 bytes (full uint32 Pa).
    """
    if len(payload) < 8:
        # Fall back to old 6-byte format (big-endian, truncated pressure)
        if len(payload) >= 6:
            temp_raw, hum_raw, press_raw = struct.unpack(">hhH", payload[:6])
            return {
                "temp_c":    round(temp_raw / 100.0, 2),
                "humidity":  round(hum_raw  / 100.0, 2),
                "pressure_pa": press_raw * 100,   # was hPa, convert to Pa
            }
        return None

    temp_raw, hum_raw, press_pa = struct.unpack_from("<hHI", payload, 0)
    return {
        "temp_c":      round(temp_raw / 100.0, 2),
        "humidity":    round(hum_raw  / 100.0, 2),
        "pressure_pa": press_pa,
        "pressure_hpa": round(press_pa / 100.0, 1),
    }


def _sensor_id_from_mac(name: str, address: str) -> str:
    import re
    mac_suffix = address.replace(":", "")[-6:].lower()
    safe_name  = re.sub(r"[^a-zA-Z0-9_\-]", "-", name).lower().strip("-")[:20]
    return f"{safe_name}-{mac_suffix}"


# ── SensorSession ─────────────────────────────────────────────────────────

class SensorSession:
    """
    Manages the GATT session for one sensor.

    Handles both new framed packets and legacy raw burst format.
    Assembles multi-chunk raw bursts. Passes decoded data to processor.
    """

    def __init__(self, address: str, name: str, sensor_id: str,
                 config, store, mqtt_client):
        self.address   = address
        self.name      = name
        self.sensor_id = sensor_id
        self._config   = config
        self._store    = store
        self._mqtt     = mqtt_client

        # New-protocol state
        self._framed_mode      = None   # True=framed, False=legacy, None=unknown
        self._pending_time_stats: dict | None = None
        self._pending_fft_stats:  dict | None = None
        # Raw burst reassembly: seq → {chunk_index: bytes}
        self._raw_chunks: dict[int, dict[int, bytes]] = {}
        self._raw_sample_count: dict[int, int] = {}

        # Legacy state
        self._legacy_buf = bytearray()

        # Shared state
        self._last_env   = {}
        self._last_vib   = {}
        self._prev_alarm = False

    # ── GATT notification handlers ────────────────────────────────────────

    def on_burst(self, sender, data: bytes):
        """Called for every BLE notification on the vibration characteristic."""
        if self._framed_mode is None:
            # Auto-detect on first packet
            hdr = _parse_header(data)
            self._framed_mode = (hdr is not None)
            log.info(f"{self.name}: packet mode = {'framed' if self._framed_mode else 'legacy'}")

        if self._framed_mode:
            self._handle_framed(data)
        else:
            self._handle_legacy(data)

    def on_env(self, sender, data: bytes):
        """Called for every BLE notification on the environment characteristic."""
        # ENV packets from new firmware arrive with a header on the burst char,
        # but also still sent on the env char (for backward compat) without header.
        parsed = None

        # Try new 8-byte env (with header stripped already, or headerless)
        hdr = _parse_header(data)
        if hdr and hdr["type"] == PKT_TYPE_ENV:
            parsed = _parse_env(hdr["payload"])
        else:
            # Old format: raw 6-byte big-endian on env char
            parsed = _parse_env(data)

        if parsed:
            self._last_env = parsed
            self._publish_environment()

    # ── Framed packet dispatch ────────────────────────────────────────────

    def _handle_framed(self, data: bytes):
        hdr = _parse_header(data)
        if not hdr:
            log.warning(f"{self.name}: framed mode but failed to parse header, "
                        f"len={len(data)} bytes[0]={data[0]:02x}")
            return

        pkt_type = hdr["type"]

        if pkt_type == PKT_TYPE_TIME_STATS:
            stats = _parse_time_stats(hdr["payload"])
            if stats:
                stats["seq"] = hdr["seq"]
                self._pending_time_stats = stats
                log.debug(f"{self.name}: time_stats seq={hdr['seq']} "
                          f"rms=[{stats['rms_x_mg']},{stats['rms_y_mg']},{stats['rms_z_mg']}]mg")
            # If we get time_stats without a preceding FFT (e.g. first burst),
            # try to publish immediately if we already have FFT from last burst.
            self._try_publish_combined(hdr["seq"])

        elif pkt_type == PKT_TYPE_FFT_STATS:
            fft = _parse_fft_stats(hdr["payload"])
            if fft:
                fft["seq"] = hdr["seq"]
                self._pending_fft_stats = fft
                log.debug(f"{self.name}: fft_stats seq={hdr['seq']} "
                          f"X dom={fft['x']['dominant_hz']}Hz "
                          f"bpfo={fft['x']['bpfo_energy']}")
            self._try_publish_combined(hdr["seq"])

        elif pkt_type == PKT_TYPE_RAW:
            self._accumulate_raw_chunk(hdr)

        elif pkt_type == PKT_TYPE_ENV:
            parsed = _parse_env(hdr["payload"])
            if parsed:
                self._last_env = parsed
                self._publish_environment()

    def _try_publish_combined(self, seq: int):
        """
        Publish the full burst result once we have BOTH time_stats and fft_stats
        for the same seq number. If only one arrives (firmware with SEND_RAW_BURST=0
        and no FFT), publish what we have after a short grace period.
        """
        ts = self._pending_time_stats
        ff = self._pending_fft_stats

        if ts is None:
            return   # nothing to publish yet

        if ff is not None and ff.get("seq") != ts.get("seq"):
            # Sequence mismatch — FFT is from an older burst, use time_stats alone
            ff = None

        # We have time_stats and (optionally) fft_stats for the same burst
        self._publish_burst_result(ts, ff)
        self._pending_time_stats = None
        self._pending_fft_stats  = None

    def _accumulate_raw_chunk(self, hdr: dict):
        """Reassemble multi-chunk raw burst."""
        seq         = hdr["seq"]
        chunk_index = hdr["chunk_index"]
        sample_count = hdr["sample_count"]

        if seq not in self._raw_chunks:
            self._raw_chunks[seq]       = {}
            self._raw_sample_count[seq] = sample_count

        self._raw_chunks[seq][chunk_index] = hdr["payload"]

        # Calculate expected chunks: ceil(sample_count / 39)
        samples_per_chunk = (244 - 8) // 6   # 39
        expected_chunks   = (sample_count + samples_per_chunk - 1) // samples_per_chunk

        if len(self._raw_chunks[seq]) >= expected_chunks:
            # All chunks received — reassemble in order
            ordered = [self._raw_chunks[seq][i]
                       for i in sorted(self._raw_chunks[seq])]
            raw_bytes = b"".join(ordered)
            log.debug(f"{self.name}: raw burst seq={seq} complete "
                      f"({len(raw_bytes)} bytes, {sample_count} samples)")
            # Clean up
            del self._raw_chunks[seq]
            del self._raw_sample_count[seq]
            # Send to processor for FFT (optional path — only if SEND_RAW_BURST=1)
            self._handle_raw_burst(raw_bytes)

    def _handle_raw_burst(self, raw_bytes: bytes):
        """Process reassembled raw burst through the full FFT pipeline."""
        from engine_processor import process_burst_raw
        summary = process_burst_raw(
            raw_bytes, self.sensor_id, self._config, self._mqtt
        )
        if summary:
            self._last_vib = summary
            self._store.update_sensor(self.sensor_id, self.name, self.address,
                                      summary, self._last_env)
            self._publish_status(connected=True)
            self._check_alert(summary)

    # ── Legacy burst handler ──────────────────────────────────────────────

    def _handle_legacy(self, data: bytes):
        """Old firmware: accumulate raw bytes until 3072 bytes complete."""
        self._legacy_buf.extend(data)
        if len(self._legacy_buf) >= 512 * 6:
            burst = bytes(self._legacy_buf[:512 * 6])
            self._legacy_buf = bytearray()
            self._handle_raw_burst(burst)

    # ── Publish burst result (new framed path) ────────────────────────────

    def _publish_burst_result(self, time_stats: dict, fft_stats: dict | None):
        """
        Publish all MQTT topics from a decoded stats burst:
          vibration/time_stats   — time-domain features
          vibration/fft_stats    — frequency-domain features (if available)
          vibration/features     — combined compact summary for ML/display
          status                 — overall sensor status
          alert                  — on alarm state change
        """
        from engine_config import ALARMS
        ts_now = int(time.time())

        # ── vibration/time_stats ──────────────────────────────────────────
        self._mqtt.publish(
            topic=self._config.topic(self.sensor_id, "vibration", "time_stats"),
            payload={
                "ts":          ts_now,
                "sensor_id":   self.sensor_id,
                "name":        self.name,
                "seq":         time_stats.get("seq", 0),
                "sample_count": time_stats["sample_count"],
                # RMS per axis
                "rms_x_mg":    time_stats["rms_x_mg"],
                "rms_y_mg":    time_stats["rms_y_mg"],
                "rms_z_mg":    time_stats["rms_z_mg"],
                "rms_x_g":     time_stats["rms_x_g"],
                "rms_y_g":     time_stats["rms_y_g"],
                "rms_z_g":     time_stats["rms_z_g"],
                "vector_rms_g": time_stats["vector_rms_g"],
                # Peak
                "peak_x_g":    time_stats["peak_x_g"],
                "peak_y_g":    time_stats["peak_y_g"],
                "peak_z_g":    time_stats["peak_z_g"],
                # Crest factor
                "crest_x":     time_stats["crest_x"],
                "crest_y":     time_stats["crest_y"],
                "crest_z":     time_stats["crest_z"],
                # Kurtosis (3.0 = Gaussian; >4 = bearing fault signature)
                "kurtosis_x":  time_stats["kurtosis_x"],
                "kurtosis_y":  time_stats["kurtosis_y"],
                "kurtosis_z":  time_stats["kurtosis_z"],
                # Variance
                "variance_x_mg2": time_stats["variance_x_mg2"],
                "variance_y_mg2": time_stats["variance_y_mg2"],
                "variance_z_mg2": time_stats["variance_z_mg2"],
            },
            qos=1,
        )

        # ── vibration/fft_stats ───────────────────────────────────────────
        if fft_stats:
            self._mqtt.publish(
                topic=self._config.topic(self.sensor_id, "vibration", "fft_stats"),
                payload={
                    "ts":        ts_now,
                    "sensor_id": self.sensor_id,
                    "seq":       fft_stats.get("seq", 0),
                    # X axis
                    "x_dominant_hz":  fft_stats["x"]["dominant_hz"],
                    "x_dominant_mag": fft_stats["x"]["dominant_mag"],
                    "x_total_power":  fft_stats["x"]["total_power"],
                    "x_bpfo_energy":  fft_stats["x"]["bpfo_energy"],
                    "x_bpfi_energy":  fft_stats["x"]["bpfi_energy"],
                    "x_bsf_energy":   fft_stats["x"]["bsf_energy"],
                    "x_ftf_energy":   fft_stats["x"]["ftf_energy"],
                    "x_noise_floor":  fft_stats["x"]["noise_floor"],
                    "x_snr_bpfo":     fft_stats["x"]["snr_bpfo"],
                    # Y axis
                    "y_dominant_hz":  fft_stats["y"]["dominant_hz"],
                    "y_bpfo_energy":  fft_stats["y"]["bpfo_energy"],
                    "y_snr_bpfo":     fft_stats["y"]["snr_bpfo"],
                    # Z axis
                    "z_dominant_hz":  fft_stats["z"]["dominant_hz"],
                    "z_bpfo_energy":  fft_stats["z"]["bpfo_energy"],
                    "z_snr_bpfo":     fft_stats["z"]["snr_bpfo"],
                },
                qos=1,
            )

        # ── vibration/features — compact summary for ML/display ───────────
        vib_rms  = time_stats["vector_rms_g"]
        dom_hz   = fft_stats["x"]["dominant_hz"] if fft_stats else 0
        max_kurt = max(time_stats["kurtosis_x"],
                       time_stats["kurtosis_y"],
                       time_stats["kurtosis_z"])
        max_snr_bpfo = max(
            fft_stats["x"]["snr_bpfo"],
            fft_stats["y"]["snr_bpfo"],
            fft_stats["z"]["snr_bpfo"],
        ) if fft_stats else 0.0

        alarm = vib_rms >= ALARMS["vib_rms_alarm"]
        warn  = vib_rms >= ALARMS["vib_rms_warn"]

        self._mqtt.publish(
            topic=self._config.topic(self.sensor_id, "vibration", "features"),
            payload={
                "ts":             ts_now,
                "sensor_id":      self.sensor_id,
                "name":           self.name,
                "seq":            time_stats.get("seq", 0),
                # Primary health indicators
                "vector_rms_g":   vib_rms,
                "dominant_hz":    dom_hz,
                "max_kurtosis":   round(max_kurt, 2),
                "max_snr_bpfo":   round(max_snr_bpfo, 2),
                # Per-axis summary
                "rms_x_g":    time_stats["rms_x_g"],
                "rms_y_g":    time_stats["rms_y_g"],
                "rms_z_g":    time_stats["rms_z_g"],
                "crest_x":    time_stats["crest_x"],
                "crest_y":    time_stats["crest_y"],
                "crest_z":    time_stats["crest_z"],
                "kurtosis_x": time_stats["kurtosis_x"],
                "kurtosis_y": time_stats["kurtosis_y"],
                "kurtosis_z": time_stats["kurtosis_z"],
                # Fault indicators
                "alarm":      alarm,
                "warn":       warn,
                # Fault interpretation guide (for MQTT Explorer display)
                "_notes": {
                    "kurtosis":  "3.0=normal, >4.0=early fault, >10=severe",
                    "snr_bpfo":  ">2.0 suggests outer-race fault",
                    "crest":     "<1.5=smooth, 1.5-3.0=moderate, >3.0=impulsive",
                },
            },
            qos=1,
        )

        # Update live state
        summary = {
            "vib_rms":    vib_rms,
            "vib_peak":   time_stats["peak_x_g"],   # worst-case axis
            "dominant_hz": dom_hz,
            "alarm":      alarm,
            "warn":       warn,
            "kurtosis_x": time_stats["kurtosis_x"],
            "kurtosis_y": time_stats["kurtosis_y"],
            "kurtosis_z": time_stats["kurtosis_z"],
        }
        self._last_vib = summary
        self._store.update_sensor(self.sensor_id, self.name, self.address,
                                  summary, self._last_env)
        self._publish_status(connected=True)
        self._check_alert(summary)

    # ── Shared publish helpers ────────────────────────────────────────────

    def _publish_status(self, connected: bool):
        vib = self._last_vib
        env = self._last_env
        self._mqtt.publish(
            topic=self._config.topic(self.sensor_id, "status"),
            payload={
                "ts":           int(time.time()),
                "sensor_id":    self.sensor_id,
                "name":         self.name,
                "connected":    connected,
                "rssi":         self._store.get_rssi(self.sensor_id),
                "battery":      self._store.get_battery(self.sensor_id),
                # Vibration summary
                "vector_rms_g": vib.get("vib_rms",     0.0),
                "vib_peak_g":   vib.get("vib_peak",    0.0),
                "dominant_hz":  vib.get("dominant_hz", 0.0),
                "kurtosis_x":   vib.get("kurtosis_x",  0.0),
                "kurtosis_y":   vib.get("kurtosis_y",  0.0),
                "kurtosis_z":   vib.get("kurtosis_z",  0.0),
                "alarm":        vib.get("alarm", False),
                "warn":         vib.get("warn",  False),
                # Environment
                "temp_c":       env.get("temp_c",        0.0),
                "humidity":     env.get("humidity",      0.0),
                "pressure_hpa": env.get("pressure_hpa",  0.0),
            },
            qos=0,
            retain=True,
        )

    def _publish_environment(self):
        env = self._last_env
        self._mqtt.publish(
            topic=self._config.topic(self.sensor_id, "environment"),
            payload={
                "ts":           int(time.time()),
                "sensor_id":    self.sensor_id,
                "temp_c":       env.get("temp_c",       0.0),
                "humidity":     env.get("humidity",     0.0),
                "pressure_pa":  env.get("pressure_pa",  0),
                "pressure_hpa": env.get("pressure_hpa", 0.0),
            },
            qos=0,
        )

    def _check_alert(self, summary: dict):
        from engine_config import ALARMS
        alarm = summary.get("alarm", False)
        warn  = summary.get("warn",  False)

        if alarm != self._prev_alarm:
            level = "alarm" if alarm else ("warn" if warn else "ok")
            self._mqtt.publish(
                topic=self._config.topic(self.sensor_id, "alert"),
                payload={
                    "ts":          int(time.time()),
                    "sensor_id":   self.sensor_id,
                    "level":       level,
                    "vector_rms_g": summary["vib_rms"],
                    "threshold_g": ALARMS["vib_rms_alarm"] if alarm
                                   else ALARMS["vib_rms_warn"],
                    "dominant_hz":  summary.get("dominant_hz", 0.0),
                    "kurtosis_x":   summary.get("kurtosis_x",  0.0),
                    "kurtosis_y":   summary.get("kurtosis_y",  0.0),
                    "kurtosis_z":   summary.get("kurtosis_z",  0.0),
                },
                qos=1,
                retain=True,
            )
            log.info(f"{self.name}: alert level={level} rms={summary['vib_rms']:.4f}g")
            self._prev_alarm = alarm

    def publish_disconnected(self):
        self._mqtt.publish(
            topic=self._config.topic(self.sensor_id, "status"),
            payload={
                "ts":        int(time.time()),
                "sensor_id": self.sensor_id,
                "name":      self.name,
                "connected": False,
            },
            qos=0,
            retain=True,
        )


# ── BLE async tasks ───────────────────────────────────────────────────────

async def _connect_and_monitor(address: str, name: str, sensor_id: str,
                                config, store, mqtt_client):
    from bleak import BleakClient
    from engine_config import BURST_DATA_UUID, ENV_DATA_UUID

    session = SensorSession(address, name, sensor_id, config, store, mqtt_client)

    while True:
        try:
            log.info(f"Connecting to {name} ({address})...")
            async with BleakClient(address, timeout=config.BLE["connect_timeout"]) as client:
                log.info(f"Connected: {name}")
                await client.start_notify(BURST_DATA_UUID, session.on_burst)
                await client.start_notify(ENV_DATA_UUID,   session.on_env)
                log.info(f"{name}: subscribed to burst + env")
                while client.is_connected:
                    await asyncio.sleep(1.0)

            session.publish_disconnected()
            log.warning(f"{name}: disconnected — retrying in {config.BLE['retry_delay']}s")

        except asyncio.CancelledError:
            session.publish_disconnected()
            return
        except Exception as e:
            session.publish_disconnected()
            log.warning(f"{name}: error {e} — retrying in {config.BLE['retry_delay']}s")

        await asyncio.sleep(config.BLE["retry_delay"])


async def _scan_loop(config, store, mqtt_client):
    from bleak import BleakScanner

    known = set()

    while True:
        try:
            log.info("Scanning for HVAC-Vibe sensors...")
            devices = await BleakScanner.discover(timeout=config.BLE["scan_interval"])
            for d in devices:
                dname = d.name or ""
                if dname.lower().startswith(config.BLE["device_prefix"].lower()):
                    sensor_id = _sensor_id_from_mac(dname, d.address)
                    if sensor_id not in known:
                        known.add(sensor_id)
                        log.info(f"Discovered: {dname} ({d.address}) → {sensor_id}")
                        asyncio.create_task(
                            _connect_and_monitor(
                                d.address, dname, sensor_id,
                                config, store, mqtt_client
                            )
                        )
        except Exception as e:
            log.error(f"Scan error: {e}")

        await asyncio.sleep(config.BLE["scan_interval"])


# ── Simulation ────────────────────────────────────────────────────────────

_SIM_SENSORS = [
    {"address": "AA:BB:CC:DD:EE:01", "name": "HVAC-Vibe-A1"},
]


def _sim_loop(config, store, mqtt_client):
    """
    Simulation: synthesize PKT_TYPE_TIME_STATS + PKT_TYPE_FFT_STATS packets
    without BLE hardware. Publishes the same MQTT topics as real sensors.
    """
    import math
    log.info("BLE: simulation mode")

    sessions = []
    for s in _SIM_SENSORS:
        sid     = _sensor_id_from_mac(s["name"], s["address"])
        session = SensorSession(
            s["address"], s["name"], sid, config, store, mqtt_client
        )
        sessions.append((s, session, sid))
        log.info(f"Sim sensor: {s['name']} → {sid}")

    seq = 0
    t   = 0.0

    while True:
        time.sleep(10.0)
        t   += 10.0
        seq += 1

        for info, session, sid in sessions:
            # Simulate slowly drifting vibration level
            rms_mg = int(420 + 120 * math.sin(t * 0.07))
            kurt   = int(300 + 50  * math.sin(t * 0.13))   # ×100

            # Build a synthetic time_stats_t packet
            sample_count = 512
            peak_raw     = int(rms_mg * 1.5 / 3.9)         # raw counts
            crest        = int((peak_raw * 3.9 / rms_mg) * 100)
            var_mg2      = rms_mg * rms_mg // 10

            time_stats_payload = struct.pack("<HHHhhhHHHhhhHHHHI",
                rms_mg, int(rms_mg*0.9), int(rms_mg*0.3),   # rms x,y,z
                peak_raw, int(peak_raw*0.9), int(peak_raw*0.3),  # peak x,y,z
                crest, int(crest*0.95), int(crest*0.8),     # crest x,y,z
                kurt, int(kurt*0.98), int(kurt*0.85),        # kurtosis x,y,z
                var_mg2, int(var_mg2*0.8), int(var_mg2*0.1), # variance x,y,z
                0,           # reserved
                sample_count,
            )
            hdr = struct.pack("<BBHHh", PKT_TYPE_TIME_STATS, 0, seq, sample_count, 0)
            session.on_burst(None, hdr + time_stats_payload)

            # Build a synthetic fft_stats_t packet
            dom_hz = 30 + int(5 * math.sin(t * 0.05))
            bpfo   = int(200 + 80 * math.sin(t * 0.11))
            noise  = 50

            def axis_bytes(dom, bpfo_e):
                snr = min(int(bpfo_e / max(noise, 1) * 100), 65535)
                return struct.pack("<HHHHHHHHHH",
                    dom, 1000, 800,   # dom_hz, dom_mag, total_power
                    bpfo_e, int(bpfo_e*0.6), int(bpfo_e*0.4), int(bpfo_e*0.2),  # bpfo,bpfi,bsf,ftf
                    noise, snr, 0     # noise_floor, snr_bpfo, reserved
                )

            fft_payload = (axis_bytes(dom_hz, bpfo) +
                           axis_bytes(dom_hz, int(bpfo*0.8)) +
                           axis_bytes(dom_hz, int(bpfo*0.4)))
            hdr = struct.pack("<BBHHh", PKT_TYPE_FFT_STATS, 0, seq, sample_count, 0)
            session.on_burst(None, hdr + fft_payload)

            # Simulate environment
            session._last_env = {
                "temp_c":      round(24.3 + 0.8 * math.sin(t * 0.05), 2),
                "humidity":    round(52.1 + 1.5 * math.sin(t * 0.03), 2),
                "pressure_pa": 101325,
                "pressure_hpa": 1013.25,
            }
            session._publish_environment()


# ── Public API ────────────────────────────────────────────────────────────

class BLEScanner:
    def __init__(self):
        self._thread = None
        self._loop   = None
        self._stop   = threading.Event()

    def start(self, config, store, mqtt_client):
        if config.sim_mode:
            self._thread = threading.Thread(
                target=_sim_loop,
                args=(config, store, mqtt_client),
                name="ble-sim",
                daemon=True,
            )
        else:
            def _run():
                self._loop = asyncio.new_event_loop()
                asyncio.set_event_loop(self._loop)
                self._loop.run_until_complete(
                    _scan_loop(config, store, mqtt_client)
                )
            self._thread = threading.Thread(
                target=_run,
                name="ble-scanner",
                daemon=True,
            )
        self._thread.start()
        log.info(f"BLE thread started: {self._thread.name}")

    def stop(self):
        self._stop.set()
        if self._loop and not self._loop.is_closed():
            self._loop.call_soon_threadsafe(self._loop.stop)
        log.info("BLE scanner stopped")


ble_scanner = BLEScanner()
