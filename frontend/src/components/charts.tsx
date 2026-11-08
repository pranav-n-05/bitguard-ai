import { Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'

const AXIS = { stroke: '#94a3b8', fontSize: 11, tickLine: false, axisLine: { stroke: '#26324a' } }
const TT = { contentStyle: { background: '#0f172a', border: '1px solid #26324a', borderRadius: 6, fontSize: 12 }, labelStyle: { color: '#e5e7eb' } }

export function VolumeChart({ data }: { data: { t: string; tx_count: number }[] }) {
  return (
    <div className="h-56" role="img" aria-label="Transaction volume over time">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data.map((d) => ({ ...d, day: d.t.slice(0, 10) }))} margin={{ left: 0, right: 8, top: 8 }}>
          <CartesianGrid stroke="#26324a" strokeDasharray="3 3" vertical={false} />
          <XAxis dataKey="day" {...AXIS} minTickGap={24} />
          <YAxis {...AXIS} width={40} allowDecimals={false} />
          <Tooltip {...TT} />
          <Area type="monotone" dataKey="tx_count" name="Transactions" stroke="#38bdf8" fill="#38bdf8" fillOpacity={0.15} strokeWidth={1.5} />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  )
}

const BAND_COLOR: Record<string, string> = { low: '#22c55e', moderate: '#38bdf8', elevated: '#f59e0b', high: '#ef4444' }

export function BandChart({ bands }: { bands: Record<string, number> }) {
  const data = ['low', 'moderate', 'elevated', 'high'].map((b) => ({ band: b, count: bands[b] ?? 0 }))
  return (
    <div className="h-48" role="img" aria-label="Risk band distribution">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ left: 0, right: 8, top: 8 }}>
          <CartesianGrid stroke="#26324a" strokeDasharray="3 3" vertical={false} />
          <XAxis dataKey="band" {...AXIS} />
          <YAxis {...AXIS} width={44} allowDecimals={false} scale="sqrt" />
          <Tooltip {...TT} />
          <Bar dataKey="count" name="Entities">
            {data.map((d) => <Cell key={d.band} fill={BAND_COLOR[d.band]} />)}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

export function HistogramChart({ data, xKey, label }: { data: Record<string, unknown>[]; xKey: string; label: string }) {
  return (
    <div className="h-48" role="img" aria-label={label}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ left: 0, right: 8, top: 8 }}>
          <CartesianGrid stroke="#26324a" strokeDasharray="3 3" vertical={false} />
          <XAxis dataKey={xKey} {...AXIS} />
          <YAxis {...AXIS} width={44} allowDecimals={false} scale="sqrt" />
          <Tooltip {...TT} />
          <Bar dataKey="count" name="Count" fill="#f7931a" />
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

export function HBar({ data, label }: { data: { name: string; value: number }[]; label: string }) {
  return (
    <div style={{ height: Math.max(120, data.length * 26) }} role="img" aria-label={label}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} layout="vertical" margin={{ left: 8, right: 16 }}>
          <XAxis type="number" {...AXIS} />
          <YAxis type="category" dataKey="name" {...AXIS} width={170} />
          <Tooltip {...TT} />
          <Bar dataKey="value" fill="#38bdf8" />
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}
