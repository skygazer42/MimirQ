// @vitest-environment happy-dom

import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'
import { MetricControls } from './diagnostics-controls'
import { metricRows, previewSummary, type PreviewResult, type ProbeStatus } from './diagnostics-model'
import { RetrievalChain } from './retrieval-chain'
import { DiagnosticEmpty } from './diagnostic-empty'
import type { DiagnosticsController } from './use-diagnostics'

vi.stubGlobal('React', React)
vi.mock('@/i18n/navigation', () => ({ Link: 'a' }))

function controller(status: ProbeStatus = 'idle', result: PreviewResult | null = null) {
  const metrics = metricRows(result?.preview ?? null)
  return {
    preview: { status, result, error: status === 'error' ? '检索服务暂不可用' : null },
    summary: previewSummary(result),
    metrics,
    visibleMetrics: metrics.map((metric) => metric.key),
    documents: [],
  } as unknown as DiagnosticsController
}

describe('retrieval presentation', () => {
  it('shows one guide before running and keeps all metrics available in a closed disclosure', () => {
    const c = controller()
    const output = renderToStaticMarkup(<RetrievalChain controller={c} />)
    expect(output).toContain('尚未运行检索预览')
    expect(output).not.toContain('待执行')
    expect(output).not.toContain('<table')
    expect(output).toContain('召回与引用核对')
    expect(output).toContain('检索链路与耗时')
    expect(output).toContain('相关性与安全评分')
    expect(output).toContain('向量漂移检查')
    expect(output).toContain('性能门禁压测')
    const controls = renderToStaticMarkup(<MetricControls controller={c} />)
    expect(controls).toContain('显示指标（已选 10 / 10 项）')
    expect(controls).not.toContain(' open=')
    expect(controls.match(/role="checkbox"/g)).toHaveLength(10)
  })

  it.each(['running', 'error'] as const)('keeps the full result surface when %s', (status) => {
    const output = renderToStaticMarkup(<RetrievalChain controller={controller(status)} />)
    expect(output).not.toContain('尚未运行检索预览')
    expect(output).toContain('评分读数')
    expect(output).toContain(status === 'running' ? '运行中' : '检索服务暂不可用')
  })

  it('retains the previous result and its failure explanation after a later request fails', () => {
    const result: PreviewResult = {
      scope: { datasetId: 'ds', datasetName: '资料', documentIds: [], documentNames: [], query: '查询' },
      preview: { query_for_retrieval: '查询', prompt_messages: [], prompt_text: '', variables: {}, citations: [] },
      explain: null,
      configHash: null,
      contractReason: null,
      partialErrors: [],
      finishedAt: 1,
    }
    const output = renderToStaticMarkup(<RetrievalChain controller={controller('error', result)} />)
    expect(output).toContain('的上次结果')
    expect(output).toContain('评分读数')
    expect(output).toContain('检索服务暂不可用')
  })

  it.each([
    ['drift', '尚未运行漂移检查', '可比样本范围'],
    ['performance', '尚未运行性能门禁', '基线与门禁结论'],
  ] as const)('keeps the %s guide independent from retrieval results', (kind, title, dimension) => {
    const output = renderToStaticMarkup(<DiagnosticEmpty kind={kind} controller={controller()} />)
    expect(output).toContain(title)
    expect(output).toContain(dimension)
    expect(output).not.toContain('<table')
    expect(output).not.toContain('已通过')
  })

  it('shows a channel timing only when that channel returned one', () => {
    const result: PreviewResult = {
      scope: { datasetId: 'ds', datasetName: '资料', documentIds: [], documentNames: [], query: '查询' },
      preview: { query_for_retrieval: '查询', prompt_messages: [], prompt_text: '', variables: {}, citations: [] },
      explain: {
        channels: { counts: { vector_candidates: 12, bm25_candidates: 4 }, timing: { vector_elapsed_sec: 0.15 } },
      },
      configHash: null,
      contractReason: null,
      partialErrors: [],
      finishedAt: 1,
    }
    const output = document.createElement('div')
    output.innerHTML = renderToStaticMarkup(<RetrievalChain controller={controller('success', result)} />)
    expect(output.querySelector('button[data-kind="vector"]')?.textContent).toContain('0.15 s')
    expect(output.querySelector('button[data-kind="keyword"]')?.textContent).not.toContain(' s')
  })
})
