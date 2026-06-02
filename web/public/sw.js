const CACHE_VERSION = 'v4'
const STATIC_CACHE = `mimirq-static-${CACHE_VERSION}`
const APP_SHELL_CACHE = `mimirq-app-shell-${CACHE_VERSION}`
const APP_SHELL_URLS = [
  '/',
  '/knowledge',
  '/knowledge/similarity',
  '/graph',
  '/favicon-light.svg',
  '/favicon-dark.svg',
  '/icon.svg',
]

globalThis.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(APP_SHELL_CACHE).then((cache) => cache.addAll(APP_SHELL_URLS)).then(() => globalThis.skipWaiting())
  )
})

globalThis.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys
          .filter((key) => key !== STATIC_CACHE && key !== APP_SHELL_CACHE)
          .map((key) => caches.delete(key))
      )
    ).then(() => globalThis.clients.claim())
  )
})

const PDF_WORKER_PATTERN = /pdf\.worker(?:\.min)?\.[^.]+\.mjs$/i

function isPdfWorkerRequest(url) {
  return PDF_WORKER_PATTERN.test(url.pathname)
}

function isSupportedStaticPath(url) {
  return (
    url.pathname.startsWith('/_next/static/') ||
    url.pathname.startsWith('/monaco/') ||
    url.pathname.startsWith('/fonts/') ||
    url.pathname.startsWith('/pdfjs-dist/') ||
    url.pathname.endsWith('.svg') ||
    url.pathname.endsWith('.woff2')
  )
}

function isStaticAssetRequest(request) {
  const url = new URL(request.url)
  return url.origin === self.location.origin && (isPdfWorkerRequest(url) || isSupportedStaticPath(url))
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
