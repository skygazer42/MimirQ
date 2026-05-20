import { describe, expect, it } from 'vitest'

import {
  buildChunkStrategyCatalog,
  CHUNK_STRATEGY_OPTIONS,
  getChunkStrategyRecommendation,
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

  it('parses backend recommendation notes into frontend tiers', () => {
    expect(getChunkStrategyRecommendation('langchain_recursive', '[Mainstream RAG recommended] Recursive splitter.')).toBe('mainstream')
    expect(getChunkStrategyRecommendation('docker_compose', '[Specialized document strategy] Compose service-aware chunking.')).toBe('specialized')
    expect(getChunkStrategyRecommendation('raptor', '[Experimental or corpus-specific] Hierarchical chunk scaffold.')).toBe('experimental')
    expect(getChunkStrategyRecommendation('llama_index', '[Optional dependency] Requires LLAMA_INDEX_ENABLED=true.')).toBe('optional')
    expect(getChunkStrategyRecommendation('integrated_naive', '[Integrated parse+chunk preset] Integrated pipeline.')).toBe('integrated')
  })

  it('merges backend capabilities into a grouped catalog without dropping dynamic entries', () => {
    const catalog = buildChunkStrategyCatalog([
      { name: 'langchain_recursive', available: true, notes: '[Mainstream RAG recommended] Recursive splitter.' },
      { name: 'docker_compose', available: true, notes: '[Specialized document strategy] Compose service-aware chunking.' },
      { name: 'future_strategy', available: true, notes: '[Experimental or corpus-specific] Future dynamic strategy.' },
    ])

    expect(catalog.find((item) => item.value === 'langchain_recursive')?.recommendation).toBe('mainstream')
    expect(catalog.find((item) => item.value === 'docker_compose')?.recommendation).toBe('specialized')
    expect(catalog.find((item) => item.value === 'future_strategy')?.label).toBe('Future Strategy')
    expect(catalog.find((item) => item.value === 'future_strategy')?.recommendation).toBe('experimental')
  })
})
