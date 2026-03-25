/**
 * Build auth/tenant headers for backend calls.
 *
 * Backend expects:
 * - X-User-ID (required)
 * - X-Tenant-ID (optional; falls back to backend DEFAULT_TENANT_ID)
 */

export function getAuthHeaders(): Record<string, string> {
  const headers: Record<string, string> = {}

  if (globalThis.window !== undefined) {
    const token = globalThis.window.localStorage.getItem('mimirq_access_token')
    if (token) {
      headers['Authorization'] = `Bearer ${token}`
    }
  }

  const envUserId = process.env.NEXT_PUBLIC_USER_ID
  const envTenantId = process.env.NEXT_PUBLIC_TENANT_ID
  const defaultUserId = process.env.NODE_ENV === 'development' ? 'demo' : undefined

  let userId = envUserId
  let tenantId = envTenantId

  if (globalThis.window !== undefined) {
    userId = globalThis.window.localStorage.getItem('mimirq_user_id') || userId
    tenantId = globalThis.window.localStorage.getItem('mimirq_tenant_id') || tenantId
  }

  if (!headers['Authorization']) {
    const fallbackUserId = userId || defaultUserId
    if (fallbackUserId) {
      headers['X-User-ID'] = fallbackUserId
    }
  }
  if (tenantId) {
    headers['X-Tenant-ID'] = tenantId
  }

  return headers
}
