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
  const target = new URL(url && url.startsWith('/app/') ? url : '/app/', self.location.origin).href
  event.waitUntil(
    (async () => {
      const windows = await self.clients.matchAll({ type: 'window', includeUncontrolled: true })
      for (const client of windows) {
        if (new URL(client.url).pathname.startsWith('/app/')) {
          try {
            const focused = await client.focus()
            await focused.navigate(target)
            return
          } catch {
            break // not controlled by this worker: open a fresh window instead
          }
        }
      }
      await self.clients.openWindow(target)
    })(),
  )
})
