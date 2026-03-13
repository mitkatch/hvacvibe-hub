// components/charts/FFTChart.jsx
// FFT spectrum chart — overlays X, Y, Z axes.
// X axis = frequency (Hz), Y axis = amplitude (g)

import { useState } from 'react'
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid,
  ResponsiveContainer, Tooltip, Legend
} from 'recharts'

const AXIS_COLORS = { x: '#ff4444', y: '#44ff88', z: '#44aaff' }

function buildChartData(fft) {
  if (!fft?.x?.frequencies?.length) return []
  const freqs = fft.x.frequencies
  return freqs.map((f, i) => ({
    hz: f,
    x:  fft.x.amplitudes[i] ?? 0,
    y:  fft.y.amplitudes[i] ?? 0,
    z:  fft.z.amplitudes[i] ?? 0,
  }))
}

export function FFTChart({ fft, height = 180 }) {
  const [visible, setVisible] = useState({ x: true, y: true, z: true })
  const data = buildChartData(fft)

  if (!data.length) {
    return (
      <div style={{
        height,
        display:        'flex',
        alignItems:     'center',
        justifyContent: 'center',
        color:          'var(--grey)',
        fontSize:        12,
        fontFamily:     'var(--font-mono)',
        border:         '1px solid var(--divider)',
        borderRadius:    4,
      }}>
        Waiting for FFT data...
      </div>
    )
  }

  const toggle = axis => setVisible(v => ({ ...v, [axis]: !v[axis] }))

  return (
    <div style={{ width: '100%' }}>
      {/* Axis toggles */}
      <div style={{ display: 'flex', gap: 12, marginBottom: 6, paddingLeft: 8 }}>
        {['x','y','z'].map(axis => (
          <button
            key={axis}
            onClick={() => toggle(axis)}
            style={{
              background:   visible[axis] ? AXIS_COLORS[axis] + '22' : 'transparent',
              border:       `1px solid ${visible[axis] ? AXIS_COLORS[axis] : 'var(--edge)'}`,
              color:        visible[axis] ? AXIS_COLORS[axis] : 'var(--grey)',
              borderRadius:  3,
              padding:      '2px 10px',
              fontSize:      11,
              fontFamily:   'var(--font-mono)',
              cursor:       'pointer',
              textTransform:'uppercase',
            }}
          >
            {axis}
          </button>
        ))}
      </div>

      <div style={{ width: '100%', height, minWidth: 0 }}>
        <ResponsiveContainer width="100%" height="100%" minWidth={0}>
          <LineChart data={data} margin={{ top: 4, right: 8, bottom: 16, left: 32 }}>
            <CartesianGrid
              strokeDasharray="2 4"
              stroke="var(--divider)"
              vertical={false}
            />
            <XAxis
              dataKey="hz"
              type="number"
              domain={[0, 800]}
              ticks={[0, 100, 200, 300, 400, 500, 600, 700, 800]}
              tickFormatter={v => `${v}`}
              tick={{ fill: 'var(--grey)', fontSize: 10, fontFamily: 'var(--font-mono)' }}
              stroke="var(--edge)"
              label={{ value: 'Hz', fill: 'var(--grey)', fontSize: 10,
                       position: 'insideBottomRight', offset: -4 }}
            />
            <YAxis
              tickFormatter={v => v.toFixed(3)}
              tick={{ fill: 'var(--grey)', fontSize: 10, fontFamily: 'var(--font-mono)' }}
              stroke="var(--edge)"
              width={38}
            />
            <Tooltip
              contentStyle={{
                background:   'var(--panel)',
                border:       '1px solid var(--edge)',
                borderRadius:  4,
                fontSize:      11,
                fontFamily:   'var(--font-mono)',
              }}
              labelFormatter={v => `${v} Hz`}
              formatter={(v, name) => [`${v.toFixed(5)}g`, name.toUpperCase()]}
            />
            {['x','y','z'].map(axis => visible[axis] && (
              <Line
                key={axis}
                type="monotone"
                dataKey={axis}
                stroke={AXIS_COLORS[axis]}
                strokeWidth={1.5}
                dot={false}
                isAnimationActive={false}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}
