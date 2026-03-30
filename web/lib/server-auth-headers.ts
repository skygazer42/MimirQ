import 'server-only'

import { cookies, headers } from 'next/headers'

function resolveRequestOrigin(requestHeaders: Headers): string | null {
  const forwardedProto = String(requestHeaders.get('x-forwarded-proto') || '').trim()
  const forwardedHost = String(requestHeaders.get('x-forwarded-host') || '').trim()
  if (forwardedProto && forwardedHost) {
    return `${forwardedProto}://${forwardedHost}`
  }

  const host = String(requestHeaders.get('host') || '').trim()
  if (!host) return null

  const protocol = host.includes('localhost') || host.startsWith('127.0.0.1') ? 'http' : 'https'
  return `${protocol}://${host}`
}

function serializeCookieHeader(cookieValues: Array<{ name: string; value: string }>) {
  return cookieValues
    .map(({ name, value }) => `${name}=${value}`)
    .join('; ')
    .trim()
}

async function getOidcAccessToken(origin: string, requestHeaders: Headers, cookieHeader: string) {
  try {
    const forwardedProto = String(requestHeaders.get('x-forwarded-proto') || '').trim()
    const forwardedHost = String(
      requestHeaders.get('x-forwarded-host') || requestHeaders.get('host') || ''
    ).trim()

    const refreshHeaders: Record<string, string> = {
      'Content-Type': 'application/json',
      Origin: origin,
      Cookie: cookieHeader,
    }
    if (forwardedProto) refreshHeaders['X-Forwarded-Proto'] = forwardedProto
    if (forwardedHost) refreshHeaders['X-Forwarded-Host'] = forwardedHost

    const response = await fetch(`${origin}/api/oidc/refresh`, {
      method: 'POST',
      headers: refreshHeaders,
      cache: 'no-store',
    })
    if (!response.ok) return null

    const data = (await response.json().catch(() => null)) as { access_token?: string } | null
    const accessToken = String(data?.access_token || '').trim()
    return accessToken || null
  } catch {
    return null
  }
}

export async function getServerAuthHeaders(): Promise<Record<string, string>> {
  const requestHeaders = await headers()
  const cookieStore = await cookies()

  const out: Record<string, string> = {}
  const acceptLanguage = String(requestHeaders.get('accept-language') || '').trim()
  if (acceptLanguage) {
    out['Accept-Language'] = acceptLanguage
  }

  const tenantId = String(process.env.NEXT_PUBLIC_TENANT_ID || '').trim()
  if (tenantId) {
    out['X-Tenant-ID'] = tenantId
  }

  const origin = resolveRequestOrigin(requestHeaders)
  const cookieHeader = serializeCookieHeader(cookieStore.getAll())
  if (origin && cookieHeader) {
    const accessToken = await getOidcAccessToken(origin, requestHeaders, cookieHeader)
    if (accessToken) {
      out['Authorization'] = `Bearer ${accessToken}`
      return out
    }
  }

  const fallbackUserId =
    String(process.env.NEXT_PUBLIC_USER_ID || '').trim() ||
    (process.env.NODE_ENV === 'development' ? 'demo' : '')
  if (fallbackUserId) {
    out['X-User-ID'] = fallbackUserId
  }

  return out
}
