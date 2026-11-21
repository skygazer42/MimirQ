const STALE_CHUNK_RELOAD_PREFIX = 'mimirq:stale-chunk-reloaded:'
const STALE_CHUNK_RELOAD_COOLDOWN_MS = 30_000

const STALE_CHUNK_PATTERNS = [
  /ChunkLoadError/i,
  /Loading chunk [\w-]+ failed/i,
  /Loading CSS chunk [\w-]+ failed/i,
  /failed to fetch dynamically imported module/i,
  /Importing a module script failed/i,
  /dynamically imported module/i,
]

function primitiveErrorText(value: unknown): string {
  if (typeof value === 'string') return value
  if (typeof value === 'number' || typeof value === 'boolean' || typeof value === 'bigint') {
    return String(value)
  }
  return ''
}

function getErrorText(error: unknown): string {
  if (error instanceof Error) {
    const digest = 'digest' in error ? primitiveErrorText(error.digest) : undefined
    return [error.name, error.message, error.stack, digest].filter(Boolean).join('\n')
  }
  if (typeof error === 'string') return error
  if (!error || typeof error !== 'object') return primitiveErrorText(error)
  try {
    return JSON.stringify(error)
  } catch {
    return Object.prototype.toString.call(error)
  }
}

function isLikelyStaleChunkError(error: unknown) {
  const text = getErrorText(error)
  return STALE_CHUNK_PATTERNS.some((pattern) => pattern.test(text))
}

export function reloadOnceForStaleChunk(error: unknown) {
  if (!isLikelyStaleChunkError(error)) return false
  if (globalThis.window === undefined) return false

  try {
    const storageKey = [
      STALE_CHUNK_RELOAD_PREFIX,
      globalThis.window.location.pathname,
      globalThis.window.location.search,
    ].join('')
    const storedReloadTime = globalThis.window.sessionStorage.getItem(storageKey)
    const now = Date.now()
    if (storedReloadTime !== null) {
      const lastReloadedAt = Number(storedReloadTime)
      if (
        Number.isFinite(lastReloadedAt) &&
        lastReloadedAt > 0 &&
        now - lastReloadedAt < STALE_CHUNK_RELOAD_COOLDOWN_MS
      ) {
        return false
      }
    }
    globalThis.window.sessionStorage.setItem(storageKey, String(now))
  } catch {
    return false
  }

  globalThis.window.location.reload()
  return true
}
