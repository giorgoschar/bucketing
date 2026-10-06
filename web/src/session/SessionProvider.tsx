import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { api, onUnauthorized, readCsrf } from '../api/client'
import type { paths } from '../api/schema'
import { cacheGet, cachePut, wipe } from '../offline/db'
import { forgetKey } from '../offline/crypto'
import { setIdentity } from '../offline/identity'
import { queryClient } from '../queryClient'

export type Me = paths['/api/v1/auth/me']['get']['responses']['200']['content']['application/json']
type Status = 'loading' | 'signedOut' | 'signedIn'
export interface Session {
  status: Status
  me?: Me
  /** The device was cleared but the server didn't confirm the logout; its session may still be alive. */
  logoutFailed: boolean
  signOut(): Promise<void>
  /** POST the logout again (with a freshly read CSRF cookie); clears `logoutFailed` on success. */
  retryLogout(): Promise<void>
}

const CHANNEL = 'tameio-session'
const SIGNED_OUT = 'signedOut'
const ACCOUNT_SWITCHED = 'ACCOUNT_SWITCHED'
const ME_TIMEOUT_MS = 5000

/** 5xx, 408 and 429 mean "the server can't say right now": keep the cached profile, as when offline. */
const transient = (status: number) => status >= 500 || status === 408 || status === 429

/** True once the server has no session for us (200, or 401 because it was already gone). */
async function serverLogout(): Promise<boolean> {
  const res = await fetch('/app/auth/logout', {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'X-CSRF-Token': readCsrf() },
  }).catch(() => null)
  return !!res && (res.ok || res.status === 401)
}

const Ctx = createContext<Session>({
  status: 'loading',
  logoutFailed: false,
  signOut: async () => {},
  retryLogout: async () => {},
})
// eslint-disable-next-line react/only-export-components
export const useSession = () => useContext(Ctx)

function openChannel(): BroadcastChannel | null {
  return typeof BroadcastChannel === 'function' ? new BroadcastChannel(CHANNEL) : null
}

export function SessionProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<Status>('loading')
  const [me, setMe] = useState<Me>()
  const [logoutFailed, setLogoutFailed] = useState(false)
  // Bumped when another tab switched accounts; re-reads /me so this tab follows the cookie.
  const [reloads, setReloads] = useState(0)
  // Bumped on every sign-out; async work started under an older epoch must not sign anyone back in.
  const epoch = useRef(0)
  const channel = useRef<BroadcastChannel | null>(null)

  // The queue stamps each write with who made it; only a signed-in tab has an identity.
  useEffect(() => {
    setIdentity(me ? { user_id: me.id, household_id: me.household_id } : null)
  }, [me])

  // Sign-out and session expiry both land here. This only drops in-memory state: an expired session
  // keeps the encrypted store so queued writes survive until the same account signs in again.
  const markSignedOut = useCallback(() => {
    epoch.current++
    queryClient.clear()
    setMe(undefined)
    setStatus('signedOut')
  }, [])

  const signedOut = useCallback(async () => {
    epoch.current++
    channel.current?.postMessage(SIGNED_OUT)
    forgetKey()
    try {
      await wipe()
    } catch {
      // The key was forgotten above; a failed clear leaves only ciphertext this session can't open.
    }
    markSignedOut()
  }, [markSignedOut])

  // Another tab signed out: the shared IndexedDB is already wiped there, so drop our in-memory key.
  useEffect(() => {
    const ch = openChannel()
    channel.current = ch
    if (!ch) return
    ch.onmessage = (e: MessageEvent) => {
      if (e.data?.type === ACCOUNT_SWITCHED) {
        // Another tab signed in as a different account and wiped the store: drop our key and identity.
        forgetKey()
        queryClient.clear()
        setReloads((n) => n + 1)
        return
      }
      if (e.data !== SIGNED_OUT) return
      forgetKey()
      markSignedOut()
    }
    return () => {
      ch.close()
      if (channel.current === ch) channel.current = null
    }
  }, [markSignedOut])

  useEffect(() => onUnauthorized(markSignedOut), [markSignedOut])

  useEffect(() => {
    let live = true
    const started = epoch.current
    const current = () => live && epoch.current === started

    const fromCache = async () => {
      const cached = await cacheGet<Me>('me').catch(() => undefined)
      if (!current()) return
      if (cached) {
        setMe(cached)
        setStatus('signedIn')
      } else setStatus('signedOut')
    }

    ;(async () => {
      const res = await api
        .GET('/api/v1/auth/me', { signal: AbortSignal.timeout(ME_TIMEOUT_MS) })
        .catch(() => null)
      if (!current()) return
      if (!res) return fromCache() // offline or timed out
      const { data, response } = res
      if (response.ok && data) {
        // A different account than the one whose data is on this device: nothing of theirs may carry over.
        const cached = await cacheGet<Me>('me').catch(() => undefined)
        if (!current()) return
        if (cached && (cached.id !== data.id || cached.household_id !== data.household_id)) {
          await wipe().catch(() => {}) // the key is forgotten either way; leftovers are unreadable
          if (!current()) return
          channel.current?.postMessage({ type: ACCOUNT_SWITCHED })
        }
        setMe(data)
        setStatus('signedIn')
        await cachePut('me', data).catch(() => {}) // a racing wipe wins; nothing to persist
      } else if (response.status === 401) {
        markSignedOut() // expired session: show sign-in but keep the encrypted queue
      } else if (transient(response.status)) {
        await fromCache() // server unavailable: behave as offline rather than signing the user out
      } else {
        setStatus('signedOut')
      }
    })()
    return () => {
      live = false
    }
  }, [markSignedOut, reloads])

  // Clearing the device wins even when the server can't be reached; the failure is surfaced for a retry.
  const signOut = useCallback(async () => {
    const ok = await serverLogout()
    await signedOut()
    setLogoutFailed(!ok)
  }, [signedOut])

  const retryLogout = useCallback(async () => {
    if (await serverLogout()) setLogoutFailed(false)
  }, [])

  const value = useMemo(
    () => ({ status, me, logoutFailed, signOut, retryLogout }),
    [status, me, logoutFailed, signOut, retryLogout],
  )
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}
