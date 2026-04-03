import { afterEach, describe, expect, it, vi } from 'vitest'

import { apiClient } from './api/core'

describe('api client cancellation handling', () => {
  const responseHandlers = (apiClient.interceptors.response as any).handlers as Array<{
    rejected?: (error: unknown) => Promise<unknown>
  }>
  const rejected = responseHandlers[0]?.rejected

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('does not log a backend network error for canceled axios requests', async () => {
    expect(typeof rejected).toBe('function')

    const error = {
      code: 'ERR_CANCELED',
      name: 'CanceledError',
      message: 'canceled',
      request: {},
      config: {
        headers: {
          'X-Request-ID': 'rid-cancelled',
        },
      },
    }

    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {})

    await expect(rejected?.(error)).rejects.toBe(error)
    expect(consoleError).not.toHaveBeenCalled()
  })
})
