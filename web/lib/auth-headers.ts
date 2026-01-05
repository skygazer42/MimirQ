/**
 * Build auth/tenant headers for backend calls.
 *
 * Backend expects:
 * - X-User-ID (required)
 * - X-Tenant-ID (optional; falls back to backend DEFAULT_TENANT_ID)
 */

export function getAuthHeaders(): Record<string, string> {
  const headers: Record<string, string> = {}

  const envUserId = process.env.NEXT_PUBLIC_USER_ID
  const envTenantId = process.env.NEXT_PUBLIC_TENANT_ID

  let userId = envUserId
  let tenantId = envTenantId

  if (typeof window !== 'undefined') {
    userId = window.localStorage.getItem('mimirq_user_id') || userId
    tenantId = window.localStorage.getItem('mimirq_tenant_id') || tenantId
  }

  headers['X-User-ID'] = userId || 'demo'
  if (tenantId) {
    headers['X-Tenant-ID'] = tenantId
  }

  return headers
}

