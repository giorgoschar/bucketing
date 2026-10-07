export type ProgressTone = 'ok' | 'warn' | 'over'

/** Spec §4.4: the tint changes at 80% and at 100%. */
export function progressTone(pct: number): ProgressTone {
  return pct >= 100 ? 'over' : pct >= 80 ? 'warn' : 'ok'
}

export interface ProgressBarProps { value: number; max: number; label: string; tone?: ProgressTone; thin?: boolean }

export function ProgressBar({ value, max, label, tone, thin }: ProgressBarProps) {
  const pct = max > 0 && Number.isFinite(value) ? (value / max) * 100 : 0
  const width = Math.min(100, Math.max(0, pct))
  return (
    <div className={thin ? 'ui-bar ui-bar--thin' : 'ui-bar'} role="progressbar" aria-label={label}
      aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(pct)} data-tone={tone ?? progressTone(pct)}>
      <span className="ui-bar__fill" style={{ width: `${width}%` }} />
    </div>
  )
}
