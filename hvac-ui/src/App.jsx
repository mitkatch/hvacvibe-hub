// App.jsx — HVAC-Vibe main app
// Manages screen state: overview ↔ detail ↔ screensaver
// BTN1 = spacebar (keyboard) or touch the clock area (touch)

import { useState, useEffect, useCallback } from 'react'
import { useWebSocket }    from './hooks/useWebSocket'
import { OverviewScreen }  from './screens/OverviewScreen'
import { SingleScreen }    from './screens/SingleScreen'
import { BalloonScreen }   from './screens/BalloonScreen'

const SCREENS = { OVERVIEW: 'overview', DETAIL: 'detail', BALLOON: 'balloon' }

// CSS keyframes injected once
const GLOBAL_CSS = `
  @keyframes riseAndSway {
    0%   { transform: translateX(-50%) translateY(0)    rotate(0deg);   opacity: 0; }
    5%   { opacity: 1; }
    48%  { transform: translateX(calc(-50% + 18px)) translateY(-110vh) rotate(3deg);  }
    52%  { transform: translateX(calc(-50% - 18px)) translateY(-115vh) rotate(-3deg); }
    95%  { opacity: 1; }
    100% { transform: translateX(-50%) translateY(-120vh) rotate(0deg); opacity: 0; }
  }
  @keyframes pulse {
    0%, 100% { opacity: 1;   transform: translateX(-50%) scale(1);    }
    50%       { opacity: 0.6; transform: translateX(-50%) scale(1.08); }
  }
  @keyframes bounce {
    0%, 80%, 100% { transform: scale(0.8); opacity: 0.5; }
    40%            { transform: scale(1.2); opacity: 1;   }
  }
`

export default function App() {
  const { sensors, connected } = useWebSocket()
  const [screen,   setScreen]  = useState(SCREENS.OVERVIEW)
  const [selected, setSelected] = useState(null)   // sensor for detail view
  const [clock,    setClock]    = useState(new Date().toLocaleTimeString())

  // Clock tick
  useEffect(() => {
    const id = setInterval(() => setClock(new Date().toLocaleTimeString()), 1000)
    return () => clearInterval(id)
  }, [])

  // Keep selected sensor fresh from live data
  const selectedSensor = selected
    ? sensors.find(s => s.sensor_id === selected) ?? null
    : null

  // BTN1 — toggle screensaver / back to overview
  const handleBtn1 = useCallback(() => {
    setScreen(s => s === SCREENS.BALLOON ? SCREENS.OVERVIEW : SCREENS.BALLOON)
  }, [])

  // Keyboard: Space = BTN1, Escape = back
  useEffect(() => {
    const handler = e => {
      if (e.key === ' ')        { e.preventDefault(); handleBtn1() }
      if (e.key === 'Escape')   { setScreen(SCREENS.OVERVIEW); setSelected(null) }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [handleBtn1])

  const goDetail = useCallback((sensor) => {
    setSelected(sensor.sensor_id)
    setScreen(SCREENS.DETAIL)
  }, [])

  const goBack = useCallback(() => {
    setScreen(SCREENS.OVERVIEW)
    setSelected(null)
  }, [])

  return (
    <>
      {/* Inject global keyframes */}
      <style>{GLOBAL_CSS}</style>

      {/* Connection indicator */}
      {!connected && (
        <div style={{
          position:       'fixed',
          top:             0,
          left:            0,
          right:           0,
          zIndex:          100,
          background:     'var(--red)',
          color:          '#fff',
          fontSize:        11,
          fontFamily:     'var(--font-mono)',
          textAlign:      'center',
          padding:        '2px 0',
          letterSpacing:   1,
        }}>
          ⚠ DISCONNECTED — reconnecting...
        </div>
      )}

      {/* Screen router */}
      <div style={{ width: '100%', height: '100%' }}>
        {screen === SCREENS.BALLOON && (
          <BalloonScreen sensors={sensors} />
        )}

        {screen === SCREENS.DETAIL && selectedSensor && (
          <SingleScreen sensor={selectedSensor} onBack={goBack} />
        )}

        {screen === SCREENS.DETAIL && !selectedSensor && (
          // Sensor disappeared — fall back
          <OverviewScreen sensors={sensors} onSelect={goDetail} />
        )}

        {screen === SCREENS.OVERVIEW && (
          <OverviewScreen sensors={sensors} onSelect={goDetail} />
        )}
      </div>
    </>
  )
}
