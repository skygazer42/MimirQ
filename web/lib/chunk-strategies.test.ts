import { describe, expect, it } from 'vitest'

import {
  CHUNK_STRATEGY_OPTIONS,
  INGESTION_FALLBACK_CHUNK_STRATEGY_VALUES,
} from '@/lib/chunk-strategies'

describe('chunk strategy registry', () => {
  it('derives the ingestion fallback values from the shared strategy registry', () => {
    const integratedValues = CHUNK_STRATEGY_OPTIONS
      .filter((option) => option.group === 'integrated')
      .map((option) => option.value)

    expect(INGESTION_FALLBACK_CHUNK_STRATEGY_VALUES).toEqual([
      'langchain_recursive',
      ...integratedValues,
    ])
  })
})
