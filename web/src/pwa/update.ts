// Applies service-worker updates at a safe moment: never reload under the user while the app is visible.
export const INITIAL_WINDOW_MS = 3000
export const UPDATE_CHECK_INTERVAL_MS = 30 * 60 * 1000

export interface UpdateDeps {
  /** Registers the SW; returns updateSW (posts SKIP_WAITING and reloads on controllerchange). */
  register: (opts: {
    onNeedRefresh: () => void
    onRegisteredSW: (url: string, registration: ServiceWorkerRegistration | undefined) => void
  }) => (reload?: boolean) => Promise<void>
  doc?: Pick<Document, 'visibilityState' | 'addEventListener'>
  now?: () => number
}

export function setupPwaUpdates({ register, doc = document, now = Date.now }: UpdateDeps) {
  const start = now()
  let waiting = false
  let applied = false
  let lastCheck = start
  let registration: ServiceWorkerRegistration | undefined

  const apply = () => {
    if (applied) return
    applied = true
    void updateSW(true)
  }

  const updateSW = register({
    onNeedRefresh() {
      waiting = true
      if (now() - start <= INITIAL_WINDOW_MS) apply()
    },
    onRegisteredSW(_url, reg) {
      registration = reg
    },
  })

  doc.addEventListener('visibilitychange', () => {
    if (doc.visibilityState === 'hidden') {
      if (waiting) apply()
    } else if (registration && now() - lastCheck >= UPDATE_CHECK_INTERVAL_MS) {
      lastCheck = now()
      void registration.update().catch(() => {})
    }
  })
}
