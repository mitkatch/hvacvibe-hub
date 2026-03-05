// screens/BalloonScreen.jsx
// Screensaver — one balloon per sensor, rises continuously.
// CSS animation port of BalloonScreenOne pygame.
// Color by status: green=ok, yellow=warn, red=alarm, grey=offline

import { useEffect, useRef } from 'react'

const STATUS_COLORS = {
  ok:    { body: '#1eb464', glow: '#1eb46444', string: '#3c8c58' },
  warn:  { body: '#dc8c14', glow: '#dc8c1444', string: '#b46a0a' },
  alarm: { body: '#c82d2d', glow: '#c82d2d66', string: '#8c1e1e' },
  disc:  { body: '#505a69', glow: '#505a6922', string: '#3c4450' },
}

function sensorStatus(s) {
  if (!s.connected) return 'disc'
  if (s.alarm)      return 'alarm'
  if (s.warn)       return 'warn'
  return 'ok'
}

function BalloonSVG({ color, size }) {
  return (
    <svg width={size} height={size * 1.35} viewBox="0 0 100 135" fill="none">
      {/* Shadow */}
      <ellipse cx="54" cy="100" rx="28" ry="8" fill="rgba(0,0,0,0.3)" />
      {/* Body */}
      <ellipse cx="50" cy="50" rx="38" ry="46" fill={color.body} />
      {/* Highlight */}
      <ellipse cx="36" cy="32" rx="10" ry="14" fill="rgba(255,255,255,0.25)"
               transform="rotate(-20 36 32)" />
      {/* Knot */}
      <ellipse cx="50" cy="97" rx="5" ry="4" fill={color.string} />
      {/* Tie */}
      <path d="M46 100 Q50 106 54 100" stroke={color.string} strokeWidth="2" fill="none" />
    </svg>
  )
}

function Balloon({ sensor, index, total }) {
  const status = sensorStatus(sensor)
  const color  = STATUS_COLORS[status]
  const size   = 60 + (sensor.vib_rms / 2.0) * 30  // size scales with RMS
  const dur    = 6 + index * 1.5   // staggered speeds
  const delay  = -(index * (dur / total))  // stagger start positions
  const left   = `${10 + (index / Math.max(total - 1, 1)) * 80}%`

  return (
    <div style={{
      position:  'absolute',
      left,
      bottom:    0,
      transform: 'translateX(-50%)',
      animation: `riseAndSway ${dur}s ${delay}s linear infinite`,
      filter:    `drop-shadow(0 0 8px ${color.glow})`,
    }}>
      <BalloonSVG color={color} size={size} />

      {/* String */}
      <svg width="4" height="70" style={{ display: 'block', margin: '0 auto' }}>
        <path d={`M2 0 Q${2 + Math.sin(index) * 8} 35 2 70`}
              stroke={color.string} strokeWidth="1.5" fill="none" />
      </svg>

      {/* Label */}
      <div style={{
        textAlign:   'center',
        color:       'var(--white)',
        fontSize:     11,
        fontFamily:  'var(--font-mono)',
        whiteSpace:  'nowrap',
      }}>
        {sensor.name}
      </div>
      <div style={{
        textAlign:   'center',
        color:        color.body,
        fontSize:     13,
        fontWeight:   600,
        fontFamily:  'var(--font-mono)',
      }}>
        {sensor.vib_rms.toFixed(3)}g
      </div>

      {/* Alarm badge */}
      {sensor.alarm && (
        <div style={{
          position:    'absolute',
          top:          size * 0.3,
          left:        '50%',
          transform:   'translateX(-50%)',
          color:       '#ff3c3c',
          fontSize:     11,
          fontFamily:  'var(--font-mono)',
          fontWeight:   700,
          animation:   'pulse 1s ease-in-out infinite',
        }}>
          ALARM
        </div>
      )}
    </div>
  )
}

export function BalloonScreen({ sensors }) {
  return (
    <div style={{
      width:      '100%',
      height:     '100%',
      background: 'var(--bg)',
      position:   'relative',
      overflow:   'hidden',
    }}>
      {/* Stars background */}
      <div style={{
        position:   'absolute', inset: 0,
        background: 'radial-gradient(ellipse at 20% 50%, #0a0f1a 0%, var(--bg) 100%)',
      }} />

      {sensors.length === 0 ? (
        <div style={{
          position:       'absolute', inset: 0,
          display:        'flex',
          alignItems:     'center',
          justifyContent: 'center',
          color:          'var(--grey)',
          fontFamily:     'var(--font-mono)',
        }}>
          No sensors
        </div>
      ) : (
        sensors.map((s, i) => (
          <Balloon key={s.sensor_id} sensor={s} index={i} total={sensors.length} />
        ))
      )}

      {/* Clock */}
      <div style={{
        position:   'absolute',
        top:         8,
        right:       10,
        color:      'var(--grey)',
        fontSize:    11,
        fontFamily: 'var(--font-mono)',
      }}>
        {new Date().toLocaleTimeString()}
      </div>

      {/* Hint */}
      <div style={{
        position:   'absolute',
        bottom:      6,
        left:       '50%',
        transform:  'translateX(-50%)',
        color:      'rgba(255,255,255,0.12)',
        fontSize:    10,
        fontFamily: 'var(--font-mono)',
      }}>
        [ BTN1 ] return to dashboard
      </div>
    </div>
  )
}
