import { describe, expect, it } from 'vitest'

import {
  HTML_API_ERROR_MESSAGE,
  formatApiError,
  splitApiErrorDisplay,
  stripRequestIdFromMessage,
  toApiErrorInfo,
} from './api-errors'

describe('api error user-facing copy hygiene', () => {
  it('never leaks developer environment or proxy internals for network, timeout, or HTML responses', () => {
    const network = toApiErrorInfo({ code: 'ERR_NETWORK', message: 'Network Error', requestId: 'req-net-1' }, '无法读取权限')
    expect(network.message).toBe('服务连接暂时中断，请检查网络后重试')
    expect(network.message).not.toContain('NEXT_PUBLIC_API_URL')
    expect(network.message).not.toContain('反向代理')
    expect(network.message).not.toContain('后端')
    expect(network.requestId).toBe('req-net-1')

    const timeout = toApiErrorInfo({ code: 'ETIMEDOUT', message: 'timeout' }, '保存失败')
    expect(timeout.message).toBe('请求响应超时，请稍后刷新确认或重试')
    expect(timeout.message).not.toContain('后端')

    expect(HTML_API_ERROR_MESSAGE).not.toContain('NEXT_PUBLIC_API_URL')
    expect(HTML_API_ERROR_MESSAGE).not.toContain('Backend returned HTML')
  })

  it('separates request_id from display copy without losing diagnostic metadata', () => {
    const formatted = formatApiError(
      { code: 'ERR_NETWORK', message: 'Network Error', requestId: 'eb1a1801-0672-44b4-8fde-89941c0eb7b7' },
      '无法读取权限',
    )
    expect(formatted).toContain('request_id=eb1a1801-0672-44b4-8fde-89941c0eb7b7')

    const split = splitApiErrorDisplay(formatted)
    expect(split).toEqual({
      message: '服务连接暂时中断，请检查网络后重试',
      requestId: 'eb1a1801-0672-44b4-8fde-89941c0eb7b7',
    })
    expect(stripRequestIdFromMessage('权限更新失败 (request_id=abc-123)')).toBe('权限更新失败')
  })
})
