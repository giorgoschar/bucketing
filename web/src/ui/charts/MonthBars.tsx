import { scaleMax, seriesColor } from './scale'
import './charts.css'

export interface MonthSeries { name: string; values: number[] }
export interface MonthBarsProps {
  /** Accessible name, also the hidden table's caption. */
  title: string
  /** Oldest first. */
  months: string[]
  /** One or two series, one value per month. */
  series: MonthSeries[]
  format(n: number): string
  /** The last month is still running: drawn lighter and called "so far". */
  current?: boolean
  width?: number
  height?: number
}

const TOP = 16 // room for the max label
const BOTTOM = 18 // room for the month initials

export function MonthBars({ title, months, series, format, current = false, width = 306, height = 130 }: MonthBarsProps) {
  const all = series.flatMap((s) => s.values)
  const max = scaleMax(all)
  const realMax = Math.max(0, ...all.filter(Number.isFinite))
  const plotH = height - TOP - BOTTOM
  const group = width / Math.max(months.length, 1)
  const gap = 2
  const bar = series.length > 1 ? Math.min(14, group * 0.32) : Math.min(22, group * 0.5)
  const span = series.length * bar + (series.length - 1) * gap

  const bars = months.flatMap((_, m) =>
    series.map((s, k) => {
      const v = Number.isFinite(s.values[m]) && s.values[m] > 0 ? s.values[m] : 0
      const h = (v / max) * plotH
      return {
        key: `${m}-${k}`,
        k,
        v,
        h,
        x: m * group + (group - span) / 2 + k * (bar + gap),
        y: TOP + plotH - h,
        running: current && m === months.length - 1,
      }
    }),
  )
  const top = realMax > 0 ? bars.find((b) => b.v === realMax) : undefined

  return (
    <figure className="chart-fig">
      <svg className="chart" viewBox={`0 0 ${width} ${height}`} aria-hidden="true" focusable="false">
        <line className="chart__grid" x1={0} x2={width} y1={TOP + plotH} y2={TOP + plotH} />
        {bars.map((b) => (
          <rect
            key={b.key}
            className={b.running ? 'chart__bar chart__bar--running' : 'chart__bar'}
            x={b.x}
            y={b.y}
            width={bar}
            height={b.h}
            rx={Math.min(3, bar / 2)}
            style={{ fill: seriesColor(b.k), fillOpacity: b.running ? 0.5 : 1 }}
          />
        ))}
        {top && (
          <text className="chart__max" x={top.x + bar / 2} y={Math.max(10, top.y - 4)} textAnchor="middle">
            {format(realMax)}
          </text>
        )}
        {months.map((m, i) => (
          <text key={m + i} x={i * group + group / 2} y={height - 4} textAnchor="middle">
            {m.slice(0, 3)}
          </text>
        ))}
      </svg>
      {series.length > 0 && (
        <ul className="chart-legend">
          {series.map((s, k) => (
            <li key={s.name}>
              <span className="chart-legend__swatch" style={{ background: seriesColor(k) }} aria-hidden="true" />
              {s.name}
            </li>
          ))}
        </ul>
      )}
      <table className="chart-sr">
        <caption>{title}</caption>
        <thead>
          <tr>
            <th scope="col">Month</th>
            {series.map((s) => <th scope="col" key={s.name}>{s.name}</th>)}
          </tr>
        </thead>
        <tbody>
          {months.map((m, i) => (
            <tr key={m + i}>
              <th scope="row">{current && i === months.length - 1 ? `${m} (so far)` : m}</th>
              {series.map((s) => <td key={s.name}>{format(s.values[i] ?? 0)}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </figure>
  )
}
