"""
engine_processor.py — FFT and feature extraction from raw vibration bursts.

Takes a 512-sample burst (3-axis int16 from ADXL343) and produces:
  - FFT result per axis  → published to vibration/fft
  - Feature set          → published to vibration/features
  - RMS + peak           → used in status + alert topics

ADXL343 scale: 4 mg/LSB (±16g range, 13-bit)
Sample rate:   1600 Hz  → Nyquist 800 Hz
Burst size:    512 samples → frequency resolution = 1600/512 = 3.125 Hz
"""

import logging
import math
import struct
import time

import numpy as np
from scipy.signal import welch

log = logging.getLogger("engine_processor")

# Must match firmware + engine_config
SAMPLES       = 512
SAMPLE_RATE   = 1600          # Hz
MG_PER_LSB    = 4
G_PER_MG      = 0.001
BYTES_PER_SAMPLE = 6          # 3x int16


def parse_burst(data: bytes) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Parse raw BLE burst bytes into 3 numpy arrays (x, y, z) in g.

    Returns (x_g, y_g, z_g) each shape (512,).
    Raises ValueError if data is too short.
    """
    n = len(data) // BYTES_PER_SAMPLE
    if n == 0:
        raise ValueError(f"Burst too short: {len(data)} bytes")

    raw = np.frombuffer(data[:n * BYTES_PER_SAMPLE], dtype="<i2")
    raw = raw.reshape(n, 3).astype(np.float32)
    scale = MG_PER_LSB * G_PER_MG
    x = raw[:, 0] * scale
    y = raw[:, 1] * scale
    z = raw[:, 2] * scale
    return x, y, z


def compute_fft(axis_g: np.ndarray) -> tuple[list[float], list[float]]:
    """
    Compute one-sided FFT of an axis array.

    Returns (frequencies_hz, amplitudes) as plain Python lists
    suitable for JSON serialization.
    Applies Hann window to reduce spectral leakage.
    """
    n = len(axis_g)
    window = np.hanning(n)
    windowed = axis_g * window
    fft_vals = np.abs(np.fft.rfft(windowed)) * (2.0 / n)
    freqs    = np.fft.rfftfreq(n, d=1.0 / SAMPLE_RATE)

    # Round to 4dp to keep JSON compact
    return (
        [round(float(f), 3) for f in freqs],
        [round(float(a), 5) for a in fft_vals],
    )


def compute_features(x_g, y_g, z_g) -> dict:
    """
    Extract compact feature set (~200 bytes JSON) for ML pipeline.

    Features per axis: rms, peak, crest_factor, dominant_freq, top3_harmonics
    Plus: vector_rms (magnitude across all 3 axes)
    """
    features = {}
    axes = {"x": x_g, "y": y_g, "z": z_g}

    for name, sig in axes.items():
        rms    = float(np.sqrt(np.mean(sig ** 2)))
        peak   = float(np.max(np.abs(sig)))
        crest  = round(peak / rms, 3) if rms > 1e-6 else 0.0
        freqs, amps = compute_fft(sig)
        amp_arr     = np.array(amps)
        dom_idx     = int(np.argmax(amp_arr))
        dom_freq    = freqs[dom_idx]

        # Top 3 harmonic frequencies above 1 Hz (skip DC)
        nondc = [(freqs[i], amps[i]) for i in range(1, len(freqs))]
        top3  = sorted(nondc, key=lambda t: t[1], reverse=True)[:3]

        features[name] = {
            "rms":          round(rms, 5),
            "peak":         round(peak, 5),
            "crest_factor": crest,
            "dominant_hz":  round(dom_freq, 3),
            "top3_hz":      [round(f, 2) for f, _ in top3],
        }

    # Vector RMS: magnitude of combined 3-axis signal
    mag = np.sqrt(x_g**2 + y_g**2 + z_g**2)
    features["vector_rms"]  = round(float(np.sqrt(np.mean(mag**2))), 5)
    features["vector_peak"] = round(float(np.max(mag)), 5)

    return features


def process_burst(data: bytes, sensor_id: str, config, mqtt_client) -> dict:
    """
    Full pipeline: raw bytes → parse → FFT → features → MQTT publish.

    Returns a summary dict for status/alert decisions:
      { rms, peak, dominant_hz, alarm, warn }
    """
    from engine_config import ALARMS

    try:
        x_g, y_g, z_g = parse_burst(data)
    except ValueError as e:
        log.warning(f"{sensor_id} burst parse error: {e}")
        return {}

    ts = int(time.time())

    # ── FFT — publish one message per axis ────────────────────
    for axis_name, sig in [("x", x_g), ("y", y_g), ("z", z_g)]:
        freqs, amps = compute_fft(sig)
        mqtt_client.publish(
            topic=config.topic(sensor_id, "vibration", "fft"),
            payload={
                "ts":         ts,
                "axis":       axis_name,
                "frequencies": freqs,
                "amplitudes":  amps,
                "sample_rate": SAMPLE_RATE,
                "n_samples":   len(sig),
            },
            qos=0,
        )

    # ── Features — one message, all axes ─────────────────────
    features = compute_features(x_g, y_g, z_g)
    features["ts"]        = ts
    features["sensor_id"] = sensor_id
    mqtt_client.publish(
        topic=config.topic(sensor_id, "vibration", "features"),
        payload=features,
        qos=1,    # features are valuable — use QoS 1
    )

    # ── Summary for caller ────────────────────────────────────
    vib_rms  = features["vector_rms"]
    vib_peak = features["vector_peak"]
    dom_hz   = features["x"]["dominant_hz"]

    return {
        "vib_rms":    vib_rms,
        "vib_peak":   vib_peak,
        "dominant_hz": dom_hz,
        "alarm":      vib_rms >= ALARMS["vib_rms_alarm"],
        "warn":       vib_rms >= ALARMS["vib_rms_warn"],
    }
