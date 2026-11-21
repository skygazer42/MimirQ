// @vitest-environment happy-dom
import React, { act } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Document } from '@/types/documents'
import type { DocumentChunk, DocumentChunkList } from '@/types/processing'

const ports = vi.hoisted(() => ({
  documents: {
    get: vi.fn(),
    getAccess: vi.fn(),
    getLifecycleMetadata: vi.fn(),
    listVersions: vi.fn(),
    getTimeline: vi.fn(),
    listChunks: vi.fn(),
    patchUserMetadata: vi.fn(),
    patchLifecycleMetadata: vi.fn(),
  },
  translate: (key: string) => key,
  log: vi.fn(),
  success: vi.fn(),
}))
vi.hoisted(() => vi.stubGlobal('BroadcastChannel', undefined))
vi.mock('@/lib/api', () => ({ documentApi: ports.documents, kgApi: {}, lineageApi: {} }))
vi.mock('@/lib/api/documents', () => ({ documentApi: ports.documents }))
vi.mock('@/lib/api/graph', () => ({ kgApi: {} }))
vi.mock('@/lib/api/lineage', () => ({ lineageApi: {} }))
vi.mock('@/lib/client-logging', () => ({ reportClientError: ports.log, reportClientWarning: vi.fn() }))
vi.mock('next-intl', () => ({ useTranslations: () => ports.translate }))
vi.mock('sonner', () => ({ toast: { success: ports.success, error: vi.fn() } }))
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
import { queryKeys } from '@/lib/query-keys'
import processingFixtures from './document-processing.fixture.json'

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
function mount(id = 'document-a', documentForId: (id: string) => Document = row) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  const holder = document.createElement('div')
  document.body.appendChild(holder)
  const root = createRoot(holder)
  let mounted = true
  const render = (next: string) =>
    act(() =>
      root.render(
        <QueryClientProvider client={client}>
          <DocumentDetailDialog document={documentForId(next)} />
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

function editTags() {
  click('actions.edit')
  const label = Array.from(document.body.querySelectorAll('label')).find(
    (element) => element.textContent === 'tags.title',
  )!
  const input = document.getElementById(label.htmlFor) as HTMLInputElement
  expect(input).not.toBeNull()
  return { input, form: input.closest('form')! }
}

function appendTag(input: HTMLInputElement, value: string) {
  act(() => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(input, value)
    input.dispatchEvent(new Event('input', { bubbles: true }))
  })
  act(() => input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true })))
}

function submitTags(form: HTMLFormElement) {
  act(() => form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })))
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
  ports.documents.patchUserMetadata.mockReset()
  ports.documents.patchLifecycleMetadata.mockReset()
})

