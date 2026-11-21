import { getAccessToken, getStoredUserId, getTenantId } from './auth-storage'

export function getAuthHeaders(): Record<string, string> {
  const headers: Record<string, string> = {}

  const token = getAccessToken()
  if (token) {
    headers['Authorization'] = `Bearer ${token}`
  } else {
    const defaultUserId = process.env.NODE_ENV === 'development' ? 'demo' : undefined
    const userId = getStoredUserId() || process.env.NEXT_PUBLIC_USER_ID || defaultUserId
    if (userId) {
      headers['X-User-ID'] = userId
    }
  }

  const tenantId = getTenantId()
  if (tenantId) {
    headers['X-Tenant-ID'] = tenantId
  }

  return headers
}
