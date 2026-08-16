// @vitest-environment happy-dom

import React, { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const hookState = vi.hoisted(() => ({
  indexAudit: null as any,
  indexAuditError: null as string | null,
  indexAuditHasDocumentScope: false,
  indexAuditLoading: false,
  indexAuditReconcileState: {
    status: 'idle' as 'idle' | 'loading' | 'success' | 'error',
    message: null as string | null,
    taskId: null as string | null,
    backendStatus: null as string | null,
    currentIndexReadiness: null as string | null,
  } as {
    status: 'idle' | 'loading' | 'success' | 'error'
    message: string | null
    taskId: string | null
    backendStatus: string | null
    currentIndexReadiness: string | null
  },
  reconcileIndexAudit: vi.fn(),
  runIndexAudit: vi.fn(),
}))

vi.mock('@/hooks/use-index-audit', async (importOriginal) => {
  const actual =
    await importOriginal<typeof import('@/hooks/use-index-audit')>()
  return {
    ...actual,
    useIndexAudit: () => hookState,
  }
})
vi.mock('next-intl', () => ({
  useTranslations: () => (key: string) => key,
}))
vi.mock('framer-motion', async () => {
  const React = await import('react')
  return {
    motion: new Proxy(
      {},
      {
        get: (_target, tag: string) =>
          ({
            children,
            ...props
          }: React.HTMLAttributes<HTMLElement> & {
            whileHover?: unknown
          }) => {
            delete props.whileHover
            return React.createElement(tag, props, children)
          },
      }
    ),
  }
})

import {
  buildIndexAuditReconcilePayload,
  pollIndexAuditReconcileStatus,
} from '@/hooks/use-index-audit'

import { KnowledgeRetrievalPanel } from './knowledge-retrieval-panel'

describe('KnowledgeRetrievalPanel', () => {
  beforeEach(() => {
    ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
    hookState.indexAudit = null
    hookState.indexAuditError = null
    hookState.indexAuditHasDocumentScope = false
    hookState.indexAuditLoading = false
    hookState.indexAuditReconcileState = {
      status: 'idle',
      message: null,
      taskId: null,
      backendStatus: null,
      currentIndexReadiness: null,
    }
    hookState.reconcileIndexAudit.mockReset()
    hookState.runIndexAudit.mockReset()
  })

  afterEach(() => {
    document.body.innerHTML = ''
    vi.clearAllMocks()
  })

  it('renders compat and unknown channel states and exposes reconcile only with document scope', async () => {
    hookState.indexAudit = {
      tenant_id: 'tenant-1',
      dataset_id: 'dataset-1',
      vector_backend: 'milvus',
      active_documents: 2,
      active_chunks: 4,
      vector_id_missing: 0,
      vector_ids_checked: 4,
      vector_ids_missing_in_backend: 0,
      vector_ids_missing_in_backend_sample: [],
      milvus_ids_sampled: 0,
      milvus_orphan_ids_sample: [],
      index_channels: {
        documents_with_channel_rows: 1,
        documents_using_legacy_fallback: 1,
        ready_documents: 0,
        required_pending_documents: 0,
        required_error_documents: 1,
        status_counts_by_channel: {
          vector: { ready: 2 },
          bm25: { error: 1 },
          sparse: { disabled: 1 },
        },
        legacy_by_channel: { sparse: 1 },
      },
    }
    hookState.indexAuditHasDocumentScope = true
    hookState.indexAuditReconcileState = {
      status: 'success',
      message: '已提交索引修复任务',
      taskId: 'task-1',
      backendStatus: 'ready',
      currentIndexReadiness: 'ready',
    }

    const container = document.createElement('div')
    document.body.appendChild(container)
    const root = createRoot(container)

    act(() => {
      root.render(
        React.createElement(KnowledgeRetrievalPanel, {
          selectedDatasetId: 'dataset-1',
          selectedDocumentIds: ['doc-1'],
          compact: true,
        })
      )
    })

    expect(container.textContent).toContain('vector')
    expect(container.textContent).toContain('Ready')
    expect(container.textContent).toContain('bm25')
    expect(container.textContent).toContain('Error')
    expect(container.textContent).toContain('兼容 / disabled 1 · legacy 1')
    expect(container.textContent).toContain('compat 1')
    expect(container.textContent).toContain('unknown 0')
    expect(container.textContent).toContain('发现索引错误')
    expect(container.textContent).toContain('Reconcile')
    expect(container.textContent).toContain('已提交索引修复任务')
    expect(container.textContent).toContain('[ready]')

    const reconcileButton = Array.from(
      container.querySelectorAll<HTMLButtonElement>('button')
    ).find((button) => button.textContent?.includes('Reconcile'))
    expect(reconcileButton).not.toBeUndefined()

    await act(async () => {
      reconcileButton?.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })
    expect(hookState.reconcileIndexAudit).toHaveBeenCalledTimes(1)

    act(() => root.unmount())
  })

  it('stops polling once reconcile status becomes ready', async () => {
    const fetchStatus = vi
      .fn()
      .mockResolvedValueOnce({
        status: 'pending',
        current_index_readiness: {
          ready: false,
          pending_channels: ['bm25'],
          error_channels: [],
        },
      })
      .mockResolvedValueOnce({
        status: 'ready',
        current_index_readiness: {
          ready: true,
          pending_channels: [],
          error_channels: [],
        },
      })

    const result = await pollIndexAuditReconcileStatus({
      datasetId: 'dataset-1',
      documentId: 'doc-1',
      fetchStatus,
      wait: async () => undefined,
    })

    expect(fetchStatus).toHaveBeenCalledTimes(2)
    expect(result).toEqual({
      status: 'success',
      message: '索引修复完成 · ready',
      backendStatus: 'ready',
      currentIndexReadiness: 'ready',
    })
  })

  it('uses the backend single-document reconcile contract', () => {
    expect(buildIndexAuditReconcilePayload('dataset-1', 'doc-1')).toEqual({
      dataset_id: 'dataset-1',
      document_id: 'doc-1',
    })
  })

  it('does not report unaudited aggregate counters as healthy', () => {
    const container = document.createElement('div')
    document.body.appendChild(container)
    const root = createRoot(container)

    act(() => {
      root.render(
        React.createElement(KnowledgeRetrievalPanel, {
          aggregateDocuments: 2,
          aggregateChunks: 8,
          compact: true,
        })
      )
    })

    expect(container.textContent).toContain('聚合数据（未审计）')
    expect(container.textContent).not.toContain('正常运行')
    expect(container.textContent).toContain('未知')

    act(() => root.unmount())
  })

  it('stops polling after the bounded pending timeout', async () => {
    const fetchStatus = vi.fn().mockResolvedValue({
      status: 'pending',
      current_index_readiness: {
        ready: false,
        pending_channels: ['bm25'],
        error_channels: [],
      },
    })

    const result = await pollIndexAuditReconcileStatus({
      datasetId: 'dataset-1',
      documentId: 'doc-1',
      fetchStatus,
      maxAttempts: 3,
      wait: async () => undefined,
    })

    expect(fetchStatus).toHaveBeenCalledTimes(3)
    expect(result).toEqual({
      status: 'error',
      message: '索引修复状态轮询超时，请稍后手动刷新审计结果',
      backendStatus: 'unknown',
      currentIndexReadiness: null,
    })
  })
})
