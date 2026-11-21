import { readNonEmptyString } from '@/lib/primitive-text'
import { recordSchema } from '@/lib/response-schema'

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

function readEnv(name: string): string | undefined {
  return readNonEmptyString(process.env[name])
}

function readProviderText(raw: unknown): string | undefined {
  if (typeof raw === 'number' || typeof raw === 'boolean') return String(raw)
  return readNonEmptyString(raw)
}

function normalizeIssuer(raw: unknown): string | undefined {
  const issuer = readProviderText(raw)?.replace(/\/+$/, '')
  return issuer === '' ? undefined : issuer
}

function normalizeProviderId(raw: unknown): string | undefined {
  const id = readProviderText(raw)
  if (id === undefined || id.length > 64 || !/^[a-zA-Z0-9][a-zA-Z0-9_-]*$/.test(id)) return undefined
  return id
}

export function parseOidcAuthParams(raw: unknown): Record<string, string> {
  if (typeof raw === 'string') {
    const trimmed = raw.trim()
    if (!trimmed) return {}
    const params = new URLSearchParams(trimmed.startsWith('?') ? trimmed.slice(1) : trimmed)
    const out: Record<string, string> = {}
    for (const [key, value] of params.entries()) {
      const parameterName = key.trim()
      if (parameterName === '') continue
      out[parameterName] = value
    }
    return out
  }
  if (typeof raw === 'object' && raw !== null) {
    const out: Record<string, string> = {}
    for (const [name, parameter] of Object.entries(raw)) {
      const key = name.trim()
      if (!key) continue
      const value = readProviderText(parameter)
      if (value === undefined) continue
      out[key] = value
    }
    return out
  }
  return {}
}

function parseProvidersJson(raw: string | undefined): unknown[] {
  const trimmed = raw?.trim()
  if (!trimmed) return []
  try {
    const parsed: unknown = JSON.parse(trimmed)
    return Array.isArray(parsed) ? parsed : []
  } catch {
    return []
  }
}

function selectOidcProvider<Provider extends { id: string }>(
  providers: readonly Provider[],
  providerId?: string | null,
): Provider | null {
  const id = providerId?.trim()
  if (id !== undefined && id !== '') return providers.find((provider) => provider.id === id) ?? null
  return providers.length === 1 ? providers[0] : null
}

export function getOidcPublicProvidersFromEnv(): OidcProviderPublic[] {
  if (process.env.NEXT_PUBLIC_OIDC_ENABLED?.trim().toLowerCase() === 'false') return []

  const raw = readNonEmptyString(process.env.NEXT_PUBLIC_OIDC_PROVIDERS_JSON) ?? process.env.NEXT_PUBLIC_OIDC_PROVIDERS
  const items = parseProvidersJson(raw)
  const out: OidcProviderPublic[] = []
  const seen: Set<string> = new Set()

  for (const it of items) {
    const result = recordSchema.safeParse(it)
    if (!result.success) continue
    const obj = result.data
    const id = normalizeProviderId(obj.id)
    if (!id || seen.has(id)) continue
    const issuer = normalizeIssuer(obj.issuer)
    const clientId = readProviderText(obj.client_id)
    if (!issuer || !clientId) continue

    const name = readProviderText(obj.name)
    const scopes = readProviderText(obj.scopes)
    const authParams = parseOidcAuthParams(obj.auth_params)

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
    const issuer = normalizeIssuer(process.env.NEXT_PUBLIC_OIDC_ISSUER)
    const clientId = process.env.NEXT_PUBLIC_OIDC_CLIENT_ID?.trim()
    if (issuer && clientId) {
      out.push({ id: 'default', issuer, client_id: clientId })
    }
  }

  return out
}

export function getOidcServerProvidersFromEnv(): OidcProviderServer[] {
  const raw = readEnv('OIDC_PROVIDERS_JSON') ?? readEnv('OIDC_PROVIDERS')
  const items = parseProvidersJson(raw)
  const out: OidcProviderServer[] = []
  const seen: Set<string> = new Set()

  for (const it of items) {
    const result = recordSchema.safeParse(it)
    if (!result.success) continue
    const obj = result.data
    const id = normalizeProviderId(obj.id)
    if (!id || seen.has(id)) continue
    const issuer = normalizeIssuer(obj.issuer)
    const clientId = readProviderText(obj.client_id)
    if (!issuer || !clientId) continue

    const name = readProviderText(obj.name)
    const secret = readProviderText(obj.client_secret)
    const rawMethod = readProviderText(obj.client_auth_method)?.toLowerCase()
    const clientAuthMethod = rawMethod === 'post' || rawMethod === 'basic' ? rawMethod : undefined

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
    const issuer = normalizeIssuer(readEnv('OIDC_ISSUER') ?? readEnv('NEXT_PUBLIC_OIDC_ISSUER'))
    const clientId = readEnv('OIDC_CLIENT_ID') ?? readEnv('NEXT_PUBLIC_OIDC_CLIENT_ID')
    if (issuer && clientId) {
      out.push({
        id: 'default',
        issuer,
        client_id: clientId,
        client_secret: readEnv('OIDC_CLIENT_SECRET'),
        client_auth_method: readEnv('OIDC_CLIENT_AUTH_METHOD')?.toLowerCase() === 'post' ? 'post' : 'basic',
      })
    }
  }

  return out
}

export function resolveOidcServerProvider(providerId?: string | null): OidcProviderServer | null {
  return selectOidcProvider(getOidcServerProvidersFromEnv(), providerId)
}
