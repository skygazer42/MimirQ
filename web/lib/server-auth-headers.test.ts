import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('server-only', () => ({}))
vi.mock('next/headers', () => ({
  headers: vi.fn().mockResolvedValue(new Headers({ 'Accept-Language': 'zh-CN' })),
}))

import { getServerAuthHeaders } from './server-auth-headers'

describe('getServerAuthHeaders', () => {
  beforeEach(() => {
    vi.unstubAllGlobals()
  })

  it('does not consume a rotating OIDC refresh cookie during server rendering', async () => {
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)

    expect(await getServerAuthHeaders()).toMatchObject({ 'Accept-Language': 'zh-CN' })
    expect(fetchMock).not.toHaveBeenCalled()
  })
})
