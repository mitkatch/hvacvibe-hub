// utils/sensor.js — shared sensor utilities

const EMPTY_FFT = {
  x: { frequencies: [], amplitudes: [] },
  y: { frequencies: [], amplitudes: [] },
  z: { frequencies: [], amplitudes: [] },
}

export function safeSensor(s) {
  if (!s) return null
  return {
    ...s,
    vib_rms:     s.vib_rms     ?? 0,
    vib_peak:    s.vib_peak    ?? 0,
    temp_c:      s.temp_c      ?? 0,
    humidity:    s.humidity    ?? 0,
    pressure:    s.pressure    ?? 0,
    dominant_hz: s.dominant_hz ?? 0,
    battery:     s.battery     ?? 0,
    rssi:        s.rssi        ?? -99,
    fft:         s.fft         ?? EMPTY_FFT,
  }
}
