/** The price chart's scale, apart from the component so the tests can check the coordinates. */
import type { HistoryPoint } from './types'

export interface ChartBox { width: number; height: number; padX: number; padTop: number; padBottom: number }
export interface ChartPoint { x: number; y: number; date: string; price: number }

const BOX: ChartBox = { width: 326, height: 120, padX: 6, padTop: 30, padBottom: 12 }
const DAY_MS = 86_400_000
const dayOf = (iso: string) => Date.UTC(+iso.slice(0, 4), +iso.slice(5, 7) - 1, +iso.slice(8, 10)) / DAY_MS
export const month = (iso: string) => new Date(`${iso.slice(0, 10)}T12:00:00`).toLocaleDateString('en-GB', { month: 'short' })
export const dayMonth = (iso: string) =>
  new Date(`${iso.slice(0, 10)}T12:00:00`).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })

/**
 * Where each point goes, to scale: x by its date (days since the first point), y by its price between the
 * lowest and highest (a line shows change, so the price axis needn't start at 0). Pure, for the tests.
 */
export function chartGeometry(history: readonly HistoryPoint[], box: ChartBox = BOX) {
  const rows = history.filter((h) => Number.isFinite(h.min_price)).slice().sort((a, b) => a.date.localeCompare(b.date))
  const first = rows.length ? dayOf(rows[0].date) : 0
  const span = rows.length > 1 ? dayOf(rows[rows.length - 1].date) - first : 0
  let lo = Math.min(...rows.map((r) => r.min_price))
  let hi = Math.max(...rows.map((r) => r.min_price))
  if (!(hi - lo > 1e-9)) { const pad = Math.abs(hi) * 0.05 || 1; lo -= pad; hi += pad }
  const plotW = box.width - 2 * box.padX
  const plotH = box.height - box.padTop - box.padBottom
  const points: ChartPoint[] = rows.map((r) => ({
    x: box.padX + (span > 0 ? ((dayOf(r.date) - first) / span) * plotW : plotW / 2),
    y: box.padTop + ((hi - r.min_price) / (hi - lo)) * plotH,
    date: r.date,
    price: r.min_price,
  }))
  const low = points.reduce((best, p, i) => (p.price < points[best].price ? i : best), 0)
  const path = points.map((p, i) => `${i ? 'L' : 'M'}${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join(' ')
  return { points, low, path, box }
}
