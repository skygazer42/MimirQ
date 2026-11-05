// @vitest-environment happy-dom
import React, { act } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Document, DocumentChunk, DocumentChunkList } from '@/types'

const ports = vi.hoisted(() => ({
  documents: {
    get: vi.fn(),
    getAccess: vi.fn(),
    getLifecycleMetadata: vi.fn(),
    listVersions: vi.fn(),
    getTimeline: vi.fn(),
    listChunks: vi.fn(),
  },
  translate: (key: string) => key,
  log: vi.fn(),
}))
vi.hoisted(() => vi.stubGlobal('BroadcastChannel', undefined))
vi.mock('@/lib/api', () => ({ documentApi: ports.documents, kgApi: {}, lineageApi: {} }))
vi.mock('@/lib/api/documents', () => ({ documentApi: ports.documents }))
vi.mock('@/lib/api/graph', () => ({ kgApi: {} }))
vi.mock('@/lib/api/lineage', () => ({ lineageApi: {} }))
vi.mock('@/lib/client-logging', () => ({ reportClientError: ports.log, reportClientWarning: vi.fn() }))
vi.mock('next-intl', () => ({ useTranslations: () => ports.translate }))
// Retain the production list and row behavior; only native layout observation is adapted.
vi.mock('@tanstack/react-virtual', () => ({
  useVirtualizer: ({ count }: { count: number }) => ({
    getTotalSize: () => count * 220,
    getVirtualItems: () =>
      Array.from({ length: count }, (_, index) => ({ key: index, index, start: index * 220, end: (index + 1) * 220 })),
    measureElement: () => {},
  }),
}))

import { DocumentDetailDialog } from '../document-detail-dialog'
import { clearAuthSession, setAuthSession } from '@/lib/auth-storage'

const cleanups: Array<() => void> = []
function row(id: string): Document {
  return {
    id,
    filename: `${id}.txt`,
    file_type: 'txt',
    file_size: 10,
    status: 'completed',
    processing_progress: 100,
    processing_attempts: 0,
    chunk_count: 1,
    total_characters: 5,
    publication_status: 'draft',
    created_at: '2026-11-05T00:00:00Z',
    updated_at: '2026-11-05T00:00:00Z',
  }
}
function chunk(content: string): DocumentChunk {
  return { id: content, chunk_index: 0, content, metadata: {} }
}
function page(content: string, total = 1): DocumentChunkList {
  return { items: [chunk(content)], total }
}
function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (error: unknown) => void
  const promise = new Promise<T>((yes, no) => {
    resolve = yes
    reject = no
  })
  return { promise, resolve, reject }
}
function session() {
  setAuthSession({
    user: {
      id: 'review-user',
      username: 'review-user',
      email: 'review@example.test',
      is_active: true,
      created_at: '',
      last_login_at: null,
    },
    token: { access_token: 'review-token', token_type: 'bearer', expires_in: 3600 },
  })
}
async function settle(ms = 0) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms)
  })
  await act(async () => {
    await vi.advanceTimersByTimeAsync(1)
  })
}
function mount(id = 'document-a') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  const holder = document.createElement('div')
  document.body.appendChild(holder)
  const root = createRoot(holder)
  let mounted = true
  const render = (next: string) =>
    act(() =>
      root.render(
        <QueryClientProvider client={client}>
          <DocumentDetailDialog document={row(next)} />
        </QueryClientProvider>,
      ),
    )
  const unmount = () => {
    if (mounted) {
      mounted = false
      act(() => root.unmount())
      client.clear()
      holder.remove()
    }
  }
  cleanups.push(unmount)
  render(id)
  act(() => holder.querySelector<HTMLButtonElement>('button')!.click())
  return { holder, render, unmount, client }
}
function click(text: string) {
  const button = Array.from(document.body.querySelectorAll<HTMLButtonElement>('button')).find(
    (element) => element.textContent?.trim() === text,
  )
  expect(button, text).toBeDefined()
  act(() => button!.click())
}
function search(value: string) {
  const input = document.body.querySelector<HTMLInputElement>('input[placeholder="search.placeholder"]')!
  expect(input).not.toBeNull()
  act(() => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(input, value)
    input.dispatchEvent(new Event('input', { bubbles: true }))
  })
}

