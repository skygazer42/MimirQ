// @vitest-environment happy-dom

import { act } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { toast } from 'sonner'

import { downloadBlob } from '@/lib/download'
import { renderHook } from '@/test/hook-harness'
import { useReportExports } from './use-report-exports'

const api = vi.hoisted(() => ({
  exportDatasetReportJson: vi.fn<typeof import('@/lib/api/reports').reportApi.exportDatasetReportJson>(),
  exportDatasetReportHtml: vi.fn<typeof import('@/lib/api/reports').reportApi.exportDatasetReportHtml>(),
  exportDatasetRagAuditHtml: vi.fn<typeof import('@/lib/api/reports').reportApi.exportDatasetRagAuditHtml>(),
  exportDatasetReportBundleZip: vi.fn<typeof import('@/lib/api/reports').reportApi.exportDatasetReportBundleZip>(),
}))
const auth = vi.hoisted(() => ({ sessionKey: 'report-session' }))

vi.mock('@/lib/api/reports', () => ({ reportApi: api }))
vi.mock('@/lib/auth-storage', () => ({ getAuthSessionKey: () => auth.sessionKey }))
vi.mock('@/lib/download', () => ({ downloadBlob: vi.fn() }))
vi.mock('sonner', () => ({ toast: { error: vi.fn(), success: vi.fn() } }))
vi.mock('@/lib/client-logging', () => ({ reportClientError: vi.fn() }))

const hooks: Array<{ unmount: () => void }> = []
beforeEach(() => {
  vi.clearAllMocks()
  auth.sessionKey = 'report-session'
})
afterEach(() => {
  for (const hook of hooks.splice(0)) hook.unmount()
})

describe('reports bundle export', () => {
  it('downloads the current redacted bundle once for repeated clicks', async () => {
    const request = Promise.withResolvers<Blob>()
    api.exportDatasetReportBundleZip.mockReturnValueOnce(request.promise)
    const hook = renderHook(() =>
      useReportExports({
        sessionKey: 'report-session',
        datasetId: 'dataset-1',
        pipelineHash: 'pipeline-1',
        connectorRunsLimit: 50,
        redact: true,
      }),
    )
    hooks.push(hook)
    let operation!: Promise<void>
    act(() => {
      operation = hook.result.current.exportReport('bundle')
      void hook.result.current.exportReport('bundle')
    })

    expect(api.exportDatasetReportBundleZip).toHaveBeenCalledOnce()
    expect(api.exportDatasetReportBundleZip).toHaveBeenCalledWith(
      'dataset-1',
      { pipeline_hash: 'pipeline-1', connector_runs_limit: 50, redact: true },
      { signal: expect.any(AbortSignal) },
    )
    expect(hook.result.current.exporting).toBe('bundle')
    const bundle = new Blob(['bundle'], { type: 'application/zip' })
    await act(async () => {
      request.resolve(bundle)
      await operation
    })

    expect(downloadBlob).toHaveBeenCalledExactlyOnceWith('dataset.report-bundle.zip', bundle)
    expect(toast.success).toHaveBeenCalledOnce()
    expect(hook.result.current.exporting).toBeNull()
  })

  it('aborts an export when its login changes and ignores the old result', async () => {
    const request = Promise.withResolvers<Blob>()
    api.exportDatasetReportBundleZip.mockReturnValueOnce(request.promise)
    const hook = renderHook(() =>
      useReportExports({
        sessionKey: auth.sessionKey,
        datasetId: 'dataset-1',
        pipelineHash: '',
        connectorRunsLimit: 20,
        redact: true,
      }),
    )
    hooks.push(hook)
    let operation!: Promise<void>
    act(() => {
      operation = hook.result.current.exportReport('bundle')
    })
    const signal = api.exportDatasetReportBundleZip.mock.calls[0][2]?.signal

    auth.sessionKey = 'replacement-session'
    hook.rerender()
    expect(signal?.aborted).toBe(true)
    await act(async () => {
      request.resolve(new Blob(['old bundle']))
      await operation
    })

    expect(downloadBlob).not.toHaveBeenCalled()
    expect(toast.success).not.toHaveBeenCalled()
    expect(toast.error).not.toHaveBeenCalled()
    expect(hook.result.current.exporting).toBeNull()
  })
})
