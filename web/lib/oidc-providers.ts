export type OidcProviderPublic = {
  id: string
  name?: string
  issuer: string
  client_id: string
  scopes?: string
  auth_params?: Record<string, string>
}

export type OidcProviderServer = {
  id: string
  name?: string
  issuer: string
  client_id: string
  client_secret?: string
  client_auth_method?: 'basic' | 'post'
}

function readEnv(name: string): string {
  return String(process.env[name] || '').trim()
}

function normalizeIssuer(raw: unknown): string {
  return String(raw || '')
    .trim()
    .replace(/\/+$/, '')
}

function normalizeProviderId(raw: unknown): string {
  const id = String(raw || '').trim()
  if (!id) return ''
  if (id.length > 64) return ''
  if (!/^[a-zA-Z0-9][a-zA-Z0-9_-]*$/.test(id)) return ''
  return id
}

function parseAuthParams(raw: unknown): Record<string, string> {
  if (!raw) return {}
  if (typeof raw === 'string') {
    const trimmed = raw.trim()
    if (!trimmed) return {}
    const params = new URLSearchParams(trimmed.startsWith('?') ? trimmed.slice(1) : trimmed)
    const out: Record<string, string> = {}
    for (const [key, value] of params.entries()) {
      const k = String(key || '').trim()
      if (!k) continue
      out[k] = String(value || '')
    }
    return out
  }
  if (typeof raw === 'object') {
    const out: Record<string, string> = {}
    for (const [k, v] of Object.entries(raw as Record<string, unknown>)) {
      const key = String(k || '').trim()
      if (!key) continue
      const value = String(v ?? '').trim()
      if (!value) continue
      out[key] = value
    }
    return out
  }
  return {}
}

function parseProvidersJson(raw: string): unknown[] {
  const trimmed = String(raw || '').trim()
  if (!trimmed) return []
  try {
    const parsed = JSON.parse(trimmed) as unknown
    return Array.isArray(parsed) ? parsed : []
  } catch {
    return []
  }
}

export function getOidcPublicProvidersFromEnv(): OidcProviderPublic[] {
  const raw = readEnv('NEXT_PUBLIC_OIDC_PROVIDERS_JSON') || readEnv('NEXT_PUBLIC_OIDC_PROVIDERS')
  const items = raw ? parseProvidersJson(raw) : []
  const out: OidcProviderPublic[] = []
  const seen: Set<string> = new Set()

  for (const it of items) {
    if (!it || typeof it !== 'object') continue
    const obj = it as Record<string, unknown>
    const id = normalizeProviderId(obj.id)
    if (!id || seen.has(id)) continue
    const issuer = normalizeIssuer(obj.issuer)
    const clientId = String(obj.client_id || '').trim()
    if (!issuer || !clientId) continue

    const name = String(obj.name || '').trim() || undefined
    const scopes = String(obj.scopes || '').trim() || undefined
    const authParams = parseAuthParams(obj.auth_params)

    seen.add(id)
    out.push({
      id,
      name,
      issuer,
      client_id: clientId,
      scopes,
      auth_params: Object.keys(authParams).length ? authParams : undefined,
    })
  }

  // Backward compatible fallback: single-provider env vars.
  if (out.length === 0) {
    const issuer = normalizeIssuer(readEnv('NEXT_PUBLIC_OIDC_ISSUER'))
    const clientId = String(readEnv('NEXT_PUBLIC_OIDC_CLIENT_ID') || '').trim()
    if (issuer && clientId) {
      out.push({ id: 'default', issuer, client_id: clientId })
    }
  }

  return out
}

export function resolveOidcPublicProvider(providerId?: string | null): OidcProviderPublic | null {
  const providers = getOidcPublicProvidersFromEnv()
  if (providers.length === 0) return null

  const pid = normalizeProviderId(providerId)
  if (pid) {
    return providers.find((p) => p.id === pid) ?? null
  }

  if (providers.length === 1) return providers[0]
  return null
}

export function getOidcServerProvidersFromEnv(): OidcProviderServer[] {
  const raw = readEnv('OIDC_PROVIDERS_JSON') || readEnv('OIDC_PROVIDERS')
  const items = raw ? parseProvidersJson(raw) : []
  const out: OidcProviderServer[] = []
  const seen: Set<string> = new Set()

  for (const it of items) {
    if (!it || typeof it !== 'object') continue
    const obj = it as Record<string, unknown>
    const id = normalizeProviderId(obj.id)
    if (!id || seen.has(id)) continue
    const issuer = normalizeIssuer(obj.issuer)
    const clientId = String(obj.client_id || '').trim()
    if (!issuer || !clientId) continue

    const name = String(obj.name || '').trim() || undefined
    const secret = String(obj.client_secret || '').trim() || undefined
    const rawMethod = String(obj.client_auth_method || '').trim().toLowerCase()
    const clientAuthMethod = rawMethod === 'post' ? 'post' : rawMethod === 'basic' ? 'basic' : undefined

    seen.add(id)
    out.push({
      id,
      name,
      issuer,
      client_id: clientId,
      client_secret: secret,
      client_auth_method: clientAuthMethod,
    })
  }

  // Backward compatible fallback: single-provider env vars.
  if (out.length === 0) {
    const issuer = normalizeIssuer(readEnv('OIDC_ISSUER') || readEnv('NEXT_PUBLIC_OIDC_ISSUER'))
    const clientId = String(readEnv('OIDC_CLIENT_ID') || readEnv('NEXT_PUBLIC_OIDC_CLIENT_ID') || '').trim()
    if (issuer && clientId) {
      out.push({
        id: 'default',
        issuer,
        client_id: clientId,
        client_secret: String(readEnv('OIDC_CLIENT_SECRET') || '').trim() || undefined,
        client_auth_method: (String(readEnv('OIDC_CLIENT_AUTH_METHOD') || '').trim().toLowerCase() === 'post' ? 'post' : 'basic') as
          | 'basic'
          | 'post',
      })
    }
  }

  return out
}

export function resolveOidcServerProvider(providerId?: string | null): OidcProviderServer | null {
  const providers = getOidcServerProvidersFromEnv()
  if (providers.length === 0) return null

  const pid = normalizeProviderId(providerId)
  if (pid) {
    return providers.find((p) => p.id === pid) ?? null
  }

  if (providers.length === 1) return providers[0]
  return null
}

