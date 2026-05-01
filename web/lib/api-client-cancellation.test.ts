import { afterEach, describe, expect, it, vi } from 'vitest'

import { apiClient } from './api/core'

describe('api client cancellation handling', () => {
  const responseHandlers = (apiClient.interceptors.response as any).handlers as Array<{
    rejected?: (error: unknown) => Promise<unknown>
  }>
  const rejected = responseHandlers[0]?.rejected

  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
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

  it('uses console.warn for handled browser API failures in dev to avoid Next error overlay', async () => {
    expect(typeof rejected).toBe('function')
    vi.stubGlobal('window', {})

    const error = {
      request: {},
      message: 'Network Error',
      config: {
        headers: {
          'X-Request-ID': 'rid-network',
        },
      },
    }

    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {})
    const consoleWarn = vi.spyOn(console, 'warn').mockImplementation(() => {})

    await expect(rejected?.(error)).rejects.toBe(error)
    expect(consoleError).not.toHaveBeenCalled()
    expect(consoleWarn).toHaveBeenCalledWith(
      '[API] 网络连接中断或后端不可达，请检查后端服务 / API 地址',
      '(request_id=rid-network)'
    )
  })
})
