import { useEffect } from 'react'
import { useLocation, useNavigate } from 'react-router'
import { useIsDesktop } from '../../ui/useIsDesktop'
import { Activity } from './Activity'
import { Detail } from './Detail'
import './activity.css'

/** `/activity/:id`. On the phone it is the full-screen detail, as always. On desktop it is the table with the
 *  same detail beside it in a 420 px pane (Phase A spec §4.4). Esc, or Back in the pane, closes the pane. */
export function ActivityIdRoute() {
  const desktop = useIsDesktop()
  const navigate = useNavigate()
  const { search } = useLocation()

  useEffect(() => {
    if (!desktop) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape' || e.defaultPrevented) return
      // Esc in a field, or while a sheet is open, belongs to that field or sheet.
      const t = e.target as Element | null
      if (t?.closest?.('input, textarea, select') || document.querySelector('[aria-modal="true"], dialog[open]')) return
      void navigate({ pathname: '/activity', search }, { replace: true })
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [desktop, navigate, search])

  if (!desktop) return <Detail />
  const close = () => void navigate({ pathname: '/activity', search }, { replace: true })
  return (
    <div className="dact shell__main--wide">
      <div className="dact__main"><Activity /></div>
      <aside className="dact__pane" aria-label="Payment details">
        <Detail onBack={close} />
      </aside>
    </div>
  )
}
