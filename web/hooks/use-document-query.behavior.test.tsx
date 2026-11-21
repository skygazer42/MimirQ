// @vitest-environment happy-dom

import React, { act, useState } from 'react'
import { isCancelledError, QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { Document, DocumentBatchUploadResponse, DocumentList, DocumentStatus } from '@/types/backend'
import { queryKeys } from '@/lib/query-keys'
import { renderHook, waitForAssertion } from '@/test/hook-harness'

const api = vi.hoisted(() => ({
  list: vi.fn(),
  get: vi.fn(),
  getStatus: vi.fn(),
  cancel: vi.fn(),
  delete: vi.fn(),
  uploadBatch: vi.fn(),
  uploadFromUrl: vi.fn(),
}))

vi.mock('@/lib/api/documents', () => ({ documentApi: api }))
vi.mock('@/lib/client-logging', () => ({ reportClientError: vi.fn() }))

import { useDocumentActions } from './use-document-actions'
import { useDocumentList } from './use-document-list'
import { useDocumentPolling } from './use-document-polling'
import { useDocumentUpload } from './use-document-upload'
import type { DocumentListParams } from './use-document-shared'

const cleanup: Array<() => void> = []

function documentRow(id: string, overrides: Partial<Document> = {}): Document {
  return {
    id,
    filename: `${id}.txt`,
    file_type: 'txt',
    file_size: 10,
    status: 'processing',
    processing_progress: 0,
    processing_attempts: 0,
    chunk_count: 0,
    total_characters: 0,
    publication_status: 'draft',
    created_at: '2026-11-04T00:00:00Z',
    updated_at: '2026-11-04T00:00:00Z',
    ...overrides,
  }
}

function statusRow(id: string, processingProgress: number, status: DocumentStatus['status'] = 'processing') {
  return { id, status, processing_progress: processingProgress, processing_attempts: 0 } satisfies DocumentStatus
}

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (error: unknown) => void
  const promise = new Promise<T>((done, fail) => {
    resolve = done
    reject = fail
  })
  return { promise, resolve, reject }
}

function createClient() {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false, staleTime: 10_000, gcTime: Infinity },
      mutations: { retry: 0, gcTime: Infinity },
    },
  })
  cleanup.push(() => client.clear())
  return client
}

