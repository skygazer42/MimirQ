import { describe, expect, it, vi } from 'vitest'
import { z } from 'zod'

import { createOpenApiAxiosClient } from './openapi-request'

describe('openapiRequest response schema validation', () => {
  it('returns schema-parsed data when a response schema is provided', async () => {
    const request = vi.fn().mockResolvedValue({
      data: {
        ok: 'true',
        time: '2026-03-29T00:00:00.000Z',
      },
      headers: {
        'x-request-id': 'rid-health-ok',
      },
    })

    const openapiRequest = createOpenApiAxiosClient({ request } as any)
    const responseSchema = z.object({
      ok: z.coerce.boolean(),
      time: z.string(),
    })

    await expect(
      openapiRequest({
        path: '/api/v1/health',
        method: 'get',
        responseSchema,
        responseSchemaName: 'HealthResponse',
      } as any)
    ).resolves.toEqual({
      ok: true,
      time: '2026-03-29T00:00:00.000Z',
    })
  })

  it('rejects malformed payloads with request_id-aware schema errors', async () => {
    const request = vi.fn().mockResolvedValue({
      data: {
        ok: 'definitely-not-a-boolean',
      },
      headers: {
        'x-request-id': 'rid-health-bad',
      },
    })

    const openapiRequest = createOpenApiAxiosClient({ request } as any)

    await expect(
      openapiRequest({
        path: '/api/v1/health',
        method: 'get',
        responseSchema: z.object({
          ok: z.boolean(),
          time: z.string(),
        }),
        responseSchemaName: 'HealthResponse',
      } as any)
    ).rejects.toThrow(/request_id=rid-health-bad/)
  })
})
