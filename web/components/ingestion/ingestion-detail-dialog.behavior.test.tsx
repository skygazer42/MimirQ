// @vitest-environment happy-dom

import React, { act } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Document, DocumentVersionDiff, DocumentVersionList } from '@/types'
import { setAuthSession } from '@/lib/auth-storage'

const api = vi.hoisted(() => ({
  get: vi.fn(),
  listVersions: vi.fn(),
  diffVersions: vi.fn(),
  cancel: vi.fn(),
  retry: vi.fn(),
}))
const notices = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }))
vi.mock('@/lib/api', () => ({ documentApi: api }))
vi.mock('@/lib/api/documents', () => ({ documentApi: api }))

vi.mock('sonner', () => ({ toast: notices }))
vi.mock('next-intl', () => ({ useTranslations: () => (key: string) => key }))
vi.mock('@/store/document-view', () => ({ useDocumentView: () => ({ openDocument: vi.fn() }) }))
vi.mock('@/components/ui/sheet', () => ({
  Sheet: ({ open, children }: { open: boolean; children: React.ReactNode }) => (open ? <div>{children}</div> : null),
  SheetContent: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  SheetHeader: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  SheetTitle: ({ children }: { children: React.ReactNode }) => <h2>{children}</h2>,
  SheetDescription: ({ children }: { children: React.ReactNode }) => <p>{children}</p>,
}))
vi.mock('@/components/ui/select', () => ({
  Select: ({
    value,
    onValueChange,
    children,
  }: {
    value: string
    onValueChange: (value: string) => void
    children: React.ReactNode
  }) => (
    <select value={value} onChange={(event) => onValueChange(event.target.value)}>
      {children}
    </select>
  ),
  SelectTrigger: () => null,
  SelectValue: () => null,
  SelectContent: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  SelectItem: ({ value, children }: { value: string; children: React.ReactNode }) => (
    <option value={value}>{children}</option>
  ),
}))

import { IngestionDetailDialog } from './ingestion-detail-dialog'

function documentDto(id: string): Document {
  return {
    id,
    filename: `${id}.pdf`,
    file_type: 'pdf',
    file_size: 3,
    status: 'completed',
    processing_progress: 100,
    processing_attempts: 1,
    chunk_count: 2,
    total_characters: 30,
    publication_status: 'published',
    created_at: '2026-11-05T00:00:00Z',
    updated_at: '2026-11-05T00:00:00Z',
    dataset_id: 'ds-1',
  }
}
function versionsDto(id: string): DocumentVersionList {
  return {
    document_id: id,
    active_pipeline_hash: `${id}-active`,
    pipeline_hash: `${id}-current`,
    items: ['active', 'current'].map((name) => ({
      pipeline_hash: `${id}-${name}`,
      doc_pipeline_key: `${id}:${name}`,
      chunk_count: 2,
      active: name === 'active',
    })),
  }
}
function diffDto(id: string): DocumentVersionDiff {
  return {
    document_id: id,
    from_pipeline_hash: `${id}-active`,
    to_pipeline_hash: `${id}-current`,
    from_chunk_count: 2,
    to_chunk_count: 3,
    unchanged_chunks: 2,
    added_chunks: 1,
    removed_chunks: 0,
    changed_transforms: [`${id}-transform`],
  }
}
function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (error: Error) => void
  const promise = new Promise<T>((yes, no) => {
    resolve = yes
    reject = no
  })
  return { promise, resolve, reject }
}
const cleanups: Array<() => void> = []
function renderDialog() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const host = document.createElement('div')
  document.body.append(host)
  const root = createRoot(host)
  const onOpenChange = vi.fn()
  async function visit(id: string, open = true) {
    await act(async () =>
      root.render(
        <QueryClientProvider client={client}>
          <IngestionDetailDialog open={open} onOpenChange={onOpenChange} documentId={id} />
        </QueryClientProvider>,
      ),
    )
    if (open)
      await act(async () => {
        await vi.waitFor(() => expect(host.textContent).toContain(`${id}.pdf`))
      })
  }
  cleanups.push(() => {
    act(() => root.unmount())
    client.clear()
    host.remove()
  })
  return { host, client, visit }
}
function button(host: HTMLElement, label: string) {
  const value = Array.from(host.querySelectorAll('button')).find((item) => item.textContent === label)
  if (!value) throw new Error(`button missing: ${label}`)
  return value
}
async function compare(host: HTMLElement) {
  await act(async () => button(host, 'actions.compare').click())
}
beforeEach(() => {
  ;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  api.get.mockImplementation(async (id: string) => documentDto(id))
  api.listVersions.mockImplementation(async (id: string) => versionsDto(id))
  api.diffVersions.mockImplementation(async ({ document_id }: { document_id: string }) => diffDto(document_id))
  api.cancel.mockResolvedValue(undefined)
  api.retry.mockResolvedValue(undefined)
})
afterEach(() => {
  cleanups.splice(0).forEach((cleanup) => cleanup())
  vi.resetAllMocks()
})

