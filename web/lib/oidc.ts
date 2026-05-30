'use client'

import type { AuthResponse, AuthToken, UserProfile } from '@/types'
import { setAuthSession } from '@/lib/auth-storage'
import { toTrimmedPrimitiveString } from '@/lib/primitive-text'
import { generateOauthState, generatePkceCodeVerifier, pkceChallengeFromVerifier, tryDecodeJwtPayload } from '@/lib/oidc-pkce'
import { getOidcPublicProvidersFromEnv, resolveOidcPublicProvider } from '@/lib/oidc-providers'

type OidcDiscovery = {
  authorization_endpoint: string
  token_endpoint: string
  issuer?: string
}

type OidcTokenResponse = {
  access_token?: string
  token_type?: string
  expires_in?: number
  refresh_token?: string
  id_token?: string
  scope?: string
  error?: string
  error_description?: string
}

type OidcTransaction = {
  v: 1 | 2
  created_at_ms: number
  provider_id?: string
  issuer: string
  client_id: string
  redirect_uri: string
  code_verifier: string
  return_to: string
}

const TX_KEY_PREFIX = 'mimirq_oidc_tx:'

function readEnv(name: string): string {
  // Next.js replaces process.env.* at build time for NEXT_PUBLIC_* variables.
  return String((process.env as Record<string, string | undefined>)[name] || '').trim()
}

function isFalsey(value: string): boolean {
  const v = String(value || '').trim().toLowerCase()
  return v === '0' || v === 'false' || v === 'no' || v === 'off' || v === 'disabled'
}

function parseAuthParams(raw: string): Record<string, string> {
  const out: Record<string, string> = {}
  const trimmed = String(raw || '').trim()
  if (!trimmed) return out

  const params = new URLSearchParams(trimmed.startsWith('?') ? trimmed.slice(1) : trimmed)
  for (const [key, value] of params.entries()) {
    const k = String(key || '').trim()
    if (!k) continue
    out[k] = String(value || '')
  }
  return out
}

function resolveRedirectUri(): string {
  const override = readEnv('NEXT_PUBLIC_OIDC_REDIRECT_URI')
  if (override) return override

  if (globalThis.window === undefined) {
    // Only used client-side; keep a stable placeholder for type safety.
    return '/auth/oidc/callback'
  }
  return `${globalThis.window.location.origin}/auth/oidc/callback`
}

function resolveScopes(): string {
  const scopes = readEnv('NEXT_PUBLIC_OIDC_SCOPES')
  return scopes || 'openid profile email'
}

function txStorageKey(state: string): string {
  return `${TX_KEY_PREFIX}${state}`
}

function sessionSet(key: string, value: string) {
  try {
    globalThis.window.sessionStorage.setItem(key, value)
  } catch {
    // ignore
  }
}

function sessionGet(key: string): string | null {
  try {
    return globalThis.window.sessionStorage.getItem(key)
  } catch {
    return null
  }
}

function sessionDel(key: string) {
  try {
    globalThis.window.sessionStorage.removeItem(key)
  } catch {
    // ignore
  }
}

let cachedDiscovery: { issuer: string; value: OidcDiscovery } | null = null

async function discover(issuer: string): Promise<OidcDiscovery> {
  const cached = cachedDiscovery
  if (cached?.issuer === issuer) return cached.value

  const url = `${issuer}/.well-known/openid-configuration`
  const res = await fetch(url, { method: 'GET' })
  if (!res.ok) {
    throw new Error(`oidc_discovery_failed_${res.status}`)
  }
  const data = (await res.json().catch(() => null))
  if (!data || typeof data !== 'object') {
    throw new Error('oidc_discovery_invalid')
  }

  const authorizationEndpoint = String(data.authorization_endpoint || '').trim()
  const tokenEndpoint = String(data.token_endpoint || '').trim()
  if (!authorizationEndpoint || !tokenEndpoint) {
    throw new Error('oidc_discovery_missing_endpoints')
  }

  const out: OidcDiscovery = {
    authorization_endpoint: authorizationEndpoint,
    token_endpoint: tokenEndpoint,
    issuer: String(data.issuer || '').trim() || undefined,
  }
  cachedDiscovery = { issuer, value: out }
  return out
}

function buildUserFromClaims(claims: any): UserProfile {
  const sub = String(claims?.sub || '').trim() || 'oidc-user'
  const email = String(claims?.email || '').trim() || 'unknown@example.invalid'
  const username =
    String(claims?.preferred_username || '').trim() ||
    String(claims?.name || '').trim() ||
    (email === 'unknown@example.invalid' ? '' : email) ||
    sub

  const now = new Date().toISOString()
  return {
    id: sub,
    email,
    username,
    is_active: true,
    created_at: now,
    last_login_at: null,
  }
}

function normalizeTokenType(raw: unknown): string {
  const t = toTrimmedPrimitiveString(raw)
  return t ? t.toLowerCase() : 'bearer'
}

export function isOidcEnabled(): boolean {
  const enabled = readEnv('NEXT_PUBLIC_OIDC_ENABLED')
  if (enabled && isFalsey(enabled)) return false
  return getOidcPublicProvidersFromEnv().length > 0
}

