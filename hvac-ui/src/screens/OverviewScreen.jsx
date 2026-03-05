// screens/OverviewScreen.jsx
import { ConnDot, SignalBars, Battery, StatusBadge, ValueBlock } from '../components/ui/Indicators'
import { DailyChart }  from '../components/charts/DailyChart'
import { FFTChart }    from '../components/charts/FFTChart'
import { useHistory }  from '../hooks/useHistory'
import { safeSensor }  from '../utils/sensor'

function alarmColor(s) {
  if (s.alarm) return 'var(--red)'
  if (s.warn)  return 'var(--warn)'
  return 'var(--accent)'
}

function Header({ count, time }) {
  return (
    <div style={{
      display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      padding: '5px 10px', background: 'var(--panel)',
      borderBottom: '1px solid var(--accent)', flexShrink: 0,
    }}>
      <span style={{ color: 'var(--accent)', fontWeight: 700, letterSpacing: 1 }}>
        HVAC-Vibe
        <span style={{ color: 'var(--grey)', fontWeight: 400, fontSize: 11, marginLeft: 8 }}>
          {count} sensor{count !== 1 ? 's' : ''}
        </span>
      </span>
      <span style={{ color: 'var(--grey)', fontSize: 11, fontFamily: 'var(--font-mono)' }}>
        {time}
      </span>
    </div>
  )
}

function SingleFull({ sensor, onSelect }) {
  const s = safeSensor(sensor)
  const { history } = useHistory(s.sensor_id)
  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column',
                  padding: '8px 10px', gap: 8, overflow: 'hidden', cursor: 'pointer' }}
         onClick={() => onSelect(sensor)}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap',
                    background: 'var(--panel)', padding: '6px 10px', flexShrink: 0,
                    borderRadius: 4, border: '1px solid var(--edge)' }}>
        <ConnDot connected={s.connected} />
        <span style={{ color: alarmColor(s), fontWeight: 700, flex: 1 }}>{s.name}</span>
        <StatusBadge alarm={s.alarm} warn={s.warn} connected={s.connected} />
        <ValueBlock label="RMS"  value={s.vib_rms.toFixed(3)}  unit="g"  color={alarmColor(s)} />
        <ValueBlock label="PEAK" value={s.vib_peak.toFixed(3)} unit="g"  color="var(--yellow)" />
        <ValueBlock label="TEMP" value={s.temp_c.toFixed(1)}   unit="°C" color="var(--yellow)" />
        <ValueBlock label="HUM"  value={s.humidity.toFixed(1)} unit="%"  color="var(--accent)" />
        <SignalBars rssi={s.rssi} />
        <Battery pct={s.battery} />
      </div>
      <div style={{ background: 'var(--panel)', border: '1px solid var(--edge)',
                    borderRadius: 4, padding: '6px 8px', flexShrink: 0 }}>
        <div style={{ color: 'var(--grey)', fontSize: 10, fontFamily: 'var(--font-mono)',
                      marginBottom: 4 }}>FFT SPECTRUM</div>
        <FFTChart fft={s.fft} height={140} />
      </div>
      <div style={{ flex: 1, background: 'var(--panel)', border: '1px solid var(--edge)',
                    borderRadius: 4, padding: '6px 8px', minHeight: 140 }}>
        <div style={{ color: 'var(--grey)', fontSize: 10, fontFamily: 'var(--font-mono)',
                      marginBottom: 4 }}>VIB RMS — TODAY</div>
        <DailyChart history={history} height={110} />
      </div>
    </div>
  )
}

function DualPane({ sensor, onSelect }) {
  const s = safeSensor(sensor)
  const { history } = useHistory(s.sensor_id)
  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column',
                  padding: '6px 8px', gap: 6, borderRight: '1px solid var(--divider)',
                  cursor: 'pointer', overflow: 'hidden' }}
         onClick={() => onSelect(sensor)}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        <ConnDot connected={s.connected} size={8} />
        <span style={{ color: alarmColor(s), fontWeight: 700, fontSize: 13, flex: 1 }}>{s.name}</span>
        <StatusBadge alarm={s.alarm} warn={s.warn} connected={s.connected} />
      </div>
      <div style={{ display: 'flex', gap: 8 }}>
        <ValueBlock label="RMS"  value={s.vib_rms.toFixed(3)}  unit="g"  color={alarmColor(s)} />
        <ValueBlock label="PEAK" value={s.vib_peak.toFixed(3)} unit="g"  color="var(--yellow)" />
        <ValueBlock label="TEMP" value={s.temp_c.toFixed(1)}   unit="°C" color="var(--yellow)" />
        <ValueBlock label="HUM"  value={s.humidity.toFixed(1)} unit="%"  color="var(--accent)" />
      </div>
      <FFTChart fft={s.fft} height={110} />
      <div style={{ minHeight: 90 }}>
        <DailyChart history={history} height={90} />
      </div>
    </div>
  )
}