describe('document detail tag saves', () => {
  it('keeps all stored tags and the edited draft after failure, then reads the confirmed result', async () => {
    const tags = Array.from({ length: 50 }, (_, index) => `#标签 ${index}`)
    const stored = { ...row('document-a'), metadata: { user: { tags } } }
    ports.documents.get.mockResolvedValue(stored)
    const save = deferred<Document>()
    ports.documents.patchUserMetadata.mockReturnValueOnce(save.promise)
    const view = mount()
    await settle()
    const { input, form } = editTags()
    expect(form.textContent).toContain('50 / 50')
    const remove = Array.from(form.querySelectorAll('span')).find((element) => element.textContent === tags[49])!
    act(() => remove.parentElement!.querySelector<HTMLButtonElement>('button')!.click())
    submitTags(form)
    expect(ports.documents.patchUserMetadata).toHaveBeenCalledExactlyOnceWith('document-a', {
      replace: false,
      patch: { tags: tags.slice(0, -1) },
    })
    expect(input.disabled).toBe(true)
    await act(async () => save.reject(new Error('tag write failed')))
    expect(document.body.textContent).toContain('tag write failed')
    expect(form.textContent).toContain('49 / 50')
    expect(input.disabled).toBe(false)
    expect(ports.success).not.toHaveBeenCalled()

    const saved = { ...stored, metadata: { user: { tags: tags.slice(0, -1) } } }
    ports.documents.patchUserMetadata.mockResolvedValueOnce(saved)
    ports.documents.get.mockResolvedValue(saved)
    submitTags(form)
    await settle()
    expect(document.body.contains(form)).toBe(false)
    expect(view.client.getQueryData(queryKeys.documents.detail('document-a'))).toEqual(saved)
    expect(ports.success).toHaveBeenCalledOnce()
    await act(async () => {
      await view.client.refetchQueries({ queryKey: queryKeys.documents.detail('document-a'), exact: true })
    })
    await settle()
    expect(editTags().form.textContent).toContain('49 / 50')
  })

  it('synchronously claims one write per document and uses the explicit deletion patch for no tags', async () => {
    ports.documents.get.mockResolvedValue({ ...row('document-a'), metadata: { user: { tags: ['one'] } } })
    ports.documents.patchUserMetadata.mockReturnValue(deferred<Document>().promise)
    mount()
    await settle()
    const { form } = editTags()
    act(() => form.querySelector<HTMLButtonElement>('button[aria-label="tagInput.removeLabel"]')!.click())
    act(() => {
      form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
      form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
    })
    expect(ports.documents.patchUserMetadata).toHaveBeenCalledExactlyOnceWith('document-a', {
      replace: false,
      patch: { tags: null },
    })
  })

  it('allows a different document to save without letting the earlier completion close its editor', async () => {
    const save = deferred<Document>()
    ports.documents.patchUserMetadata.mockReturnValueOnce(save.promise)
    const view = mount()
    await settle()
    const first = editTags()
    appendTag(first.input, 'first')
    submitTags(first.form)
    view.render('document-b')
    await settle()
    const second = editTags()
    appendTag(second.input, 'second')
    const otherSave = deferred<Document>()
    ports.documents.patchUserMetadata.mockReturnValueOnce(otherSave.promise)
    submitTags(second.form)
    expect(ports.documents.patchUserMetadata).toHaveBeenNthCalledWith(2, 'document-b', {
      replace: false,
      patch: { tags: ['second'] },
    })
    const saved = { ...row('document-a'), metadata: { user: { tags: ['first'] } } }
    await act(async () => save.resolve(saved))
    await settle()
    expect(document.body.contains(second.form)).toBe(true)
    expect(second.input.disabled).toBe(true)
    expect(second.form.textContent).toContain('second')
    expect(view.client.getQueryData(queryKeys.documents.detail('document-a'))).toEqual(saved)
    expect(ports.success).not.toHaveBeenCalled()
    await act(async () => otherSave.resolve({ ...row('document-b'), metadata: { user: { tags: ['second'] } } }))
    await settle()
    expect(document.body.contains(second.form)).toBe(false)
    expect(ports.success).toHaveBeenCalledOnce()
  })

  it('does not revive feedback or editing from a closed visit while preserving the confirmed cache result', async () => {
    const save = deferred<Document>()
    ports.documents.patchUserMetadata.mockReturnValueOnce(save.promise)
    const view = mount()
    await settle()
    const first = editTags()
    appendTag(first.input, 'first')
    submitTags(first.form)
    click('close')
    act(() => view.holder.querySelector<HTMLButtonElement>('button')!.click())
    await settle()
    const edit = Array.from(document.body.querySelectorAll<HTMLButtonElement>('button')).find(
      (button) => button.textContent?.trim() === 'actions.edit',
    )!
    expect(edit.disabled).toBe(true)
    const saved = { ...row('document-a'), metadata: { user: { tags: ['first'] } } }
    await act(async () => save.resolve(saved))
    await settle()
    expect(ports.success).not.toHaveBeenCalled()
    expect(edit.disabled).toBe(false)
    expect(document.body.textContent).toContain('first')
  })

  it('does not publish a previous login write into a replacement cache with the same document id', async () => {
    const save = deferred<Document>()
    ports.documents.patchUserMetadata.mockReturnValueOnce(save.promise)
    const view = mount()
    await settle()
    const first = editTags()
    appendTag(first.input, 'retired')
    submitTags(first.form)
    const current = { ...row('document-a'), metadata: { user: { tags: ['current'] } } }
    ports.documents.get.mockResolvedValue(current)
    act(() => {
      session()
      view.client.clear()
      view.client.setQueryData(queryKeys.documents.detail('document-a'), current)
    })
    await act(async () => save.resolve({ ...row('document-a'), metadata: { user: { tags: ['retired'] } } }))
    await settle()
    expect(view.client.getQueryData(queryKeys.documents.detail('document-a'))).toEqual(current)
    expect(ports.success).not.toHaveBeenCalled()
    expect(document.body.textContent).not.toContain('retired')
  })

  it('does not replace a rebuilt query or report a stale view as saved', async () => {
    const save = deferred<Document>()
    ports.documents.patchUserMetadata.mockReturnValueOnce(save.promise)
    const view = mount()
    await settle()
    const first = editTags()
    appendTag(first.input, 'pending')
    submitTags(first.form)
    const current = { ...row('document-a'), metadata: { user: { tags: ['current'] } } }
    const read = deferred<Document>()
    ports.documents.get.mockResolvedValue(current)
    let readback!: Promise<Document>
    act(() => {
      view.client.removeQueries({ queryKey: queryKeys.documents.detail('document-a'), exact: true })
      view.client.setQueryData(queryKeys.documents.detail('document-a'), current)
      readback = view.client.fetchQuery({
        queryKey: queryKeys.documents.detail('document-a'),
        queryFn: () => read.promise,
      })
    })
    await settle()
    expect(view.client.isFetching({ queryKey: queryKeys.documents.detail('document-a'), exact: true })).toBe(1)
    await act(async () => save.resolve({ ...row('document-a'), metadata: { user: { tags: ['pending'] } } }))
    await settle()
    expect(view.client.isFetching({ queryKey: queryKeys.documents.detail('document-a'), exact: true })).toBe(1)
    await act(async () => {
      read.resolve(current)
      await readback
    })
    await settle()
    expect(view.client.getQueryData(queryKeys.documents.detail('document-a'))).toEqual(current)
    expect(document.body.contains(first.form)).toBe(true)
    expect(document.body.textContent).toContain('errors.tagsRefreshRequired')
    expect(ports.success).not.toHaveBeenCalled()
  })

  it('cancels a previous read before committing confirmed tags so that the read cannot overwrite them', async () => {
    const view = mount()
    await settle()
    const read = deferred<Document>()
    ports.documents.get.mockReturnValueOnce(read.promise)
    let refresh!: Promise<void>
    act(() => {
      refresh = view.client.refetchQueries({ queryKey: queryKeys.documents.detail('document-a'), exact: true })
    })
    const first = editTags()
    appendTag(first.input, 'saved')
    const saved = { ...row('document-a'), metadata: { user: { tags: ['saved'] } } }
    ports.documents.patchUserMetadata.mockResolvedValueOnce(saved)
    submitTags(first.form)
    await settle()
    await act(async () => {
      read.resolve({ ...row('document-a'), metadata: { user: { tags: ['stale'] } } })
      await refresh
    })
    await settle()
    expect(view.client.getQueryData(queryKeys.documents.detail('document-a'))).toEqual(saved)
    expect(document.body.textContent).toContain('saved')
    expect(document.body.textContent).not.toContain('stale')
  })
})
afterEach(() => {
  for (const cleanup of cleanups.splice(0)) cleanup()
  vi.useRealTimers()
})

