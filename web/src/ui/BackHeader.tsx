import type { ReactNode } from 'react'
import { Link, useLocation } from 'react-router'
import './controls.css'

/** Sub-screen header: Back (to a fixed parent, keeping the period/lens query when asked), title, one action. */
export function BackHeader({ title, back, keepSearch = false, action }: { title: string; back: string; keepSearch?: boolean; action?: ReactNode }) {
  const { search } = useLocation()
  return (
    <header className="topbar backheader">
      <Link className="backheader__back" to={{ pathname: back, search: keepSearch ? search : '' }} aria-label="Back">
        <svg viewBox="0 0 24 24" width="24" height="24" aria-hidden="true"><path d="M15 18l-6-6 6-6" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" /></svg>
      </Link>
      <h1 className="topbar__title backheader__title">{title}</h1>
      <div className="backheader__action">{action}</div>
    </header>
  )
}
