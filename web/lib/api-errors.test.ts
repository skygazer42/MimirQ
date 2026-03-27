import { describe, expect, it } from 'vitest'

import {
  extractAxiosRequestId,
  extractBackendMessage,
  extractBackendRequestId,
  extractRequestIdFromError,
  toApiErrorInfo,
  withRequestId,
} from './api-errors'

describe('api-errors', () => {
  it('extractBackendRequestId reads request_id', () => {
    expect(extractBackendRequestId({ request_id: 'rid' })).toBe('rid')
    expect(extractBackendRequestId({})).toBeUndefined()
  })

  it('extractBackendMessage prefers message/detail', () => {
    expect(extractBackendMessage('  hi  ')).toBe('hi')
    expect(extractBackendMessage({ message: 'm' })).toBe('m')
    expect(extractBackendMessage({ detail: 'd' })).toBe('d')
  })

  it('extractBackendMessage handles FastAPI validation detail array', () => {
    expect(extractBackendMessage({ detail: [{ loc: ['x'], msg: 'bad' }] })).toBe('Validation error')
  })

  it('withRequestId appends request_id once', () => {
    expect(withRequestId('oops', 'rid')).toBe('oops (request_id=rid)')
    expect(withRequestId('oops (request_id=rid)', 'rid')).toBe('oops (request_id=rid)')
  })

  it('extractAxiosRequestId prefers explicit requestId property', () => {
    expect(extractAxiosRequestId({ requestId: 'rid-direct' })).toBe('rid-direct')
  })

  it('extractAxiosRequestId falls back to response body request_id', () => {
    expect(extractAxiosRequestId({ response: { data: { request_id: 'rid-body' } } })).toBe('rid-body')
  })

  it('extractAxiosRequestId falls back to response header x-request-id', () => {
    expect(extractAxiosRequestId({ response: { headers: { 'x-request-id': 'rid-header' } } })).toBe('rid-header')
  })

  it('extractAxiosRequestId falls back to config header X-Request-ID', () => {
    expect(extractAxiosRequestId({ config: { headers: { 'X-Request-ID': 'rid-config' } } })).toBe('rid-config')
  })

  it('extractRequestIdFromError reads explicit requestId values and request_id strings', () => {
    expect(extractRequestIdFromError({ requestId: 'rid-direct' })).toBe('rid-direct')
    expect(extractRequestIdFromError(new Error('boom (request_id=rid-string)'))).toBe('rid-string')
    expect(extractRequestIdFromError('request_id=rid-text')).toBe('rid-text')
  })

  it('toApiErrorInfo returns message + requestId + status for axios-like errors', () => {
    const info = toApiErrorInfo(
      { response: { status: 500, headers: { 'x-request-id': 'rid' }, data: { detail: 'boom' } } },
      'fallback'
    )
    expect(info.status).toBe(500)
    expect(info.requestId).toBe('rid')
    expect(info.message).toBe('boom')
  })

  it('toApiErrorInfo formats 429 with retry_after_sec + scope + limit', () => {
    const info = toApiErrorInfo(
      {
        response: {
          status: 429,
          headers: { 'x-request-id': 'rid' },
          data: {
            error: 'RATE_LIMIT_EXCEEDED',
            message: 'Too many requests. Please try again later.',
            detail: { retry_after_sec: 5, limit: 1, scope: 'api' },
            request_id: 'rid',
          },
        },
      },
      'fallback'
    )
    expect(info.status).toBe(429)
    expect(info.requestId).toBe('rid')
    expect(info.message).toContain('5')
    expect(info.message).toContain('scope=api')
    expect(info.message).toContain('limit=1')
  })
})
