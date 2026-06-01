/**
 * Build auth/tenant headers for backend calls.
 *
 * Backend expects:
 * - X-User-ID (required)
 * - X-Tenant-ID (optional; falls back to backend DEFAULT_TENANT_ID)
 */

import { getAccessToken, getStoredUserId, getTenantId } from './auth-storage'

export function getAuthHeaders(): Record<string, string> {
  const headers: Record<string, string> = {}

  const token = getAccessToken()
  if (token) {
    headers['Authorization'] = `Bearer ${token}`
  }

  const envUserId = process.env.NEXT_PUBLIC_USER_ID
  const defaultUserId = process.env.NODE_ENV === 'development' ? 'demo' : undefined

  const userId = getStoredUserId() || envUserId
  const tenantId = getTenantId()

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
