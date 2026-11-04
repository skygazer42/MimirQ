import {
  clearAuthSession,
  getAccessToken,
  getAuthCacheScope,
  getAuthSessionRevision,
  setAccessToken,
} from '@/lib/auth-storage'
import { tryRefreshOidcAccessToken } from '@/lib/oidc-session'

type AuthenticatedFetchOptions = RequestInit & {
  allowSessionLogoutOnUnauthorized?: boolean
}

type InflightOidcRefresh = {
  sessionToken: string
  sessionRevision: number
  scope: string
  promise: Promise<Awaited<ReturnType<typeof tryRefreshOidcAccessToken>>>
}

let inflightOidcRefresh: InflightOidcRefresh | null = null

function getRequestHeaders(input: RequestInfo | URL, headers?: HeadersInit): Headers {
  const merged = new Headers(input instanceof Request ? input.headers : undefined)
  new Headers(headers).forEach((value, key) => {
    merged.set(key, value)
  })
  return merged
}

export async function authenticatedFetch(
  input: RequestInfo | URL,
  init: AuthenticatedFetchOptions = {},
): Promise<Response> {
  const { allowSessionLogoutOnUnauthorized = true, ...requestInit } = init
  const sessionRevision = getAuthSessionRevision()
  const scope = getAuthCacheScope()
  const signal = requestInit.signal ?? (input instanceof Request ? input.signal : undefined)
  const headers = getRequestHeaders(input, requestInit.headers)
  let response = await fetch(input, requestInit)
  if (response.status !== 401) return response
  signal?.throwIfAborted()
  const ownsSession = () => sessionRevision === getAuthSessionRevision() && scope === getAuthCacheScope()
  if (!ownsSession()) return response

  const token = getAccessToken()
  const requestAuthorization = headers.get('Authorization')
  const requestUsesSessionToken = !!token && requestAuthorization === `Bearer ${token}`
  const canAttemptRefresh = requestUsesSessionToken && globalThis.window !== undefined
  let attemptedSessionToken = token

  if (canAttemptRefresh && token) {
    const refreshed = await getSharedOidcRefreshResult(token, sessionRevision, scope)
    signal?.throwIfAborted()
    if (!ownsSession()) return response
    const activeToken = getAccessToken()
    const canReuseRefreshResult = !!refreshed && (activeToken === token || activeToken === refreshed.access_token)

    if (refreshed && canReuseRefreshResult) {
      if (activeToken !== refreshed.access_token) {
        setAccessToken(refreshed)
      }
      attemptedSessionToken = refreshed.access_token
      headers.set('Authorization', `Bearer ${refreshed.access_token}`)
      response = await fetch(input, {
        ...requestInit,
        headers,
      })
      if (response.status !== 401) return response
    }
  }

  if (!allowSessionLogoutOnUnauthorized) return response
  signal?.throwIfAborted()
  if (!ownsSession()) return response
  const activeToken = getAccessToken()
  if (!token || !requestUsesSessionToken || activeToken !== attemptedSessionToken) return response

  clearAuthSession()
  if (globalThis.window === undefined) return response

  const path = String(globalThis.window.location?.pathname || '')
  if (!path.startsWith('/auth')) {
    globalThis.window.location.href = '/auth'
  }

  return response
}

async function getSharedOidcRefreshResult(
  sessionToken: string,
  sessionRevision: number,
  scope: string,
): Promise<Awaited<ReturnType<typeof tryRefreshOidcAccessToken>>> {
  if (
    !inflightOidcRefresh ||
    inflightOidcRefresh.sessionToken !== sessionToken ||
    inflightOidcRefresh.sessionRevision !== sessionRevision ||
    inflightOidcRefresh.scope !== scope
  ) {
    const promise = Promise.resolve(tryRefreshOidcAccessToken()).finally(() => {
      if (inflightOidcRefresh?.promise === promise) {
        inflightOidcRefresh = null
      }
    })
    inflightOidcRefresh = {
      sessionToken,
      sessionRevision,
      scope,
      promise,
    }
  }
  return inflightOidcRefresh.promise
}
