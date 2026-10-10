import { useEffect, useMemo, useRef } from 'react'
import { useSearchParams } from 'react-router'
import { PanelProvider } from '../features/composer/panel'
import { Compose } from '../screens/lazy'
import { OWN_PANEL_KEYS, panelOf, resetPanelParams } from './addPanel'

/** The composer in a 440 px panel over the screen behind (Phase A spec §4.5). The URL drives it, so a reload keeps it. */
export default function AddPanel() {
  const [params, setParams] = useSearchParams()
  const panel = panelOf(params)
  // A new copy link remounts the form; the reset after a save (which clears `copy`) does not.
  const copy = useRef<string | null>(null)
  if (params.get('copy')) copy.current = params.get('copy')

  const host = useMemo(() => ({
    editId: panel?.kind === 'edit' ? panel.id : undefined,
    close: () => setParams((p) => {
      const next = new URLSearchParams(p)
      for (const k of OWN_PANEL_KEYS) next.delete(k)
      return next
    }, { replace: true }),
    reset: () => setParams((p) => resetPanelParams(p), { replace: true }),
    openEdit: (id: string) => setParams((p) => {
      const next = new URLSearchParams(p)
      next.delete('add')
      next.set('edit', id)
      return next
    }, { replace: true }),
  }), [panel?.kind, panel?.kind === 'edit' ? panel.id : null, setParams]) // eslint-disable-line react-hooks/exhaustive-deps

  // Focus goes back to what opened the panel (the Add button, or the row's Edit link) when it closes.
  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null
    return () => { if (opener && opener !== document.body && document.contains(opener)) opener.focus() }
  }, [])

  if (!panel) return null
  return (
    <aside className="addpanel" aria-label={panel.kind === 'edit' ? 'Edit entry' : 'Add entry'}>
      <PanelProvider value={host}>
        <Compose key={panel.kind === 'edit' ? `edit:${panel.id}` : copy.current ? `copy:${copy.current}` : 'add'} />
      </PanelProvider>
    </aside>
  )
}