function GridCell({ sensor, onSelect }) {
  const s = safeSensor(sensor)
  const { history } = useHistory(s.sensor_id)
  return (
    <div style={{
      display: 'flex', flexDirection: 'column', padding: '6px 8px', gap: 4,
      border: `1px solid ${s.alarm ? 'var(--red)' : 'var(--divider)'}`,
      borderRadius: 4, cursor: 'pointer', overflow: 'hidden',
      background: s.alarm ? '#1a0808' : 'var(--panel)',
    }}
         onClick={() => onSelect(sensor)}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        <ConnDot connected={s.connected} size={8} />
        <span style={{ color: alarmColor(s), fontWeight: 700, fontSize: 12, flex: 1 }}>{s.name}</span>
        <StatusBadge alarm={s.alarm} warn={s.warn} connected={s.connected} />
      </div>
      <div style={{ display: 'flex', gap: 8 }}>
        <ValueBlock label="RMS"  value={s.vib_rms.toFixed(3)}  unit="g" color={alarmColor(s)} />
        <ValueBlock label="PEAK" value={s.vib_peak.toFixed(2)} unit="g" color="var(--yellow)" />
      </div>
      <div style={{ display: 'flex', gap: 8 }}>
        <ValueBlock label="TEMP" value={s.temp_c.toFixed(1)}   unit="°C" color="var(--yellow)" />
        <ValueBlock label="HUM"  value={s.humidity.toFixed(1)} unit="%"  color="var(--accent)" />
      </div>
      <div style={{ minHeight: 70 }}>
        <DailyChart history={history} height={70} />
      </div>
    </div>
  )
}

function ListRow({ sensor, onSelect }) {
  const s = safeSensor(sensor)
  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 10,
      padding: '6px 10px', borderBottom: '1px solid var(--divider)',
      cursor: 'pointer', background: s.alarm ? '#1a0808' : 'transparent',
    }}
         onClick={() => onSelect(sensor)}>
      <ConnDot connected={s.connected} size={8} />
      <span style={{ color: alarmColor(s), fontWeight: 600, width: 100 }}>{s.name}</span>
      <ValueBlock label="RMS"  value={s.vib_rms.toFixed(3)}  unit="g"  color={alarmColor(s)} />
      <ValueBlock label="TEMP" value={s.temp_c.toFixed(1)}   unit="°C" color="var(--yellow)" />
      <ValueBlock label="HUM"  value={s.humidity.toFixed(1)} unit="%"  color="var(--accent)" />
      <div style={{ flex: 1 }} />
      <SignalBars rssi={s.rssi} />
      <StatusBadge alarm={s.alarm} warn={s.warn} connected={s.connected} />
    </div>
  )
}

function Waiting() {
  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column',
                  alignItems: 'center', justifyContent: 'center', gap: 12 }}>
      <div style={{ color: 'var(--grey)', fontSize: 14, fontFamily: 'var(--font-mono)' }}>
        Scanning for sensors...
      </div>
      <div style={{ display: 'flex', gap: 6 }}>
        {[0,1,2].map(i => (
          <div key={i} style={{
            width: 8, height: 8, borderRadius: '50%', background: 'var(--accent)',
            animation: `bounce 1.2s ease-in-out ${i * 0.2}s infinite`,
          }} />
        ))}
      </div>
    </div>
  )
}

export function OverviewScreen({ sensors, onSelect }) {
  const time = new Date().toLocaleTimeString()
  const n    = sensors.length

  return (
    <div style={{ width: '100%', height: '100%', display: 'flex',
                  flexDirection: 'column', overflow: 'hidden' }}>
      <Header count={n} time={time} />
      {n === 0 && <Waiting />}
      {n === 1 && <SingleFull sensor={sensors[0]} onSelect={onSelect} />}
      {n === 2 && (
        <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>
          {sensors.map(s => <DualPane key={s.sensor_id} sensor={s} onSelect={onSelect} />)}
        </div>
      )}
      {n >= 3 && n <= 4 && (
        <div style={{ flex: 1, display: 'grid', gridTemplateColumns: '1fr 1fr',
                      gap: 6, padding: 8, overflow: 'hidden' }}>
          {sensors.map(s => <GridCell key={s.sensor_id} sensor={s} onSelect={onSelect} />)}
        </div>
      )}
      {n >= 5 && (
        <div style={{ flex: 1, overflow: 'auto' }}>
          {sensors.map(s => <ListRow key={s.sensor_id} sensor={s} onSelect={onSelect} />)}
        </div>
      )}
    </div>
  )
}
