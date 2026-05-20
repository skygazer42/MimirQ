import { afterEach, describe, expect, it, vi } from 'vitest'

import { auditApi } from './api/audit'
import { apiClient } from './api/core'
import { difyExternalKnowledgeApi } from './api/dify'
import { promptTemplateApi } from './api/prompts'
import { reportApi } from './api/reports'
import { settingsApi } from './api/settings'
import { usageApi } from './api/usage'
import { API_LONG_TIMEOUT_MS } from './env'

afterEach(() => {
  vi.restoreAllMocks()
})

describe('management surface api clients', () => {
  it('posts duplicate and new-version prompt template requests to the expected endpoints', async () => {
    const duplicatePayload = { data: { id: 'dup-1', name: 'Copy' } }
    const versionPayload = { data: { id: 'ver-1', version: 4 } }
    const syncPayload = { data: { created: 4, updated: 0, template_keys: ['rag_answer_claude_xml_zh'] } }
    const postSpy = vi.spyOn(apiClient, 'post')
    postSpy.mockResolvedValueOnce(duplicatePayload as never)
    postSpy.mockResolvedValueOnce(versionPayload as never)
    postSpy.mockResolvedValueOnce(syncPayload as never)

    await expect(promptTemplateApi.duplicate('tpl-123')).resolves.toEqual(duplicatePayload.data)
    await expect(
      promptTemplateApi.createVersion('tpl-123', {
        content: 'v4',
        description: 'next rollout',
        is_active: true,
        deactivate_previous: true,
      })
    ).resolves.toEqual(versionPayload.data)
    await expect(promptTemplateApi.syncBuiltins()).resolves.toEqual(syncPayload.data)

    expect(postSpy).toHaveBeenNthCalledWith(1, '/prompt-templates/tpl-123/duplicate')
    expect(postSpy).toHaveBeenNthCalledWith(2, '/prompt-templates/tpl-123/versions', {
      content: 'v4',
      description: 'next rollout',
      is_active: true,
      deactivate_previous: true,
    })
    expect(postSpy).toHaveBeenNthCalledWith(3, '/prompt-templates/builtins/sync')
  })

  it('passes report query params and blob response types through export helpers', async () => {
    const reportPayload = { data: { dataset_id: 'ds-1', profile: { total_documents: 2 } } }
    const blob = new Blob(['report'])
    const getSpy = vi.spyOn(apiClient, 'get')
    getSpy
      .mockResolvedValueOnce(reportPayload as never)
      .mockResolvedValueOnce({ data: blob } as never)
      .mockResolvedValueOnce({ data: blob } as never)
      .mockResolvedValueOnce({ data: blob } as never)

    await expect(
      reportApi.getDatasetReport('ds-1', { pipeline_hash: 'abc123', connector_runs_limit: 12 })
    ).resolves.toEqual(reportPayload.data)
    await expect(reportApi.exportDatasetReportJson('ds-1', { pipeline_hash: 'abc123' })).resolves.toBe(blob)
    await expect(reportApi.exportDatasetReportHtml('ds-1', { redact: true })).resolves.toBe(blob)
    await expect(reportApi.exportDatasetReportBundleZip('ds-1', { redact: false })).resolves.toBe(blob)

    expect(getSpy).toHaveBeenNthCalledWith(1, '/reports/datasets/ds-1', {
      params: { pipeline_hash: 'abc123', connector_runs_limit: 12 },
    })
    expect(getSpy).toHaveBeenNthCalledWith(2, '/reports/datasets/ds-1/export', {
      params: { pipeline_hash: 'abc123' },
      responseType: 'blob',
    })
    expect(getSpy).toHaveBeenNthCalledWith(3, '/reports/datasets/ds-1/export-html', {
      params: { redact: true },
      responseType: 'blob',
    })
    expect(getSpy).toHaveBeenNthCalledWith(4, '/reports/datasets/ds-1/export-bundle', {
      params: { redact: false },
      responseType: 'blob',
    })
  })

  it('covers system settings get/update/status and llm test helpers', async () => {
    const getSpy = vi.spyOn(apiClient, 'get')
    const putSpy = vi.spyOn(apiClient, 'put')
    const postSpy = vi.spyOn(apiClient, 'post')

    getSpy
      .mockResolvedValueOnce({ data: { feature_flags: { kg_enabled: true } } } as never)
      .mockResolvedValueOnce({ data: { database: { connected: true, message: 'ok' } } } as never)
    putSpy.mockResolvedValueOnce({ data: { success: true, message: 'saved', updated_keys: ['feature_flags.kg_enabled'] } } as never)
    postSpy.mockResolvedValueOnce({ data: { success: true, message: 'llm ok' } } as never)

    await expect(settingsApi.get()).resolves.toMatchObject({ feature_flags: { kg_enabled: true } })
    await expect(settingsApi.update({ feature_flags: { kg_enabled: false } as never })).resolves.toEqual({
      success: true,
      message: 'saved',
      updated_keys: ['feature_flags.kg_enabled'],
    })
    await expect(settingsApi.getStatus()).resolves.toMatchObject({ database: { connected: true } })
    await expect(
      settingsApi.testLLM({
        api_key: 'sk-test',
        api_base: 'https://example.com',
        model: 'gpt-test',
      })
    ).resolves.toEqual({ success: true, message: 'llm ok' })

    expect(getSpy).toHaveBeenNthCalledWith(1, '/settings')
    expect(putSpy).toHaveBeenCalledWith('/settings', { feature_flags: { kg_enabled: false } })
    expect(getSpy).toHaveBeenNthCalledWith(2, '/settings/status')
    expect(postSpy).toHaveBeenCalledWith('/settings/llm/test', {
      api_key: 'sk-test',
      api_base: 'https://example.com',
      model: 'gpt-test',
    })
  })

  it('posts external knowledge retrieval payloads to the dify integration endpoint', async () => {
    const postSpy = vi.spyOn(apiClient, 'post')
    postSpy.mockResolvedValueOnce({
      data: {
        records: [
          {
            content: 'chunk text',
            score: 0.91,
            title: 'Doc A',
            metadata: { dataset_id: 'ds-1' },
          },
        ],
      },
    } as never)

    await expect(
      difyExternalKnowledgeApi.retrieve({
        knowledge_id: 'sales-all',
        query: '报价口径',
        retrieval_setting: { top_k: 4, score_threshold: 0.3 },
        metadata_condition: { filter: { lifecycle: { $eq: 'active' } } },
      })
    ).resolves.toEqual({
      records: [
        {
          content: 'chunk text',
          score: 0.91,
          title: 'Doc A',
          metadata: { dataset_id: 'ds-1' },
        },
      ],
    })

    expect(postSpy).toHaveBeenCalledWith('/integrations/dify/retrieval', {
      knowledge_id: 'sales-all',
      query: '报价口径',
      retrieval_setting: { top_k: 4, score_threshold: 0.3 },
      metadata_condition: { filter: { lifecycle: { $eq: 'active' } } },
    })
  })

  it('forwards usage summary and quota requests to the expected endpoints', async () => {
    const getSpy = vi.spyOn(apiClient, 'get')
    getSpy
      .mockResolvedValueOnce({ data: { total_assistant_tokens: 11 } } as never)
      .mockResolvedValueOnce({ data: { total_llm_total_tokens: 22 } } as never)
      .mockResolvedValueOnce({ data: { enabled: true, exceeded: false } } as never)
      .mockResolvedValueOnce({ data: { datasets: [] } } as never)

    await expect(usageApi.getChatTokenUsageSummary({ window_days: 7 })).resolves.toMatchObject({ total_assistant_tokens: 11 })
    await expect(usageApi.getChatCostUsageSummary({ since: '2026-04-01' })).resolves.toMatchObject({ total_llm_total_tokens: 22 })
    await expect(usageApi.getChatTokenQuotaStatus()).resolves.toMatchObject({ enabled: true })
    await expect(usageApi.getTenantQuotaSummary()).resolves.toMatchObject({ datasets: [] })

    expect(getSpy).toHaveBeenNthCalledWith(1, '/usage/chat/tokens/summary', { params: { window_days: 7 } })
    expect(getSpy).toHaveBeenNthCalledWith(2, '/usage/chat/cost/summary', { params: { since: '2026-04-01' } })
    expect(getSpy).toHaveBeenNthCalledWith(3, '/usage/chat/tokens/quota')
    expect(getSpy).toHaveBeenNthCalledWith(4, '/usage/tenant/quotas')
  })

  it('parses access-graph export cursors from response headers and tolerates malformed values', async () => {
    const blob = new Blob(['graph'])
    const getSpy = vi.spyOn(apiClient, 'get')
    getSpy
      .mockResolvedValueOnce({
        data: blob,
        headers: {
          'x-next-cursor': JSON.stringify({
            after_kind: 'dataset',
            after_created_at: '2026-04-09T00:00:00Z',
            after_id: 'cursor-1',
          }),
        },
      } as never)
      .mockResolvedValueOnce({
        data: blob,
        headers: {
          'x-next-cursor': '{bad json',
        },
      } as never)

    await expect(auditApi.exportAccessGraphPage({ limit: 200, export_format: 'ndjson' })).resolves.toEqual({
      blob,
      nextCursor: {
        after_kind: 'dataset',
        after_created_at: '2026-04-09T00:00:00Z',
        after_id: 'cursor-1',
      },
    })
    await expect(auditApi.exportAccessGraphPage({ limit: 50, export_format: 'json' })).resolves.toEqual({
      blob,
      nextCursor: null,
    })

    expect(getSpy).toHaveBeenNthCalledWith(1, '/audit/access-graph/export', {
      params: { limit: 200, export_format: 'ndjson' },
      responseType: 'blob',
    })
    expect(getSpy).toHaveBeenNthCalledWith(2, '/audit/access-graph/export', {
      params: { limit: 50, export_format: 'json' },
      responseType: 'blob',
    })
  })

  it('forwards audit purge scope and filters to the backend purge endpoint', async () => {
    const postSpy = vi.spyOn(apiClient, 'post')
    postSpy.mockResolvedValueOnce({
      data: { scope: 'filtered', eligible: 4, deleted: 0 },
    } as never)

    await expect(
      auditApi.purgeLogs({
        purge_scope: 'filtered',
        action: 'audit.logs.purge',
        actor_id: 'demo',
        max_delete: 100,
        dry_run: true,
      })
    ).resolves.toMatchObject({ scope: 'filtered', eligible: 4 })

    expect(postSpy).toHaveBeenCalledWith('/audit/logs/purge', undefined, {
      params: {
        purge_scope: 'filtered',
        action: 'audit.logs.purge',
        actor_id: 'demo',
        max_delete: 100,
        dry_run: true,
      },
    })
  })

  it('calls audit single and bulk delete endpoints with selected ids', async () => {
    const deleteSpy = vi.spyOn(apiClient, 'delete')
    const postSpy = vi.spyOn(apiClient, 'post')
    deleteSpy.mockResolvedValueOnce({ data: { requested: 1, deleted: 1, missing: 0, ids: ['log-1'] } } as never)
    postSpy.mockResolvedValueOnce({ data: { requested: 2, deleted: 2, missing: 0, ids: ['log-1', 'log-2'] } } as never)

    await expect(auditApi.deleteLog('log/1')).resolves.toMatchObject({ deleted: 1 })
    await expect(auditApi.bulkDeleteLogs(['log-1', 'log-2'])).resolves.toMatchObject({ deleted: 2 })

    expect(deleteSpy).toHaveBeenCalledWith('/audit/logs/log%2F1')
    expect(postSpy).toHaveBeenCalledWith(
      '/audit/logs/bulk-delete',
      {
        ids: ['log-1', 'log-2'],
      },
      { timeout: API_LONG_TIMEOUT_MS }
    )
  })

  it('chunks audit bulk delete requests at the backend request limit', async () => {
    const ids = Array.from({ length: 501 }, (_, index) => `00000000-0000-0000-0000-${String(index).padStart(12, '0')}`)
    const postSpy = vi.spyOn(apiClient, 'post')
    postSpy
      .mockResolvedValueOnce({ data: { requested: 500, deleted: 499, missing: 1, ids: ids.slice(0, 500) } } as never)
      .mockResolvedValueOnce({ data: { requested: 1, deleted: 1, missing: 0, ids: ids.slice(500) } } as never)

    await expect(auditApi.bulkDeleteLogs(ids)).resolves.toMatchObject({
      requested: 501,
      deleted: 500,
      missing: 1,
    })

    expect(postSpy).toHaveBeenCalledTimes(2)
    expect(postSpy).toHaveBeenNthCalledWith(1, '/audit/logs/bulk-delete', { ids: ids.slice(0, 500) }, { timeout: API_LONG_TIMEOUT_MS })
    expect(postSpy).toHaveBeenNthCalledWith(2, '/audit/logs/bulk-delete', { ids: ids.slice(500) }, { timeout: API_LONG_TIMEOUT_MS })
  })
})
