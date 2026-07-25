import type { AuthToken, UserProfile } from '@/types'
import { readClientStorage, removeClientStorage, writeClientStorage } from './client-storage'

const ACCESS_TOKEN_KEY = 'mimirq_access_token'
const USER_KEY = 'mimirq_user_profile'
const USER_ID_KEY = 'mimirq_user_id'
const TENANT_ID_KEY = 'mimirq_tenant_id'
const TOKEN_EXPIRES_AT_KEY = 'mimirq_token_expires_at'
export const DOCUMENT_VIEW_STORAGE_KEY = 'mimirq_document_view_v1'
const TOKEN_STORAGE_KIND = 'session' as const
const LEGACY_TOKEN_STORAGE_KIND = 'local' as const
const AUTH_SYNC_STORAGE_KEY = 'mimirq_auth_sync'
const AUTH_SYNC_CHANNEL_NAME = 'mimirq:auth-sync'
const AUTH_SYNC_CLEAR_TYPE = 'session-cleared'

export const AUTH_SCOPE_CHANGED_EVENT = 'mimirq:auth-scope-changed'
const AUTH_SCOPE_STORAGE_KEYS = new Set([USER_ID_KEY, TENANT_ID_KEY])

type AuthSyncMessage = {
  id: string
  source: string
  type: typeof AUTH_SYNC_CLEAR_TYPE
}

const AUTH_SYNC_SOURCE = `tab:${Math.random().toString(36).slice(2, 10)}`
let authSyncChannel: BroadcastChannel | null = null
let authSyncChannelInitialized = false
let lastHandledAuthSyncMessageId: string | null = null

function getEnvTenantId(): string | null {
  return process.env.NEXT_PUBLIC_TENANT_ID || null
}

function readStoredAccessToken(): string | null {
  return (
    readClientStorage(ACCESS_TOKEN_KEY, TOKEN_STORAGE_KIND) ||
    readClientStorage(ACCESS_TOKEN_KEY, LEGACY_TOKEN_STORAGE_KIND)
  )
}

function hasStoredAccessToken(): boolean {
  return Boolean(readStoredAccessToken())
}

function getAuthScopeTenantId(): string | null {
  if (!hasStoredAccessToken()) return getEnvTenantId()
  return readClientStorage(TENANT_ID_KEY) || getEnvTenantId()
}

function getAuthScopeUserId(): string | null {
  if (!hasStoredAccessToken()) return null
  return readClientStorage(USER_ID_KEY)
}

function buildAuthCacheScope(tenantId: string | null, userId: string | null): string {
  return `${encodeURIComponent(tenantId || 'default')}:${encodeURIComponent(userId || 'anonymous')}`
}

function notifyAuthScopeChanged(previousScope?: string, force = false) {
  if (!force && previousScope !== undefined && previousScope === getAuthCacheScope()) return
  removeClientStorage(DOCUMENT_VIEW_STORAGE_KEY)
  globalThis.window?.dispatchEvent(new Event(AUTH_SCOPE_CHANGED_EVENT))
}

function removeStoredAccessToken() {
  removeClientStorage(ACCESS_TOKEN_KEY, TOKEN_STORAGE_KIND)
  removeClientStorage(ACCESS_TOKEN_KEY, LEGACY_TOKEN_STORAGE_KIND)
  removeClientStorage(TOKEN_EXPIRES_AT_KEY, TOKEN_STORAGE_KIND)
  removeClientStorage(TOKEN_EXPIRES_AT_KEY, LEGACY_TOKEN_STORAGE_KIND)
}

function isAuthSyncMessage(value: unknown): value is AuthSyncMessage {
  if (!value || typeof value !== 'object') return false
  const candidate = value as Partial<AuthSyncMessage>
  return (
    typeof candidate.id === 'string' &&
    typeof candidate.source === 'string' &&
    candidate.type === AUTH_SYNC_CLEAR_TYPE
  )
}

function handleRemoteSessionClear() {
  if (globalThis.window === undefined) return
  const previousScope = getAuthCacheScope()
  removeStoredAccessToken()
  notifyAuthScopeChanged(previousScope, true)
}

function handleAuthSyncMessage(message: AuthSyncMessage) {
  if (message.source === AUTH_SYNC_SOURCE || message.id === lastHandledAuthSyncMessageId) return
  lastHandledAuthSyncMessageId = message.id
  handleRemoteSessionClear()
}

function handleAuthSyncStorageValue(rawValue: string | null) {
  if (!rawValue) return
  try {
    const parsed = JSON.parse(rawValue)
    if (!isAuthSyncMessage(parsed)) return
    handleAuthSyncMessage(parsed)
  } catch {
    // Ignore malformed sync payloads from older builds or manual storage edits.
  }
}

function disposeAuthSyncChannel() {
  authSyncChannel?.close()
  authSyncChannel = null
  authSyncChannelInitialized = false
}

