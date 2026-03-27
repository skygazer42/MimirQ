const STATIC_CACHE = 'mimirq-static-v2'
const APP_SHELL_CACHE = 'mimirq-app-shell-v2'
const APP_SHELL_URLS = [
  '/',
  '/knowledge',
  '/knowledge/similarity',
  '/graph',
  '/favicon-light.svg',
  '/favicon-dark.svg',
  '/icon.svg',
  '/lottie/empty-documents.json',
  '/lottie/thinking.json',
  '/lottie/processing.json',
]

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(APP_SHELL_CACHE).then((cache) => cache.addAll(APP_SHELL_URLS)).then(() => self.skipWaiting())
  )
})

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys
          .filter((key) => key !== STATIC_CACHE && key !== APP_SHELL_CACHE)
          .map((key) => caches.delete(key))
      )
    ).then(() => self.clients.claim())
  )
})

function isStaticAssetRequest(request) {
  const url = new URL(request.url)
  return url.origin === self.location.origin && (
    url.pathname.startsWith('/_next/static/') ||
    url.pathname.startsWith('/lottie/') ||
    url.pathname.startsWith('/fonts/') ||
    url.pathname.endsWith('.json') ||
    url.pathname.endsWith('.svg') ||
    url.pathname.endsWith('.woff2')
  )
}

self.addEventListener('fetch', (event) => {
  const { request } = event
  if (request.method !== 'GET') return

  if (request.mode === 'navigate') {
    event.respondWith(
      fetch(request).catch(async () => {
        const cache = await caches.open(APP_SHELL_CACHE)
        return (
          (await cache.match(request)) ||
          (await cache.match(new URL(request.url).pathname)) ||
          (await cache.match('/')) ||
          Response.error()
        )
      })
    )
    return
  }

  if (!isStaticAssetRequest(request)) return

  event.respondWith(
    caches.open(STATIC_CACHE).then(async (cache) => {
      const cached = await cache.match(request)
      if (cached) return cached
      const response = await fetch(request)
      cache.put(request, response.clone())
      return response
    })
  )
})
