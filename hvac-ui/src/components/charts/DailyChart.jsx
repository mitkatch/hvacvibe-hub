// components/charts/DailyChart.jsx
// Daily RMS chart — x axis = minutes of day (0-1439), y axis = vib_rms
// Matches pygame draw_chart: grid, NOW line, alarm threshold, filled area.

import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid,
  ReferenceLine, ResponsiveContainer, Tooltip
} from 'recharts'

const MINUTES_PER_DAY = 1440
const ALARM_THRESHOLD = 0.60
const WARN_THRESHOLD  = 0.50

function minuteToLabel(m) {
  const h = Math.floor(m / 60).toString().padStart(2, '0')
  const mn = (m % 60).toString().padStart(2, '0')
  return `${h}:${mn}`
}

function nowMinute() {
  const d = new Date()
  return d.getHours() * 60 + d.getMinutes()
}

export function DailyChart({ history = [], height = 160 }) {
  const now = nowMinute()

  // Fill sparse history into dense array for smooth line
  // Only show points up to now
  const data = history
    .filter(h => h.minute <= now)
    .map(h => ({ minute: h.minute, rms: h.vib_rms }))

  const yMax = Math.max(
    ALARM_THRESHOLD * 1.3,
    ...data.map(d => d.rms)
  ) * 1.1

  const xTicks = [0, 360, 720, 1080, 1439]

  return (
    <div style={{ width: '100%', height, minWidth: 0 }}>
      <ResponsiveContainer width="100%" height="100%" minWidth={0}>
        <AreaChart data={data} margin={{ top: 8, right: 50, bottom: 16, left: 32 }}>
          <defs>
            <linearGradient id="rmsGrad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%"  stopColor="var(--chart-line)" stopOpacity={0.5} />
              <stop offset="95%" stopColor="var(--chart-line)" stopOpacity={0.05} />
            </linearGradient>
          </defs>

          <CartesianGrid
            strokeDasharray="2 4"
            stroke="var(--divider)"
            vertical={false}
          />

          <XAxis
            dataKey="minute"
            type="number"
            domain={[0, MINUTES_PER_DAY - 1]}
            ticks={xTicks}
            tickFormatter={minuteToLabel}
            tick={{ fill: 'var(--grey)', fontSize: 10, fontFamily: 'var(--font-mono)' }}
            stroke="var(--edge)"
          />

          <YAxis
            domain={[0, yMax]}
            tickFormatter={v => v.toFixed(2)}
            tick={{ fill: 'var(--grey)', fontSize: 10, fontFamily: 'var(--font-mono)' }}
            stroke="var(--edge)"
            width={30}
          />

          <Tooltip
            contentStyle={{
              background: 'var(--panel)',
              border:     '1px solid var(--edge)',
              borderRadius: 4,
              fontSize:   11,
              fontFamily: 'var(--font-mono)',
            }}
            labelFormatter={minuteToLabel}
            formatter={v => [`${v.toFixed(4)}g`, 'RMS']}
          />

          {/* Alarm threshold line */}
          <ReferenceLine
            y={ALARM_THRESHOLD}
            stroke="var(--red)"
            strokeDasharray="4 2"
            label={{ value: 'ALM', fill: 'var(--red)', fontSize: 10,
                     fontFamily: 'var(--font-mono)', position: 'right' }}
          />

          {/* Warn threshold line */}
          <ReferenceLine
            y={WARN_THRESHOLD}
            stroke="var(--warn)"
            strokeDasharray="2 4"
          />

          {/* NOW line */}
          <ReferenceLine
            x={now}
            stroke="var(--now-line)"
            strokeWidth={1.5}
            label={{ value: 'NOW', fill: 'var(--now-line)', fontSize: 10,
                     fontFamily: 'var(--font-mono)', position: 'insideTopLeft' }}
          />

          <Area
            type="monotone"
            dataKey="rms"
            stroke="var(--chart-line)"
            strokeWidth={2}
            fill="url(#rmsGrad)"
            dot={false}
            activeDot={{ r: 3, fill: 'var(--white)' }}
            isAnimationActive={false}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  )
}
