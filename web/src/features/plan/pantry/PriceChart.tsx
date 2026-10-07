import { type PointerEvent, useState } from 'react'
import { formatMoney } from '../../../ui/format'
import { chartGeometry, dayMonth, month } from './priceScale'
import type { HistoryPoint } from './types'

/** The 6-month lowest price (pantry spec §4.4): one series, its low and latest marked, a hover readout, a table. */
export function PriceChart({ history, title }: { history: readonly HistoryPoint[]; title: string }) {
  const [hover, setHover] = useState<number | null>(null)
  const g = chartGeometry(history)
  const head = (low?: string) => (
    <div className="pantry-card__head">
      <h2 className="pantry-card__title">{title}</h2>
      {low && <span className="pantry-card__meta">{low}</span>}
    </div>
  )
  if (g.points.length < 2) {
    return <>{head()}<p className="pantry-chart__empty">Not enough price history yet</p></>
  }
  const { points, box } = g
  const low = points[g.low]
  const last = points[points.length - 1]
  const firstP = points[0]
  const shown = hover == null ? null : points[hover]

  const onMove = (e: PointerEvent<SVGSVGElement>) => {
    const r = e.currentTarget.getBoundingClientRect()
    if (!r.width) return
    const x = ((e.clientX - r.left) / r.width) * box.width
    let best = 0
    for (let i = 1; i < points.length; i++) if (Math.abs(points[i].x - x) < Math.abs(points[best].x - x)) best = i
    setHover(best)
  }

  return (
    <figure className="pantry-chart">
      {head(`Low ${formatMoney(low.price)} in ${month(low.date)}`)}
      <div className="pantry-chart__plot">
        <svg viewBox={`0 0 ${box.width} ${box.height}`} className="pantry-chart__svg" aria-hidden="true" focusable="false"
          onPointerMove={onMove} onPointerLeave={() => setHover(null)}>
          <line className="pantry-chart__base" x1={box.padX} x2={box.width - box.padX} y1={box.height - box.padBottom}
            y2={box.height - box.padBottom} />
          <path d={g.path} className="pantry-chart__line" />
          {shown && <line className="pantry-chart__cross" x1={shown.x} x2={shown.x} y1={box.padTop - 6} y2={box.height - box.padBottom} />}
          <circle className="pantry-chart__dot pantry-chart__dot--low" cx={low.x} cy={low.y} r={4} />
          {g.low !== points.length - 1 && <circle className="pantry-chart__dot" cx={last.x} cy={last.y} r={4} />}
          {shown && <circle className="pantry-chart__dot pantry-chart__dot--hover" cx={shown.x} cy={shown.y} r={5} />}
        </svg>
        {shown && (
          <div className="pantry-chart__tip" style={{ left: `${Math.min(84, Math.max(16, (shown.x / box.width) * 100))}%` }}>
            <b className="ui-num">{formatMoney(shown.price)}</b> {dayMonth(shown.date)}
          </div>
        )}
      </div>
      <div className="pantry-chart__ends">
        <span>{month(firstP.date)} {formatMoney(firstP.price)}</span>
        <span>{month(last.date)} {formatMoney(last.price)}</span>
      </div>
      <table className="ui-sr">
        <caption>Lowest price by day</caption>
        <tbody>
          {points.map((p) => (
            <tr key={p.date}><th scope="row">{dayMonth(p.date)}</th><td>{formatMoney(p.price)}</td></tr>
          ))}
        </tbody>
      </table>
    </figure>
  )
}
