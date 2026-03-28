import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import type { RagTrace } from '@/types'

import {
  RagTracePipelineTimeline,
  buildPipelineInspectorSections,
  buildPipelineTimelineSteps,
  movePipelineSelectionIndex,
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
})