beforeEach(() => {
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  vi.useFakeTimers()
  vi.clearAllMocks()
  localStorage.clear()
  sessionStorage.clear()
  clearAuthSession()
  session()
  ports.documents.get.mockReset().mockImplementation(async (id: string) => row(id))
  ports.documents.getAccess
    .mockReset()
    .mockResolvedValue({ mode: 'inherit', owner_id: null, partial_member_list: [], partial_group_list: [] })
  ports.documents.getLifecycleMetadata.mockReset().mockResolvedValue({ publication_status: 'draft' })
  ports.documents.listVersions
    .mockReset()
    .mockResolvedValue({ document_id: 'document-a', active_pipeline_hash: null, items: [] })
  ports.documents.getTimeline.mockReset().mockResolvedValue({ items: [], total: 0 })
  ports.documents.listChunks.mockReset().mockResolvedValue(page('current chunk'))
})
afterEach(() => {
  for (const cleanup of cleanups.splice(0)) cleanup()
  vi.useRealTimers()
})

describe('document detail chunk request ownership', () => {
  it('keeps a newer search result when an older reload succeeds later', async () => {
    const old = deferred<DocumentChunkList>()
    ports.documents.listChunks.mockReturnValueOnce(old.promise)
    mount()
    await settle()
    search(' current ')
    await settle(250)
    expect(ports.documents.listChunks).toHaveBeenLastCalledWith('document-a', {
      skip: 0,
      limit: 200,
      q: 'current',
      pipeline_hash: undefined,
    })
    expect(document.body.textContent).toContain('current chunk')
    await act(async () => old.resolve(page('retired chunk')))
    expect(document.body.textContent).toContain('current chunk')
    expect(document.body.textContent).not.toContain('retired chunk')
  })

  it('does not show an old search error or clear the current search busy state', async () => {
    const old = deferred<DocumentChunkList>()
    const current = deferred<DocumentChunkList>()
    ports.documents.listChunks.mockReturnValueOnce(old.promise).mockReturnValueOnce(current.promise)
    mount()
    await settle()
    search('current')
    await settle(250)
    await act(async () => old.reject(new Error('retired search failed')))
    expect(document.body.textContent).not.toContain('retired search failed')
    expect(document.body.textContent).toContain('loadingChunks')
    await act(async () => current.resolve(page('current chunk')))
    expect(document.body.textContent).toContain('current chunk')
  })

  it('does not append an old load-more page to a replacement search', async () => {
    const old = deferred<DocumentChunkList>()
    ports.documents.listChunks.mockResolvedValueOnce(page('first page', 3)).mockReturnValueOnce(old.promise)
    mount()
    await settle()
    click('chunks.loadMore')
    expect(ports.documents.listChunks).toHaveBeenLastCalledWith('document-a', {
      skip: 1,
      limit: 200,
      q: undefined,
      pipeline_hash: undefined,
    })
    search('current')
    await settle(250)
    await act(async () => old.resolve(page('retired next page', 3)))
    expect(document.body.textContent).toContain('current chunk')
    expect(document.body.textContent).not.toContain('retired next page')
  })

  it('retires a request when the same dialog instance receives another document', async () => {
    const old = deferred<DocumentChunkList>()
    ports.documents.listChunks.mockReturnValueOnce(old.promise)
    const view = mount()
    await settle()
    view.render('document-b')
    await settle()
    await act(async () => old.resolve(page('retired document-a chunk')))
    expect(document.body.textContent).not.toContain('retired document-a chunk')
    expect(document.body.textContent).toContain('current chunk')
  })

  it('does not revive chunks from the previous open visit after reopening', async () => {
    const old = deferred<DocumentChunkList>()
    ports.documents.listChunks.mockReturnValueOnce(old.promise)
    const view = mount()
    await settle()
    click('close')
    act(() => view.holder.querySelector<HTMLButtonElement>('button')!.click())
    await settle()
    await act(async () => old.resolve(page('retired closed visit')))
    expect(document.body.textContent).not.toContain('retired closed visit')
    expect(document.body.textContent).toContain('current chunk')
  })

  it('ignores the completion owned by a previous explicit login session', async () => {
    const old = deferred<DocumentChunkList>()
    ports.documents.listChunks.mockReturnValueOnce(old.promise)
    mount()
    await settle()
    act(() => session())
    await act(async () => old.resolve(page('retired login chunk')))
    expect(document.body.textContent).not.toContain('retired login chunk')
  })

  it('keeps current failures visible and allows retry', async () => {
    ports.documents.listChunks.mockRejectedValueOnce(new Error('current load failed'))
    mount()
    await settle()
    expect(document.body.textContent).toContain('current load failed')
    click('retry')
    await settle()
    expect(document.body.textContent).toContain('current chunk')
    expect(document.body.textContent).not.toContain('current load failed')
  })
})
