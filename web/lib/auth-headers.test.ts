import { beforeEach, describe, expect, it, vi } from 'vitest'

const authStorage = vi.hoisted(() => ({
  getAccessToken: vi.fn<() => string | undefined>(),
  getStoredUserId: vi.fn<() => string | undefined>(),
  getTenantId: vi.fn<() => string | undefined>(),
}))

vi.mock('./auth-storage', () => authStorage)

import { getAuthHeaders } from './auth-headers'

describe('getAuthHeaders', () => {
  beforeEach(() => vi.resetAllMocks())

  it('prefers bearer auth and includes tenant context', () => {
    authStorage.getAccessToken.mockReturnValue('token')
    authStorage.getStoredUserId.mockReturnValue('user-1')
    authStorage.getTenantId.mockReturnValue('tenant-1')
    expect(getAuthHeaders()).toEqual({ Authorization: 'Bearer token', 'X-Tenant-ID': 'tenant-1' })
  })

  it('falls back to an explicit stored user without a token', () => {
    authStorage.getStoredUserId.mockReturnValue('user-1')
    expect(getAuthHeaders()).toEqual({ 'X-User-ID': 'user-1' })
  })
})
