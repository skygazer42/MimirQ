import { describe, expect, it } from 'vitest'

import { buildRagPreviewDiagnosticsSummary } from './rag-preview-diagnostics'

describe('buildRagPreviewDiagnosticsSummary', () => {
  it('extracts only real preview/explain/hash fields into the diagnostics summary', () => {
    const summary = buildRagPreviewDiagnosticsSummary({
      promptPreview: {
        query_for_retrieval: '如何解释 recall 下降',
        prompt_messages: [],
        prompt_text: '',
        variables: {},
        citations: [],
        metrics: {
          elapsed_sec: 1.2,
          prompt_render_elapsed_sec: 0.08,
        },
      },
      explain: {
        channels: {
          vector: { candidate_count: 18, returned_count: 8 },
          lexical: { candidate_count: 6 },
        },
        candidate_counts: { query_count: 2, citations: 8 },
        rerank: {
          used: true,
          candidates_n: 20,
          pipeline_stages: ['cross_encoder'],
        },
        stage_timings: {
          retrieval_elapsed_sec: 0.72,
        },
        metrics: {
          selection_fallback: 'single_document',
        },
      },
      configHash: {
        hash: 'abc123def456',
        effective_config: {
          retrieval_profile: 'grounded_strict',
          retrieval_mode: 'hybrid',
          score_threshold: 0.55,
          fusion_strategy: 'weighted',
          enable_reranker: true,
        },
      },
      explainEnabled: true,
      contractReason: null,
    })

    expect(summary.profile).toBe('grounded_strict')
    expect(summary.configHash).toBe('abc123def456')
    expect(summary.channelCandidates).toEqual(
      expect.arrayContaining([
        { label: 'vector', value: 'candidate_count=18 · returned_count=8' },
        { label: 'query_count', value: '2' },
      ])
    )
    expect(summary.filtering).toEqual(
      expect.arrayContaining([{ label: 'score_threshold', value: '0.55' }])
    )
    expect(summary.fusion).toEqual(
      expect.arrayContaining([
        { label: 'retrieval_mode', value: 'hybrid' },
        { label: 'fusion_strategy', value: 'weighted' },
      ])
    )
    expect(summary.reranker).toEqual(
      expect.arrayContaining([
        { label: 'enable_reranker', value: 'true' },
        { label: 'used', value: 'true' },
      ])
    )
    expect(summary.fallback).toContain(
      'selection_fallback: single_document'
    )
  })

  it('maps real backend degraded and fallback fields instead of only legacy aliases', () => {
    const summary = buildRagPreviewDiagnosticsSummary({
      promptPreview: {
        query_for_retrieval: 'fallback query',
        prompt_messages: [],
        prompt_text: '',
        variables: {},
        citations: [],
        metrics: {},
      },
      explain: {
        metrics: {
          retrieval_degraded: true,
          retrieval_degraded_reasons: ['main:sparse:timeout'],
          retrieval_fallback_reason: 'strict_span_empty',
        },
        query_debug: {
          retrieval_degraded: true,
          retrieval_degraded_reasons: ['hard_fallback:keyword:timeout'],
          fallback_reason: 'strict_span_empty',
        },
      },
      configHash: null,
      explainEnabled: true,
      contractReason: null,
    })

    expect(summary.degraded).toEqual(
      expect.arrayContaining([
        'retrieval_degraded: true',
        'retrieval_degraded_reasons: main:sparse:timeout',
        'retrieval_degraded_reasons: hard_fallback:keyword:timeout',
        'fallback_reason: strict_span_empty',
      ])
    )
    expect(summary.fallback).toEqual(
      expect.arrayContaining([
        'retrieval_fallback_reason: strict_span_empty',
        'fallback_reason: strict_span_empty',
      ])
    )
  })
})
