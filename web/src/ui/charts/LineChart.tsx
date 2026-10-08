import './charts.css'

export interface LinePoint { label: string; value: number }
export interface LineChartProps {
  title: string
  points: LinePoint[]
  format(n: number): string
  average?: number | null
  width?: number
  height?: number
}

const PAD_X = 28
const PAD_TOP = 18
const PAD_BOTTOM = 14

export function LineChart({ title, points, format, average = null, width = 306, height = 132 }: LineChartProps) {
  const values = points.map((p) => (Number.isFinite(p.value) ? p.value : 0))
  const domain = average != null ? [...values, average] : values
  let lo = Math.min(...domain, Infinity)
  let hi = Math.max(...domain, -Infinity)
  if (!Number.isFinite(lo) || !Number.isFinite(hi)) { lo = 0; hi = 1 }
  if (hi - lo < 1e-9) { const pad = Math.abs(hi) * 0.05 || 1; lo -= pad; hi += pad }
  const plotH = height - PAD_TOP - PAD_BOTTOM
  const y = (v: number) => PAD_TOP + plotH - ((v - lo) / (hi - lo)) * plotH
  const x = (i: number) => (points.length > 1 ? PAD_X + (i / (points.length - 1)) * (width - 2 * PAD_X) : width / 2)
  const path = values.map((v, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)} ${y(v).toFixed(1)}`).join(' ')
  const last = values.length - 1

  return (
    <figure className="chart-fig">
      <svg className="chart" viewBox={`0 0 ${width} ${height}`} aria-hidden="true" focusable="false">
        {average != null && (
          <>
            <line className="chart__grid" x1={PAD_X} x2={width - PAD_X} y1={y(average)} y2={y(average)} strokeDasharray="4 4" />
            <text x={width - PAD_X} y={y(average) - 4} textAnchor="end">{`avg ${format(average)}`}</text>
          </>
        )}
        {values.length > 1 && <path d={path} fill="none" style={{ stroke: 'var(--c1)', strokeWidth: 2 }} />}
        {values.map((v, i) => (
          <circle key={i} cx={x(i)} cy={y(v)} r={i === last ? 4 : 3} style={{ fill: 'var(--c1)' }} />
        ))}
        {values.length > 0 && <text x={x(0)} y={y(values[0]) - 8} textAnchor="middle">{format(values[0])}</text>}
        {last > 0 && <text x={x(last)} y={y(values[last]) - 8} textAnchor="middle">{format(values[last])}</text>}
      </svg>
      <table className="chart-sr">
        <caption>{title}</caption>
        <tbody>
          {points.map((p, i) => (
            <tr key={i}><th scope="row">{p.label}</th><td>{format(values[i])}</td></tr>
          ))}
          {average != null && <tr><th scope="row">Average</th><td>{format(average)}</td></tr>}
        </tbody>
      </table>
    </figure>
  )
}