describe('document processing provenance', () => {
  it('shows an unreturned detail snapshot as missing, then preserves actual server defaults without stale list metadata', async () => {
    const read = deferred<Document>()
    ports.documents.get.mockReturnValueOnce(read.promise)
    mount('document-a', (id) => ({ ...row(id), metadata: { parser_backend: 'retired-list-parser' } }))
    await settle()
    expect(document.body.textContent).not.toContain('false')
    expect(document.body.textContent).not.toContain('cards.governance.disabled')
    expect(document.body.textContent).toContain('cards.notProvided')
    await act(async () => read.resolve({ ...row('document-a'), ...processingFixtures.empty }))
    await settle()
    const values = new Map(
      Array.from(document.body.querySelectorAll('dt')).map((term) => [
        term.textContent,
        term.nextElementSibling?.textContent,
      ]),
    )
    expect(values.get('cards.fields.vectorEnabled')).toBe('cards.disabledValue')
    expect(values.get('cards.fields.charCount')).toBe('0')
    expect(document.body.textContent).toContain('cards.governance.disabled')
    expect(document.body.textContent).not.toContain('retired-list-parser')
  })

  it('uses the accepted typed snapshot, preserves zero and flags, and respects a cleared active version', async () => {
    ports.documents.get.mockResolvedValue({ ...row('document-a'), ...processingFixtures.processed } satisfies Document)
    mount()
    await settle()
    expect(document.body.textContent).not.toContain('old-active-snapshot')
    expect(document.body.textContent).toContain('last-canonical-version')
    expect(document.body.textContent).toContain('custom-legal-sections')
    expect(document.body.textContent).toContain('cards.governance.enabled')
    const values = new Map(
      Array.from(document.body.querySelectorAll('dt')).map((term) => [
        term.textContent,
        term.nextElementSibling?.textContent,
      ]),
    )
    expect(values.get('cards.fields.chunkSize')).toBe('0')
    expect(values.get('cards.fields.charCount')).toBe('0')
    expect(values.get('cards.fields.vectorEnabled')).toBe('cards.disabledValue')
    expect(values.get('cards.fields.bm25Enabled')).toBe('cards.enabledValue')
    expect(values.get('cards.fields.requestedParser')).toBe('cards.emptyValue')
    expect(values.get('cards.fields.activeVersion')).toBe('cards.notProvided')
    expect(document.body.querySelector('button[aria-label="cards.chunking.copyPipelineHash"]')).toBeNull()
  })
})

