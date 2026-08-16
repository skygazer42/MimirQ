import { describe, expect, it } from 'vitest'

import type { RAGConfig } from '@/lib/api/settings'
import type { DatasetRagDefaults } from '@/types'

import {
  buildDatasetRagDefaultsForUpdate,
  buildRetrievalConfigHashRequest,
  hasDatasetRagContract,
  mergeDatasetRagDefaultsIntoRagConfig,
} from './dataset-rag-contract'

const baseRag: RAGConfig = {
  chunk_size: 1000,
  chunk_overlap: 200,
  chunk_min_chars: 0,
  retrieval_top_k: 5,
  similarity_threshold: 0.7,
  default_parser_backend: 'deepdoc',
  default_chunk_strategy: 'semantic',
  bm25_index_enabled: true,
  enable_reranker: false,
  reranker_provider: 'cross_encoder',
  reranker_top_n: 20,
  show_image_in_answer: false,
  image_append_max: 0,
}

describe('dataset rag contract helpers', () => {
  it('merges dataset rag defaults into the system rag config', () => {
    const merged = mergeDatasetRagDefaultsIntoRagConfig(baseRag, {
      top_k: 12,
      score_threshold: 0.55,
      retrieval_mode: 'hybrid',
      enable_reranker: true,
      reranker_provider: 'cohere',
    })

    expect(merged.retrieval_top_k).toBe(12)
    expect(merged.similarity_threshold).toBe(0.55)
    expect(merged.retrieval_mode).toBe('hybrid')
    expect(merged.enable_reranker).toBe(true)
    expect(merged.reranker_provider).toBe('cohere')
  })

  it('builds a non-destructive dataset rag_defaults update payload', () => {
    const existingDefaults: DatasetRagDefaults = {
      retrieval_profile: 'grounded_strict',
      enable_reranker: true,
      reranker_provider: 'cohere',
      visible_evidence_only: true,
    }

    const payload = buildDatasetRagDefaultsForUpdate({
      currentDefaults: existingDefaults,
      savedRag: baseRag,
      draftRag: {
        ...baseRag,
        retrieval_top_k: 18,
        similarity_threshold: 0.6,
        retrieval_mode: 'hybrid',
      },
    })

    expect(payload).toEqual({
      retrieval_profile: 'grounded_strict',
      enable_reranker: true,
      reranker_provider: 'cohere',
      visible_evidence_only: true,
      top_k: 18,
      score_threshold: 0.6,
      retrieval_mode: 'hybrid',
    })
  })

  it('creates a config-hash request only when a dataset contract exists', () => {
    expect(hasDatasetRagContract(null)).toBe(false)
    expect(buildRetrievalConfigHashRequest(null)).toBeNull()

    expect(
      buildRetrievalConfigHashRequest({
        retrieval_profile: 'grounded_strict',
        retrieval_mode: 'hybrid',
        top_k: 20,
      })
    ).toEqual({
      rag_config: {
        retrieval_profile: 'grounded_strict',
        retrieval_mode: 'hybrid',
        top_k: 20,
      },
      include_runtime_defaults: true,
    })
  })
})
