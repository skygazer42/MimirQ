import 'server-only'

import { headers } from 'next/headers'

export async function getServerAuthHeaders(): Promise<Record<string, string>> {
  const requestHeaders = await headers()

  const out: Record<string, string> = {}
  const acceptLanguage = String(requestHeaders.get('accept-language') || '').trim()
  if (acceptLanguage) {
    out['Accept-Language'] = acceptLanguage
  }

  const tenantId = String(process.env.NEXT_PUBLIC_TENANT_ID || '').trim()
  if (tenantId) {
    out['X-Tenant-ID'] = tenantId
  }

  // Server Components cannot forward a rotated Set-Cookie from an internal refresh request.
  const fallbackUserId =
    String(process.env.NEXT_PUBLIC_USER_ID || '').trim() ||
    (process.env.NODE_ENV === 'development' ? 'demo' : '')
  if (fallbackUserId) {
    out['X-User-ID'] = fallbackUserId
  }

  return out
}
