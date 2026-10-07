import { useSyncExternalStore } from 'react'
import { AlertIcon } from './icons'

export interface ToastAction { label: string; onClick: () => void }
export interface ToastOptions { action?: ToastAction; durationMs?: number; tone?: 'default' | 'error' }
interface Shown extends ToastOptions { id: number; message: string }

const DEFAULT_MS = 4000
let current: Shown | null = null
let seq = 0
let timer: ReturnType<typeof setTimeout> | undefined
const subs = new Set<() => void>()
const emit = () => subs.forEach((cb) => cb())
const subscribe = (cb: () => void) => {
  subs.add(cb)
  return () => { subs.delete(cb) }
}

/** Show a toast; it replaces the one on screen. Callable outside React (useAction uses it). */
export function toast(message: string, opts: ToastOptions = {}): void {
  clearTimeout(timer)
  current = { ...opts, id: ++seq, message }
  emit()
  timer = setTimeout(dismissToast, opts.durationMs ?? DEFAULT_MS)
}

export function dismissToast(): void {
  clearTimeout(timer)
  if (!current) return
  current = null
  emit()
}

const handle = { show: toast, dismiss: dismissToast }
/** For components that prefer a hook; the functions are module-level and stable. */
export function useToast(): typeof handle {
  return handle
}

/** Rendered once by AppShell (and by renderWithProviders in tests). */
export function Toaster() {
  const t = useSyncExternalStore(subscribe, () => current, () => null)
  return (
    <div className="ui-toast-region" role="status" aria-live="polite">
      {t && (
        <div key={t.id} className={t.tone === 'error' ? 'ui-toast ui-toast--error' : 'ui-toast'}>
          {t.tone === 'error' && <AlertIcon />}
          <span className="ui-toast__text">{t.message}</span>
          {t.action && (
            <button type="button" className="ui-toast__action"
              onClick={() => { t.action?.onClick(); dismissToast() }}>
              {t.action.label}
            </button>
          )}
        </div>
      )}
    </div>
  )
}
