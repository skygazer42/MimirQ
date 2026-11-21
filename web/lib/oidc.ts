'use client'

import type { AuthResponse, AuthToken, UserProfile } from '@/types'
import { readOidcExpiresIn } from '@/lib/auth-response-schema'
import { readClientStorage, removeClientStorage, writeClientStorage } from '@/lib/client-storage'
import { readNonEmptyString, toTrimmedPrimitiveString } from '@/lib/primitive-text'
import {
  generateOauthState,
  generatePkceCodeVerifier,
  pkceChallengeFromVerifier,
  tryDecodeJwtPayload,
} from '@/lib/oidc-pkce'
import { parseOidcAuthParams, type OidcProviderPublic } from '@/lib/oidc-providers'

type OidcDiscovery = {
  authorization_endpoint: string
  token_endpoint: string
  issuer?: string
}

type OidcTokenResponse = {
  access_token?: string
  token_type?: string
  expires_in?: unknown
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
type OidcClaims = Record<string, unknown>

const TX_KEY_PREFIX = 'mimirq_oidc_tx:'

function claimString(claims: OidcClaims, key: string): string {
  return toTrimmedPrimitiveString(claims[key])
}

function resolveRedirectUri(origin: string): string {
  return process.env.NEXT_PUBLIC_OIDC_REDIRECT_URI?.trim() || `${origin}/auth/oidc/callback`
}

function resolveScopes(): string {
  return process.env.NEXT_PUBLIC_OIDC_SCOPES?.trim() || 'openid profile email'
}

function txStorageKey(state: string): string {
  return `${TX_KEY_PREFIX}${state}`
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
  const data = await res.json().catch(() => null)
  if (!data || typeof data !== 'object') {
    throw new Error('oidc_discovery_invalid')
  }

  const authorizationEndpoint = readNonEmptyString(data.authorization_endpoint)
  const tokenEndpoint = readNonEmptyString(data.token_endpoint)
  if (!authorizationEndpoint || !tokenEndpoint) {
    throw new Error('oidc_discovery_missing_endpoints')
  }

  const out: OidcDiscovery = {
    authorization_endpoint: authorizationEndpoint,
    token_endpoint: tokenEndpoint,
    issuer: readNonEmptyString(data.issuer),
  }
  cachedDiscovery = { issuer, value: out }
  return out
}

function buildUserFromClaims(claims: OidcClaims): UserProfile {
  const sub = claimString(claims, 'sub') || 'oidc-user'
  const email = claimString(claims, 'email') || 'unknown@example.invalid'
  const username =
    claimString(claims, 'preferred_username') ||
    claimString(claims, 'name') ||
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

export async function prepareOidcLogin(provider: OidcProviderPublic): Promise<() => void> {
  const browserWindow = globalThis.window
  if (browserWindow === undefined) {
    throw new Error('oidc_browser_only')
  }

  const issuer = provider.issuer
  const clientId = provider.client_id

  const discovery = await discover(issuer)
  const redirectUri = resolveRedirectUri(browserWindow.location.origin)

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
    return_to: '/',
  }

  const url = new URL(discovery.authorization_endpoint)
  const extra = parseOidcAuthParams(process.env.NEXT_PUBLIC_OIDC_AUTH_PARAMS)
  const mergedExtra = { ...extra, ...provider.auth_params }
  for (const [key, value] of Object.entries(mergedExtra)) url.searchParams.set(key, value)

  url.searchParams.set('response_type', 'code')
  url.searchParams.set('client_id', clientId)
  url.searchParams.set('redirect_uri', redirectUri)
  url.searchParams.set('scope', provider.scopes ?? resolveScopes())
  url.searchParams.set('state', state)
  url.searchParams.set('code_challenge', codeChallenge)
  url.searchParams.set('code_challenge_method', 'S256')

  return () => {
    if (!writeClientStorage(txStorageKey(state), JSON.stringify(tx), 'session')) {
      throw new Error('无法保存登录状态，请检查浏览器的会话存储。')
    }
    browserWindow.location.assign(url.toString())
  }
}

export async function completeOidcLogin(params: {
  code: string
  state: string
}): Promise<{ session: AuthResponse; returnTo: string }> {
  if (globalThis.window === undefined) {
    throw new Error('oidc_browser_only')
  }

  const code = params.code.trim()
  const state = params.state.trim()
  if (!code || !state) {
    throw new Error('missing_code_or_state')
  }

  const key = txStorageKey(state)
  const raw = readClientStorage(key, 'session')
  removeClientStorage(key, 'session')
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
      const message = readNonEmptyString(data?.error_description) ?? readNonEmptyString(data?.error)
      throw new Error(message ?? `oidc_token_exchange_failed_${res.status}`)
    }
  } catch (err: unknown) {
    // Fallback: exchange server-side to avoid browser CORS/client_secret constraints.
    const providerId = readNonEmptyString(tx.provider_id)
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
    const serverData = (await serverRes.json().catch(() => null)) as OidcTokenResponse | null
    if (!serverRes.ok) {
      const msg = toTrimmedPrimitiveString(serverData?.error)
      const originalMsg = err instanceof Error ? err.message.trim() : toTrimmedPrimitiveString(err)
      const originalLower = originalMsg.toLowerCase()
      const preferServer =
        Boolean(msg) &&
        (!originalMsg ||
          originalLower === 'failed to fetch' ||
          originalLower.includes('networkerror') ||
          originalLower.startsWith('oidc_token_exchange_failed_'))
      throw new Error((preferServer ? msg : originalMsg) || msg || `oidc_server_exchange_failed_${serverRes.status}`)
    }
    data = serverData
  }

  const accessToken = readNonEmptyString(data?.access_token)
  if (!accessToken) {
    throw new Error('oidc_missing_access_token')
  }

  // Important: Do NOT persist the refresh token in browser storage.
  const expiresIn = readOidcExpiresIn(data?.expires_in)
  if (expiresIn === null) throw new Error('oidc_invalid_expiry')
  const token: AuthToken = {
    access_token: accessToken,
    token_type: normalizeTokenType(data?.token_type),
    expires_in: expiresIn,
  }

  const idToken = readNonEmptyString(data?.id_token)
  const claims =
    (idToken === undefined ? null : tryDecodeJwtPayload<OidcClaims>(idToken)) ||
    tryDecodeJwtPayload<OidcClaims>(accessToken) ||
    {}

  const user: UserProfile = buildUserFromClaims(claims)
  const session: AuthResponse = { user, token }

  return { session, returnTo: readNonEmptyString(tx.return_to) ?? '/' }
}
