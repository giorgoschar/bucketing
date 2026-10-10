import { useId } from 'react'
import { barPct, scaleMax } from '../../../ui/charts'
import '../../../ui/charts/charts.css'
import type { MonthCell } from './history'

/* Hand-drawn SVG in the fuel screen's manner: theme tokens (--c1, --line, --ink-2), tabular numbers, a <title> on
   every <svg>. The table under the charts is their text alternative (spec §5.3). */

const W = 306
const H = 140
const LEFT = 36
const RIGHT = 6
const TOP = 12
const BOTTOM = 20
const MONTH_LETTERS = ['J', 'F', 'M', 'A', 'M', 'J', 'J', 'A', 'S', 'O', 'N', 'D']
const MONTH_NAMES = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
// The lighter bar also carries a 1 px outline in the series colour, so it does not rely on a pale fill alone.
const LAST_YEAR_FILL = 'color-mix(in srgb, var(--c1) 38%, var(--surface))'

const plotW = W - LEFT - RIGHT
const plotH = H - TOP - BOTTOM
const slot = plotW / 12
const cx = (month: number) => LEFT + slot * (month - 0.5)

/** A bar anchored on the baseline with a rounded top (4 px at most). */
function barPath(x: number, w: number, h: number): string {
  const base = TOP + plotH
  const r = Math.min(4, w / 2, h)
  return `M${x} ${base} V${base - h + r} Q${x} ${base - h} ${x + r} ${base - h} H${x + w - r} Q${x + w} ${base - h} ${x + w} ${base - h + r} V${base} Z`
}

function Frame({ title, max, min = 0, format, children }: { title: string; max: number; min?: number; format: (n: number) => string; children: React.ReactNode }) {
  const id = useId()
  return (
    <svg className="chart billchart" viewBox={`0 0 ${W} ${H}`} role="img" aria-labelledby={id} focusable="false">
      <title id={id}>{title}</title>
      <line className="chart__grid" x1={LEFT} x2={W - RIGHT} y1={TOP} y2={TOP} strokeDasharray="4 4" />
      <text x={LEFT - 4} y={TOP + 3} textAnchor="end">{format(max)}</text>
      <line className="chart__grid" x1={LEFT} x2={W - RIGHT} y1={TOP + plotH} y2={TOP + plotH} />
      <text x={LEFT - 4} y={TOP + plotH + 3} textAnchor="end">{format(min)}</text>
      {children}
      {MONTH_LETTERS.map((l, i) => <text key={i} x={cx(i + 1)} y={H - 6} textAnchor="middle">{l}</text>)}
    </svg>
  )
}

export interface BarsProps {
  title: string
  year: number
  cells: MonthCell[]
  /** What each bar shows. */
  value: (c: MonthCell) => number | null
  /** The lighter bar for the same month a year earlier. */
  compare?: (c: MonthCell) => number | null
  format: (n: number) => string
  /** Shorter labels for the axis (whole euros, no unit); defaults to `format`. */
  axisFormat?: (n: number) => string
}

/** Twelve months of bars for a year, each with an optional lighter bar for the same month last year. */
export function YearBars({ title, year, cells, value, compare, format, axisFormat = format }: BarsProps) {
  const all = cells.flatMap((c) => [value(c), compare?.(c) ?? null]).filter((v): v is number => v !== null)
  const max = scaleMax(all)
  const hasLast = compare !== undefined && cells.some((c) => compare(c) !== null)
  const barW = hasLast ? Math.min(9, slot / 2 - 1) : Math.min(14, slot - 4)
  return (
    <figure className="chart-fig billchart__fig">
      <Frame title={title} max={max} format={axisFormat}>
        {cells.map((c) => {
          const v = value(c)
          const prev = compare?.(c) ?? null
          const gap = 1
          const xThis = hasLast ? cx(c.month) + gap / 2 : cx(c.month) - barW / 2
          const xPrev = cx(c.month) - barW - gap / 2
          const name = `${MONTH_NAMES[c.month - 1]} ${year}`
          return (
            <g key={c.month}>
              {prev !== null && (
                <path data-kind="last-year" data-month={c.month} d={barPath(xPrev, barW, Math.max(1, (barPct(prev, max) / 100) * plotH))}
                  style={{ fill: LAST_YEAR_FILL, stroke: 'var(--c1)', strokeWidth: 1 }}>
                  <title>{`${MONTH_NAMES[c.month - 1]} ${year - 1}: ${format(prev)}`}</title>
                </path>
              )}
              {v !== null && (
                <path data-kind="year" data-month={c.month} d={barPath(xThis, barW, Math.max(1, (barPct(v, max) / 100) * plotH))}
                  style={{ fill: 'var(--c1)' }}>
                  <title>{`${name}: ${format(v)}`}</title>
                </path>
              )}
            </g>
          )
        })}
      </Frame>
      {hasLast && (
        <ul className="chart-legend" aria-hidden="true">
          <li><span className="chart-legend__swatch" style={{ background: 'var(--c1)' }} />{year}</li>
          <li><span className="chart-legend__swatch" style={{ background: LAST_YEAR_FILL }} />{year - 1}</li>
        </ul>
      )}
    </figure>
  )
}

/** The price per unit over the year: a 2 px line, broken where a month has no figure. */
export function UnitPriceLine({ title, year, cells, format }: { title: string; year: number; cells: MonthCell[]; format: (n: number) => string }) {
  const have = cells.filter((c) => c.unitPrice !== null)
  const values = have.map((c) => c.unitPrice as number)
  let lo = Math.min(...values)
  let hi = Math.max(...values)
  if (hi - lo < 1e-9) { const pad = Math.abs(hi) * 0.05 || 1; lo -= pad; hi += pad }
  const y = (v: number) => TOP + plotH - ((v - lo) / (hi - lo)) * plotH
  const segments: MonthCell[][] = []
  for (const c of cells) {
    if (c.unitPrice === null) segments.push([])
    else {
      if (segments.length === 0) segments.push([])
      segments[segments.length - 1].push(c)
    }
  }
  const last = have[have.length - 1]
  return (
    <figure className="chart-fig billchart__fig">
      <Frame title={title} max={hi} min={lo} format={format}>
        {segments.filter((s) => s.length > 1).map((s, i) => (
          <path key={i} fill="none" d={s.map((c, j) => `${j ? 'L' : 'M'}${cx(c.month).toFixed(1)} ${y(c.unitPrice as number).toFixed(1)}`).join(' ')}
            style={{ stroke: 'var(--c1)', strokeWidth: 2, strokeLinecap: 'round', strokeLinejoin: 'round' }} />
        ))}
        {have.map((c) => (
          <circle key={c.month} data-month={c.month} cx={cx(c.month)} cy={y(c.unitPrice as number)} r={c === last ? 4 : 3}
            style={{ fill: 'var(--c1)', stroke: 'var(--surface)', strokeWidth: 2 }}>
            <title>{`${MONTH_NAMES[c.month - 1]} ${year}: ${format(c.unitPrice as number)}`}</title>
          </circle>
        ))}
      </Frame>
    </figure>
  )
}
