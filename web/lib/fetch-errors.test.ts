import { describe, expect, it } from 'vitest'

import { buildFetchError } from './fetch-errors'

describe('buildFetchError', () => {
  it('prefers backend json message and request_id over header', async () => {
    const response = new Response(JSON.stringify({ detail: 'bad request', request_id: 'rid-body' }), {
      status: 422,
      headers: {
        'Content-Type': 'application/json',
        'X-Request-ID': 'rid-header',
      },
    })

    const err = await buildFetchError(response, 'fallback')
    expect(err.message).toContain('bad request')
    expect(err.message).toContain('request_id=rid-body')
  })

  it('falls back to header request id when body is not json', async () => {
    const response = new Response('oops', {
      status: 500,
      headers: {
        'X-Request-ID': 'rid-header',
      },
    })

    const err = await buildFetchError(response, 'fallback')
    expect(err.message).toContain('oops')
    expect(err.message).toContain('request_id=rid-header')
  })
})

