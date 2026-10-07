// Runs after `vite build` (npm "postbuild"): fails the build if the emitted /app/ worker lost a
// Phase 1 behaviour or the 2d push handlers. src/sw.test.ts pins the logic; this pins the output.
import { readFileSync } from 'node:fs'

const sw = readFileSync(new URL('../dist/sw.js', import.meta.url), 'utf8')
const manifest = JSON.parse(readFileSync(new URL('../dist/manifest.webmanifest', import.meta.url), 'utf8'))
const entry = readFileSync(new URL('../dist/index.html', import.meta.url), 'utf8')

const urls = [...sw.matchAll(/"url":"([^"]+)"/g)].map((m) => m[1])
const count = (s) => sw.split(s).length - 1
const checks = [
  ['the precache manifest was injected', !sw.includes('__WB_MANIFEST') && urls.length > 0],
  ['the app shell and the web manifest are precached', urls.includes('index.html') && urls.includes('manifest.webmanifest')],
  ['the worker never precaches itself', !urls.some((u) => /(^|\/)sw\.js$/.test(u))],
  ['navigations fall back to /app/index.html', sw.includes('/app/index.html')],
  ['/app/auth/ and /api/ are never answered with the shell', sw.includes('denylist:[/^\\/app\\/auth\\//,/^\\/api\\//]')],
  ['updates wait for SKIP_WAITING (one skipWaiting call, behind the message)', sw.includes('SKIP_WAITING') && count('skipWaiting') === 1],
  ['no clients.claim', !/clientsClaim|clients\.claim\(/.test(sw)],
  ['no runtime caching strategies', !/NetworkFirst|CacheFirst|StaleWhileRevalidate|ExpirationPlugin/.test(sw)],
  ['a classic script (iOS registers it as classic)', !/^\s*(import|export)\s/m.test(sw)],
  ['push and notificationclick are handled', /[`"]push[`"]/.test(sw) && /[`"]notificationclick[`"]/.test(sw)],
  ['the manifest keeps the /app/ scope', manifest.scope === '/app/' && manifest.start_url === '/app/' && manifest.id === '/app/'],
  ['the page links the manifest under /app/', entry.includes('/app/manifest.webmanifest')],
]

const failed = checks.filter(([, ok]) => !ok)
for (const [name, ok] of checks) console.log(`${ok ? 'ok  ' : 'FAIL'} sw: ${name}`)
if (failed.length) {
  console.error(`check-sw: ${failed.length} check(s) failed`)
  process.exit(1)
}
