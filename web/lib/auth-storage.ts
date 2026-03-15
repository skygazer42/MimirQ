import type { AuthToken, UserProfile } from '@/types'

const ACCESS_TOKEN_KEY = 'mimirq_access_token'
const USER_KEY = 'mimirq_user_profile'
const USER_ID_KEY = 'mimirq_user_id'
const TENANT_ID_KEY = 'mimirq_tenant_id'
const TOKEN_EXPIRES_AT_KEY = 'mimirq_token_expires_at'

export function getAccessToken(): string | null {
  if (globalThis.window === undefined) return null
  return globalThis.window.localStorage.getItem(ACCESS_TOKEN_KEY)
}

export function getTenantId(): string | null {
  const envTenantId = process.env.NEXT_PUBLIC_TENANT_ID
  if (globalThis.window === undefined) return envTenantId || null
  return globalThis.window.localStorage.getItem(TENANT_ID_KEY) || envTenantId || null
}

export function getStoredUser(): UserProfile | null {
  if (globalThis.window === undefined) return null
  const raw = globalThis.window.localStorage.getItem(USER_KEY)
  if (!raw) return null
  try {
    return JSON.parse(raw) as UserProfile
  } catch {
    return null
  }
}

export function setAuthSession(params: { token: AuthToken; user: UserProfile }) {
  if (globalThis.window === undefined) return
  const { token, user } = params
  globalThis.window.localStorage.setItem(ACCESS_TOKEN_KEY, token.access_token)
  globalThis.window.localStorage.setItem(USER_KEY, JSON.stringify(user))
  globalThis.window.localStorage.setItem(USER_ID_KEY, user.id)
  const expiresAt = Date.now() + token.expires_in * 1000
  globalThis.window.localStorage.setItem(TOKEN_EXPIRES_AT_KEY, String(expiresAt))
}

export function setAccessToken(token: AuthToken) {
  if (globalThis.window === undefined) return
  globalThis.window.localStorage.setItem(ACCESS_TOKEN_KEY, token.access_token)
  const expiresAt = Date.now() + token.expires_in * 1000
  globalThis.window.localStorage.setItem(TOKEN_EXPIRES_AT_KEY, String(expiresAt))
}

export function setStoredUser(user: UserProfile) {
  if (globalThis.window === undefined) return
  globalThis.window.localStorage.setItem(USER_KEY, JSON.stringify(user))
  globalThis.window.localStorage.setItem(USER_ID_KEY, user.id)
}

export function clearAuthSession() {
  if (globalThis.window === undefined) return
  globalThis.window.localStorage.removeItem(ACCESS_TOKEN_KEY)
  globalThis.window.localStorage.removeItem(USER_KEY)
  globalThis.window.localStorage.removeItem(USER_ID_KEY)
  globalThis.window.localStorage.removeItem(TOKEN_EXPIRES_AT_KEY)
}