function mount<T>(hook: () => T, client = createClient()) {
  const result = renderHook(hook, {
    wrapper: ({ children }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>,
  })
  cleanup.push(result.unmount)
  return result
}

function useDocumentControls(params: DocumentListParams) {
  const [error, setActionError] = useState<string | null>(null)
  const list = useDocumentList({ setActionError, initialParams: params })
  const polling = useDocumentPolling(list)
  const actions = useDocumentActions({ ...list, ...polling, setActionError })
  const uploads = useDocumentUpload({
    ...list,
    preferences: {
      parserBackend: 'auto',
      chunkStrategy: 'langchain_recursive',
      pipelineOverridesEnabled: false,
      pipelineOptions: {},
    },
    pollDocumentStatus: polling.pollDocumentStatus,
    setActionError,
  })
  return { ...list, ...polling, ...actions, ...uploads, error }
}

function mountPolling(initial: Document) {
  const client = createClient()
  const key = queryKeys.documents.list({})
  client.setQueryData<DocumentList>(key, { items: [initial], total: 1 })
  const hook = mount(() => {
    const list = useDocumentList({ initialParams: {}, setActionError: () => undefined })
    return useDocumentPolling(list)
  }, client)
  return { client, key, hook }
}

beforeEach(() => {
  vi.resetAllMocks()
  api.getStatus.mockImplementation(async (id: string) => statusRow(id, 0))
})

afterEach(() => {
  for (const dispose of cleanup.splice(0).reverse()) dispose()
  document.body.innerHTML = ''
})

describe('document query ownership', () => {
  it('keeps an explicit list query when equal initial parameters are recreated', async () => {
    const allDocument = documentRow('all', { filename: 'alpha.txt' })
    const matchingDocument = documentRow('matching', { filename: 'beta.txt' })
    api.list.mockImplementation(async (params: DocumentListParams) => ({
      items: params.q === 'beta' ? [matchingDocument] : [allDocument],
      total: 1,
    }))
    const hook = mount(() => useDocumentControls({ dataset_id: 'dataset-a' }))
    await waitForAssertion(() => expect(hook.result.current.documents).toEqual([allDocument]))

    await act(async () => hook.result.current.loadDocuments({ q: 'beta' }))

    await waitForAssertion(() => expect(hook.result.current.documents).toEqual([matchingDocument]))
    expect(hook.result.current.lastListParamsRef.current.q).toBe('beta')
  })

  it('discards an in-flight status after polling is cancelled', async () => {
    const status = deferred<DocumentStatus>()
    api.getStatus.mockReturnValue(status.promise)
    const { client, key, hook } = mountPolling(documentRow('doc-a'))
    act(() => hook.result.current.pollDocumentStatus('doc-a'))
    act(() => hook.result.current.cancelDocumentPolling('doc-a'))
    expect(api.getStatus.mock.calls[0]?.[1]?.signal?.aborted).toBe(true)

    await act(async () => {
      status.resolve(statusRow('doc-a', 80))
      await status.promise
    })

    expect(client.getQueryData<DocumentList>(key)?.items[0]?.processing_progress).toBe(0)
  })

  it('keeps polling when document cancellation fails', async () => {
    const status = deferred<DocumentStatus>()
    api.getStatus.mockReturnValue(status.promise)
    api.cancel.mockRejectedValueOnce(new Error('取消失败'))
    api.list.mockResolvedValue({ items: [documentRow('doc-a')], total: 1 })
    const hook = mount(() => useDocumentControls({}))
    await waitForAssertion(() => expect(hook.result.current.documents).toHaveLength(1))

    act(() => hook.result.current.pollDocumentStatus('doc-a'))
    await act(async () => {
      await expect(hook.result.current.cancelDocument('doc-a')).rejects.toThrow('取消失败')
    })

    expect(api.getStatus.mock.calls[0]?.[1]?.signal?.aborted).toBe(false)
    await act(async () => status.resolve(statusRow('doc-a', 35)))
    expect(hook.result.current.documents[0].processing_progress).toBe(35)
  })

  it('keeps the newer polling result when the previous request completes last', async () => {
    const oldStatus = deferred<DocumentStatus>()
    api.getStatus.mockReturnValueOnce(oldStatus.promise).mockResolvedValueOnce(statusRow('doc-a', 80))
    const { client, key, hook } = mountPolling(documentRow('doc-a'))
    act(() => hook.result.current.pollDocumentStatus('doc-a'))
    await act(async () => hook.result.current.pollDocumentStatus('doc-a'))
    expect(client.getQueryData<DocumentList>(key)?.items[0]?.processing_progress).toBe(80)

    await act(async () => {
      oldStatus.resolve(statusRow('doc-a', 20))
      await oldStatus.promise
    })

    expect(client.getQueryData<DocumentList>(key)?.items[0]?.processing_progress).toBe(80)
  })

  it('discards an old full-document response after polling restarts', async () => {
    const fullDocument = deferred<Document>()
    api.getStatus.mockResolvedValueOnce(statusRow('doc-a', 100, 'completed'))
    api.get.mockReturnValue(fullDocument.promise)
    const { client, key, hook } = mountPolling(documentRow('doc-a'))
    await act(async () => hook.result.current.pollDocumentStatus('doc-a'))
    await act(async () => {
      api.getStatus.mockResolvedValue(statusRow('doc-a', 20))
      hook.result.current.pollDocumentStatus('doc-a')
    })
    expect(api.get.mock.calls[0]?.[2]?.signal?.aborted).toBe(true)

    await act(async () => {
      fullDocument.resolve(documentRow('doc-a', { status: 'completed', processing_progress: 100 }))
      await fullDocument.promise
    })

    expect(client.getQueryData<DocumentList>(key)?.items[0]?.status).toBe('processing')
    expect(client.getQueryData<DocumentList>(key)?.items[0]?.processing_progress).toBe(20)
  })

  it('publishes the current terminal document detail', async () => {
    const completed = documentRow('doc-a', {
      status: 'completed',
      processing_progress: 100,
      filename: 'parsed-document.txt',
      chunk_count: 4,
    })
    api.getStatus.mockResolvedValue(statusRow('doc-a', 100, 'completed'))
    api.get.mockResolvedValue(completed)
    const { client, key, hook } = mountPolling(documentRow('doc-a'))

    await act(async () => hook.result.current.pollDocumentStatus('doc-a'))

    expect(client.getQueryData<DocumentList>(key)?.items).toEqual([completed])
  })

  it('retains the current list total when deleting from a previous dataset', async () => {
    const deletion = deferred<void>()
    const docA = documentRow('doc-a', { dataset_id: 'dataset-a' })
    const docB = documentRow('doc-b', { dataset_id: 'dataset-b' })
    api.list.mockImplementation(async (params: DocumentListParams) =>
      params.dataset_id === 'dataset-a' ? { items: [docA], total: 1 } : { items: [docB], total: 3 },
    )
    api.delete.mockReturnValue(deletion.promise)
    const client = createClient()
    let params: DocumentListParams = { dataset_id: 'dataset-a' }
    const hook = mount(() => useDocumentControls(params), client)
    await waitForAssertion(() => expect(hook.result.current.documents).toEqual([docA]))
    let completion!: Promise<void>
    act(() => {
      completion = hook.result.current.deleteDocument('doc-a')
    })
    params = { dataset_id: 'dataset-b' }
    hook.rerender()
    await waitForAssertion(() => expect(hook.result.current.documents).toEqual([docB]))

    await act(async () => {
      deletion.resolve()
      await completion
    })

    expect(client.getQueryData<DocumentList>(queryKeys.documents.list(params))?.total).toBe(3)
    expect(client.getQueryData<DocumentList>(queryKeys.documents.list({ dataset_id: 'dataset-a' }))).toEqual({
      items: [],
      total: 0,
    })
    expect(hook.result.current.total).toBe(3)
    expect(hook.result.current.documents).toEqual([docB])
  })

  it('does not decrement a server-refreshed total twice when deletion completes', async () => {
    const deletion = deferred<void>()
    const removed = documentRow('removed')
    const remaining = documentRow('remaining')
    const params: DocumentListParams = { dataset_id: 'dataset-a' }
    api.list.mockResolvedValue({ items: [removed, remaining], total: 2 })
    api.delete.mockReturnValueOnce(deletion.promise).mockResolvedValue(undefined)
    const client = createClient()
    const hook = mount(() => useDocumentControls(params), client)
    await waitForAssertion(() => expect(hook.result.current.documents).toEqual([removed, remaining]))
    let completion!: Promise<void>
    act(() => {
      completion = hook.result.current.deleteDocument(removed.id)
    })
    await act(async () => {
      const duplicate = await hook.result.current.deleteDocument(removed.id).catch((error) => error)
      expect(isCancelledError(duplicate)).toBe(true)
    })
    expect(api.delete).toHaveBeenCalledOnce()
    act(() => client.setQueryData(queryKeys.documents.list(params), { items: [remaining], total: 1 }))

    await act(async () => {
      deletion.resolve()
      await completion
    })

    expect(client.getQueryData<DocumentList>(queryKeys.documents.list(params))).toEqual({
      items: [remaining],
      total: 1,
    })
  })

  it('does not publish a previous list request error over the current dataset', async () => {
    const earlier = deferred<DocumentList>()
    const docA = documentRow('doc-a', { dataset_id: 'dataset-a' })
    const docB = documentRow('doc-b', { dataset_id: 'dataset-b' })
    api.list.mockResolvedValueOnce({ items: [docA], total: 1 }).mockReturnValueOnce(earlier.promise)
    const client = createClient()
    let params: DocumentListParams = { dataset_id: 'dataset-a' }
    const hook = mount(() => useDocumentControls(params), client)
    await waitForAssertion(() => expect(hook.result.current.documents).toEqual([docA]))
    client.setQueryData(queryKeys.documents.list(params), { items: [docA], total: 1 }, { updatedAt: 1 })
    let completion!: Promise<void>
    act(() => {
      completion = hook.result.current.loadDocuments()
    })
    api.list.mockResolvedValue({ items: [docB], total: 1 })
    params = { dataset_id: 'dataset-b' }
    hook.rerender()
    await waitForAssertion(() => expect(hook.result.current.documents).toEqual([docB]))

    await act(async () => {
      earlier.reject(new Error('previous dataset failed'))
      await completion
    })

    expect(hook.result.current.error).toBeNull()
    expect(hook.result.current.documents).toEqual([docB])
  })

  it('keeps previous list data during a dataset change while the cached query still exists', async () => {
    const next = deferred<DocumentList>()
    const docA = documentRow('doc-a', { dataset_id: 'dataset-a' })
    const docB = documentRow('doc-b', { dataset_id: 'dataset-b' })
    api.list.mockResolvedValueOnce({ items: [docA], total: 1 }).mockReturnValue(next.promise)
    let params: DocumentListParams = { dataset_id: 'dataset-a' }
    const hook = mount(() => useDocumentControls(params))
    await waitForAssertion(() => expect(hook.result.current.documents).toEqual([docA]))

    params = { dataset_id: 'dataset-b' }
    hook.rerender()

    expect(hook.result.current.documents).toEqual([docA])
    expect(hook.result.current.isFetching).toBe(true)
    await act(async () => {
      next.resolve({ items: [docB], total: 1 })
      await next.promise
    })
    await waitForAssertion(() => expect(hook.result.current.documents).toEqual([docB]))
  })

  it('clears retired list placeholders and existing action errors before replacement data arrives', async () => {
    const replacement = deferred<DocumentList>()
    const docA = documentRow('doc-a')
    const docB = documentRow('doc-b')
    api.list.mockResolvedValueOnce({ items: [docA], total: 1 })
    api.delete.mockRejectedValue(new Error('previous action failed'))
    const client = createClient()
    const params: DocumentListParams = {}
    const hook = mount(() => useDocumentControls(params), client)
    await waitForAssertion(() => expect(hook.result.current.documents).toEqual([docA]))
    await act(async () => {
      await hook.result.current.deleteDocument('doc-a').catch(() => undefined)
    })
    await waitForAssertion(() => expect(hook.result.current.error).toBe('previous action failed'))
    api.list.mockReturnValue(replacement.promise)

    act(() => client.clear())
    hook.rerender()

    expect(hook.result.current.documents).toEqual([])
    expect(hook.result.current.error).toBeNull()
    expect(hook.result.current.isListLoading).toBe(true)
    await act(async () => {
      replacement.resolve({ items: [docB], total: 1 })
      await replacement.promise
    })
    await waitForAssertion(() => expect(hook.result.current.documents).toEqual([docB]))
  })

  it('hides retired documents when queries are cleared without a manual rerender', async () => {
    const replacement = deferred<DocumentList>()
    const docA = documentRow('doc-a')
    const docB = documentRow('doc-b')
    api.list.mockResolvedValueOnce({ items: [docA], total: 1 })
    const client = createClient()
    const params: DocumentListParams = {}
    const hook = mount(() => useDocumentControls(params), client)
    await waitForAssertion(() => {
      expect(hook.result.current.documents).toEqual([docA])
      expect(hook.result.current.isFetching).toBe(false)
    })
    api.list.mockReturnValue(replacement.promise)

    act(() => client.clear())

    await waitForAssertion(() => {
      expect(hook.result.current.documents).toEqual([])
      expect(hook.result.current.isListLoading).toBe(true)
    })
    await act(async () => {
      replacement.resolve({ items: [docB], total: 1 })
      await replacement.promise
    })
    await waitForAssertion(() => expect(hook.result.current.documents).toEqual([docB]))
  })

  it('keeps replacement query data when an earlier upload completes after queries are cleared', async () => {
    const upload = deferred<Document>()
    const oldDocument = documentRow('old-document')
    const replacement = documentRow('replacement-document')
    api.list.mockResolvedValue({ items: [], total: 0 })
    api.uploadFromUrl.mockReturnValue(upload.promise)
    const client = createClient()
    const params: DocumentListParams = {}
    const hook = mount(() => useDocumentControls(params), client)
    await waitForAssertion(() => expect(hook.result.current.isListLoading).toBe(false))
    let completion!: Promise<string>
    act(() => {
      completion = hook.result.current.uploadDocumentFromUrl({ url: 'https://example.com/old.txt' }).then(
        () => 'completed',
        (error: unknown) => {
          if (!isCancelledError(error)) throw error
          return 'cancelled'
        },
      )
    })
    await waitForAssertion(() => expect(api.uploadFromUrl).toHaveBeenCalledOnce())
    api.list.mockResolvedValue({ items: [replacement], total: 1 })
    act(() => client.clear())
    hook.rerender()
    await waitForAssertion(() => expect(hook.result.current.documents).toEqual([replacement]))

    await act(async () => {
      upload.resolve(oldDocument)
      expect(await completion).toBe('cancelled')
    })

    expect(hook.result.current.documents).toEqual([replacement])
    expect(client.getQueryData<DocumentList>(queryKeys.documents.list(params))).toEqual({
      items: [replacement],
      total: 1,
    })
  })

  it('stops the remaining upload batch after the originating queries are cleared', async () => {
    const firstBatch = deferred<DocumentBatchUploadResponse>()
    const files = Array.from({ length: 51 }, (_, index) => new File(['test'], `file-${index}.txt`))
    const replacement = documentRow('replacement-document')
    api.list.mockResolvedValue({ items: [], total: 0 })
    api.uploadBatch.mockReturnValueOnce(firstBatch.promise).mockResolvedValue({
      total: 1,
      successful_count: 1,
      failed_count: 0,
      successful: [{ document_id: 'doc-50', filename: 'file-50.txt', status: 'pending' }],
      failed: [],
    })
    const client = createClient()
    const params: DocumentListParams = {}
    const hook = mount(() => useDocumentControls(params), client)
    await waitForAssertion(() => expect(hook.result.current.isListLoading).toBe(false))
    let completion!: Promise<string>
    act(() => {
      completion = hook.result.current.uploadDocuments(files, { maxRetries: 0 }).then(
        () => 'completed',
        (error: unknown) => {
          if (!isCancelledError(error)) throw error
          return 'cancelled'
        },
      )
    })
    await waitForAssertion(() => expect(api.uploadBatch).toHaveBeenCalledOnce())
    api.list.mockResolvedValue({ items: [replacement], total: 1 })
    act(() => client.clear())
    hook.rerender()
    await waitForAssertion(() => expect(hook.result.current.documents).toEqual([replacement]))

    let outcome: string | undefined
    await act(async () => {
      firstBatch.resolve({
        total: 50,
        successful_count: 50,
        failed_count: 0,
        successful: files.slice(0, 50).map((file, index) => ({
          document_id: `doc-${index}`,
          filename: file.name,
          status: 'pending',
        })),
        failed: [],
      })
      outcome = await completion
    })

    expect(api.uploadBatch).toHaveBeenCalledOnce()
    expect(outcome).toBe('cancelled')
    expect(client.getQueryData<DocumentList>(queryKeys.documents.list(params))).toEqual({
      items: [replacement],
      total: 1,
    })
  })

  it('refreshes the original upload dataset without selecting it again', async () => {
    const upload = deferred<DocumentBatchUploadResponse>()
    const newDocument = documentRow('new-document', { dataset_id: 'dataset-a' })
    const docB = documentRow('doc-b', { dataset_id: 'dataset-b' })
    let serverDocumentsA: Document[] = []
    api.list.mockImplementation(async (params: DocumentListParams) => {
      const items = params.dataset_id === 'dataset-a' ? serverDocumentsA : [docB]
      return { items, total: items.length }
    })
    api.uploadBatch.mockReturnValue(upload.promise)
    const client = createClient()
    let params: DocumentListParams = { dataset_id: 'dataset-a' }
    const hook = mount(() => useDocumentControls(params), client)
    await waitForAssertion(() => expect(hook.result.current.isListLoading).toBe(false))
    let completion!: Promise<DocumentBatchUploadResponse>
    act(() => {
      completion = hook.result.current.uploadDocuments([new File(['test'], 'new.txt')])
    })
    await waitForAssertion(() => expect(api.uploadBatch).toHaveBeenCalledOnce())
    params = { dataset_id: 'dataset-b' }
    hook.rerender()
    await waitForAssertion(() => expect(hook.result.current.documents).toEqual([docB]))
    client.setQueryData(
      queryKeys.documents.list({ dataset_id: 'dataset-a' }),
      { items: [], total: 0 },
      { updatedAt: 1 },
    )
    serverDocumentsA = [newDocument]

    await act(async () => {
      upload.resolve({
        total: 1,
        successful_count: 1,
        failed_count: 0,
        successful: [{ document_id: newDocument.id, filename: 'new.txt', status: 'pending' }],
        failed: [],
      })
      await completion
    })

    await waitForAssertion(() =>
      expect(client.getQueryData<DocumentList>(queryKeys.documents.list({ dataset_id: 'dataset-a' }))?.items).toEqual([
        newDocument,
      ]),
    )
    expect(hook.result.current.documents).toEqual([docB])
    expect(hook.result.current.lastListParamsRef.current.dataset_id).toBe('dataset-b')
  })

  it('uses the dataset selected when the upload was requested', async () => {
    api.list.mockResolvedValue({ items: [], total: 0 })
    api.uploadFromUrl.mockImplementation(async (options: { dataset_id?: string }) =>
      documentRow('new-document', { dataset_id: options.dataset_id }),
    )
    let params: DocumentListParams = { dataset_id: 'dataset-a' }
    const hook = mount(() => useDocumentControls(params))
    await waitForAssertion(() => expect(hook.result.current.isListLoading).toBe(false))
    let completion!: Promise<Document>
    act(() => {
      completion = hook.result.current.uploadDocumentFromUrl({
        url: 'https://example.com/new.txt',
        dataset_id: 'dataset-a',
      })
    })
    params = { dataset_id: 'dataset-b' }
    hook.rerender()

    await act(async () => {
      expect((await completion).dataset_id).toBe('dataset-a')
    })

    expect(api.uploadFromUrl.mock.calls[0]?.[0]).toMatchObject({ dataset_id: 'dataset-a' })
    expect(hook.result.current.lastListParamsRef.current.dataset_id).toBe('dataset-b')
  })

  it.each([
    { maxRetries: 1, maxConcurrent: 99, expectedConcurrent: 10 },
    { maxRetries: Number.NaN, maxConcurrent: 5.5, expectedConcurrent: 5 },
  ])(
    'retries matched failures with $expectedConcurrent concurrent uploads',
    async ({ maxRetries, maxConcurrent, expectedConcurrent }) => {
      const first = new File(['first'], 'first.txt')
      const second = new File(['second'], 'second.txt')
      const duplicateFirst = new File(['third'], 'duplicate.txt')
      const duplicateSecond = new File(['fourth'], 'duplicate.txt')
      Object.defineProperty(duplicateFirst, 'webkitRelativePath', { value: ' manual /duplicate.txt' })
      Object.defineProperty(duplicateSecond, 'webkitRelativePath', { value: 'manual/duplicate.txt' })
      const ambiguousFailure = {
        filename: duplicateSecond.name,
        source_path: 'manual/duplicate.txt',
        error: 'cannot retry by source path',
      }
      let serverDocuments: Document[] = []
      api.list.mockImplementation(async () => ({ items: serverDocuments, total: serverDocuments.length }))
      api.uploadBatch
        .mockResolvedValueOnce({
          total: 4,
          successful_count: 2,
          failed_count: 2,
          successful: [
            { document_id: 'doc-first', filename: first.name, status: 'pending' },
            { document_id: 'doc-duplicate', filename: duplicateFirst.name, status: 'pending' },
          ],
          failed: [{ filename: second.name, error: 'temporary failure' }, ambiguousFailure],
        })
        .mockImplementationOnce(async () => {
          serverDocuments = [documentRow('doc-first'), documentRow('doc-second'), documentRow('doc-duplicate')]
          return {
            total: 1,
            successful_count: 1,
            failed_count: 0,
            successful: [{ document_id: 'doc-second', filename: second.name, status: 'pending' }],
            failed: [],
          }
        })
      const client = createClient()
      const params: DocumentListParams = { dataset_id: 'dataset-a' }
      const hook = mount(() => useDocumentControls(params), client)
      await waitForAssertion(() => expect(hook.result.current.isListLoading).toBe(false))
      client.setQueryData(queryKeys.documents.list(params), { items: [], total: 0 }, { updatedAt: 1 })

      await act(async () => {
        const result = await hook.result.current.uploadDocuments([first, second, duplicateFirst, duplicateSecond], {
          maxRetries,
          maxConcurrent,
        })
        expect(result).toMatchObject({ total: 4, successful_count: 3, failed_count: 1, failed: [ambiguousFailure] })
      })

      expect(api.uploadBatch.mock.calls.map(([files]) => files)).toEqual([
        [first, second, duplicateFirst, duplicateSecond],
        [second],
      ])
      expect(api.uploadBatch.mock.calls[0]?.[1]).toEqual({
        parser_backend: 'auto',
        chunk_strategy: 'langchain_recursive',
        dataset_id: 'dataset-a',
        pipeline: undefined,
        max_concurrent: expectedConcurrent,
      })
      expect(client.getQueryData<DocumentList>(queryKeys.documents.list(params))?.items.map((doc) => doc.id)).toEqual([
        'doc-first',
        'doc-second',
        'doc-duplicate',
      ])
    },
  )

  it('keeps confirmed file results when the next batch request fails', async () => {
    const files = Array.from({ length: 51 }, (_, index) => new File(['test'], `file-${index}.txt`))
    const failed = { filename: files[49].name, error: 'file rejected' }
    api.list.mockResolvedValue({ items: [], total: 0 })
    api.uploadBatch
      .mockResolvedValueOnce({
        total: 50,
        successful_count: 49,
        failed_count: 1,
        successful: files.slice(0, 49).map((file, index) => ({
          document_id: `doc-${index}`,
          filename: file.name,
          status: 'pending',
        })),
        failed: [failed],
      })
      .mockRejectedValueOnce(new Error('connection lost'))
    const hook = mount(() => useDocumentControls({ dataset_id: 'dataset-a' }))
    await waitForAssertion(() => expect(hook.result.current.isListLoading).toBe(false))

    await act(async () => {
      const result = await hook.result.current.uploadDocuments(files)
      expect(result).toMatchObject({
        total: 51,
        successful_count: 49,
        failed_count: 1,
        failed: [failed],
        interruption: 'connection lost',
      })
    })

    expect(api.uploadBatch).toHaveBeenCalledTimes(2)
  })

  it('returns an empty batch result without starting an upload', async () => {
    api.list.mockResolvedValue({ items: [], total: 0 })
    const client = createClient()
    const hook = mount(() => useDocumentControls({ dataset_id: 'dataset-a' }), client)
    await waitForAssertion(() => expect(hook.result.current.isListLoading).toBe(false))

    await act(async () => {
      expect(await hook.result.current.uploadDocuments([])).toEqual({
        total: 0,
        successful_count: 0,
        failed_count: 0,
        successful: [],
        failed: [],
      })
    })

    expect(api.uploadBatch).not.toHaveBeenCalled()
    expect(client.getMutationCache().getAll()).toHaveLength(0)
  })

  it.each(['cancel', 'delete', 'uploadFromUrl'] as const)(
    'retains the visible failure from the current %s operation',
    async (action) => {
      const failure = new Error('current request failed')
      api.list.mockResolvedValue({ items: [documentRow('doc-a')], total: 1 })
      api[action].mockRejectedValue(failure)
      const params: DocumentListParams = { dataset_id: 'dataset-a' }
      const hook = mount(() => useDocumentControls(params))
      await waitForAssertion(() => expect(hook.result.current.isListLoading).toBe(false))

      let received: unknown
      await act(async () => {
        try {
          if (action === 'cancel') await hook.result.current.cancelDocument('doc-a')
          else if (action === 'delete') await hook.result.current.deleteDocument('doc-a')
          else await hook.result.current.uploadDocumentFromUrl({ url: 'https://example.com/new.txt' })
        } catch (error) {
          received = error
        }
      })

      expect(received).toBe(failure)
      await waitForAssertion(() => expect(hook.result.current.error).toBe('current request failed'))
    },
  )
})
