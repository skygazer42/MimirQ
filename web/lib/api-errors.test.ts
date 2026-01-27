import { describe, expect, it } from 'vitest'

import { extractBackendMessage, extractBackendRequestId, withRequestId } from './api-errors'

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
})

