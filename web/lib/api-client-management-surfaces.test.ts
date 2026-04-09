import { afterEach, describe, expect, it, vi } from 'vitest'

import { auditApi } from './api/audit'
import { apiClient } from './api/core'
import { promptTemplateApi } from './api/prompts'
import { reportApi } from './api/reports'
import { settingsApi } from './api/settings'
import { usageApi } from './api/usage'

afterEach(() => {
  vi.restoreAllMocks()
})

describe('management surface api clients', () => {
  it('posts duplicate and new-version prompt template requests to the expected endpoints', async () => {
    const duplicatePayload = { data: { id: 'dup-1', name: 'Copy' } }
    const versionPayload = { data: { id: 'ver-1', version: 4 } }
    const postSpy = vi.spyOn(apiClient, 'post')
    postSpy.mockResolvedValueOnce(duplicatePayload as never)
    postSpy.mockResolvedValueOnce(versionPayload as never)

    await expect(promptTemplateApi.duplicate('tpl-123')).resolves.toEqual(duplicatePayload.data)
    await expect(
      promptTemplateApi.createVersion('tpl-123', {
        content: 'v4',
        description: 'next rollout',
        is_active: true,
        deactivate_previous: true,
      })
    ).resolves.toEqual(versionPayload.data)

    expect(postSpy).toHaveBeenNthCalledWith(1, '/prompt-templates/tpl-123/duplicate')
    expect(postSpy).toHaveBeenNthCalledWith(2, '/prompt-templates/tpl-123/versions', {
      content: 'v4',
      description: 'next rollout',
      is_active: true,
      deactivate_previous: true,
    })
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
})
