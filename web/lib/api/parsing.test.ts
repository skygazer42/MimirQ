import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { z } from 'zod'

const requests = vi.hoisted(() => ({ send: vi.fn() }))

vi.mock('@/lib/api/core', () => ({ apiClient: {}, openapiRequest: requests.send }))

import { parsingApi } from './parsing'

describe('parsing quality response', () => {
  beforeEach(() => {
    requests.send.mockReset()
  })

  it.each([null, 0, 0.75])('preserves the reading-order measurement %s', async (score) => {
    requests.send.mockImplementation(async ({ responseSchema }: { responseSchema: z.ZodType }) =>
      responseSchema.parse({
        document_id: 'quality-document',
        parser_backend: 'pdf',
        markdown_content: 'Saved body',
        original_markdown_content: 'Saved body',
        edited: false,
        pdf_quality: {
          score: 0,
          text_quality_score: 0,
          format_consistency_score: 0,
          table_quality_score: 0,
          reading_order_score: score,
          is_scanned: false,
          page_count: 0,
        },
        quality_gate: {
          grade: 'pass',
          reasons: [],
          evidence: { vlm_correction: { changed: false, error: 'page_1:http_503' } },
        },
      }),
    )

    const result = await parsingApi.getContent('quality-document')
    expect(result.edited).toBe(false)
    expect(result.pdf_quality).toHaveProperty('reading_order_score', score)
    expect(result.pdf_quality?.score).toBe(0)
    expect(result.quality_gate?.evidence).toHaveProperty('vlm_correction.error', 'page_1:http_503')
  })

  it.each([undefined, 'false'])('rejects a missing or invalid edited state %s', async (edited) => {
    requests.send.mockImplementation(async ({ responseSchema }: { responseSchema: z.ZodType }) =>
      responseSchema.parse({
        document_id: 'quality-document',
        parser_backend: 'pdf',
        markdown_content: 'Saved body',
        original_markdown_content: 'Saved body',
        edited,
      }),
    )

    await expect(parsingApi.getContent('quality-document')).rejects.toThrow()
  })
})
