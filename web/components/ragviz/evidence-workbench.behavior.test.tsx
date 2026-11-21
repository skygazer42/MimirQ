// @vitest-environment happy-dom

import React, { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { NextIntlClientProvider } from 'next-intl'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const controlled = vi.hoisted(() => ({
  retrieve: vi.fn(),
  listDatasets: vi.fn(),
  download: vi.fn(),
  toast: { success: vi.fn(), warning: vi.fn(), message: vi.fn() },
}))
vi.hoisted(() => vi.stubGlobal('BroadcastChannel', undefined))

vi.mock('@/lib/api', () => ({
  ragApi: { retrieveEvidence: controlled.retrieve },
  datasetApi: { listAll: controlled.listDatasets },
}))
vi.mock('@/lib/download', () => ({ downloadBlob: controlled.download }))
vi.mock('sonner', () => ({ toast: controlled.toast }))

import ragMessages from '@/i18n/messages/zh-CN/rag'
import { clearAuthSession } from '@/lib/auth-storage'
import { waitForAssertion } from '@/test/hook-harness'
import { EvidenceWorkbench } from './evidence-workbench'

let root: Root
let client: QueryClient

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (error: Error) => void
  const promise = new Promise<T>((fulfill, fail) => {
    resolve = fulfill
    reject = fail
  })
  return { promise, resolve, reject }
}

function response(citations: Array<Record<string, unknown>>, query = '服务器检索问题') {
  return {
    schema: 'mimirq.evidence.v1',
    query_for_retrieval: query,
    citations,
    has_evidence: true,
    abstain_triggered: false,
  }
}

function button(label: string) {
  const element = Array.from(document.querySelectorAll('button')).find((item) => item.textContent?.trim() === label)
  if (element === undefined) throw new Error(`Missing button: ${label}`)
  return element
}

function changeQuery(value: string) {
  const textarea = document.querySelector<HTMLTextAreaElement>('textarea[aria-label="检索问题"]')!
  act(() => {
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!.call(textarea, value)
    textarea.dispatchEvent(new Event('input', { bubbles: true }))
  })
}

function submit() {
  document.querySelector('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
}

beforeEach(async () => {
  vi.clearAllMocks()
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  controlled.listDatasets.mockResolvedValue([])
  client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  const container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
  await act(async () => {
    root.render(
      <QueryClientProvider client={client}>
        <NextIntlClientProvider locale="zh-CN" messages={ragMessages}>
          <EvidenceWorkbench />
        </NextIntlClientProvider>
      </QueryClientProvider>,
    )
  })
  changeQuery('当前问题')
})

afterEach(() => {
  act(() => root.unmount())
  client.clear()
  document.body.replaceChildren()
})

describe('evidence retrieval data and request ownership', () => {
  it('keeps minimal citations, score precedence, zero coordinates and explicit empty source text', async () => {
    controlled.retrieve.mockResolvedValue(
      response([
        { document_id: 'minimal-id' },
        {
          document_id: 'full-id',
          document_name: '原文',
          chunk_content: '',
          retrieval_score: 0.875,
          relevance_score: 0.1,
          page_number: 0,
          chunk_index: 0,
        },
        { document_id: 'zero-id', document_name: '零分', chunk_content: '  source\n', retrieval_score: 0 },
      ]),
    )
    await act(async () => submit())
    const articles = document.querySelectorAll('article')
    expect(articles).toHaveLength(3)
    expect(articles[0].textContent).toContain('minimal-id')
    expect(articles[0].textContent).toContain('未提供')
    expect(articles[1].textContent).toContain('0.8750')
    expect(articles[1].textContent).toContain('P.0')
    expect(articles[1].textContent).toContain('原文为空')
    expect(articles[2].textContent).toContain('0.0000')
    expect(articles[2].querySelector('p')?.textContent).toBe('  source\n')
  })

  it.each([false, true, '', '0.7'])('reports invalid numeric field %j instead of inventing a score', async (score) => {
    controlled.retrieve.mockResolvedValue(
      response([{ document_id: 'id', document_name: '原文', relevance_score: score }]),
    )
    await act(async () => submit())
    expect(document.querySelector('[role="alert"]')?.textContent).toContain('relevance_score')
    expect(document.querySelectorAll('article')).toHaveLength(0)
    expect(controlled.toast.success).not.toHaveBeenCalled()
  })

  it('does not treat null score fields as zero', async () => {
    controlled.retrieve.mockResolvedValue(
      response([{ document_id: 'id', retrieval_score: null, relevance_score: null }]),
    )
    await act(async () => submit())
    expect(document.querySelector('article')?.textContent).toContain('未提供')
    expect(document.querySelector('article')?.textContent).not.toContain('0.0000')
  })

  it('serializes duplicate submits and ignores old completion after a draft changes away and back', async () => {
    const old = deferred<ReturnType<typeof response>>()
    const current = deferred<ReturnType<typeof response>>()
    controlled.retrieve.mockReturnValueOnce(old.promise).mockReturnValueOnce(current.promise)
    act(() => {
      submit()
      submit()
    })
    expect(controlled.retrieve).toHaveBeenCalledTimes(1)
    changeQuery('另一问题')
    changeQuery('当前问题')
    act(() => submit())
    await act(async () => old.resolve(response([{ document_id: 'old-id' }])))
    expect(document.querySelector<HTMLButtonElement>('button[type="submit"]')?.disabled).toBe(true)
    expect(document.querySelectorAll('article')).toHaveLength(0)
    await act(async () => current.resolve(response([{ document_id: 'current-id' }])))
    expect(document.querySelector('article')?.textContent).toContain('current-id')
    expect(controlled.toast.success).toHaveBeenCalledTimes(1)
  })

  it('retains the committed response on a failed refresh and exports every raw response field', async () => {
    const raw = {
      ...response([{ document_id: 'raw-id', extra: { kept: false } }], ''),
      retrieval_trace: { count: 0 },
      query_debug: { query: '' },
    }
    controlled.retrieve.mockResolvedValueOnce(raw).mockRejectedValueOnce(new Error('读取失败'))
    await act(async () => submit())
    await act(async () => submit())
    expect(document.querySelector('[role="alert"]')?.textContent).toContain('读取失败')
    expect(document.querySelector('article')?.textContent).toContain('raw-id')
    act(() => button('导出结果').click())
    expect(controlled.download).toHaveBeenCalledTimes(1)
    const [filename, blob] = controlled.download.mock.calls[0] as [string, Blob]
    expect(filename).toMatch(/^evidence-pack-all-/)
    const pack = JSON.parse(await blob.text())
    expect(pack).toMatchObject(raw)
    expect(pack.query_for_retrieval).toBe('')
    expect(pack.request.query).toBe('当前问题')
  })

  it('invalidates pending feedback when its session ends', async () => {
    const pending = deferred<ReturnType<typeof response>>()
    controlled.retrieve.mockReturnValue(pending.promise)
    act(() => submit())
    act(() => clearAuthSession())
    await act(async () => pending.resolve(response([{ document_id: 'old-session' }])))
    await waitForAssertion(() => expect(document.querySelectorAll('article')).toHaveLength(0))
    expect(controlled.toast.success).not.toHaveBeenCalled()
  })
})
