import { beforeEach, describe, expect, it, vi } from 'vitest'

const client = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
}))

vi.mock('@/lib/api/core', () => ({
  apiClient: client,
}))

import { observabilityApi } from './observability'

describe('observabilityApi index audit repair contracts', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    client.get.mockResolvedValue({ data: { status: 'pending' } })
    client.post.mockResolvedValue({ data: { status: 'enqueued' } })
  })

  it('uses the single-document reconcile and durable status routes', async () => {
    const controller = new AbortController()

    await observabilityApi.reconcileIndexAudit({
      dataset_id: 'dataset-1',
      document_id: 'doc-1',
    })
    await observabilityApi.getIndexAuditReconcileStatus(
      { dataset_id: 'dataset-1', document_id: 'doc-1' },
      { signal: controller.signal }
    )

    expect(client.post).toHaveBeenNthCalledWith(
      1,
      '/observability/index-audit/reconcile',
      { dataset_id: 'dataset-1', document_id: 'doc-1' }
    )
    expect(client.get).toHaveBeenCalledWith(
      '/observability/index-audit/reconcile-status',
      {
        params: { dataset_id: 'dataset-1', document_id: 'doc-1' },
        signal: controller.signal,
      }
    )
  })

  it('exposes the bounded dataset repair-job entry', async () => {
    await observabilityApi.enqueueIndexAuditReconcileJob({
      dataset_id: 'dataset-1',
      limit: 100,
      dry_run: true,
    })

    expect(client.post).toHaveBeenCalledWith(
      '/observability/index-audit/reconcile-jobs',
      { dataset_id: 'dataset-1', limit: 100, dry_run: true }
    )
  })
})
