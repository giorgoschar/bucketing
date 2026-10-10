// Runs after `vite build` (npm "postbuild"): fails the build if the emitted /app/ worker lost a
// Phase 1 behaviour or the 2d push handlers. src/sw.test.ts pins the logic; this pins the output.
import { readFileSync, readdirSync, statSync } from 'node:fs'

const sw = readFileSync(new URL('../dist/sw.js', import.meta.url), 'utf8')
const manifest = JSON.parse(readFileSync(new URL('../dist/manifest.webmanifest', import.meta.url), 'utf8'))
const entry = readFileSync(new URL('../dist/index.html', import.meta.url), 'utf8')

function themeBootFirst(html) {
  const tag = /<script\b[^>]*theme-boot\.js[^>]*>/.exec(html)?.[0]
  if (!tag || /type=|async|defer/.test(tag)) return false
  const at = html.indexOf(tag)
  const before = (needle) => html.indexOf(needle) === -1 || at < html.indexOf(needle)
  return at < html.indexOf('</head>') && before('type="module"') && before('rel="stylesheet"')
}

// The entry chunk is the one the page loads first; a lazy boundary that turns static (or a shared dependency the
// chunker pulls in) shows up here first. 323 kB at the Pantry release; 340 kB is the ceiling.
const MAIN_CHUNK_MAX = 340_000
const assets = new URL('../dist/assets/', import.meta.url)
const mainChunk = readdirSync(assets).find((f) => /^index-.*\.js$/.test(f))
const mainBytes = mainChunk ? statSync(new URL(mainChunk, assets)).size : Infinity

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
  ['a tap on an open app window asks the page to navigate (no reload)', /type:[`"]navigate[`"]/.test(sw)],
  ['the manifest keeps the /app/ scope', manifest.scope === '/app/' && manifest.start_url === '/app/' && manifest.id === '/app/'],
  ['the page links the manifest under /app/', entry.includes('/app/manifest.webmanifest')],
  [`the main chunk stays under ${MAIN_CHUNK_MAX / 1000} kB (${mainChunk} is ${(mainBytes / 1000).toFixed(1)} kB)`, mainBytes <= MAIN_CHUNK_MAX],
  ['react-router is its own precached chunk, not part of the main chunk', urls.some((u) => /^assets\/router-.*\.js$/.test(u))],
  // The Activity tab root is a lazy chunk (Phase A): a cold start offline needs its code and its styles.
  ['the Activity chunk (JS and CSS) is precached', urls.some((u) => /^assets\/ActivityRoute-.*\.js$/.test(u)) && urls.some((u) => /^assets\/ActivityRoute-.*\.css$/.test(u))],
  // Settings › Appearance: the before-first-paint boot must work offline and stay render-blocking.
  ['the theme boot script is precached', urls.includes('theme-boot.js')],
  ['the page loads the theme boot as a classic script in head, before the module script and the stylesheet', themeBootFirst(entry)],
]

const failed = checks.filter(([, ok]) => !ok)
for (const [name, ok] of checks) console.log(`${ok ? 'ok  ' : 'FAIL'} sw: ${name}`)
if (failed.length) {
  console.error(`check-sw: ${failed.length} check(s) failed`)
  process.exit(1)
}
