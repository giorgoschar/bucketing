const CACHE_NAME = 'expenses-v2';
const CDN_CACHE = 'expenses-cdn-v2';

const STATIC_ASSETS = [
  '/static/manifest.json',
  '/static/icons/icon-192.png',
  '/static/icons/icon-512.png',
];

// CDN origins to cache with stale-while-revalidate
const CDN_ORIGINS = [
  'cdn.tailwindcss.com',
  'cdn.jsdelivr.net',
  'unpkg.com',
];

// Branded offline page shown when a navigation fails and no cached page exists
const OFFLINE_HTML = `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <meta name="theme-color" content="#6366f1" />
  <title>Offline — Expenses</title>
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
      background: #f9fafb;
      color: #111827;
      display: flex;
      align-items: center;
      justify-content: center;
      min-height: 100dvh;
      padding: 1.5rem;
    }
    .card {
      text-align: center;
      max-width: 320px;
    }
    .icon {
      width: 72px;
      height: 72px;
      border-radius: 20px;
      background: #6366f1;
      display: flex;
      align-items: center;
      justify-content: center;
      margin: 0 auto 1.5rem;
    }
    .icon svg { color: #fff; }
    h1 { font-size: 1.375rem; font-weight: 700; margin-bottom: 0.5rem; }
    p { color: #6b7280; font-size: 0.9375rem; line-height: 1.5; margin-bottom: 1.75rem; }
    button {
      background: #6366f1;
      color: #fff;
      border: none;
      border-radius: 12px;
      padding: 0.75rem 2rem;
      font-size: 0.9375rem;
      font-weight: 600;
      cursor: pointer;
      transition: background 150ms;
    }
    button:hover { background: #4f46e5; }
  </style>
</head>
<body>
  <div class="card">
    <div class="icon">
      <svg width="36" height="36" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.75">
        <path stroke-linecap="round" stroke-linejoin="round" d="M18.364 5.636a9 9 0 11-12.728 0M12 3v9" />
      </svg>
    </div>
    <h1>You're offline</h1>
    <p>Check your connection and try again. Any expenses you add while offline will sync when you reconnect.</p>
    <button onclick="location.reload()">Try again</button>
  </div>
</body>
</html>`;

// Install: pre-cache static assets
self.addEventListener('install', event => {
  self.skipWaiting();
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => cache.addAll(STATIC_ASSETS))
  );
});

// Activate: clean up old caches
self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(
        keys
          .filter(k => k !== CACHE_NAME && k !== CDN_CACHE)
          .map(k => caches.delete(k))
      )
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', event => {
  const { request } = event;
  const url = new URL(request.url);

  // --- CDN assets: stale-while-revalidate ---
  if (CDN_ORIGINS.includes(url.hostname)) {
    event.respondWith(
      caches.open(CDN_CACHE).then(async cache => {
        const cached = await cache.match(request);
        const fetchPromise = fetch(request).then(response => {
          if (response.ok) cache.put(request, response.clone());
          return response;
        }).catch(() => null);
        // Serve cached immediately; background-revalidate
        return cached || fetchPromise;
      })
    );
    return;
  }

  // Only handle same-origin from here on
  if (url.origin !== location.origin) return;

  // --- Same-origin static assets: cache-first ---
  if (url.pathname.startsWith('/static/')) {
    event.respondWith(
      caches.match(request).then(cached => {
        if (cached) return cached;
        return fetch(request).then(response => {
          if (response.ok) {
            const clone = response.clone();
            caches.open(CACHE_NAME).then(cache => cache.put(request, clone));
          }
          return response;
        });
      })
    );
    return;
  }

  // --- HTML navigation: network-first, cache on success, branded offline fallback ---
  if (request.method === 'GET' && request.headers.get('Accept')?.includes('text/html')) {
    event.respondWith(
      fetch(request)
        .then(response => {
          if (response.ok) {
            const clone = response.clone();
            caches.open(CACHE_NAME).then(cache => cache.put(request, clone));
          }
          return response;
        })
        .catch(async () => {
          // Try: cached version of this URL → cached /dashboard → offline page
          const cached = await caches.match(request);
          if (cached) return cached;
          const dashboard = await caches.match('/dashboard');
          if (dashboard) return dashboard;
          return new Response(OFFLINE_HTML, { headers: { 'Content-Type': 'text/html' } });
        })
    );
    return;
  }
});