describe('document lifecycle editing', () => {
  function editLifecycle() {
    const buttons = Array.from(document.body.querySelectorAll<HTMLButtonElement>('button')).filter(
      (button) => button.textContent?.trim() === 'actions.edit',
    )
    act(() => buttons[1]!.click())
    const input = document.body.querySelector<HTMLInputElement>('input[name="lifecycle_owner"]')!
    expect(input).not.toBeNull()
    return input.closest('form')!
  }
  function fill(input: HTMLInputElement, value: string) {
    act(() => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(input, value)
      input.dispatchEvent(new Event('input', { bubbles: true }))
    })
  }
  function saveForm(form: HTMLFormElement) {
    const button = Array.from(form.elements).find(
      (element): element is HTMLButtonElement => element instanceof HTMLButtonElement && element.type === 'submit',
    )
    expect(button).toBeDefined()
    act(() => button!.click())
  }
  const current = {
    publication_status: 'draft' as const,
    lifecycle_owner: 'current-owner',
    authority_level: 5,
    review_due_at: '2026-11-16T12:34:56.789123Z',
    supersedes_document_id: null,
  }

  it('edits the actual lifecycle read instead of a stale detail snapshot', async () => {
    ports.documents.get.mockResolvedValue({ ...row('document-a'), lifecycle_owner: 'retired-owner' })
    ports.documents.getLifecycleMetadata.mockResolvedValue(current)
    mount()
    await settle()
    const form = editLifecycle()
    expect(form.querySelector<HTMLInputElement>('input[name="lifecycle_owner"]')!.value).toBe('current-owner')
  })

  it('saves a valid exponent as its actual number and leaves untouched precise time out of the patch', async () => {
    ports.documents.get.mockResolvedValue({ ...row('document-a'), ...current })
    ports.documents.getLifecycleMetadata.mockResolvedValue(current)
    ports.documents.patchLifecycleMetadata.mockResolvedValue({ ...current, authority_level: 10 })
    mount()
    await settle()
    const form = editLifecycle()
    fill(form.querySelector<HTMLInputElement>('input[name="authority_level"]')!, '1e1')
    saveForm(form)
    await settle()
    expect(ports.documents.patchLifecycleMetadata).toHaveBeenCalledExactlyOnceWith('document-a', {
      authority_level: 10,
    })
  })

  it('keeps untouched fields and a failed owner draft, then only sends the chosen owner change', async () => {
    ports.documents.get.mockResolvedValue({ ...row('document-a'), ...current })
    ports.documents.getLifecycleMetadata.mockResolvedValue(current)
    ports.documents.patchLifecycleMetadata.mockRejectedValueOnce(new Error('lifecycle write rejected'))
    mount()
    await settle()
    const form = editLifecycle()
    const input = form.querySelector<HTMLInputElement>('input[name="lifecycle_owner"]')!
    fill(input, '  next-owner  ')
    saveForm(form)
    await settle()
    expect(ports.documents.patchLifecycleMetadata).toHaveBeenCalledExactlyOnceWith('document-a', {
      lifecycle_owner: 'next-owner',
    })
    expect(input.value).toBe('  next-owner  ')
    expect(document.body.contains(form)).toBe(true)
    expect(document.body.textContent).toContain('lifecycle write rejected')
  })
})

describe('document detail chunk request ownership', () => {
  it('keeps a newer search result when an older reload succeeds later', async () => {
    const old = deferred<DocumentChunkList>()
    ports.documents.listChunks.mockReturnValueOnce(old.promise)
    mount()
    await settle()
    search(' current ')
    await settle(250)
    expect(ports.documents.listChunks).toHaveBeenLastCalledWith(
      'document-a',
      { skip: 0, limit: 200, q: 'current', pipeline_hash: undefined },
      { signal: expect.any(AbortSignal) },
    )
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
    expect(ports.documents.listChunks).toHaveBeenLastCalledWith(
      'document-a',
      { skip: 1, limit: 200, q: undefined, pipeline_hash: undefined },
      { signal: expect.any(AbortSignal) },
    )
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
