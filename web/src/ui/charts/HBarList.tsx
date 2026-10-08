import type { CSSProperties } from 'react'
import { barPct, scaleMax, seriesColor } from './scale'
import './charts.css'

export interface HBarRow {
  id: string
  label: string
  value: number
  icon?: string
  /** Cash not logged yet: hatched, labelled "not logged", never tappable. */
  hatched?: boolean
}

export interface HBarListProps {
  label: string
  rows: HBarRow[]
  format(n: number): string
  onSelect?(row: HBarRow): void
}

/** Horizontal bars with the value written on every row (the text equivalent). */
export function HBarList({ label, rows, format, onSelect }: HBarListProps) {
  const max = scaleMax(rows.map((r) => r.value))
  return (
    <ul className="hbars" aria-label={label}>
      {rows.map((row, i) => {
        const style = { width: `${barPct(row.value, max)}%`, '--bar': seriesColor(i) } as CSSProperties
        const body = (
          <>
            <span className="hbars__head">
              {row.icon && <span className="hbars__icon" aria-hidden="true">{row.icon}</span>}
              <span className="hbars__label">{row.label}</span>
              {row.hatched && <span className="hbars__note">not logged</span>}
              <span className="hbars__value num">{format(row.value)}</span>
            </span>
            <span className="hbars__track" aria-hidden="true">
              <span className={row.hatched ? 'hbars__fill hbars__fill--hatched' : 'hbars__fill'} style={style} />
            </span>
          </>
        )
        return (
          <li key={row.id}>
            {onSelect && !row.hatched ? (
              <button type="button" className="hbars__row" onClick={() => onSelect(row)}>{body}</button>
            ) : (
              <div className="hbars__row">{body}</div>
            )}
          </li>
        )
      })}
    </ul>
  )
}
