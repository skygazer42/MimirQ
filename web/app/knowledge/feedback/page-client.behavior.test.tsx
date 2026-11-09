// @vitest-environment happy-dom

import React, { act } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { MessageFeedbackEnriched } from '@/types'

const api = vi.hoisted(() => ({ listEnriched: vi.fn(), update: vi.fn(), toRegressionCase: vi.fn(), loopCandidates: vi.fn() }))
const chat = vi.hoisted(() => ({ getMessages: vi.fn() }))
const router = vi.hoisted(() => ({ push: vi.fn() }))
vi.mock('@/lib/api', () => ({ feedbackApi: api, chatApi: chat }))
vi.mock('@/i18n/navigation', () => ({ usePathname: () => '/knowledge/feedback', useRouter: () => router, Link: ({ children, ...props }: React.AnchorHTMLAttributes<HTMLAnchorElement>) => React.createElement('a', props, children) }))
vi.mock('next/navigation', () => ({ useSearchParams: () => new URLSearchParams() }))
vi.mock('@/components/app-frame', () => ({ AppFrame: ({ children }: { children: React.ReactNode }) => React.createElement('div', null, children) }))
vi.mock('@/components/ui/page-scaffold', () => ({ PageScaffold: ({ top, children }: { top: React.ReactNode; children: React.ReactNode }) => React.createElement('div', null, top, children) }))
vi.mock('@/components/ui/page-title-icon', () => ({ PageTitleIcon: () => null }))
vi.mock('@/components/ui/search-input', () => ({ SearchInput: ({ value, onValueChange, placeholder }: { value: string; onValueChange: (v: string) => void; placeholder: string }) => React.createElement('input', { value, placeholder, onInput: (e: Event) => onValueChange((e.target as HTMLInputElement).value) }) }))
vi.mock('@/components/ui/select', () => ({
  Select: ({ children, value, onValueChange }: { children: React.ReactNode; value: string; onValueChange: (v: string) => void }) => React.createElement('select', { value, onChange: (e: Event) => onValueChange((e.target as HTMLSelectElement).value) }, children),
  SelectTrigger: () => null, SelectValue: () => null,
  SelectContent: ({ children }: { children: React.ReactNode }) => React.createElement(React.Fragment, null, children),
  SelectItem: ({ children, value }: { children: React.ReactNode; value: string }) => React.createElement('option', { value }, children),
}))
vi.mock('@/components/ui/file-type-icon', () => ({ FileTypeIcon: () => null }))
vi.mock('@/store/document-view', () => ({ useDocumentView: () => ({ openDocument: vi.fn() }) }))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

import FeedbackTriagePage from './page-client'

let records: MessageFeedbackEnriched[]
const cleanups: (() => void)[] = []
function feedback(id: string, overrides: Partial<MessageFeedbackEnriched> = {}): MessageFeedbackEnriched {
  return { id, tenant_id: 'tenant', conversation_id: `conversation-${id}`, message_id: `message-${id}`, account_id: 'reader', rating: 2, reason: `反馈原因 ${id}`, expected_answer: `期望 ${id}`, tags: [], extra: { source: 'web' }, message_content: `原回答 ${id}`, conversation_title: `问题 ${id}`, created_at: '2026-10-22T02:24:00Z', updated_at: '2026-10-22T02:24:00Z', ...overrides }
}
function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  const container = document.createElement('div'); document.body.appendChild(container)
  const root = createRoot(container)
  act(() => root.render(<QueryClientProvider client={queryClient}><FeedbackTriagePage /></QueryClientProvider>))
  cleanups.push(() => { act(() => root.unmount()); queryClient.clear(); container.remove() })
  return container
}
function button(container: HTMLElement, label: string) {
  const target = Array.from(container.querySelectorAll('button')).find(item => item.getAttribute('aria-label') === label || item.textContent?.trim() === label)
  expect(target, label).toBeTruthy(); return target!
}
async function click(target: HTMLElement) { await act(async () => target.click()) }
async function ready(container: HTMLElement) { await act(async () => vi.waitFor(() => expect(container.querySelector('[data-feedback-item]')).toBeTruthy())) }

