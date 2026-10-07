/// <reference lib="webworker" />
// The /app/ service worker (vite-plugin-pwa injectManifest). Phase 1 behaviour, kept exactly:
// precache the build, answer navigations with the app shell except /app/auth/* and /api/*,
// no runtime caching (API data lives in the encrypted Dexie store), and no skipWaiting on install
// or clientsClaim: the new worker waits until src/pwa/update.ts posts SKIP_WAITING at a safe moment.
// Added in 2d: push and notificationclick. Pinned by src/sw.test.ts and scripts/check-sw.mjs.
import { cleanupOutdatedCaches, createHandlerBoundToURL, precacheAndRoute, type PrecacheEntry } from 'workbox-precaching'
import { NavigationRoute, registerRoute } from 'workbox-routing'
import { noticeFromPush } from './pwa/pushPayload'

declare const self: ServiceWorkerGlobalScope & { __WB_MANIFEST: Array<PrecacheEntry | string> }

self.addEventListener('message', (event) => {
  if (event.data && event.data.type === 'SKIP_WAITING') void self.skipWaiting()
})

precacheAndRoute(self.__WB_MANIFEST)
cleanupOutdatedCaches()
registerRoute(
  new NavigationRoute(createHandlerBoundToURL('/app/index.html'), {
    // Server routes (passkey redirects) and the API must never be answered with the shell.
    denylist: [/^\/app\/auth\//, /^\/api\//],
  }),
)

self.addEventListener('push', (event) => {
  const notice = noticeFromPush(event.data ? event.data.text() : null)
  event.waitUntil(self.registration.showNotification(notice.title, notice.options))
})

self.addEventListener('notificationclick', (event) => {
  event.notification.close()
  const url = (event.notification.data as { url?: string } | null)?.url
  // Only ever open a page inside the app's scope.
  const path = url && url.startsWith('/app/') && !url.startsWith('//') ? url : '/app/'
  const target = new URL(path, self.location.origin).href
  const inApp = (client: Client) => new URL(client.url).pathname.startsWith('/app/')
  event.waitUntil(
    (async () => {
      // An app window this worker controls navigates with its router (no reload): see src/pwa/swMessages.ts.
      const controlled = (await self.clients.matchAll({ type: 'window' })).find(inApp) as WindowClient | undefined
      if (controlled) {
        controlled.postMessage({ type: 'navigate', url: path })
        await controlled.focus()
        return
      }
      // Any other app window (open before this worker took over): navigate it directly.
      const other = (await self.clients.matchAll({ type: 'window', includeUncontrolled: true })).find(inApp) as WindowClient | undefined
      if (other) {
        try {
          const focused = await other.focus()
          await focused.navigate(target)
          return
        } catch {
          // not navigable by this worker: open a fresh window instead
        }
      }
      await self.clients.openWindow(target)
    })(),
  )
})
