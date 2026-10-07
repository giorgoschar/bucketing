import type { ReactNode } from 'react'

export type BadgeTone = 'neutral' | 'pos' | 'neg' | 'warn' | 'acc'

export function Badge({ tone = 'neutral', icon, children }: { tone?: BadgeTone; icon?: ReactNode; children: ReactNode }) {
  return <span className={`ui-badge ui-badge--${tone}`}>{icon}{children}</span>
}
