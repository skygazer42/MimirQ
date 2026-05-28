const STALE_CHUNK_RELOAD_PREFIX = 'mimirq:stale-chunk-reloaded:'

const STALE_CHUNK_PATTERNS = [
  /ChunkLoadError/i,
  /Loading chunk [\w-]+ failed/i,
  /Loading CSS chunk [\w-]+ failed/i,
  /failed to fetch dynamically imported module/i,
  /Importing a module script failed/i,
  /dynamically imported module/i,
]

function getErrorText(error: unknown): string {
  if (error instanceof Error) {
    const digest =
      'digest' in error ? String((error as Error & { digest?: unknown }).digest || '') : ''
    return [error.name, error.message, error.stack, digest].filter(Boolean).join('\n')
  }
  if (typeof error === 'string') return error
  if (!error || typeof error !== 'object') return String(error || '')
  try {
    return JSON.stringify(error)
  } catch {
    return String(error)
  }
}

export function isLikelyStaleChunkError(error: unknown) {
  const text = getErrorText(error)
  return STALE_CHUNK_PATTERNS.some((pattern) => pattern.test(text))
}

export function reloadOnceForStaleChunk(error: unknown) {
  if (!isLikelyStaleChunkError(error)) return false
  if (typeof globalThis.window === 'undefined') return false

  try {
    const storageKey = [
      STALE_CHUNK_RELOAD_PREFIX,
      globalThis.window.location.pathname,
      globalThis.window.location.search,
    ].join('')
    if (globalThis.window.sessionStorage.getItem(storageKey) === '1') return false
    globalThis.window.sessionStorage.setItem(storageKey, '1')
  } catch {
    // If storage is unavailable, still prefer one hard reload over a stale chunk error page.
  }

  globalThis.window.location.reload()
  return true
}
