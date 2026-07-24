import { clearAuthSession, getAccessToken, setAccessToken } from '@/lib/auth-storage'
import { tryRefreshOidcAccessToken } from '@/lib/oidc-session'

type AuthenticatedFetchOptions = RequestInit & {
  allowSessionLogoutOnUnauthorized?: boolean
}

function getRequestHeaders(input: RequestInfo | URL, headers?: HeadersInit): Headers {
  const merged = new Headers(input instanceof Request ? input.headers : undefined)
  new Headers(headers).forEach((value, key) => {
    merged.set(key, value)
  })
  return merged
}

export async function authenticatedFetch(
  input: RequestInfo | URL,
  init: AuthenticatedFetchOptions = {}
): Promise<Response> {
  const { allowSessionLogoutOnUnauthorized = true, ...requestInit } = init
  let response = await fetch(input, requestInit)
  if (response.status !== 401) return response

  const token = getAccessToken()
  const headers = getRequestHeaders(input, requestInit.headers)
  const requestAuthorization = headers.get('Authorization')
  const requestUsesSessionToken = !!token && requestAuthorization === `Bearer ${token}`
  const canAttemptRefresh = requestUsesSessionToken && globalThis.window !== undefined

  if (canAttemptRefresh) {
    const refreshed = await tryRefreshOidcAccessToken()
    if (refreshed) {
      setAccessToken(refreshed)
      headers.set('Authorization', `Bearer ${refreshed.access_token}`)
      response = await fetch(input, {
        ...requestInit,
        headers,
      })
      if (response.status !== 401) return response
    }
  }

  if (!allowSessionLogoutOnUnauthorized) return response
  if (!token || !requestUsesSessionToken) return response

  clearAuthSession()
  if (globalThis.window === undefined) return response

  const path = String(globalThis.window.location?.pathname || '')
  if (!path.startsWith('/auth')) {
    globalThis.window.location.href = '/auth'
  }

  return response
}
