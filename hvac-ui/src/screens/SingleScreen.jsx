// screens/SingleScreen.jsx
import { useHistory } from '../hooks/useHistory'
import { ConnDot, SignalBars, Battery, StatusBadge, ValueBlock } from '../components/ui/Indicators'
import { DailyChart } from '../components/charts/DailyChart'
import { FFTChart }   from '../components/charts/FFTChart'
import { safeSensor } from '../utils/sensor'

function alarmColor(s) {
  if (s.alarm) return 'var(--red)'
  if (s.warn)  return 'var(--warn)'
  return 'var(--accent)'
}

export function SingleScreen({ sensor, onBack }) {
  const s = safeSensor(sensor)
  const { history } = useHistory(s.sensor_id)

  return (
    <div style={{ width: '100%', height: '100%', display: 'flex',
                  flexDirection: 'column', background: 'var(--bg)', overflow: 'hidden' }}>
      {/* Header */}
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '6px 12px', background: 'var(--panel)',
        borderBottom: '1px solid var(--accent)', flexShrink: 0,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <button onClick={onBack} style={{
            background: 'transparent', border: '1px solid var(--edge)',
            color: 'var(--grey)', borderRadius: 3, padding: '2px 8px',
            cursor: 'pointer', fontSize: 12, fontFamily: 'var(--font-mono)',
          }}>
            ← BACK
          </button>
          <ConnDot connected={s.connected} />
          <span style={{ color: alarmColor(s), fontSize: 16, fontWeight: 700, letterSpacing: 1 }}>
            {s.name}
          </span>
          <StatusBadge alarm={s.alarm} warn={s.warn} connected={s.connected} />
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <SignalBars rssi={s.rssi} />
          <Battery pct={s.battery} />
          <span style={{ color: 'var(--grey)', fontSize: 11, fontFamily: 'var(--font-mono)' }}>
            {new Date().toLocaleTimeString()}
          </span>
        </div>
      </div>

      {/* Value tiles */}
      <div style={{
        display: 'flex', gap: 8, padding: '8px 12px', flexWrap: 'wrap',
        background: 'var(--panel)', borderBottom: '1px solid var(--divider)', flexShrink: 0,
      }}>
        <ValueBlock label="RMS"  value={s.vib_rms.toFixed(3)}     unit="g"   color={alarmColor(s)} />
        <div style={{ width: 1, background: 'var(--divider)' }} />
        <ValueBlock label="PEAK" value={s.vib_peak.toFixed(3)}    unit="g"   color="var(--yellow)" />
        <div style={{ width: 1, background: 'var(--divider)' }} />
        <ValueBlock label="TEMP" value={s.temp_c.toFixed(1)}      unit="°C"  color="var(--yellow)" />
        <div style={{ width: 1, background: 'var(--divider)' }} />
        <ValueBlock label="HUM"  value={s.humidity.toFixed(1)}    unit="%"   color="var(--accent)" />
        <div style={{ width: 1, background: 'var(--divider)' }} />
        <ValueBlock label="PRES" value={s.pressure}               unit="hPa" color="var(--grey)" />
        <div style={{ width: 1, background: 'var(--divider)' }} />
        <ValueBlock label="DOM"  value={s.dominant_hz.toFixed(1)} unit="Hz"  color="var(--chart-line)" />
      </div>

      {/* Charts */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column',
                    padding: '8px 12px', gap: 8, overflow: 'hidden' }}>
        <div style={{ background: 'var(--panel)', border: '1px solid var(--edge)',
                      borderRadius: 4, padding: '6px 8px', flexShrink: 0 }}>
          <div style={{ color: 'var(--grey)', fontSize: 10, fontFamily: 'var(--font-mono)',
                        marginBottom: 4, letterSpacing: 1 }}>FFT SPECTRUM</div>
          <FFTChart fft={s.fft} height={150} />
        </div>
        <div style={{ flex: 1, background: 'var(--panel)', border: '1px solid var(--edge)',
                      borderRadius: 4, padding: '6px 8px', minHeight: 140 }}>
          <div style={{ color: 'var(--grey)', fontSize: 10, fontFamily: 'var(--font-mono)',
                        marginBottom: 4, letterSpacing: 1 }}>VIB RMS — TODAY</div>
          <DailyChart history={history} height={120} />
        </div>
      </div>
    </div>
  )
}
