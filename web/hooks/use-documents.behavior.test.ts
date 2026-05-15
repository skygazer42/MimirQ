// @vitest-environment jsdom

import React, { act } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { Document } from '@/types'
import { renderHook, waitForAssertion } from '@/test/hook-harness'

const documentApiMocks = vi.hoisted(() => ({
  cancel: vi.fn(),
  delete: vi.fn(),
  get: vi.fn(),
  getStatus: vi.fn(),
  list: vi.fn(),
  upload: vi.fn(),
  uploadFromUrl: vi.fn(),
}))

vi.mock('@/lib/api/documents', () => ({
  documentApi: documentApiMocks,
}))

vi.mock('@/contexts/parser-backend-context', () => ({
  useParserBackendPreference: () => ({ parserBackend: 'marker' }),
}))

vi.mock('@/contexts/chunk-strategy-context', () => ({
  useChunkStrategyPreference: () => ({ chunkStrategy: 'semantic' }),
}))

vi.mock('@/contexts/pipeline-options-context', () => ({
  usePipelineOptions: () => ({ enabled: false, options: {} }),
}))

import { useDocuments } from './use-documents'

function makeDocument(overrides: Partial<Document> = {}): Document {
  return {
    id: 'doc-1',
    filename: 'Quarterly Report.pdf',
    status: 'completed',
    metadata: {},
    dataset_id: 'dataset-1',
    archived_at: null,
    disabled_at: null,
    ...overrides,
  } as Document
}

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: {
      mutations: { retry: false },
      queries: { retry: false },
    },
  })

  return {
    queryClient,
    wrapper({ children }: { children: React.ReactNode }) {
      return React.createElement(QueryClientProvider, { client: queryClient }, children)
    },
  }
}

describe('useDocuments behavior', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.spyOn(console, 'error').mockImplementation(() => {})
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('prepends successful uploads and replaces them with the fully refreshed document after polling', async () => {
    documentApiMocks.list.mockResolvedValue({ items: [], total: 0 })

    const uploadedDocument = makeDocument({
      id: 'doc-upload',
      filename: 'upload.pdf',
      status: 'pending',
    })
    const refreshedDocument = makeDocument({
      id: 'doc-upload',
      filename: 'upload.pdf',
      status: 'completed',
      metadata: { page_count: 4 },
    })

    documentApiMocks.upload.mockResolvedValue(uploadedDocument)
    documentApiMocks.getStatus.mockResolvedValue({
      current_stage: 'done',
      error_message: null,
      processing_progress: 100,
      status: 'completed',
    })
    documentApiMocks.get.mockResolvedValue(refreshedDocument)

    const { queryClient, wrapper } = createWrapper()
    const hook = renderHook(() => useDocuments(), { wrapper })
    const file = new File(['pdf-bytes'], 'upload.pdf', { type: 'application/pdf' })

    await waitForAssertion(() => {
      expect(documentApiMocks.list).toHaveBeenCalledTimes(1)
    })

    await act(async () => {
      await hook.result.current.uploadDocument(file)
    })

    await waitForAssertion(() => {
      expect(hook.result.current.documents).toHaveLength(1)
      expect(hook.result.current.documents[0]).toMatchObject({
        id: 'doc-upload',
        status: 'completed',
        metadata: { page_count: 4 },
      })
      expect(hook.result.current.total).toBe(1)
      expect(hook.result.current.error).toBeNull()
      expect(hook.result.current.isLoading).toBe(false)
    })

    expect(documentApiMocks.upload).toHaveBeenCalledWith(file, {
      chunk_strategy: 'semantic',
      dataset_id: undefined,
      parser_backend: 'marker',
      pipeline: undefined,
    })
    expect(documentApiMocks.getStatus).toHaveBeenCalledWith('doc-upload')
    expect(documentApiMocks.get).toHaveBeenCalledWith('doc-upload')

    hook.unmount()
    queryClient.clear()
  })

  it('surfaces upload errors with formatted API details', async () => {
    documentApiMocks.list.mockResolvedValue({ items: [], total: 0 })
    documentApiMocks.upload.mockRejectedValue({
      response: {
        data: {
          message: 'Upload exploded',
          request_id: 'req-9',
        },
      },
    })

    const { queryClient, wrapper } = createWrapper()
    const hook = renderHook(() => useDocuments(), { wrapper })
    const file = new File(['broken'], 'broken.pdf', { type: 'application/pdf' })

    await waitForAssertion(() => {
      expect(documentApiMocks.list).toHaveBeenCalledTimes(1)
    })

    await act(async () => {
      try {
        await hook.result.current.uploadDocument(file)
      } catch {
        // mutateAsync rejects, but the hook should also expose a formatted error.
      }
    })

    await waitForAssertion(() => {
      expect(hook.result.current.error).toBe('Upload exploded (request_id=req-9)')
      expect(hook.result.current.documents).toEqual([])
      expect(hook.result.current.isLoading).toBe(false)
    })

    hook.unmount()
    queryClient.clear()
  })

  it('reacts when caller-provided list params change after mount', async () => {
    documentApiMocks.list.mockImplementation(async (params) => ({
      items:
        params?.dataset_id === 'dataset-2'
          ? [makeDocument({ id: 'doc-dataset-2', dataset_id: 'dataset-2' })]
          : [makeDocument({ id: 'doc-dataset-1', dataset_id: 'dataset-1' })],
      total: 1,
    }))

    let currentDatasetId = 'dataset-1'
    const { queryClient, wrapper } = createWrapper()
    const hook = renderHook(
      () =>
        useDocuments({
          dataset_id: currentDatasetId,
          lifecycle: 'active',
          limit: 100,
        }),
      { wrapper }
    )

    await waitForAssertion(() => {
      expect(documentApiMocks.list).toHaveBeenCalledWith({
        dataset_id: 'dataset-1',
        lifecycle: 'active',
        limit: 100,
      })
      expect(hook.result.current.documents[0]?.dataset_id).toBe('dataset-1')
    })

    currentDatasetId = 'dataset-2'
    hook.rerender()

    await waitForAssertion(() => {
      expect(documentApiMocks.list).toHaveBeenCalledWith({
        dataset_id: 'dataset-2',
        lifecycle: 'active',
        limit: 100,
      })
      expect(hook.result.current.documents[0]?.dataset_id).toBe('dataset-2')
    })

    hook.unmount()
    queryClient.clear()
  })
})
