import { useEffect } from 'react'
import { useLocation, useMatch, useNavigate } from 'react-router'
import { panelOf } from '../../shell/addPanel'
import { useIsDesktop } from '../../ui/useIsDesktop'
import { Activity } from './Activity'
import { Detail } from './Detail'
import './activity.css'

/**
 * Both `/activity` and `/activity/:id` (router.tsx gives them this one element, so React keeps the instance when
 * a row opens or closes: scroll, loaded pages and focus stay).
 * Phone: the list at `/activity`, the full-screen detail at `/activity/:id`, exactly as before.
 * Desktop (Phase A spec §4.4): the table always, and at `/activity/:id` the same detail beside it in a 420 px
 * pane. Esc, or Back in the pane, closes the pane.
 */
export function ActivityRoute() {
  const desktop = useIsDesktop()
  const navigate = useNavigate()
  const { search } = useLocation()
  const open = useMatch('/activity/:id') !== null
  const close = () => void navigate({ pathname: '/activity', search }, { replace: true })

  useEffect(() => {
    if (!desktop || !open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape' || e.defaultPrevented) return
      // Esc in a field, or while a sheet is open, belongs to that field or sheet; with the Add panel open it
      // closes the panel first (the composer's own listener) and the pane on the next Esc.
      const t = e.target as Element | null
      if (t?.closest?.('input, textarea, select') || document.querySelector('[aria-modal="true"], dialog[open]')) return
      if (panelOf(new URLSearchParams(search))) return
      void navigate({ pathname: '/activity', search }, { replace: true })
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [desktop, open, navigate, search])

  if (!desktop) return open ? <Detail /> : <Activity />
  return (
    <div className="dact shell__main--wide">
      <div className="dact__main"><Activity /></div>
      {open && (
        <aside className="dact__pane" aria-label="Payment details">
          <Detail onBack={close} />
        </aside>
      )}
    </div>
  )
}
