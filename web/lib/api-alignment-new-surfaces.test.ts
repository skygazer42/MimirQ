import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  datasetApi,
  documentApi,
  industryRulesApi,
  kgApi,
  lineageApi,
  rtbfApi,
} from './api'
import { apiClient } from './api/core'

afterEach(() => {
  vi.restoreAllMocks()
})

describe('newly aligned backend api surfaces', () => {
  it('routes dataset analysis helpers to the dataset analysis endpoints', async () => {
    const blob = new Blob(['png'], { type: 'image/png' })
    const getSpy = vi.spyOn(apiClient, 'get')
    const postSpy = vi.spyOn(apiClient, 'post')

    getSpy
      .mockResolvedValueOnce({ data: { dashboard: true } } as never)
      .mockResolvedValueOnce({ data: { summary: true } } as never)
      .mockResolvedValueOnce({ data: { examples: [] } } as never)
      .mockResolvedValueOnce({ data: { suggestions: [] } } as never)
      .mockResolvedValueOnce({ data: { exported: true } } as never)
      .mockResolvedValueOnce({ data: '{"row":1}\n' } as never)
      .mockResolvedValueOnce({ data: '<html></html>' } as never)
      .mockResolvedValueOnce({ data: { status: 'done' } } as never)
      .mockResolvedValueOnce({ data: blob } as never)
    postSpy
      .mockResolvedValueOnce({ data: { writeback: true } } as never)
      .mockResolvedValueOnce({ data: { task_id: 'task-1' } } as never)

    await expect(datasetApi.getAnalysisDashboard({ limit: 3 })).resolves.toEqual({ dashboard: true })
    await expect(datasetApi.getAnalysisSummary('ds-1', { category: 'risk' })).resolves.toEqual({ summary: true })
    await expect(datasetApi.getAnalysisExamples('ds-1', { limit: 2 })).resolves.toEqual({ examples: [] })
    await expect(
      datasetApi.getAnalysisRuleSuggestions('ds-1', { ruleset: 'industrial_control', limit: 4 })
    ).resolves.toEqual({ suggestions: [] })
    await expect(datasetApi.exportAnalysisJson('ds-1')).resolves.toEqual({ exported: true })
    await expect(datasetApi.exportAnalysisJsonl('ds-1')).resolves.toBe('{"row":1}\n')
    await expect(datasetApi.exportAnalysisHtmlReport('ds-1')).resolves.toBe('<html></html>')
    await expect(
      datasetApi.writebackAnalysisGlossary('ds-1', { ruleset: 'industrial_control', limit: 5 })
    ).resolves.toEqual({ writeback: true })
    await expect(datasetApi.createAnalysisPngExportTask('ds-1', { category: 'risk' })).resolves.toEqual({
      task_id: 'task-1',
    })
    await expect(datasetApi.getAnalysisPngExportTask('ds-1', 'task-1')).resolves.toEqual({ status: 'done' })
    await expect(datasetApi.getAnalysisPngExportResult('ds-1', 'task-1')).resolves.toBe(blob)

    expect(getSpy).toHaveBeenNthCalledWith(1, '/datasets/analysis/dashboard', { params: { limit: 3 } })
    expect(getSpy).toHaveBeenNthCalledWith(2, '/datasets/ds-1/analysis/summary', { params: { category: 'risk' } })
    expect(getSpy).toHaveBeenNthCalledWith(3, '/datasets/ds-1/analysis/examples', { params: { limit: 2 } })
    expect(getSpy).toHaveBeenNthCalledWith(4, '/datasets/ds-1/analysis/rule-suggestions', {
      params: { ruleset: 'industrial_control', limit: 4 },
    })
    expect(getSpy).toHaveBeenNthCalledWith(5, '/datasets/ds-1/analysis/export.json', { params: undefined })
    expect(getSpy).toHaveBeenNthCalledWith(6, '/datasets/ds-1/analysis/export.jsonl', {
      params: undefined,
      responseType: 'text',
    })
    expect(getSpy).toHaveBeenNthCalledWith(7, '/datasets/ds-1/analysis/report.html', {
      params: undefined,
      responseType: 'text',
    })
    expect(postSpy).toHaveBeenNthCalledWith(
      1,
      '/datasets/ds-1/analysis/glossary-writeback',
      undefined,
      { params: { ruleset: 'industrial_control', limit: 5 } }
    )
    expect(postSpy).toHaveBeenNthCalledWith(2, '/datasets/ds-1/analysis/export.png', undefined, {
      params: { category: 'risk' },
    })
    expect(getSpy).toHaveBeenNthCalledWith(8, '/datasets/ds-1/analysis/export-tasks/task-1')
    expect(getSpy).toHaveBeenNthCalledWith(9, '/datasets/ds-1/analysis/export-tasks/task-1/result.png', {
      responseType: 'blob',
    })
  })

  it('routes KG network helpers to the graph analysis endpoints', async () => {
    const postSpy = vi.spyOn(apiClient, 'post').mockResolvedValue({ data: { schema: 'kg' } } as never)
    const body = {
      edges: [{ source: 'A', target: 'B', weight: 1 }],
      start_id: 'A',
      target_id: 'B',
      node_id: 'A',
      algorithm: 'degree' as const,
    }

    await kgApi.getKHopNeighbors(body)
    await kgApi.getShortestPath(body)
    await kgApi.getPathsBetween(body)
    await kgApi.getCentrality(body)
    await kgApi.getCommunityOf(body)
    await kgApi.getConnectedComponent(body)

    expect(postSpy).toHaveBeenNthCalledWith(1, '/kg/network/k_hop_neighbors', body)
    expect(postSpy).toHaveBeenNthCalledWith(2, '/kg/network/shortest_path', body)
    expect(postSpy).toHaveBeenNthCalledWith(3, '/kg/network/paths_between', body)
    expect(postSpy).toHaveBeenNthCalledWith(4, '/kg/network/centrality', body)
    expect(postSpy).toHaveBeenNthCalledWith(5, '/kg/network/community_of', body)
    expect(postSpy).toHaveBeenNthCalledWith(6, '/kg/network/connected_component', body)
  })

  it('routes industry rules helpers to the ruleset CMS endpoints', async () => {
    const getSpy = vi.spyOn(apiClient, 'get')
    const putSpy = vi.spyOn(apiClient, 'put')
    const postSpy = vi.spyOn(apiClient, 'post')

    getSpy
      .mockResolvedValueOnce({ data: { rulesets: [] } } as never)
      .mockResolvedValueOnce({ data: { ruleset: { name: 'industrial control' } } } as never)
    putSpy.mockResolvedValue({ data: { updated: true } } as never)
    postSpy.mockResolvedValueOnce({ data: { changed: true } } as never)

    await industryRulesApi.listRulesets()
    await industryRulesApi.getRuleset('industrial control')
    await industryRulesApi.updateGlossary('industrial control', { glossary: { PLC: ['controller'] } })
    await industryRulesApi.updatePatterns('industrial control', { patterns: [{ name: 'alarm' }] })
    await industryRulesApi.updateIntents('industrial control', { intents: [{ name: 'diagnose' }] })
    await industryRulesApi.previewRewrite({ ruleset: 'industrial control', query: 'PLC alarm' })

    expect(getSpy).toHaveBeenNthCalledWith(1, '/industry-rules/rulesets')
    expect(getSpy).toHaveBeenNthCalledWith(2, '/industry-rules/rulesets/industrial%20control')
    expect(putSpy).toHaveBeenNthCalledWith(1, '/industry-rules/rulesets/industrial%20control/glossary', {
      glossary: { PLC: ['controller'] },
    })
    expect(putSpy).toHaveBeenNthCalledWith(2, '/industry-rules/rulesets/industrial%20control/patterns', {
      patterns: [{ name: 'alarm' }],
    })
    expect(putSpy).toHaveBeenNthCalledWith(3, '/industry-rules/rulesets/industrial%20control/intents', {
      intents: [{ name: 'diagnose' }],
    })
    expect(postSpy).toHaveBeenCalledWith('/industry-rules/preview-rewrite', {
      ruleset: 'industrial control',
      query: 'PLC alarm',
    })
  })

  it('routes lineage, RTBF, and clean DOCX helpers to their backend endpoints', async () => {
    const blob = new Blob(['docx'])
    const getSpy = vi.spyOn(apiClient, 'get')
    const postSpy = vi.spyOn(apiClient, 'post')

    getSpy
      .mockResolvedValueOnce({ data: { chunk: true } } as never)
      .mockResolvedValueOnce({ data: { answer: true } } as never)
      .mockResolvedValueOnce({ data: { ticket_id: 'ticket-1', status: 'accepted', note: 'ok' } } as never)
      .mockResolvedValueOnce({ data: blob } as never)
    postSpy.mockResolvedValueOnce({ data: { dry_run: true } } as never)

    await expect(lineageApi.getChunkLineage('chunk-1')).resolves.toEqual({ chunk: true })
    await expect(lineageApi.getAnswerLineage('request-1')).resolves.toEqual({ answer: true })
    await expect(rtbfApi.request({ subject_account_id: 'user-1', dry_run: true })).resolves.toEqual({
      dry_run: true,
    })
    await expect(rtbfApi.getStatus('ticket-1')).resolves.toMatchObject({ ticket_id: 'ticket-1' })
    await expect(documentApi.cleanDocx('doc-1')).resolves.toBe(blob)

    expect(getSpy).toHaveBeenNthCalledWith(1, '/lineage/chunk/chunk-1')
    expect(getSpy).toHaveBeenNthCalledWith(2, '/lineage/answer/request-1')
    expect(postSpy).toHaveBeenCalledWith('/rtbf/request', { subject_account_id: 'user-1', dry_run: true })
    expect(getSpy).toHaveBeenNthCalledWith(3, '/rtbf/status/ticket-1')
    expect(getSpy).toHaveBeenNthCalledWith(4, '/documents/doc-1/clean-docx', { responseType: 'blob' })
  })
})
