import type { ReactNode } from 'react'
import { Link, useLocation } from 'react-router'
import './controls.css'

/** The kept query with the parent's own keys written over it; '' when neither has any. */
function backSearch(kept: string, parent: string): string {
  const p = new URLSearchParams(kept)
  for (const [k, v] of new URLSearchParams(parent)) p.set(k, v)
  const q = p.toString()
  return q ? `?${q}` : ''
}

/** Sub-screen header: Back (to a fixed parent, keeping the period/lens query when asked), title, one action. */
export function BackHeader({ title, back, keepSearch = false, action }: { title: string; back: string; keepSearch?: boolean; action?: ReactNode }) {
  const { search } = useLocation()
  // A fixed parent may carry its own query (e.g. `/insights?tab=bills`).
  const [pathname, parentSearch = ''] = back.split('?')
  return (
    <header className="topbar backheader">
      <Link className="backheader__back" to={{ pathname, search: backSearch(keepSearch ? search : '', parentSearch) }} aria-label="Back">
        <svg viewBox="0 0 24 24" width="24" height="24" aria-hidden="true"><path d="M15 18l-6-6 6-6" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" /></svg>
      </Link>
      <h1 className="topbar__title backheader__title">{title}</h1>
      <div className="backheader__action">{action}</div>
    </header>
  )
}
