import { beforeEach, describe, expect, it, vi } from 'vitest'

const authStorage = vi.hoisted(() => ({
  clearAuthSession: vi.fn(),
  getAccessToken: vi.fn<() => string | undefined>(),
}))

vi.mock('@/lib/auth-storage', () => authStorage)

import { buildFetchError } from './fetch-errors'

describe('buildFetchError', () => {
  beforeEach(() => vi.resetAllMocks())

  it('uses backend details and request ids', async () => {
    const response = new Response(JSON.stringify({ detail: 'Denied', request_id: 'req-1' }), {
      status: 403,
      headers: { 'Content-Type': 'application/json' },
    })
    await expect(buildFetchError(response, 'Failed')).resolves.toEqual(new Error('Denied (request_id=req-1)'))
  })

  it('clears a rejected stored token', async () => {
    authStorage.getAccessToken.mockReturnValue('expired')
    await buildFetchError(new Response('', { status: 401 }), 'Failed')
    expect(authStorage.clearAuthSession).toHaveBeenCalledOnce()
  })
})
