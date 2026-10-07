import { useCallback, useEffect, useState } from 'react'
import { fetchJson, type RawResult } from '../data/rawJson'

export type PushState = 'unsupported' | 'not-installed' | 'denied' | 'off' | 'on'

export interface PushEnv {
  /** Installed to the Home Screen: iOS only offers push there. */
  standalone: boolean
  supported: boolean
  permission(): NotificationPermission
  requestPermission(): Promise<NotificationPermission>
  /** The /app/ worker's registration (the old app's / worker is a separate one). */
  registration(): Promise<ServiceWorkerRegistration>
}

export function browserEnv(): PushEnv {
  const supported = 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window
  return {
    standalone: window.matchMedia?.('(display-mode: standalone)').matches || (navigator as Navigator & { standalone?: boolean }).standalone === true,
    supported,
    permission: () => (supported ? Notification.permission : 'denied'),
    requestPermission: () => Notification.requestPermission(),
    registration: () => navigator.serviceWorker.ready,
  }
}

export function urlBase64ToUint8Array(s: string): Uint8Array<ArrayBuffer> {
  const padded = (s + '='.repeat((4 - (s.length % 4)) % 4)).replace(/-/g, '+').replace(/_/g, '/')
  const bin = atob(padded)
  return Uint8Array.from(bin, (c) => c.charCodeAt(0))
}

export async function pushState(env: PushEnv = browserEnv()): Promise<PushState> {
  if (!env.supported) return 'unsupported'
  if (!env.standalone) return 'not-installed'
  if (env.permission() === 'denied') return 'denied'
  const sub = await (await env.registration()).pushManager.getSubscription()
  return sub && env.permission() === 'granted' ? 'on' : 'off'
}

const refused = (): RawResult<unknown> => ({
  response: new Response(null, { status: 403 }),
  error: { detail: 'Notifications are turned off for Tameio. Allow them in iOS Settings.' },
})

/** Permission (from the tap), the server's key, subscribe, POST /push/subscribe. */
export async function enablePush(env: PushEnv = browserEnv()): Promise<RawResult<unknown>> {
  const permission = await env.requestPermission()
  if (permission !== 'granted') return refused()
  const key = await fetchJson<{ public_key: string }>('GET', '/push/vapid-public-key')
  if (!key.response.ok || !key.data) return key
  const reg = await env.registration()
  const sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: urlBase64ToUint8Array(key.data.public_key) })
  // The server must know the subscription, or this device would look "on" and never get a push:
  // when the POST fails, drop the browser subscription again (best effort) so the state stays "off".
  const drop = () => sub.unsubscribe().catch(() => false)
  let res: RawResult<unknown>
  try {
    res = await fetchJson('POST', '/push/subscribe', sub.toJSON())
  } catch (err) {
    await drop()
    throw err
  }
  if (!res.response.ok) await drop()
  return res
}

export async function disablePush(env: PushEnv = browserEnv()): Promise<RawResult<unknown>> {
  const sub = await (await env.registration()).pushManager.getSubscription()
  if (!sub) return { data: { ok: true }, response: new Response(null, { status: 200 }) }
  const res = await fetchJson('DELETE', '/push/subscribe', { endpoint: sub.endpoint })
  if (res.response.ok) await sub.unsubscribe()
  return res
}

export async function sendTestPush(env: PushEnv = browserEnv()): Promise<RawResult<{ sent: boolean; error: string | null }>> {
  const sub = await (await env.registration()).pushManager.getSubscription()
  return fetchJson('POST', '/push/test', { endpoint: sub?.endpoint ?? null })
}

/** This device's push state, re-read on demand (after a toggle) and when the app returns. */
export function usePushState(): { state: PushState | null; refresh(): void } {
  const [state, setState] = useState<PushState | null>(null)
  const refresh = useCallback(() => {
    pushState().then(setState, () => setState('unsupported'))
  }, [])
  useEffect(() => {
    refresh()
    const onVisible = () => { if (document.visibilityState === 'visible') refresh() }
    document.addEventListener('visibilitychange', onVisible)
    return () => document.removeEventListener('visibilitychange', onVisible)
  }, [refresh])
  return { state, refresh }
}
