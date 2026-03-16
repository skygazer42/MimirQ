import { describe, expect, it } from 'vitest'

import {
  appendChunkPreviewFormFields,
  buildChunkPreviewQueryParams,
  coerceRetryAfterSeconds,
  formatRateLimitLogMessage,
} from './api-client'

describe('chunk preview helpers', () => {
  it('builds preview query params from explicit and pipeline-backed values', () => {
    expect(
      buildChunkPreviewQueryParams({
        chunk_size: 512,
        pipeline: { chunk_overlap: 64 },
        include_original_text: true,
        include_chunks: false,
        original_text_max_chars: 5000,
        max_chunks: 9,
        use_parse_cache: true,
      })
    ).toEqual({
      chunk_size: 512,
      chunk_overlap: 64,
      include_original_text: true,
      include_chunks: false,
      original_text_max_chars: 5000,
      max_chunks: 9,
      use_parse_cache: true,
    })
  })

  it('appends parent-child specific preview fields', () => {
    const formData = new FormData()

    appendChunkPreviewFormFields(formData, {
      dataset_id: 'dataset-1',
      child_ratio: 0.4,
      min_child_size: 128,
      separator_preset: 'markdown',
      separator: '\n## ',
      keep_separator: true,
      separator_max_chunk_size: 320,
    }, 'parent_child')

    expect(formData.get('dataset_id')).toBe('dataset-1')
    expect(formData.get('child_ratio')).toBe('0.4')
    expect(formData.get('min_child_size')).toBe('128')
    expect(formData.get('separator_preset')).toBe('markdown')
    expect(formData.get('separator')).toBe('\n## ')
    expect(formData.get('keep_separator')).toBe('true')
    expect(formData.get('separator_max_chunk_size')).toBe('320')
  })
})

describe('rate limit helpers', () => {
  it('prefers body retry_after when coercing retry seconds', () => {
    expect(coerceRetryAfterSeconds(12, '8')).toBe(12)
    expect(coerceRetryAfterSeconds('7', '8')).toBe(7)
    expect(coerceRetryAfterSeconds(undefined, '9')).toBe(9)
    expect(coerceRetryAfterSeconds(undefined, undefined)).toBeUndefined()
  })

  it('formats the rate limit log message consistently', () => {
    expect(
      formatRateLimitLogMessage({
        retryAfterSec: 6,
        scope: 'chat',
        limit: 20,
      })
    ).toEqual({
      message: '[API] 请求过于频繁，请在 6 秒后重试',
      extra: '(scope=chat, limit=20, retry_after=6s)',
    })
  })
})
