import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { api, onUnauthorized, readCsrf } from '../api/client'
import type { paths } from '../api/schema'
import { cacheGet, cachePut, wipe } from '../offline/db'
import { forgetKey } from '../offline/crypto'

export type Me = paths['/api/v1/auth/me']['get']['responses']['200']['content']['application/json']
type Status = 'loading' | 'signedOut' | 'signedIn'
export interface Session { status: Status; me?: Me; signOut(): Promise<void> }

const CHANNEL = 'tameio-session'
const SIGNED_OUT = 'signedOut'

const Ctx = createContext<Session>({ status: 'loading', signOut: async () => {} })
// eslint-disable-next-line react/only-export-components
export const useSession = () => useContext(Ctx)

function openChannel(): BroadcastChannel | null {
  return typeof BroadcastChannel === 'function' ? new BroadcastChannel(CHANNEL) : null
}

export function SessionProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<Status>('loading')
  const [me, setMe] = useState<Me>()
  // Bumped on every sign-out; async work started under an older epoch must not sign anyone back in.
  const epoch = useRef(0)
  const channel = useRef<BroadcastChannel | null>(null)

  const markSignedOut = useCallback(() => {
    epoch.current++
    setMe(undefined)
    setStatus('signedOut')
  }, [])

  const signedOut = useCallback(async () => {
    epoch.current++
    channel.current?.postMessage(SIGNED_OUT)
    try {
      await wipe()
    } catch {
      // The key is already forgotten; a failed clear leaves only unreadable ciphertext.
    }
    markSignedOut()
  }, [markSignedOut])

  // Another tab signed out: the shared IndexedDB is already wiped there, so drop our in-memory key.
  useEffect(() => {
    const ch = openChannel()
    channel.current = ch
    if (!ch) return
    ch.onmessage = (e: MessageEvent) => {
      if (e.data !== SIGNED_OUT) return
      forgetKey()
      markSignedOut()
    }
    return () => {
      ch.close()
      if (channel.current === ch) channel.current = null
    }
  }, [markSignedOut])

  useEffect(() => onUnauthorized(() => void signedOut()), [signedOut])

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
      const res = await api.GET('/api/v1/auth/me').catch(() => null)
      if (!current()) return
      if (!res) return fromCache() // offline
      const { data, response } = res
      if (response.ok && data) {
        setMe(data)
        setStatus('signedIn')
        await cachePut('me', data).catch(() => {}) // a racing wipe wins; nothing to persist
      } else if (response.status === 401) {
        await signedOut() // usually already handled by onUnauthorized, which bumps the epoch first
      } else {
        await fromCache() // server error: behave as offline rather than signing the user out
      }
    })()
    return () => {
      live = false
    }
  }, [signedOut])

  const signOut = useCallback(async () => {
    await fetch('/app/auth/logout', {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'X-CSRF-Token': readCsrf() },
    }).catch(() => {})
    await signedOut()
  }, [signedOut])

  const value = useMemo(() => ({ status, me, signOut }), [status, me, signOut])
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}
