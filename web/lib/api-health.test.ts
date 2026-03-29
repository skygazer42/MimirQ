import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'

const openapiRequestMock = vi.hoisted(() => vi.fn())

vi.mock('@/lib/api/core', () => ({
  openapiRequest: openapiRequestMock,
}))

let healthApi: typeof import('./api/health').healthApi

describe('healthApi schema adoption', () => {
  beforeAll(async () => {
    ;({ healthApi } = await import('./api/health'))
  })

  beforeEach(() => {
    openapiRequestMock.mockReset()
  })

  it('passes a runtime response schema to the shared OpenAPI request layer', async () => {
    openapiRequestMock.mockResolvedValueOnce({
      ok: true,
      time: '2026-03-29T00:00:00.000Z',
    })

    await healthApi.health()

    const requestArgs = openapiRequestMock.mock.calls[0]?.[0]
    expect(requestArgs?.responseSchemaName).toBe('HealthResponse')
    expect(requestArgs?.responseSchema.safeParse({ ok: true, time: '2026-03-29T00:00:00.000Z' }).success).toBe(true)
    expect(requestArgs?.responseSchema.safeParse({ ok: 'yes', time: '2026-03-29T00:00:00.000Z' }).success).toBe(false)
  })
})
