import { describe, expect, it } from 'vitest'

import { buildFetchError } from './fetch-errors'

describe('buildFetchError', () => {
  it('uses backend details and request ids', async () => {
    const response = new Response(JSON.stringify({ detail: 'Denied', request_id: 'req-1' }), {
      status: 403,
      headers: { 'Content-Type': 'application/json' },
    })
    await expect(buildFetchError(response, 'Failed')).resolves.toEqual(new Error('Denied (request_id=req-1)'))
  })

  it('keeps the fallback message when the response body is empty', async () => {
    await expect(buildFetchError(new Response('', { status: 401 }), 'Failed')).resolves.toEqual(
      new Error('Failed (HTTP 401)')
    )
  })
})
