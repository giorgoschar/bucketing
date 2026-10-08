/** The value bars are scaled against. Never 0, so an all-zero series draws empty bars, not NaN. */
export function scaleMax(values: readonly number[]): number {
  let max = 0
  for (const v of values) if (Number.isFinite(v) && v > max) max = v
  return max > 0 ? max : 1
}

/** A bar's length as a percentage of `max`, clamped to 0–100; negative and NaN draw nothing. */
export function barPct(value: number, max: number): number {
  if (!Number.isFinite(value) || value <= 0 || !(max > 0)) return 0
  return Math.min(100, (value / max) * 100)
}

/** The token series: --c1..--c6 switch with the theme (tokens.css). */
export function seriesColor(index: number): string {
  return `var(--c${(index % 6) + 1})`
}
