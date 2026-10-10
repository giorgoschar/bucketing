/** A small trend line of a bill's recent amounts (spec §5.2). Hand-drawn SVG; the title says what it shows. */
export interface SparklineProps { values: number[]; title: string; width?: number; height?: number }

const PAD = 4

export function Sparkline({ values, title, width = 72, height = 24 }: SparklineProps) {
  if (values.length === 0) return null
  const lo = Math.min(...values)
  const hi = Math.max(...values)
  const span = hi - lo || 1
  const x = (i: number) => (values.length > 1 ? PAD + (i / (values.length - 1)) * (width - 2 * PAD) : width / 2)
  const y = (v: number) => (hi === lo ? height / 2 : PAD + (1 - (v - lo) / span) * (height - 2 * PAD))
  const path = values.map((v, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)} ${y(v).toFixed(1)}`).join(' ')
  const last = values.length - 1
  return (
    <svg className="spark" viewBox={`0 0 ${width} ${height}`} width={width} height={height} role="img" focusable="false">
      <title>{title}</title>
      {values.length > 1 && <path d={path} fill="none" style={{ stroke: 'var(--c1)', strokeWidth: 2, strokeLinecap: 'round', strokeLinejoin: 'round' }} />}
      <circle cx={x(last)} cy={y(values[last])} r={3} style={{ fill: 'var(--c1)', stroke: 'var(--surface)', strokeWidth: 2 }} />
    </svg>
  )
}
