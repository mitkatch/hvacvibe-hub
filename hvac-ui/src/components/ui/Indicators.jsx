// components/ui/Indicators.jsx
// Small reusable indicator components matching pygame originals.

export function ConnDot({ connected, size = 10 }) {
  return (
    <span style={{
      display:      'inline-block',
      width:        size,
      height:       size,
      borderRadius: '50%',
      background:   connected ? 'var(--green)' : 'var(--red)',
      boxShadow:    connected
        ? '0 0 6px var(--green)'
        : '0 0 6px var(--red)',
      flexShrink: 0,
    }} />
  )
}

export function SignalBars({ rssi }) {
  const bars = rssi >= -60 ? 4 : rssi >= -70 ? 3 : rssi >= -80 ? 2 : rssi >= -90 ? 1 : 0
  return (
    <span style={{ display: 'inline-flex', alignItems: 'flex-end', gap: 2, height: 14 }}>
      {[1,2,3,4].map(i => (
        <span key={i} style={{
          width:        5,
          height:       i * 3 + 2,
          borderRadius: 1,
          background:   i <= bars ? 'var(--accent)' : 'var(--divider)',
        }} />
      ))}
    </span>
  )
}

export function Battery({ pct, w = 36, h = 14 }) {
  const color = pct > 50 ? 'var(--green)' : pct > 20 ? 'var(--yellow)' : 'var(--red)'
  const fill  = Math.max(2, Math.round((w - 6) * pct / 100))
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 1 }}>
      <span style={{
        position:     'relative',
        display:      'inline-block',
        width:         w,
        height:        h,
        border:       `1px solid var(--edge)`,
        borderRadius:  2,
        background:   'var(--bg)',
      }}>
        <span style={{
          position:     'absolute',
          left:          2,
          top:           2,
          width:         fill,
          height:        h - 6,
          background:    color,
          borderRadius:  1,
          transition:   'width 0.5s',
        }} />
      </span>
      <span style={{
        width:        3,
        height:       h - 6,
        background:  'var(--edge)',
        borderRadius: 1,
      }} />
    </span>
  )
}

export function StatusBadge({ alarm, warn, connected }) {
  if (!connected) return (
    <span style={{ color: 'var(--grey)', fontSize: 11, fontFamily: 'var(--font-mono)' }}>
      OFFLINE
    </span>
  )
  if (alarm) return (
    <span style={{
      background:   'var(--red)',
      color:        '#fff',
      fontSize:      11,
      padding:      '1px 6px',
      borderRadius:  2,
      fontFamily:   'var(--font-mono)',
      letterSpacing: 1,
      animation:    'pulse 1s ease-in-out infinite',
    }}>
      ALARM
    </span>
  )
  if (warn) return (
    <span style={{
      background:   'var(--warn)',
      color:        '#fff',
      fontSize:      11,
      padding:      '1px 6px',
      borderRadius:  2,
      fontFamily:   'var(--font-mono)',
    }}>
      WARN
    </span>
  )
  return (
    <span style={{ color: 'var(--green)', fontSize: 11, fontFamily: 'var(--font-mono)' }}>
      OK
    </span>
  )
}

export function ValueBlock({ label, value, unit, color = 'var(--white)' }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
      <span style={{ color: 'var(--grey)', fontSize: 10, fontFamily: 'var(--font-mono)' }}>
        {label}
      </span>
      <span style={{ color, fontSize: 15, fontWeight: 600, lineHeight: 1 }}>
        {value}
        <span style={{ fontSize: 10, color: 'var(--grey)', marginLeft: 2 }}>{unit}</span>
      </span>
    </div>
  )
}
