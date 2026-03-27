import { afterEach, describe, expect, it, vi } from 'vitest'

import { getAuthHeaders } from './auth-headers'

type StorageState = Record<string, string>

function createLocalStorage(initial: StorageState = {}) {
  const store = new Map(Object.entries(initial))
  return {
    getItem: vi.fn((key: string) => store.get(key) ?? null),
    setItem: vi.fn((key: string, value: string) => {
      store.set(key, value)
    }),
    removeItem: vi.fn((key: string) => {
      store.delete(key)
    }),
    clear: vi.fn(() => {
      store.clear()
    }),
  }
}

const originalNodeEnv = process.env.NODE_ENV
const originalUserId = process.env.NEXT_PUBLIC_USER_ID
const originalTenantId = process.env.NEXT_PUBLIC_TENANT_ID

function setNodeEnv(value: string | undefined) {
  ;(process.env as Record<string, string | undefined>).NODE_ENV = value
}

afterEach(() => {
  vi.unstubAllGlobals()
  setNodeEnv(originalNodeEnv)
  if (originalUserId === undefined) {
    delete process.env.NEXT_PUBLIC_USER_ID
  } else {
    process.env.NEXT_PUBLIC_USER_ID = originalUserId
  }
  if (originalTenantId === undefined) {
    delete process.env.NEXT_PUBLIC_TENANT_ID
  } else {
    process.env.NEXT_PUBLIC_TENANT_ID = originalTenantId
  }
})

describe('getAuthHeaders', () => {
  it('prefers a bearer token and still forwards tenant metadata', () => {
    const localStorage = createLocalStorage({
      mimirq_access_token: 'token-123',
      mimirq_user_id: 'user-123',
      mimirq_tenant_id: 'tenant-123',
    })

    vi.stubGlobal('window', { localStorage })

    expect(getAuthHeaders()).toEqual({
      Authorization: 'Bearer token-123',
      'X-Tenant-ID': 'tenant-123',
    })
  })

  it('falls back to stored user and tenant ids when no token exists', () => {
    const localStorage = createLocalStorage({
      mimirq_user_id: 'user-456',
      mimirq_tenant_id: 'tenant-456',
    })

    vi.stubGlobal('window', { localStorage })

    expect(getAuthHeaders()).toEqual({
      'X-User-ID': 'user-456',
      'X-Tenant-ID': 'tenant-456',
    })
  })

  it('uses environment headers when browser storage is unavailable', () => {
    process.env.NEXT_PUBLIC_USER_ID = 'env-user'
    process.env.NEXT_PUBLIC_TENANT_ID = 'env-tenant'

    expect(getAuthHeaders()).toEqual({
      'X-User-ID': 'env-user',
      'X-Tenant-ID': 'env-tenant',
    })
  })

  it('uses the development demo user when no explicit identity is configured', () => {
    setNodeEnv('development')
    delete process.env.NEXT_PUBLIC_USER_ID
    delete process.env.NEXT_PUBLIC_TENANT_ID

    expect(getAuthHeaders()).toEqual({
      'X-User-ID': 'demo',
    })
  })
})
