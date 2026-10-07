import type { CSSProperties } from 'react'
import { seriesColor } from './scale'
import './charts.css'

export interface StackSegment { id: string; label: string; value: number; hatched?: boolean; /** Palette index; defaults to the position in `segments`. */ color?: number }

/** One horizontal bar split by share. The accessible name lists every segment; callers
 *  also render the list underneath (widget 8), so the numbers are visible too. */
export function StackBar({ label, segments, format }: { label: string; segments: StackSegment[]; format(n: number): string }) {
  const shown = segments
    .map((s, i) => ({ ...s, color: s.color ?? i }))
    .filter((s) => Number.isFinite(s.value) && s.value > 0)
  const total = shown.reduce((sum, s) => sum + s.value, 0)
  const name = `${label}: ${shown.map((s) => `${s.label} ${format(s.value)}${s.hatched ? ' (not logged)' : ''}`).join(', ')}`
  return (
    <div className="stackbar" role="img" aria-label={shown.length ? name : `${label}: nothing yet`}>
      {total > 0 &&
        shown.map((s) => (
          <span
            key={s.id}
            className={s.hatched ? 'stackbar__seg stackbar__seg--hatched' : 'stackbar__seg'}
            style={{ width: `${Math.round((s.value / total) * 1000) / 10}%`, '--bar': seriesColor(s.color) } as CSSProperties}
          />
        ))}
    </div>
  )
}