describe('feedback inbox', () => {
  beforeEach(() => {
    ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
    vi.clearAllMocks()
    records = [feedback('1'), feedback('2', { rating: 5, extra: { source: 'api' } }), feedback('3', { extra: { source: 'web', archived: true } })]
    api.listEnriched.mockImplementation(async ({ skip = 0 }: { skip?: number }) => ({ total: records.length, items: records.slice(skip, skip + 200) }))
    chat.getMessages.mockImplementation(async (conversationId: string) => ({ conversation_id: conversationId, messages: [{ id: `user-${conversationId}`, role: 'user', content: `原问题 ${conversationId}`, created_at: '' }, { id: conversationId.replace('conversation-', 'message-'), role: 'assistant', content: '会话答复', citations: [], created_at: '' }] }))
    api.update.mockImplementation(async (id: string, body: { archived: boolean }) => { records = records.map(item => item.id === id ? { ...item, extra: { ...item.extra, archived: body.archived } } : item); return records.find(item => item.id === id) })
    api.toRegressionCase.mockResolvedValue({ id: 'case-1' })
  })
  afterEach(() => { cleanups.splice(0).forEach(cleanup => cleanup()); document.body.innerHTML = '' })

  it('reads feedback inline, navigates records and filters the queue without a detail dialog', async () => {
    const container = renderPage(); await ready(container)
    await act(async () => vi.waitFor(() => expect(container.querySelector('[data-feedback-reader]')?.textContent).toContain('原回答 1')))
    expect(container.querySelector('[role="dialog"]')).toBeNull()
    await click(button(container, '下一条反馈'))
    expect(container.querySelector('[data-feedback-reader]')?.textContent).toContain('原回答 2')
    const search = container.querySelector('input')!
    await act(async () => { search.value = '问题 3'; search.dispatchEvent(new Event('input', { bubbles: true })) })
    expect(container.querySelectorAll('[data-feedback-item]')).toHaveLength(1)
    expect(container.querySelector('[data-feedback-reader]')?.textContent).toContain('原回答 3')
  })

  it('keeps the failed record and filters, then archives and reads back the persisted status', async () => {
    const { toast } = await import('sonner')
    const container = renderPage(); await ready(container)
    api.update.mockRejectedValueOnce(new Error('不能归档'))
    await click(button(container, '归档反馈'))
    await act(async () => vi.waitFor(() => expect(toast.error).toHaveBeenCalledWith(expect.stringContaining('归档失败'), expect.objectContaining({ duration: 4000 }))))
    expect(container.querySelector('[data-feedback-item][aria-current="true"]')?.getAttribute('data-feedback-item')).toBe('1')
    await click(button(container, '归档反馈'))
    await act(async () => vi.waitFor(() => expect(button(container, '取消归档')).toBeTruthy()))
    expect(api.update).toHaveBeenLastCalledWith('1', { archived: true })
    expect(api.listEnriched.mock.calls.length).toBeGreaterThan(1)
    await click(button(container, '取消归档'))
    await act(async () => vi.waitFor(() => expect(button(container, '归档反馈')).toBeTruthy()))
  })

  it('binds late regression results to their original feedback and prevents duplicate submits', async () => {
    let finish!: (result: { id: string }) => void
    api.toRegressionCase.mockImplementation(() => new Promise(resolve => { finish = resolve }))
    const container = renderPage(); await ready(container)
    await click(button(container, '创建回归用例'))
    await click(button(container, '下一条反馈'))
    await act(async () => finish({ id: 'case-for-1' }))
    expect(container.querySelector('[data-feedback-reader]')?.textContent).not.toContain('查看回归用例')
    await click(button(container, '上一条反馈'))
    expect(container.querySelector('[data-feedback-reader]')?.textContent).toContain('查看回归用例')
    expect(api.toRegressionCase).toHaveBeenCalledTimes(1)
  })

  it('distinguishes a failed request from an empty queue, and retries without fabricated data', async () => {
    api.listEnriched.mockRejectedValueOnce(new Error('服务不可用'))
    records = []
    const container = renderPage()
    await act(async () => vi.waitFor(() => expect(container.textContent).toContain('反馈加载失败')))
    expect(container.textContent).not.toContain('暂无反馈')
    await click(button(container, '重试'))
    await act(async () => vi.waitFor(() => expect(container.textContent).toContain('暂无反馈')))
    expect(container.querySelectorAll('[data-feedback-item]')).toHaveLength(0)
  })

  it('loads later API pages so feedback outside the first response can still be found', async () => {
    records = Array.from({ length: 201 }, (_, index) => feedback(String(index + 1)))
    const container = renderPage(); await ready(container)
    await act(async () => vi.waitFor(() => expect(api.listEnriched).toHaveBeenCalledWith({ skip: 200, limit: 200 }, expect.anything())))
    const search = container.querySelector('input')!
    await act(async () => { search.value = '问题 201'; search.dispatchEvent(new Event('input', { bubbles: true })) })
    expect(container.querySelectorAll('[data-feedback-item]')).toHaveLength(1)
    expect(container.querySelector('[data-feedback-reader]')?.textContent).toContain('原回答 201')
  })
})
