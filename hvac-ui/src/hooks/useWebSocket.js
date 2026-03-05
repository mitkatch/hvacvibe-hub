// hooks/useWebSocket.js
// Connects to display server WebSocket, returns live sensor state.
// Merges incoming updates — never overwrites a good value with zero/empty.

import { useState, useEffect, useRef, useCallback } from 'react'

const WS_URL = '/ws'
const RECONNECT_DELAY = 3000

function isGoodFFT(fft) {
  return fft?.x?.frequencies?.length > 0
}

function isNonZero(val) {
  return val !== undefined && val !== null && val !== 0
}

// Merge new sensor data onto old, keeping last known good values
function mergeSensor(oldS, newS) {
  if (!oldS) return newS
  return {
    ...newS,
    // Keep last good FFT if new one is empty
    fft: isGoodFFT(newS.fft) ? newS.fft : oldS.fft,
    // Keep last non-zero env values
    temp_c:      isNonZero(newS.temp_c)      ? newS.temp_c      : oldS.temp_c,
    humidity:    isNonZero(newS.humidity)    ? newS.humidity    : oldS.humidity,
    pressure:    isNonZero(newS.pressure)    ? newS.pressure    : oldS.pressure,
    vib_peak:    isNonZero(newS.vib_peak)    ? newS.vib_peak    : oldS.vib_peak,
    dominant_hz: isNonZero(newS.dominant_hz) ? newS.dominant_hz : oldS.dominant_hz,
    battery:     isNonZero(newS.battery)     ? newS.battery     : oldS.battery,
    rssi:        newS.rssi !== -99           ? newS.rssi        : oldS.rssi,
  }
}

export function useWebSocket() {
  const [sensors,   setSensors]   = useState([])
  const [connected, setConnected] = useState(false)
  const wsRef    = useRef(null)
  const timerRef = useRef(null)

  const connect = useCallback(() => {
    const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
    const url   = `${proto}://${window.location.host}${WS_URL}`
    const ws    = new WebSocket(url)
    wsRef.current = ws

    ws.onopen = () => {
      setConnected(true)
      console.log('WS connected')
    }

    ws.onmessage = (evt) => {
      try {
        const data = JSON.parse(evt.data)
        if (data.sensors && data.sensors.length > 0 && data.sensors[0].sensor_id) {
          setSensors(prev => {
            return data.sensors.map(newS => {
              const oldS = prev.find(s => s.sensor_id === newS.sensor_id)
              return mergeSensor(oldS, newS)
            })
          })
        }
      } catch (e) {
        console.warn('WS parse error', e)
      }
    }

    ws.onclose = () => {
      setConnected(false)
      console.log(`WS closed — reconnecting in ${RECONNECT_DELAY}ms`)
      timerRef.current = setTimeout(connect, RECONNECT_DELAY)
    }

    ws.onerror = (e) => {
      console.warn('WS error', e)
      ws.close()
    }
  }, [])

  useEffect(() => {
    connect()
    return () => {
      clearTimeout(timerRef.current)
      wsRef.current?.close()
    }
  }, [connect])

  // Keep connection alive
  useEffect(() => {
    if (!connected) return
    const id = setInterval(() => {
      wsRef.current?.readyState === WebSocket.OPEN &&
        wsRef.current.send('ping')
    }, 4000)
    return () => clearInterval(id)
  }, [connected])

  return { sensors, connected }
}