function ensureAuthSyncChannel() {
  if (globalThis.window === undefined || authSyncChannelInitialized) return
  authSyncChannelInitialized = true

  if (typeof globalThis.BroadcastChannel !== 'function') return
  try {
    authSyncChannel = new globalThis.BroadcastChannel(AUTH_SYNC_CHANNEL_NAME)
    authSyncChannel.addEventListener('message', (event: MessageEvent<AuthSyncMessage>) => {
      if (!isAuthSyncMessage(event.data)) return
      handleAuthSyncMessage(event.data)
    })
    globalThis.window.addEventListener('pagehide', disposeAuthSyncChannel, { once: true })
  } catch {
    authSyncChannel = null
  }
}

function broadcastSessionCleared() {
  if (globalThis.window === undefined) return

  const message: AuthSyncMessage = {
    id: `${Date.now()}:${Math.random().toString(36).slice(2, 10)}`,
    source: AUTH_SYNC_SOURCE,
    type: AUTH_SYNC_CLEAR_TYPE,
  }
  lastHandledAuthSyncMessageId = message.id

  ensureAuthSyncChannel()
  authSyncChannel?.postMessage(message)
  writeClientStorage(AUTH_SYNC_STORAGE_KEY, JSON.stringify(message))
}

globalThis.window?.addEventListener('storage', (event) => {
  if (event.key === AUTH_SYNC_STORAGE_KEY) {
    handleAuthSyncStorageValue(event.newValue)
    return
  }
  if (event.key !== null && !AUTH_SCOPE_STORAGE_KEYS.has(event.key)) return
  if (event.key === USER_ID_KEY) {
    if (event.oldValue !== event.newValue && hasStoredAccessToken()) {
      handleRemoteSessionClear()
      return
    }
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

ensureAuthSyncChannel()

export function getAccessToken(): string | null {
  const sessionToken = readClientStorage(ACCESS_TOKEN_KEY, TOKEN_STORAGE_KIND)
  if (sessionToken) return sessionToken

  const legacyToken = readClientStorage(ACCESS_TOKEN_KEY, LEGACY_TOKEN_STORAGE_KIND)
  if (!legacyToken) return null

  writeClientStorage(ACCESS_TOKEN_KEY, legacyToken, TOKEN_STORAGE_KIND)
  removeClientStorage(ACCESS_TOKEN_KEY, LEGACY_TOKEN_STORAGE_KIND)

  const legacyExpiresAt = readClientStorage(TOKEN_EXPIRES_AT_KEY, LEGACY_TOKEN_STORAGE_KIND)
  if (legacyExpiresAt) {
    writeClientStorage(TOKEN_EXPIRES_AT_KEY, legacyExpiresAt, TOKEN_STORAGE_KIND)
    removeClientStorage(TOKEN_EXPIRES_AT_KEY, LEGACY_TOKEN_STORAGE_KIND)
  }

  return legacyToken
}

export function getTenantId(): string | null {
  return readClientStorage(TENANT_ID_KEY) || getEnvTenantId()
}

export function getStoredUserId(): string | null {
  return readClientStorage(USER_ID_KEY)
}

export function getAuthCacheScope(): string {
  return buildAuthCacheScope(getAuthScopeTenantId(), getAuthScopeUserId())
}

export function getStoredUser(): UserProfile | null {
  if (!hasStoredAccessToken()) return null
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
  const previousUserId = getStoredUserId()
  writeClientStorage(ACCESS_TOKEN_KEY, token.access_token, TOKEN_STORAGE_KIND)
  removeClientStorage(ACCESS_TOKEN_KEY, LEGACY_TOKEN_STORAGE_KIND)
  writeClientStorage(USER_KEY, JSON.stringify(user))
  if (previousUserId && previousUserId !== user.id) {
    removeClientStorage(TENANT_ID_KEY)
  }
  writeClientStorage(USER_ID_KEY, user.id)
  const expiresAt = Date.now() + token.expires_in * 1000
  writeClientStorage(TOKEN_EXPIRES_AT_KEY, String(expiresAt), TOKEN_STORAGE_KIND)
  removeClientStorage(TOKEN_EXPIRES_AT_KEY, LEGACY_TOKEN_STORAGE_KIND)
  notifyAuthScopeChanged(previousScope)
}

export function setAccessToken(token: AuthToken) {
  if (globalThis.window === undefined) return
  writeClientStorage(ACCESS_TOKEN_KEY, token.access_token, TOKEN_STORAGE_KIND)
  removeClientStorage(ACCESS_TOKEN_KEY, LEGACY_TOKEN_STORAGE_KIND)
  const expiresAt = Date.now() + token.expires_in * 1000
  writeClientStorage(TOKEN_EXPIRES_AT_KEY, String(expiresAt), TOKEN_STORAGE_KIND)
  removeClientStorage(TOKEN_EXPIRES_AT_KEY, LEGACY_TOKEN_STORAGE_KIND)
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
  removeStoredAccessToken()
  removeClientStorage(USER_KEY)
  removeClientStorage(USER_ID_KEY)
  removeClientStorage(TENANT_ID_KEY)
  notifyAuthScopeChanged(previousScope)
  broadcastSessionCleared()
}
