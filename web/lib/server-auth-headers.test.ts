import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('server-only', () => ({}))
vi.mock('next/headers', () => ({
  headers: vi.fn().mockResolvedValue(new Headers({ 'Accept-Language': 'zh-CN' })),
}))

import { getServerAuthHeaders } from './server-auth-headers'

describe('getServerAuthHeaders', () => {
  beforeEach(() => {
    vi.unstubAllGlobals()
  })

  afterEach(() => {
    vi.unstubAllEnvs()
  })

  it('does not consume a rotating OIDC refresh cookie during server rendering', async () => {
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)

    expect(await getServerAuthHeaders()).toMatchObject({ 'Accept-Language': 'zh-CN' })
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('does not trust the public fallback identity outside development', async () => {
    vi.stubEnv('NODE_ENV', 'production')
    vi.stubEnv('NEXT_PUBLIC_USER_ID', 'demo')

    expect(await getServerAuthHeaders()).not.toHaveProperty('X-User-ID')
  })

  it('keeps explicit header auth available for local development', async () => {
    vi.stubEnv('NODE_ENV', 'development')
    vi.stubEnv('NEXT_PUBLIC_USER_ID', 'local-user')

    expect(await getServerAuthHeaders()).toHaveProperty('X-User-ID', 'local-user')
  })
})
