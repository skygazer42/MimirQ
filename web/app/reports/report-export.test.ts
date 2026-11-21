// @vitest-environment happy-dom

import { act } from 'react'
import { AxiosError, AxiosHeaders } from 'axios'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { toast } from 'sonner'
import { reportClientError } from '@/lib/client-logging'
import { downloadBlob } from '@/lib/download'
import { renderHook } from '@/test/hook-harness'
import { reportExportParams } from './report-export'
import { useReportExports } from './use-report-exports'

const api = vi.hoisted(() => ({
  exportDatasetReportJson: vi.fn<typeof import('@/lib/api/reports').reportApi.exportDatasetReportJson>(),
  exportDatasetReportHtml: vi.fn<typeof import('@/lib/api/reports').reportApi.exportDatasetReportHtml>(),
  exportDatasetRagAuditHtml: vi.fn<typeof import('@/lib/api/reports').reportApi.exportDatasetRagAuditHtml>(),
  exportDatasetReportBundleZip: vi.fn<typeof import('@/lib/api/reports').reportApi.exportDatasetReportBundleZip>(),
}))

vi.mock('@/lib/api/reports', () => ({ reportApi: api }))
vi.mock('@/lib/auth-storage', () => ({ getAuthSessionKey: () => 'report-session' }))
vi.mock('@/lib/download', () => ({ downloadBlob: vi.fn() }))
vi.mock('sonner', () => ({ toast: { error: vi.fn(), success: vi.fn() } }))
vi.mock('@/lib/client-logging', () => ({ reportClientError: vi.fn() }))
beforeEach(() => vi.clearAllMocks())

const hooks: Array<{ unmount: () => void }> = []
afterEach(() => {
  for (const hook of hooks.splice(0)) hook.unmount()
})

describe('report export recovery', () => {
  it('reads JSON blob errors while releasing the pending state and retaining the error object', async () => {
    const data = new Blob([JSON.stringify({ detail: '导出服务暂不可用' })], { type: 'application/json' })
    const failure = new AxiosError('Request failed with status code 503', undefined, undefined, undefined, {
      status: 503,
      statusText: 'Service Unavailable',
      headers: {},
      config: { headers: new AxiosHeaders() },
      data,
    })
    const request = Promise.withResolvers<Blob>()
    api.exportDatasetReportHtml.mockReturnValueOnce(request.promise)
    const hook = renderHook(() =>
      useReportExports({
        sessionKey: 'report-session',
        datasetId: 'dataset',
        pipelineHash: 'pipeline',
        connectorRunsLimit: 20,
        redact: false,
      }),
    )
    hooks.push(hook)
    let operation!: Promise<void>
    act(() => {
      operation = hook.result.current.exportReport('html')
    })
    expect(hook.result.current.exporting).toBe('html')

    await act(async () => {
      request.reject(failure)
      await operation
    })
    expect(toast.error).toHaveBeenCalledWith('导出服务暂不可用')
    expect(hook.result.current.exporting).toBeNull()
    expect(reportClientError).toHaveBeenCalledWith('导出 HTML 报告失败', failure)
    expect(failure.response?.data).toBe(data)
    expect(downloadBlob).not.toHaveBeenCalled()
    expect(toast.success).not.toHaveBeenCalled()
  })
  it('keeps raw JSON exports free of the redaction parameter', () => {
    expect(reportExportParams('', 20)).toEqual({ connector_runs_limit: 20 })
    expect(reportExportParams(' pipeline ', 50, false)).toEqual({
      pipeline_hash: 'pipeline',
      connector_runs_limit: 50,
      redact: false,
    })
  })
})
