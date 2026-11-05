// @vitest-environment happy-dom

import React, { act } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { DocumentBatchUploadResponse } from '@/types'
import { setAccessToken, setAuthSession } from '@/lib/auth-storage'

const api = vi.hoisted(() => ({ uploadBatch: vi.fn(), listAll: vi.fn() }))
const notices = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }))
vi.mock('@/lib/api', () => ({ documentApi: api, datasetApi: api }))
vi.mock('@/lib/api/documents', () => ({ documentApi: api }))
vi.mock('@/lib/api/datasets', () => ({ datasetApi: api }))

vi.mock('sonner', () => ({ toast: notices }))
vi.mock('@/components/ui/dialog', () => ({
  Dialog: ({
    open,
    onOpenChange,
    children,
  }: {
    open: boolean
    onOpenChange: (value: boolean) => void
    children: React.ReactNode
  }) =>
    open ? (
      <div data-confirm="true">
        <button onClick={() => onOpenChange(false)}>close dialog</button>
        {children}
      </div>
    ) : null,
  DialogContent: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  DialogHeader: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  DialogFooter: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  DialogTitle: ({ children }: { children: React.ReactNode }) => <h2>{children}</h2>,
  DialogDescription: ({ children }: { children: React.ReactNode }) => <p>{children}</p>,
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

import { DropZone, type DropZoneHandle } from './drop-zone'

const response: DocumentBatchUploadResponse = {
  total: 1,
  successful_count: 1,
  failed_count: 0,
  successful: [{ document_id: 'doc-1', filename: 'old.pdf', status: 'pending' }],
  failed: [],
}
const session = {
  token: { access_token: 'token-a', token_type: 'bearer', expires_in: 3600 },
  user: { id: 'user-a', email: 'a@example.org', username: 'A', is_active: true, created_at: '2026-11-05T00:00:00Z' },
}
function deferred() {
  let resolve!: (value: DocumentBatchUploadResponse) => void
  let reject!: (error: Error) => void
  const promise = new Promise<DocumentBatchUploadResponse>((yes, no) => {
    resolve = yes
    reject = no
  })
  return { promise, resolve, reject }
}
const cleanups: Array<() => void> = []
function setup(datasetId: string | null = null) {
  const host = document.createElement('div')
  document.body.append(host)
  const root = createRoot(host)
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const ref = React.createRef<DropZoneHandle>()
  const onUploadComplete = vi.fn()
  async function visit(id = datasetId) {
    await act(async () =>
      root.render(
        <QueryClientProvider client={client}>
          <DropZone ref={ref} datasetId={id} onUploadComplete={onUploadComplete} />
        </QueryClientProvider>,
      ),
    )
  }
  async function pick(files: File[]) {
    const input = host.querySelector<HTMLInputElement>('input[type="file"]')!
    Object.defineProperty(input, 'files', { configurable: true, value: files })
    await act(async () => input.dispatchEvent(new Event('change', { bubbles: true })))
    if (!datasetId)
      await act(async () => {
        await vi.waitFor(() => expect(host.textContent).toContain('Dataset One'))
      })
  }
  async function selectDataset() {
    const select = host.querySelector('select')!
    await act(async () => {
      select.value = 'ds-1'
      select.dispatchEvent(new Event('change', { bubbles: true }))
    })
  }
  function button(text = '开始入库') {
    const item = Array.from(host.querySelectorAll('button')).find((node) => node.textContent === text)
    if (!item) throw new Error(`button missing: ${text}`)
    return item
  }
  cleanups.push(() => {
    act(() => root.unmount())
    client.clear()
    host.remove()
  })
  return { host, ref, onUploadComplete, visit, pick, selectDataset, button }
}
beforeEach(() => {
  ;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  window.localStorage.clear()
  window.sessionStorage.clear()
  setAuthSession(session)
  api.listAll.mockResolvedValue([{ id: 'ds-1', name: 'Dataset One' }])
  api.uploadBatch.mockResolvedValue(response)
})
afterEach(() => {
  cleanups.splice(0).forEach((cleanup) => cleanup())
  vi.resetAllMocks()
})

describe('ingestion drop zone ownership', () => {
  it('keeps a new confirmation busy when the previous upload fails', async () => {
    const first = deferred()
    const second = deferred()
    api.uploadBatch.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise)
    const view = setup()
    await view.visit()
    try {
      await view.pick([new File(['old'], 'old.pdf')])
      await view.selectDataset()
      await act(async () => view.button().click())
      await act(async () => view.button('close dialog').click())
      await view.pick([new File(['new'], 'new.pdf')])
      await act(async () => view.button().click())
      expect(api.uploadBatch).toHaveBeenCalledTimes(2)
      await act(async () => first.reject(new Error('old upload failed')))
      expect(view.host.textContent).toContain('new.pdf')
      expect(view.button().disabled).toBe(true)
      expect(notices.error).not.toHaveBeenCalled()
      expect(view.onUploadComplete).not.toHaveBeenCalled()
      await act(async () => second.resolve(response))
      expect(view.onUploadComplete).toHaveBeenCalledTimes(1)
    } finally {
      await act(async () => {
        first.resolve(response)
        second.resolve(response)
      })
    }
  })

  it.each([true, false])(
    'accepts a distinct batch while an old batch is pending (dataset changed=%s)',
    async (changeDataset) => {
      const first = deferred()
      const second = deferred()
      api.uploadBatch.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise)
      const view = setup('ds-1')
      await view.visit()
      const original = new File(['old'], 'same.pdf', { type: 'application/pdf', lastModified: 123 })
      const replacement = new File(['new'], 'same.pdf', { type: 'application/pdf', lastModified: 123 })
      let completionA!: Promise<void>
      let completionB!: Promise<void>
      let completedB = false
      try {
        await act(async () => {
          completionA = view.ref.current!.uploadFiles([original])
        })
        if (changeDataset) await view.visit('ds-2')
        await act(async () => {
          completionB = view.ref.current!.uploadFiles([replacement])
          void completionB.then(() => {
            completedB = true
          })
        })
        expect(api.uploadBatch).toHaveBeenCalledTimes(2)
        expect(api.uploadBatch.mock.calls[0]?.[0]?.[0]).toBe(original)
        expect(api.uploadBatch.mock.calls[1]?.[0]?.[0]).toBe(replacement)
        expect(api.uploadBatch.mock.calls[0]?.[1]).toMatchObject({ dataset_id: 'ds-1', max_concurrent: 4 })
        expect(api.uploadBatch.mock.calls[1]?.[1]).toMatchObject({
          dataset_id: changeDataset ? 'ds-2' : 'ds-1',
          max_concurrent: 4,
        })
        await act(async () => {
          first.resolve(response)
          await completionA
        })
        expect(completedB).toBe(false)
        await act(async () => {
          second.resolve(response)
          await completionB
        })
        expect(completedB).toBe(true)
        expect(await original.text()).toBe('old')
        expect(await replacement.text()).toBe('new')
      } finally {
        await act(async () => {
          first.resolve(response)
          second.resolve(response)
          await Promise.all([completionA, completionB])
        })
      }
    },
  )

  it('accepts a new confirmation visit while the previous accepted upload is pending', async () => {
    const first = deferred()
    const second = deferred()
    api.uploadBatch.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise)
    const view = setup()
    await view.visit()
    try {
      await view.pick([new File(['old'], 'old.pdf')])
      await view.selectDataset()
      await act(async () => view.button().click())
      await act(async () => view.button('close dialog').click())
      await view.pick([new File(['new'], 'new.pdf')])
      expect(view.button().disabled).toBe(false)
      await act(async () => view.button().click())
      expect(api.uploadBatch).toHaveBeenCalledTimes(2)
      await act(async () => first.resolve(response))
      expect(view.host.textContent).toContain('new.pdf')
      expect(view.button().disabled).toBe(true)
      await act(async () => second.resolve(response))
      expect(view.host.querySelector('[data-confirm]')).toBeNull()
    } finally {
      await act(async () => {
        first.resolve(response)
        second.resolve(response)
      })
    }
  })

  it('shares the pending completion for a duplicate batch from the same visit', async () => {
    const pending = deferred()
    api.uploadBatch.mockReturnValueOnce(pending.promise)
    const view = setup('ds-1')
    await view.visit()
    const file = new File(['old'], 'old.pdf', { lastModified: 123 })
    let first!: Promise<void>
    let duplicate!: Promise<void>
    let completed = false
    try {
      await act(async () => {
        first = view.ref.current!.uploadFiles([file])
        duplicate = view.ref.current!.uploadFiles([file])
        void duplicate.then(() => {
          completed = true
        })
      })
      expect(api.uploadBatch).toHaveBeenCalledTimes(1)
      expect(completed).toBe(false)
      await act(async () => {
        pending.resolve(response)
        await Promise.all([first, duplicate])
      })
      expect(completed).toBe(true)
      expect(view.onUploadComplete).toHaveBeenCalledTimes(1)
    } finally {
      await act(async () => {
        pending.resolve(response)
        await Promise.all([first, duplicate])
      })
    }
  })

  it('shares one pending upload across the imperative and picker paths', async () => {
    const pending = deferred()
    api.uploadBatch.mockReturnValue(pending.promise)
    const view = setup('ds-1')
    await view.visit()
    const file = new File(['old'], 'old.pdf', { lastModified: 123 })
    let first!: Promise<void>
    await act(async () => {
      first = view.ref.current!.uploadFiles([file])
    })
    await view.pick([file])
    expect(api.uploadBatch).toHaveBeenCalledTimes(1)
    await act(async () => {
      pending.resolve(response)
      await first
    })
    expect(api.uploadBatch.mock.calls[0]?.[0]?.[0]).toBe(file)
  })
  it('keeps a new confirmation draft after the old upload completes', async () => {
    const pending = deferred()
    api.uploadBatch.mockReturnValueOnce(pending.promise)
    const view = setup()
    await view.visit()
    await view.pick([new File(['old'], 'old.pdf')])
    await view.selectDataset()
    await act(async () => view.button().click())
    await act(async () => view.button('close dialog').click())
    await view.pick([new File(['new'], 'new.pdf')])
    await act(async () => pending.resolve(response))
    expect(view.host.textContent).toContain('new.pdf')
    expect(view.host.querySelector('[data-confirm]')).not.toBeNull()
    expect(notices.success).not.toHaveBeenCalled()
    expect(view.onUploadComplete).toHaveBeenCalledTimes(1)
  })
  it('reports upload errors while keeping the imperative rejection contract', async () => {
    api.uploadBatch.mockRejectedValueOnce(new Error('upload unavailable'))
    const view = setup('ds-1')
    await view.visit()
    await act(async () => {
      await expect(view.ref.current!.uploadFiles([new File(['x'], 'x.pdf')])).rejects.toThrow('upload unavailable')
    })
    expect(notices.error).toHaveBeenCalledWith('upload unavailable')
    expect(view.onUploadComplete).not.toHaveBeenCalled()
  })
  it('does not publish or refresh after explicit login replacement', async () => {
    const pending = deferred()
    api.uploadBatch.mockReturnValueOnce(pending.promise)
    const view = setup('ds-1')
    await view.visit()
    let completion!: Promise<void>
    await act(async () => {
      completion = view.ref.current!.uploadFiles([new File(['x'], 'x.pdf')])
    })
    setAuthSession(session)
    await act(async () => {
      pending.resolve(response)
      await completion
    })
    expect(notices.success).not.toHaveBeenCalled()
    expect(view.onUploadComplete).not.toHaveBeenCalled()
  })
  it('retains parser preference, mode, concurrency, bytes and token refresh success', async () => {
    const view = setup('ds-1')
    window.localStorage.setItem('mimirq.ingestion.dropParserBackend', 'markitdown')
    await view.visit()
    const file = new File(['actual bytes'], 'input.pdf', { lastModified: 456 })
    const pending = deferred()
    api.uploadBatch.mockReturnValueOnce(pending.promise)
    let completion!: Promise<void>
    await act(async () => {
      view.ref.current!.triggerFilePicker({ precheckOnly: true })
      completion = view.ref.current!.uploadFiles([file])
    })
    setAccessToken({ access_token: 'refreshed', token_type: 'bearer', expires_in: 3600 })
    await act(async () => {
      pending.resolve(response)
      await completion
    })
    expect(api.uploadBatch).toHaveBeenCalledWith([file], {
      dataset_id: 'ds-1',
      parser_backend: 'markitdown',
      chunk_strategy: 'langchain_recursive',
      precheck_only: true,
      max_concurrent: 4,
    })
    expect(await file.text()).toBe('actual bytes')
    expect(view.onUploadComplete).toHaveBeenCalledTimes(1)
    expect(notices.success).toHaveBeenCalledWith('评估完成：成功 1 / 失败 0')
  })
})