describe('ingestion detail visit ownership', () => {
  it('does not publish an action toast after the session changes during its refresh', async () => {
    const refresh = deferred<Document>()
    api.get.mockResolvedValueOnce(documentDto('A')).mockReturnValueOnce(refresh.promise)
    const { host, visit } = renderDialog()
    await visit('A')
    await act(async () => button(host, 'actions.forceRetry').click())
    expect(api.get).toHaveBeenCalledTimes(2)
    notices.success.mockClear()
    setAuthSession({
      token: { access_token: 'replacement', token_type: 'bearer', expires_in: 3600 },
      user: {
        id: 'user-a',
        email: 'a@example.org',
        username: 'A',
        is_active: true,
        created_at: '2026-11-05T00:00:00Z',
      },
    })
    await act(async () => refresh.resolve(documentDto('A')))
    expect(notices.success).not.toHaveBeenCalled()
    expect(button(host, 'actions.forceRetry').disabled).toBe(false)
  })

  it('uses the new document versions after closing and opening another document', async () => {
    const { host, visit } = renderDialog()
    await visit('A')
    await compare(host)
    await visit('A', false)
    await visit('B')
    expect(host.textContent).not.toContain('A-transform')
    await compare(host)
    expect(api.diffVersions).toHaveBeenLastCalledWith({
      document_id: 'B',
      from: 'B-active',
      to: 'B-current',
      sample_limit: 50,
    })
    expect(host.textContent).toContain('B-transform')
  })
  it.each(['success', 'error'] as const)('ignores an old pending diff %s after a new visit', async (outcome) => {
    const pending = deferred<DocumentVersionDiff>()
    api.diffVersions.mockReturnValueOnce(pending.promise)
    const { host, visit } = renderDialog()
    await visit('A')
    await compare(host)
    await visit('A', false)
    await visit('B')
    await act(async () => {
      if (outcome === 'success') pending.resolve(diffDto('A'))
      else pending.reject(new Error('old failure'))
    })
    expect(host.textContent).not.toContain('A-transform')
    expect(host.textContent).not.toContain('old failure')
    expect(button(host, 'actions.compare').disabled).toBe(false)
    await compare(host)
    expect(api.diffVersions).toHaveBeenLastCalledWith({
      document_id: 'B',
      from: 'B-active',
      to: 'B-current',
      sample_limit: 50,
    })
  })
  it('submits one comparison for two synchronous clicks', async () => {
    const pending = deferred<DocumentVersionDiff>()
    api.diffVersions.mockReturnValue(pending.promise)
    const { host, visit } = renderDialog()
    await visit('A')
    await act(async () => {
      button(host, 'actions.compare').click()
      button(host, 'actions.compare').click()
    })
    expect(api.diffVersions).toHaveBeenCalledTimes(1)
    await act(async () => pending.resolve(diffDto('A')))
  })
  it('refreshes an accepted retry for the original document after leaving it', async () => {
    const pending = deferred<void>()
    api.retry.mockReturnValueOnce(pending.promise)
    const { host, client, visit } = renderDialog()
    await visit('A')
    await act(async () => button(host, 'actions.forceRetry').click())
    await visit('B')
    await act(async () => {
      pending.resolve()
      await vi.waitFor(() => expect(api.get.mock.calls.filter(([id]) => id === 'A')).toHaveLength(2))
    })
    expect(api.get.mock.calls.filter(([id]) => id === 'B')).toHaveLength(1)
    expect(client.getQueryData(['ingestion-doc-detail', 'A'])).toEqual(documentDto('A'))
    expect(notices.success).not.toHaveBeenCalled()
  })
  it('retains the current visit success and error paths', async () => {
    const { host, visit } = renderDialog()
    await visit('A')
    await compare(host)
    expect(host.textContent).toContain('A-transform')
    api.diffVersions.mockRejectedValueOnce(new Error('current failure'))
    await compare(host)
    expect(host.textContent).toContain('current failure')
    expect(host.textContent).not.toContain('A-transform')
  })
})
