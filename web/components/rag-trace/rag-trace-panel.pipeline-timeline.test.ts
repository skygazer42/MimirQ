import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import type { RagTrace } from '@/types'

import {
  RagTracePipelineTimeline,
  buildTraceCitationChannelSummaries,
  buildTraceCitationDiff,
  buildTraceDiffCandidateOptions,
  buildCitationSimulationRows,
  buildPipelineInspectorSections,
  buildPipelineTimelineSteps,
  filterTraceCitationsByChannel,
  movePipelineSelectionIndex,
  moveTraceSelectionIndex,
} from './rag-trace-panel'

describe('rag trace panel pipeline timeline', () => {
  it('maps typed trace data into timeline rows and renders latency shares', () => {
    const trace: RagTrace = {
      schema_version: 1,
      ts_ms: 1710000000000,
      request_id: 'req-1',
      conversation_id: 'conv-1',
      retrieval: {
        mode: 'hybrid',
        query_count: 2,
        top_k: 8,
        elapsed_sec: 0.12,
      },
      rerank: {
        enabled: true,
        provider: 'cohere',
        top_n: 4,
        elapsed_sec: 0.03,
      },
      citations: [],
      citations_count: 4,
      steps: [
        {
          key: 'retrieve',
          label: 'Retrieve',
          elapsed_sec: 0.12,
          meta: { mode: 'hybrid', query_count: 2, count: 10 },
        },
        {
          key: 'rerank',
          label: 'Rerank',
          elapsed_sec: 0.03,
          meta: { count: 4 },
        },
      ],
    }

    const steps = buildPipelineTimelineSteps(trace)
    expect(steps).toHaveLength(2)
    expect(steps[0]).toMatchObject({
      label: 'Retrieve',
      queryCount: 2,
      itemCount: 10,
      topK: 8,
    })
    expect(steps[1]).toMatchObject({
      label: 'Rerank',
      itemCount: 4,
      rerankTopN: 4,
    })

    const html = renderToStaticMarkup(React.createElement(RagTracePipelineTimeline, { steps }))
    expect(html).toContain('share=80.0%')
    expect(html).toContain('queries=2')
    expect(html).toContain('count=10')
    expect(html).toContain('top_k=8')
    expect(html).toContain('top_n=4')
    expect(html).toContain('data-pipeline-share=\"80.0%\"')
  })

  it('builds stage inspector sections and keeps keyboard stage navigation cyclical', () => {
    const trace: RagTrace = {
      schema_version: 1,
      ts_ms: 1710000000000,
      request_id: 'req-2',
      conversation_id: 'conv-1',
      retrieval: {
        mode: 'hybrid',
        query_count: 2,
        top_k: 8,
        elapsed_sec: 0.12,
        per_query: [
          {
            kind: 'main',
            retriever_debug: {
              channels: {
                fusion_strategy: 'rrf',
                vector_backend: 'milvus',
                rerank: { skip_reason: 'disabled_by_flag' },
              },
              hierarchy_recall: {
                enabled: true,
                overfetch_factor: 2,
              },
            },
          },
        ],
      },
      rerank: {
        enabled: false,
        provider: 'cohere',
        top_n: 4,
        elapsed_sec: 0,
      },
      citations: [
        {
          document_id: 'doc-1',
          chunk_id: 'chunk-1',
          page_number: 4,
          relevance_score: 0.82,
          has_image: true,
          start_char: 12,
          end_char: 42,
        },
      ],
      citations_count: 1,
      steps: [
        {
          key: 'retrieve',
          label: 'Retrieve',
          elapsed_sec: 0.12,
          meta: { mode: 'hybrid', query_count: 2, count: 10 },
        },
        {
          key: 'rerank',
          label: 'Rerank',
          elapsed_sec: 0,
          meta: { count: 4 },
        },
      ],
    }

    const sections = buildPipelineInspectorSections(trace)
    expect(sections.map((section) => section.id)).toEqual(['retrieve', 'rerank', 'citations'])
    expect(sections[0].metrics).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ label: 'Fusion', value: 'rrf' }),
        expect.objectContaining({ label: 'Vector backend', value: 'milvus' }),
      ])
    )
    expect(sections[1].callout).toContain('disabled_by_flag')
    expect(sections[2].citations[0]).toMatchObject({
      document_id: 'doc-1',
      chunk_id: 'chunk-1',
    })

    expect(movePipelineSelectionIndex(0, sections.length, 1)).toBe(1)
    expect(movePipelineSelectionIndex(0, sections.length, -1)).toBe(2)

    const interactiveHtml = renderToStaticMarkup(
      React.createElement(RagTracePipelineTimeline, {
        steps: buildPipelineTimelineSteps(trace),
        selectedKey: 'retrieve',
        onSelectStep: () => {},
      })
    )
    expect(interactiveHtml).toContain('aria-pressed="true"')
  })

  it('surfaces Dify result trace metadata in the stage inspector', () => {
    const trace: RagTrace = {
      schema_version: 1,
      ts_ms: 1710000000000,
      request_id: 'trace-req-001',
      conversation_id: 'conv-1',
      retrieval: {
        mode: 'dify_result',
        query_count: 0,
        top_k: 0,
      },
      rerank: {
        enabled: false,
      },
      citations: [],
      citations_count: 0,
      steps: [
        {
          key: 'retrieve',
          label: 'Retrieve',
          elapsed_sec: 0,
          meta: { mode: 'dify_result' },
        },
        {
          key: 'dify_result',
          label: 'Dify Result',
          meta: {
            answer_chars: 26,
            answer_hash: 'hash-1',
            source_message_id: 'dify-msg-001',
            source_run_id: 'dify-run-001',
            citations_count: 1,
          },
        },
      ],
    }

    const sections = buildPipelineInspectorSections(trace)
    const difySection = sections.find((section) => section.id === 'dify_result')

    expect(difySection).toBeTruthy()
    expect(difySection?.metrics).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ label: 'Answer chars', value: '26' }),
        expect.objectContaining({ label: 'Answer hash', value: 'hash-1' }),
        expect.objectContaining({ label: 'Dify message', value: 'dify-msg-001' }),
        expect.objectContaining({ label: 'Workflow run', value: 'dify-run-001' }),
        expect.objectContaining({ label: 'Citations', value: '1' }),
      ])
    )
  })

  it('simulates citation reordering from local channel weights and cycles trace selection', () => {
    const rows = buildCitationSimulationRows(
      [
        {
          document_id: 'doc-vector',
          chunk_id: 'chunk-vector',
          relevance_score: 0.74,
          rerank_score: 0.31,
          vector_score: 0.93,
          bm25_score: 0.12,
        },
        {
          document_id: 'doc-bm25',
          chunk_id: 'chunk-bm25',
          relevance_score: 0.69,
          rerank_score: 0.42,
          vector_score: 0.14,
          bm25_score: 0.95,
        },
        {
          document_id: 'doc-rerank',
          chunk_id: 'chunk-rerank',
          relevance_score: 0.88,
          rerank_score: 0.97,
          vector_score: 0.22,
          bm25_score: 0.28,
        },
      ],
      {
        rerank_score: 0,
        vector_score: 0,
        bm25_score: 1,
      }
    )

    expect(rows[0]).toMatchObject({
      rank: 1,
      baseRank: 2,
      rankDelta: 1,
      dominantChannelKey: 'bm25_score',
      citation: expect.objectContaining({ document_id: 'doc-bm25' }),
    })
    expect(rows[2]).toMatchObject({
      citation: expect.objectContaining({ document_id: 'doc-vector' }),
    })

    expect(moveTraceSelectionIndex(0, rows.length, -1)).toBe(2)
    expect(moveTraceSelectionIndex(2, rows.length, 1)).toBe(0)
  })

  it('summarizes channel focus counts and filters citations by active retrieval channel', () => {
    const trace: RagTrace = {
      schema_version: 1,
      ts_ms: 1710000000000,
      request_id: 'req-4',
      conversation_id: 'conv-1',
      retrieval: {
        mode: 'hybrid',
        query_count: 1,
        top_k: 8,
        per_query: [
          {
            kind: 'main',
            retriever_debug: {
              channels: {
                vector: { candidates: 8 },
                bm25: { candidates: 5 },
                sparse: { candidates: 2 },
              },
            },
          },
        ],
      },
      rerank: {
        enabled: true,
        provider: 'cohere',
        top_n: 4,
      },
      citations: [
        {
          document_id: 'doc-1',
          chunk_id: 'chunk-a',
          rerank_score: 0.92,
          vector_score: 0.81,
          bm25_score: 0.22,
        },
        {
          document_id: 'doc-2',
          chunk_id: 'chunk-b',
          rerank_score: 0.71,
          bm25_score: 0.66,
        },
        {
          document_id: 'doc-3',
          chunk_id: 'chunk-c',
          rerank_score: 0.63,
          sparse_score: 0.44,
        },
      ],
      citations_count: 3,
      steps: [],
    }

    const summaries = buildTraceCitationChannelSummaries(trace, 'bm25')
    expect(summaries.find((summary) => summary.key === 'all')).toMatchObject({
      matchCount: 3,
      candidateCount: 3,
    })
    expect(summaries.find((summary) => summary.key === 'bm25')).toMatchObject({
      active: true,
      matchCount: 2,
      candidateCount: 5,
    })
    expect(summaries.find((summary) => summary.key === 'vector')).toMatchObject({
      active: false,
      matchCount: 1,
      candidateCount: 8,
    })

    expect(filterTraceCitationsByChannel(trace.citations, 'bm25').map((citation) => citation.chunk_id)).toEqual([
      'chunk-b',
      'chunk-a',
    ])
    expect(filterTraceCitationsByChannel(trace.citations, 'all').map((citation) => citation.chunk_id)).toEqual([
      'chunk-a',
      'chunk-b',
      'chunk-c',
    ])
  })

  it('prioritizes compare candidates with different retrieval configs and summarizes evidence drift', () => {
    const current: RagTrace = {
      schema_version: 1,
      ts_ms: 1710000005000,
      request_id: 'req-current',
      conversation_id: 'conv-1',
      retrieval: {
        mode: 'hybrid',
        retrieval_config_hash: 'cfg-current',
      },
      rerank: {
        enabled: true,
      },
      citations: [
        {
          document_id: 'doc-1',
          chunk_id: 'chunk-shared',
          rerank_score: 0.84,
        },
        {
          document_id: 'doc-2',
          chunk_id: 'chunk-removed',
          rerank_score: 0.61,
        },
      ],
      citations_count: 2,
      steps: [],
    }

    const traces: RagTrace[] = [
      current,
      {
        schema_version: 1,
        ts_ms: 1710000004000,
        request_id: 'req-same-cfg',
        conversation_id: 'conv-1',
        retrieval: {
          mode: 'hybrid',
          retrieval_config_hash: 'cfg-current',
        },
        rerank: { enabled: true },
        citations: [],
        citations_count: 0,
        steps: [],
      },
      {
        schema_version: 1,
        ts_ms: 1710000003000,
        request_id: 'req-changed-cfg',
        conversation_id: 'conv-1',
        retrieval: {
          mode: 'vector',
          retrieval_config_hash: 'cfg-alt',
        },
        rerank: { enabled: false },
        citations: [
          {
            document_id: 'doc-1',
            chunk_id: 'chunk-shared',
            rerank_score: 0.33,
          },
          {
            document_id: 'doc-3',
            chunk_id: 'chunk-added',
            rerank_score: 0.92,
          },
        ],
        citations_count: 2,
        steps: [],
      },
      {
        schema_version: 1,
        ts_ms: 1710000002000,
        request_id: '',
        conversation_id: 'conv-1',
        retrieval: {
          mode: 'hybrid',
        },
        rerank: { enabled: true },
        citations: [],
        citations_count: 0,
        steps: [],
      },
    ]

    const candidates = buildTraceDiffCandidateOptions(traces, current.request_id || '', current.retrieval?.retrieval_config_hash)
    expect(candidates.map((candidate) => candidate.requestId)).toEqual(['req-changed-cfg', 'req-same-cfg'])
    expect(candidates[0]).toMatchObject({
      requestId: 'req-changed-cfg',
      sameRetrievalConfig: false,
      mode: 'vector',
    })

    const drift = buildTraceCitationDiff(current, traces[2]!)
    expect(drift).toMatchObject({
      sharedCount: 1,
      addedCount: 1,
      removedCount: 1,
      scoreShiftCount: 1,
    })
    expect(drift.added[0]).toMatchObject({
      citation: expect.objectContaining({
        document_id: 'doc-3',
        chunk_id: 'chunk-added',
      }),
    })
    expect(drift.removed[0]).toMatchObject({
      citation: expect.objectContaining({
        document_id: 'doc-2',
        chunk_id: 'chunk-removed',
      }),
    })
    expect(drift.scoreShifts[0]).toMatchObject({
      scoreDelta: expect.closeTo(-0.51, 2),
      a: expect.objectContaining({
        document_id: 'doc-1',
        chunk_id: 'chunk-shared',
      }),
      b: expect.objectContaining({
        document_id: 'doc-1',
        chunk_id: 'chunk-shared',
      }),
    })
  })
})
