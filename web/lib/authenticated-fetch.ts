import { clearAuthSession, getAccessToken, getAuthSessionKey, setAccessToken } from '@/lib/auth-storage'
import { tryRefreshOidcAccessToken } from '@/lib/oidc-session'

type AuthenticatedFetchOptions = RequestInit & {
  allowSessionLogoutOnUnauthorized?: boolean
}

export async function authenticatedFetch(
  input: RequestInfo | URL,
  init: AuthenticatedFetchOptions = {},
): Promise<Response> {
  const { allowSessionLogoutOnUnauthorized = true, ...requestInit } = init
  const sessionKey = getAuthSessionKey()
  const sentToken = getAccessToken()
  const request = input instanceof Request ? input : undefined
  const signal = requestInit.signal === undefined ? request?.signal : requestInit.signal
  const headers = new Headers(requestInit.headers === undefined ? request?.headers : requestInit.headers)
  let response = await fetch(input, requestInit)
  if (response.status !== 401) return response
  signal?.throwIfAborted()
  const ownsSession = () => sessionKey === getAuthSessionKey()
  if (!ownsSession()) return response

  if (sentToken === null || headers.get('Authorization') !== `Bearer ${sentToken}`) return response
  let attemptedSessionToken = sentToken

  if (globalThis.window !== undefined) {
    const refreshed =
      getAccessToken() === sentToken ? await tryRefreshOidcAccessToken().finally(() => signal?.throwIfAborted()) : null
    if (!ownsSession()) return response
    const activeToken = getAccessToken()
    if (activeToken === null) return response
    const tokenRotated = activeToken !== sentToken
    if (!tokenRotated && refreshed !== null) setAccessToken(refreshed)
    const retryToken = tokenRotated ? activeToken : refreshed?.access_token
    if (retryToken !== undefined) {
      attemptedSessionToken = retryToken
      headers.set('Authorization', `Bearer ${retryToken}`)
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
  if (getAccessToken() !== attemptedSessionToken) return response

  clearAuthSession()
  if (globalThis.window === undefined) return response

  const path = globalThis.window.location.pathname
  if (!path.startsWith('/auth')) {
    globalThis.window.location.href = '/auth'
  }

  return response
}
