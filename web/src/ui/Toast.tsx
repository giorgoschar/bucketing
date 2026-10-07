import { useSyncExternalStore } from 'react'
import { AlertIcon } from './icons'

export interface ToastAction { label: string; onClick: () => void }
export interface ToastOptions { action?: ToastAction; durationMs?: number; tone?: 'default' | 'error' }
interface Shown extends ToastOptions { id: number; message: string }

const DEFAULT_MS = 4000
/** After a pause, a toast always gets at least this long before it goes. */
const MIN_RESUME_MS = 1000
let current: Shown | null = null
let seq = 0
let timer: ReturnType<typeof setTimeout> | undefined
let deadline = 0
let remaining = 0
let paused = false
const subs = new Set<() => void>()
const emit = () => subs.forEach((cb) => cb())
const subscribe = (cb: () => void) => {
  subs.add(cb)
  return () => { subs.delete(cb) }
}

function startTimer(ms: number) {
  clearTimeout(timer)
  deadline = Date.now() + ms
  timer = setTimeout(dismissToast, ms)
}

/** Show a toast; it replaces the one on screen. Callable outside React (useAction uses it). */
export function toast(message: string, opts: ToastOptions = {}): void {
  paused = false
  current = { ...opts, id: ++seq, message }
  emit()
  startTimer(opts.durationMs ?? DEFAULT_MS)
}

export function dismissToast(): void {
  clearTimeout(timer)
  paused = false
  if (!current) return
  current = null
  emit()
}

/** Hold the toast while the user is reaching for its action (focus or hover). */
function pauseToast(): void {
  if (!current || paused) return
  paused = true
  clearTimeout(timer)
  remaining = Math.max(0, deadline - Date.now())
}

function resumeToast(): void {
  if (!current || !paused) return
  paused = false
  startTimer(Math.max(remaining, MIN_RESUME_MS))
}

const handle = { show: toast, dismiss: dismissToast }
/** For components that prefer a hook; the functions are module-level and stable. */
export function useToast(): typeof handle {
  return handle
}

/**
 * Rendered once by AppShell (and by renderWithProviders in tests). A polite status region that is always
 * present (so screen readers pick up its changes) holds ordinary toasts; an error toast is an assertive
 * alert, inserted when it appears.
 */
export function Toaster() {
  const t = useSyncExternalStore(subscribe, () => current, () => null)
  const isError = t?.tone === 'error'
  const hold = t?.action
    ? { onPointerEnter: pauseToast, onPointerLeave: resumeToast, onFocus: pauseToast, onBlur: resumeToast }
    : {}
  const body = t && (
    <div key={t.id} className={isError ? 'ui-toast ui-toast--error' : 'ui-toast'} {...hold}>
      {isError && <AlertIcon />}
      <span className="ui-toast__text">{t.message}</span>
      {t.action && (
        <button type="button" className="ui-toast__action"
          onClick={() => { t.action?.onClick(); dismissToast() }}>
          {t.action.label}
        </button>
      )}
    </div>
  )
  return (
    <div className="ui-toast-region">
      <div role="status" aria-live="polite">{!isError && body}</div>
      {isError && <div role="alert">{body}</div>}
    </div>
  )
}