export async function startOidcLogin(params: { providerId?: string; returnTo?: string } = {}): Promise<void> {
  if (globalThis.window === undefined) {
    throw new Error('oidc_browser_only')
  }

  const providers = getOidcPublicProvidersFromEnv()
  if (providers.length === 0) {
    throw new Error('oidc_not_configured')
  }

  const providerId = String(params.providerId || '').trim() || null
  const provider = resolveOidcPublicProvider(providerId)
  if (!provider) {
    if (providerId) {
      throw new Error('oidc_unknown_provider')
    }
    throw new Error(providers.length > 1 ? 'oidc_provider_required' : 'oidc_not_configured')
  }

  const issuer = String(provider.issuer || '').trim()
  const clientId = String(provider.client_id || '').trim()
  if (!issuer || !clientId) {
    throw new Error('oidc_not_configured')
  }

  const discovery = await discover(issuer)
  const redirectUri = resolveRedirectUri()

  const state = generateOauthState()
  const codeVerifier = generatePkceCodeVerifier()
  const codeChallenge = await pkceChallengeFromVerifier(codeVerifier)

  const tx: OidcTransaction = {
    v: 2,
    created_at_ms: Date.now(),
    provider_id: provider.id,
    issuer,
    client_id: clientId,
    redirect_uri: redirectUri,
    code_verifier: codeVerifier,
    return_to: String(params.returnTo || '/').trim() || '/',
  }
  sessionSet(txStorageKey(state), JSON.stringify(tx))

  const url = new URL(discovery.authorization_endpoint)
  url.searchParams.set('response_type', 'code')
  url.searchParams.set('client_id', clientId)
  url.searchParams.set('redirect_uri', redirectUri)
  url.searchParams.set('scope', String(provider.scopes || '').trim() || resolveScopes())
  url.searchParams.set('state', state)
  url.searchParams.set('code_challenge', codeChallenge)
  url.searchParams.set('code_challenge_method', 'S256')

  const extraRaw = readEnv('NEXT_PUBLIC_OIDC_AUTH_PARAMS')
  const extra = parseAuthParams(extraRaw)
  const mergedExtra = {
    ...extra,
    ...provider.auth_params,
  }
  for (const [key, value] of Object.entries(mergedExtra)) {
    if (key) url.searchParams.set(key, String(value ?? ''))
  }

  globalThis.window.location.assign(url.toString())
}

export async function completeOidcLogin(params: { code: string; state: string }): Promise<{ session: AuthResponse; returnTo: string }> {
  if (globalThis.window === undefined) {
    throw new Error('oidc_browser_only')
  }

  const code = String(params.code || '').trim()
  const state = String(params.state || '').trim()
  if (!code || !state) {
    throw new Error('missing_code_or_state')
  }

  const key = txStorageKey(state)
  const raw = sessionGet(key)
  sessionDel(key)
  if (!raw) {
    throw new Error('missing_oidc_transaction')
  }

  let tx: OidcTransaction | null = null
  try {
    tx = JSON.parse(raw) as OidcTransaction
  } catch {
    tx = null
  }
  if (!tx || (tx.v !== 1 && tx.v !== 2) || !tx.issuer || !tx.client_id || !tx.redirect_uri || !tx.code_verifier) {
    throw new Error('invalid_oidc_transaction')
  }

  const discovery = await discover(tx.issuer)

  const body = new URLSearchParams()
  body.set('grant_type', 'authorization_code')
  body.set('client_id', tx.client_id)
  body.set('redirect_uri', tx.redirect_uri)
  body.set('code', code)
  body.set('code_verifier', tx.code_verifier)

  let data: OidcTokenResponse | null = null
  try {
    const res = await fetch(discovery.token_endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: body.toString(),
    })

    data = (await res.json().catch(() => null)) as OidcTokenResponse | null
    if (!res.ok) {
      const msg = String(data?.error_description || data?.error || '').trim()
      throw new Error(msg || `oidc_token_exchange_failed_${res.status}`)
    }
  } catch (err: any) {
    // Fallback: exchange server-side to avoid browser CORS/client_secret constraints.
    const providerId = String((tx as any)?.provider_id || '').trim() || undefined
    const serverRes = await fetch('/api/oidc/exchange', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        provider_id: providerId,
        code,
        code_verifier: tx.code_verifier,
        redirect_uri: tx.redirect_uri,
      }),
    })
    const serverData = (await serverRes.json().catch(() => null))
    if (!serverRes.ok) {
      const msg = String(serverData?.error || '').trim()
      const originalMsg = String(err?.message || '').trim()
      const originalLower = originalMsg.toLowerCase()
      const preferServer =
        Boolean(msg) &&
        (!originalMsg ||
          originalLower === 'failed to fetch' ||
          originalLower.includes('networkerror') ||
          originalLower.startsWith('oidc_token_exchange_failed_'))
      throw new Error((preferServer ? msg : originalMsg) || msg || `oidc_server_exchange_failed_${serverRes.status}`)
    }
    data = serverData as OidcTokenResponse
  }

  const accessToken = String(data?.access_token || '').trim()
  if (!accessToken) {
    throw new Error('oidc_missing_access_token')
  }

  // Important: Do NOT store refresh_token in localStorage.
  const token: AuthToken = {
    access_token: accessToken,
    token_type: normalizeTokenType(data?.token_type),
    expires_in: Number.isFinite(Number(data?.expires_in)) ? Number(data?.expires_in) : 3600,
  }

  const claims =
    (data?.id_token ? tryDecodeJwtPayload<any>(String(data.id_token)) : null) ||
    tryDecodeJwtPayload<any>(accessToken) ||
    {}

  const user: UserProfile = buildUserFromClaims(claims)
  const session: AuthResponse = { user, token }

  setAuthSession(session)
  return { session, returnTo: String(tx.return_to || '/').trim() || '/' }
}
