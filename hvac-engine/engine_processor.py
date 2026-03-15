"""
engine_processor.py — FFT and feature extraction from raw vibration bursts.

Two entry points:
  process_burst_raw(data, ...)  — legacy path: raw 3072-byte int16 burst
                                   Runs full numpy FFT on the Pi.
                                   Used when SEND_RAW_BURST=1 in firmware,
                                   or when talking to old firmware.

  process_stats_packet(...)     — new path: pre-computed stats arrived
                                   over BLE. The Pi only adds Pi-side FFT
                                   (full spectrum for display) on top.
                                   Called by engine_ble.py directly.

ADXL343 scale: 3.9 mg/LSB (full-res ±16g mode, matches firmware)
Sample rate:   1600 Hz → Nyquist 800 Hz
Burst size:    512 samples → frequency resolution = 3.125 Hz/bin
"""

import logging
import time

import numpy as np

log = logging.getLogger("engine_processor")

SAMPLES          = 512
SAMPLE_RATE      = 1600
MG_PER_LSB       = 3.9        # firmware full-res ±16g: 3.9 mg/LSB (not 4)
G_PER_MG         = 0.001
BYTES_PER_SAMPLE = 6


# ── Parse raw bytes ───────────────────────────────────────────────────────

def parse_burst(data: bytes) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Parse raw BLE burst bytes into 3 numpy arrays (x, y, z) in g.
    Handles both 512-sample (3072 byte) and shorter bursts.
    """
    n = len(data) // BYTES_PER_SAMPLE
    if n == 0:
        raise ValueError(f"Burst too short: {len(data)} bytes")

    raw = np.frombuffer(data[:n * BYTES_PER_SAMPLE], dtype="<i2")
    raw = raw.reshape(n, 3).astype(np.float32)
    scale = MG_PER_LSB * G_PER_MG   # counts → g
    return raw[:, 0] * scale, raw[:, 1] * scale, raw[:, 2] * scale


# ── FFT computation ───────────────────────────────────────────────────────

def compute_fft(axis_g: np.ndarray) -> tuple[list[float], list[float]]:
    """
    Compute one-sided FFT with Hann window.
    Returns (frequencies_hz, amplitudes) as Python lists for JSON.
    """
    n      = len(axis_g)
    window = np.hanning(n)
    fft_v  = np.abs(np.fft.rfft(axis_g * window)) * (2.0 / n)
    freqs  = np.fft.rfftfreq(n, d=1.0 / SAMPLE_RATE)
    return (
        [round(float(f), 3) for f in freqs],
        [round(float(a), 5) for a in fft_v],
    )


def compute_full_features(x_g, y_g, z_g) -> dict:
    """
    Full feature extraction from raw g arrays.
    Returns rich feature dict suitable for MQTT.
    """
    features = {}
    axes = {"x": x_g, "y": y_g, "z": z_g}

    for name, sig in axes.items():
        rms   = float(np.sqrt(np.mean(sig ** 2)))
        peak  = float(np.max(np.abs(sig)))
        crest = round(peak / rms, 3) if rms > 1e-6 else 0.0

        # Kurtosis: E[x^4] / E[x^2]^2
        mu4   = float(np.mean(sig ** 4))
        sigma4 = (float(np.mean(sig ** 2))) ** 2
        kurt  = round(mu4 / sigma4, 3) if sigma4 > 1e-12 else 0.0

        freqs, amps = compute_fft(sig)
        amp_arr     = np.array(amps)
        dom_idx     = int(np.argmax(amp_arr[1:]) + 1)   # skip DC
        dom_freq    = freqs[dom_idx]
        nondc = [(freqs[i], amps[i]) for i in range(1, len(freqs))]
        top3  = sorted(nondc, key=lambda t: t[1], reverse=True)[:3]

        features[name] = {
            "rms_g":        round(rms, 5),
            "peak_g":       round(peak, 5),
            "crest_factor": crest,
            "kurtosis":     kurt,
            "dominant_hz":  round(dom_freq, 3),
            "top3_hz":      [round(f, 2) for f, _ in top3],
        }

    mag = np.sqrt(x_g**2 + y_g**2 + z_g**2)
    features["vector_rms_g"]  = round(float(np.sqrt(np.mean(mag**2))), 5)
    features["vector_peak_g"] = round(float(np.max(mag)), 5)
    return features


# ── Raw burst pipeline (legacy / SEND_RAW_BURST=1) ────────────────────────

def process_burst_raw(data: bytes, sensor_id: str, config, mqtt_client) -> dict:
    """
    Full pipeline for raw burst bytes.
    Parses → FFT per axis (published) → features (published) → returns summary.
    Used when firmware sends PKT_TYPE_RAW or when talking to old firmware.
    """
    from engine_config import ALARMS

    try:
        x_g, y_g, z_g = parse_burst(data)
    except ValueError as e:
        log.warning(f"{sensor_id} burst parse error: {e}")
        return {}

    ts = int(time.time())

    # ── Full FFT spectrum — one message per axis for display ──────────────
    for axis_name, sig in [("x", x_g), ("y", y_g), ("z", z_g)]:
        freqs, amps = compute_fft(sig)
        mqtt_client.publish(
            topic=config.topic(sensor_id, "vibration", "fft"),
            payload={
                "ts":          ts,
                "sensor_id":   sensor_id,
                "axis":        axis_name,
                "frequencies": freqs,
                "amplitudes":  amps,
                "sample_rate": SAMPLE_RATE,
                "n_samples":   len(sig),
                "freq_resolution_hz": round(SAMPLE_RATE / len(sig), 4),
            },
            qos=0,
        )

    # ── Rich features — all axes ──────────────────────────────────────────
    features = compute_full_features(x_g, y_g, z_g)
    features["ts"]        = ts
    features["sensor_id"] = sensor_id

    from engine_config import ALARMS
    vib_rms  = features["vector_rms_g"]
    vib_peak = features["vector_peak_g"]
    dom_hz   = features["x"]["dominant_hz"]
    alarm    = vib_rms >= ALARMS["vib_rms_alarm"]
    warn     = vib_rms >= ALARMS["vib_rms_warn"]

    features["alarm"]      = alarm
    features["warn"]       = warn
    features["dominant_hz"] = dom_hz
    features["_notes"] = {
        "kurtosis":  "3.0=normal, >4.0=early fault, >10=severe",
        "crest":     "<1.5=smooth, 1.5-3.0=moderate, >3.0=impulsive",
    }

    mqtt_client.publish(
        topic=config.topic(sensor_id, "vibration", "features"),
        payload=features,
        qos=1,
    )

    return {
        "vib_rms":    vib_rms,
        "vib_peak":   vib_peak,
        "dominant_hz": dom_hz,
        "alarm":      alarm,
        "warn":       warn,
    }


# ── Legacy shim — kept so old call sites still work ──────────────────────

def process_burst(data: bytes, sensor_id: str, config, mqtt_client) -> dict:
    """Backward-compatible alias for process_burst_raw."""
    return process_burst_raw(data, sensor_id, config, mqtt_client)
