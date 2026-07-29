// InterPay console service worker - hand-rolled, no dependencies.
//
// Goal: an app that opens INSTANTLY and works offline for its shell, on modest phones and slow
// networks - WITHOUT ever caching money data. The rule that makes that safe: this worker only
// touches requests under its own scope (/console/, i.e. the built shell). Everything else - every
// API call (/auth, /transactions, /charges, /merchants, /ussd, ...) and every QR image - is left
// entirely to the network, so it is always fresh and never served from cache.

const VERSION = 'interpay-v1'
const BASE = '/console/'
const SHELL = [BASE, BASE + 'index.html', BASE + 'icon.svg', BASE + 'manifest.webmanifest']

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches
      .open(VERSION)
      .then((c) => c.addAll(SHELL))
      .then(() => self.skipWaiting()),
  )
})

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== VERSION).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  )
})

self.addEventListener('fetch', (event) => {
  const { request } = event
  if (request.method !== 'GET') return
  const url = new URL(request.url)

  // Only the shell is ours. API calls and cross-origin requests fall straight through to the
  // network - untouched, uncached, always live. This is the money-safety guarantee.
  if (url.origin !== self.location.origin || !url.pathname.startsWith(BASE)) return

  // Navigations: network-first so a new deploy is picked up, cached shell as the offline fallback.
  if (request.mode === 'navigate') {
    event.respondWith(
      fetch(request).catch(() =>
        caches.match(BASE + 'index.html').then((r) => r || caches.match(BASE)),
      ),
    )
    return
  }

  // Content-hashed build assets are immutable - serve from cache, fetch+store on a miss.
  event.respondWith(
    caches.match(request).then(
      (hit) =>
        hit ||
        fetch(request).then((res) => {
          if (res.ok) {
            const copy = res.clone()
            caches.open(VERSION).then((c) => c.put(request, copy))
          }
          return res
        }),
    ),
  )
})
