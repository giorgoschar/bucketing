import { useSearchParams } from 'react-router'

/**
 * Add as a side panel (Phase A spec §4.5). On desktop the composer is not a route: it is the screen you are on
 * plus `?add=1` or `?edit=<id>` (and the composer's own `mode`, `take`, `amount`, `from`). On the phone the same
 * addresses mean the full-screen /new and /edit/:id routes, and these helpers translate both ways.
 */
const PANEL_KEYS = ['add', 'edit'] as const
const COMPOSER_KEYS = ['mode', 'take', 'amount', 'from'] as const
const OWN_KEYS = [...PANEL_KEYS, ...COMPOSER_KEYS]
/** Every query parameter the panel and the composer own; closing the panel removes them. */
export const OWN_PANEL_KEYS: readonly string[] = OWN_KEYS

export type PanelState = { kind: 'add' } | { kind: 'edit'; id: string }

export function panelOf(params: URLSearchParams): PanelState | null {
  const edit = params.get('edit')
  if (edit) return { kind: 'edit', id: edit }
  return params.get('add') === '1' ? { kind: 'add' } : null
}

/** The address with the panel and the composer's parameters taken out. */
export function withoutPanel(params: URLSearchParams): URLSearchParams {
  const rest = new URLSearchParams(params)
  for (const k of OWN_KEYS) rest.delete(k)
  return rest
}

// The screen the user was last on, for a link to /new that arrives with no screen behind it (a bookmark, a
// notification, a reload of /new when the window is then widened). AppShell records it.
let lastScreen = '/'
export function rememberScreen(pathname: string, search: string): void {
  const rest = withoutPanel(new URLSearchParams(search)).toString()
  lastScreen = pathname + (rest ? `?${rest}` : '')
}

/** Desktop: /new?… or /edit/:id?… becomes the current screen plus the panel parameters. */
export function panelAddress(pathname: string, search: string): string {
  const [path, query = ''] = lastScreen.split('?')
  const out = new URLSearchParams(query)
  const edit = /^\/edit\/([^/]+)/.exec(pathname)
  if (edit) out.set('edit', decodeURIComponent(edit[1]))
  else out.set('add', '1')
  new URLSearchParams(search).forEach((v, k) => out.set(k, v))
  return `${path}?${out.toString()}`
}

/** Phone: ?add=1 / ?edit=<id> on any screen becomes the full-screen composer with the same parameters. */
export function fullScreenAddress(params: URLSearchParams): string | null {
  const panel = panelOf(params)
  if (!panel) return null
  const rest = new URLSearchParams(params)
  rest.delete('add')
  rest.delete('edit')
  // The screen behind's own filters are not the composer's.
  const q = new URLSearchParams()
  for (const k of COMPOSER_KEYS) {
    const v = rest.get(k)
    if (v !== null) q.set(k, v)
  }
  const tail = q.toString() ? `?${q.toString()}` : ''
  return panel.kind === 'edit' ? `/edit/${encodeURIComponent(panel.id)}${tail}` : `/new${tail}`
}

/** Opens Add: the panel over the current screen. */
export function useOpenAdd(): () => void {
  const [params, setParams] = useSearchParams()
  return () => {
    if (panelOf(params)) return // already open
    setParams((p) => {
      const next = new URLSearchParams(p)
      next.set('add', '1')
      return next
    })
  }
}
