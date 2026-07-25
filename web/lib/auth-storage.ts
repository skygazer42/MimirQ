import type { AuthToken, UserProfile } from '@/types'
import { readClientStorage, removeClientStorage, writeClientStorage } from './client-storage'

const ACCESS_TOKEN_KEY = 'mimirq_access_token'
const USER_KEY = 'mimirq_user_profile'
const USER_ID_KEY = 'mimirq_user_id'
const TENANT_ID_KEY = 'mimirq_tenant_id'
const TOKEN_EXPIRES_AT_KEY = 'mimirq_token_expires_at'
export const DOCUMENT_VIEW_STORAGE_KEY = 'mimirq_document_view_v1'

export const AUTH_SCOPE_CHANGED_EVENT = 'mimirq:auth-scope-changed'
const AUTH_SCOPE_STORAGE_KEYS = new Set([USER_ID_KEY, TENANT_ID_KEY])

function buildAuthCacheScope(tenantId: string | null, userId: string | null): string {
  return `${encodeURIComponent(tenantId || 'default')}:${encodeURIComponent(userId || 'anonymous')}`
}

function notifyAuthScopeChanged(previousScope?: string) {
  if (previousScope !== undefined && previousScope === getAuthCacheScope()) return
  removeClientStorage(DOCUMENT_VIEW_STORAGE_KEY)
  globalThis.window?.dispatchEvent(new Event(AUTH_SCOPE_CHANGED_EVENT))
}

globalThis.window?.addEventListener('storage', (event) => {
  if (event.key !== null && !AUTH_SCOPE_STORAGE_KEYS.has(event.key)) return
  if (event.key === USER_ID_KEY) {
    notifyAuthScopeChanged(buildAuthCacheScope(getTenantId(), event.oldValue))
    return
  }
  if (event.key === TENANT_ID_KEY) {
    notifyAuthScopeChanged(
      buildAuthCacheScope(event.oldValue || process.env.NEXT_PUBLIC_TENANT_ID || null, getStoredUserId())
    )
    return
  }
  notifyAuthScopeChanged()
})

export function getAccessToken(): string | null {
  return readClientStorage(ACCESS_TOKEN_KEY)
}

export function getTenantId(): string | null {
  const envTenantId = process.env.NEXT_PUBLIC_TENANT_ID
  return readClientStorage(TENANT_ID_KEY) || envTenantId || null
}

export function getStoredUserId(): string | null {
  return readClientStorage(USER_ID_KEY)
}

export function getAuthCacheScope(): string {
  return buildAuthCacheScope(getTenantId(), getStoredUserId())
}

export function getStoredUser(): UserProfile | null {
  const raw = readClientStorage(USER_KEY)
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
  const previousScope = getAuthCacheScope()
  writeClientStorage(ACCESS_TOKEN_KEY, token.access_token)
  writeClientStorage(USER_KEY, JSON.stringify(user))
  writeClientStorage(USER_ID_KEY, user.id)
  const expiresAt = Date.now() + token.expires_in * 1000
  writeClientStorage(TOKEN_EXPIRES_AT_KEY, String(expiresAt))
  notifyAuthScopeChanged(previousScope)
}

export function setAccessToken(token: AuthToken) {
  if (globalThis.window === undefined) return
  writeClientStorage(ACCESS_TOKEN_KEY, token.access_token)
  const expiresAt = Date.now() + token.expires_in * 1000
  writeClientStorage(TOKEN_EXPIRES_AT_KEY, String(expiresAt))
}

export function setStoredUser(user: UserProfile) {
  if (globalThis.window === undefined) return
  const previousScope = getAuthCacheScope()
  writeClientStorage(USER_KEY, JSON.stringify(user))
  writeClientStorage(USER_ID_KEY, user.id)
  notifyAuthScopeChanged(previousScope)
}

export function clearAuthSession() {
  if (globalThis.window === undefined) return
  const previousScope = getAuthCacheScope()
  removeClientStorage(ACCESS_TOKEN_KEY)
  removeClientStorage(USER_KEY)
  removeClientStorage(USER_ID_KEY)
  removeClientStorage(TOKEN_EXPIRES_AT_KEY)
  notifyAuthScopeChanged(previousScope)
}
