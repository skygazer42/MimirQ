// @vitest-environment happy-dom

import React, { act } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { NextIntlClientProvider } from 'next-intl'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import commandMessages from '@/i18n/messages/zh-CN/command'
import commonMessages from '@/i18n/messages/zh-CN/common'
import { AUTH_SCOPE_CHANGED_EVENT } from '@/lib/auth-storage'
import { queryKeys } from '@/lib/query-keys'
import { useCommandMenuState } from '@/store/command-menu'
import { waitForAssertion } from '@/test/hook-harness'

const api = vi.hoisted(() => ({ documents: vi.fn(), datasets: vi.fn(), conversations: vi.fn() }))
vi.hoisted(() => vi.stubGlobal('BroadcastChannel', undefined))
vi.mock('@/lib/api', () => ({
  documentApi: { list: api.documents },
  datasetApi: { list: api.datasets },
  chatApi: { listConversations: api.conversations },
}))
vi.mock('@/lib/api/documents', () => ({ documentApi: { list: api.documents } }))
vi.mock('@/lib/api/datasets', () => ({ datasetApi: { list: api.datasets } }))
vi.mock('@/lib/api/chat', () => ({ chatApi: { listConversations: api.conversations } }))
vi.mock('@/i18n/navigation', () => ({ usePathname: () => '/', useRouter: () => ({ push: vi.fn() }) }))
vi.mock('next-themes', () => ({ useTheme: () => ({ setTheme: vi.fn() }) }))
vi.mock('@/hooks/use-tenant-access', () => ({ useTenantAccess: () => ({ data: undefined }) }))
vi.mock('@/lib/navigation-visibility', () => ({ canShowAdminControlledNavigationModule: () => true }))
vi.mock('@/store/document-view', () => ({
  useDocumentView: () => ({ lastOpenedTarget: null, openDocument: vi.fn(), reopenLastDocument: vi.fn() }),
}))

import { CommandMenu } from './command-menu'

const documentResult = { total: 1, items: [{ id: 'document-a', filename: '服务器返回的文件.pdf', file_type: 'pdf' }] }
const datasetResult = { total: 1, items: [{ id: 'dataset-a', name: '服务器数据集' }] }
const conversationResult = { total: 1, items: [{ id: 'conversation-a', title: '服务器会话' }] }
let root: ReturnType<typeof createRoot>
let client: QueryClient

beforeEach(async () => {
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  vi.resetAllMocks()
  Element.prototype.scrollIntoView = vi.fn()
  api.documents.mockResolvedValue(documentResult)
  api.datasets.mockResolvedValue(datasetResult)
  api.conversations.mockResolvedValue(conversationResult)
  client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity, gcTime: 0 } } })
  useCommandMenuState.setState({ open: true })
  const container = document.createElement('div')
  document.body.append(container)
  root = createRoot(container)
  await act(async () => {
    root.render(
      <NextIntlClientProvider locale="zh-CN" timeZone="UTC" messages={{ ...commonMessages, ...commandMessages }}>
        <QueryClientProvider client={client}>
          <CommandMenu />
        </QueryClientProvider>
      </NextIntlClientProvider>,
    )
  })
})

afterEach(() => {
  act(() => root.unmount())
  client.clear()
  useCommandMenuState.setState({ open: false })
  document.body.replaceChildren()
})

async function search(value: string) {
  const input = document.querySelector<HTMLInputElement>('[cmdk-input]')!
  const setValue = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!
  act(() => {
    setValue.call(input, value)
    input.dispatchEvent(new Event('input', { bubbles: true }))
  })
  await waitForAssertion(() => expect(api.documents).toHaveBeenCalled())
}

describe('command search query ownership', () => {
  it('keeps list envelopes in the shared cache and shows server-filtered results without another text filter', async () => {
    await search('内容命中')
    await waitForAssertion(() => expect(document.body.textContent).toContain('服务器返回的文件.pdf'))
    const documentParams = api.documents.mock.calls[0][0]
    const datasetParams = api.datasets.mock.calls[0][0]
    const conversationParams = api.conversations.mock.calls[0][0]

    expect(client.getQueryData(queryKeys.documents.list(documentParams))).toEqual(documentResult)
    expect(client.getQueryData(queryKeys.datasets.list(datasetParams))).toEqual(datasetResult)
    expect(client.getQueryData(queryKeys.chat.conversations(conversationParams))).toEqual(conversationResult)
    expect(api.documents).toHaveBeenCalledWith(documentParams, { signal: expect.any(AbortSignal) })
    expect(api.datasets).toHaveBeenCalledWith(datasetParams, { signal: expect.any(AbortSignal) })
    expect(api.conversations).toHaveBeenCalledWith(conversationParams, { signal: expect.any(AbortSignal) })
  })

  it('shows a read failure while retaining usable cached document results', async () => {
    await search('内容命中')
    await waitForAssertion(() => expect(api.documents).toHaveBeenCalledOnce())
    const queryKey = queryKeys.documents.list(api.documents.mock.calls[0][0])
    api.documents.mockRejectedValue(new Error('目录暂不可用'))

    await act(async () => client.refetchQueries({ queryKey }))

    await waitForAssertion(() =>
      expect(document.querySelector('[role="alert"]')?.textContent).toContain('目录暂不可用'),
    )
    expect(document.body.textContent).toContain('服务器返回的文件.pdf')
    expect(document.body.textContent).not.toContain('未找到文档')
    expect(client.getQueryData(queryKey)).toEqual(documentResult)
  })

  it('shows untitled conversations when the server returns nullable title and message fields', async () => {
    api.conversations.mockResolvedValue({
      total: 1,
      items: [{ id: 'conversation-empty', title: null, last_message: null, last_message_at: null }],
    })

    await search('无消息会话')

    await waitForAssertion(() => expect(document.body.textContent).toContain('未命名对话'))
    expect(document.querySelector('[cmdk-item][data-value="conversation:conversation-empty"]')).not.toBeNull()
  })

  it('retires an open search and its pending transport when auth scope is invalidated', async () => {
    api.documents.mockImplementation(() => new Promise(() => {}))
    await search('未完成查询')
    const signal: AbortSignal = api.documents.mock.calls[0][1]?.signal
    expect(signal).toBeDefined()

    act(() => {
      client.clear()
      window.dispatchEvent(new Event(AUTH_SCOPE_CHANGED_EVENT))
    })

    await waitForAssertion(() => expect(document.querySelector('[role="dialog"]')).toBeNull())
    expect(useCommandMenuState.getState().open).toBe(false)
    expect(signal.aborted).toBe(true)
  })
})
