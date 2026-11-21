function trimTrailingSlashes(value: string): string {
  return value.trim().replace(/\/+$/, '')
}

function hasHttpProtocol(value: string): boolean {
  const lower = value.slice(0, 8).toLowerCase()
  return lower.startsWith('http://') || lower.startsWith('https://')
}

function isLoopbackHost(host: string): boolean {
  return host === 'localhost' || host === '127.0.0.1' || host === '0.0.0.0'
}

function resolveApiBaseUrl(): string {
  const publicUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'
  const internalUrl = process.env.API_INTERNAL_URL?.trim()

  // In Docker, the browser should call the host-mapped backend (usually http://localhost:8000),
  // but the Next.js server (SSR) must call the backend via container-to-container DNS.
  const chosen = globalThis.window === undefined && internalUrl ? internalUrl : publicUrl
  const trimmed = trimTrailingSlashes(chosen)

  // Browsers cannot call 0.0.0.0. Also, when opening the frontend via a LAN IP,
  // hardcoding the backend as localhost/127.0.0.1 will break. Best-effort rewrite
  // these loopback hosts to the current page hostname.
  if (globalThis.window !== undefined) {
    try {
      const url = new URL(trimmed)
      const apiHost = url.hostname.toLowerCase()
      const rawPageHost = globalThis.window.location.hostname.toLowerCase()
      const pageHost = rawPageHost === '0.0.0.0' ? 'localhost' : rawPageHost
      const isDev = process.env.NODE_ENV?.trim().toLowerCase() !== 'production'

      // In browser dev mode, prefer same-origin `/api/v1` so LAN clients do not
      // need direct access to the backend port (e.g. :8000).
      if (isDev && isLoopbackHost(apiHost)) {
        return ''
      }

      if (
        isLoopbackHost(apiHost) &&
        pageHost &&
        (apiHost === '0.0.0.0' || !isLoopbackHost(pageHost) || apiHost !== pageHost)
      ) {
        url.hostname = pageHost
        return trimTrailingSlashes(url.toString())
      }
    } catch {
      // A relative API base is valid for the frontend proxy.
      return trimmed
    }
  }

  return trimmed
}

function readApiTimeoutMs(value: string | undefined, defaultMs: number): number {
  const timeoutText = value?.trim()
  if (timeoutText === undefined || timeoutText === '') return defaultMs
  const timeoutMs = Number(timeoutText)
  return Number.isFinite(timeoutMs) ? timeoutMs : defaultMs
}

export const API_BASE_URL = resolveApiBaseUrl()
export const API_V1_BASE_URL = `${API_BASE_URL}/api/v1`
export const API_TIMEOUT_MS = readApiTimeoutMs(process.env.NEXT_PUBLIC_API_TIMEOUT_MS, 60_000)
export const API_LONG_TIMEOUT_MS = readApiTimeoutMs(process.env.NEXT_PUBLIC_API_LONG_TIMEOUT_MS, 600_000)

export function toAbsoluteBackendUrl(path: string): string {
  if (path === '') return API_BASE_URL
  if (hasHttpProtocol(path)) return path
  return path.startsWith('/') ? `${API_BASE_URL}${path}` : `${API_BASE_URL}/${path}`
}
