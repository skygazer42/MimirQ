// @vitest-environment happy-dom
import React, { act } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { setAccessToken, setAuthSession } from '@/lib/auth-storage'
import type { MessageFeedbackEnriched } from '@/types/feedback'

const api = vi.hoisted(() => ({
  listEnriched: vi.fn(),
  loopCandidates: vi.fn(),
  toRegressionCase: vi.fn(),
  update: vi.fn(),
}))
const chat = vi.hoisted(() => ({ getMessages: vi.fn() }))
const notices = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }))
vi.mock('@/lib/api', () => ({ feedbackApi: api, chatApi: chat }))
vi.mock('@/lib/api/feedback', () => ({ feedbackApi: api }))
vi.mock('@/lib/api/chat', () => ({ chatApi: chat }))
vi.mock('sonner', () => ({ toast: notices }))
vi.mock('@/i18n/navigation', () => ({
  Link: ({ children, ...props }: React.AnchorHTMLAttributes<HTMLAnchorElement>) => <a {...props}>{children}</a>,
  useRouter: () => ({ push: vi.fn() }),
}))
vi.mock('@/components/app-frame', () => ({
  AppFrame: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))
vi.mock('@/components/ui/page-title-icon', () => ({ PageTitleIcon: () => null }))
vi.mock('@/components/ui/file-type-icon', () => ({ FileTypeIcon: () => null }))
vi.mock('@/store/document-view', () => ({ useDocumentView: () => ({ openDocument: vi.fn() }) }))
vi.mock('@/components/ui/search-input', () => ({
  SearchInput: ({ value, onValueChange }: { value: string; onValueChange: (value: string) => void }) => (
    <input value={value} onInput={(event) => onValueChange(event.currentTarget.value)} />
  ),
}))
import FeedbackTriagePage from './page-client'

const session = {
  token: { access_token: 'token-a', token_type: 'bearer', expires_in: 3600 },
  user: { id: 'user-a', email: 'a@example.org', username: 'A', is_active: true, created_at: '2026-11-05T00:00:00Z' },
}
function feedback(id: string): MessageFeedbackEnriched {
  return {
    id,
    tenant_id: 'tenant-a',
    account_id: 'user-a',
    conversation_id: `conversation-${id}`,
    message_id: `message-${id}`,
    rating: 2,
    reason: `issue-${id}`,
    expected_answer: '',
    tags: [],
    extra: {},
    conversation_title: `question-${id}`,
    message_content: `answer-${id}`,
    created_at: '2026-11-05T00:00:00Z',
    updated_at: '2026-11-05T00:00:00Z',
  }
}
function pending<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((yes) => {
    resolve = yes
  })
  return { promise, resolve }
}
const cleanups: Array<() => void> = []
function renderPage() {
  const host = document.createElement('div')
  document.body.append(host)
  const root = createRoot(host)
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  act(() =>
    root.render(
      <QueryClientProvider client={client}>
        <FeedbackTriagePage />
      </QueryClientProvider>,
    ),
  )
  cleanups.push(() => {
    act(() => root.unmount())
    client.clear()
    host.remove()
  })
  return { host, client }
}
function button(host: HTMLElement, text: string) {
  const found = Array.from(host.querySelectorAll<HTMLButtonElement>('button')).find(
    (node) => node.getAttribute('aria-label') === text || node.textContent?.trim() === text,
  )
  expect(found, text).toBeDefined()
  return found!
}
async function ready(host: HTMLElement) {
  await act(async () => vi.waitFor(() => expect(host.querySelector('[data-feedback-item]')).not.toBeNull()))
}
async function click(host: HTMLElement, text: string) {
  await act(async () => button(host, text).click())
}
beforeEach(() => {
  ;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  vi.resetAllMocks()
  localStorage.clear()
  sessionStorage.clear()
  setAuthSession(session)
  api.listEnriched.mockResolvedValue({ total: 2, items: [feedback('A'), feedback('B')] })
  api.toRegressionCase.mockResolvedValue({ id: 'case-A' })
  api.update.mockImplementation(async (id: string) => feedback(id))
  chat.getMessages.mockResolvedValue({ messages: [] })
})
afterEach(() => cleanups.splice(0).forEach((cleanup) => cleanup()))

describe('feedback reader request ownership', () => {
  it('submits one case for two synchronous clicks in the inline reader', async () => {
    const first = pending<{ id: string }>()
    api.toRegressionCase.mockReturnValue(first.promise)
    const { host } = renderPage()
    await ready(host)
    await act(async () => {
      button(host, '创建回归用例').click()
      button(host, '创建回归用例').click()
    })
    expect(api.toRegressionCase).toHaveBeenCalledTimes(1)
    await act(async () => first.resolve({ id: 'case-A' }))
  })
  it('keeps an accepted A result on A while B has its own pending request', async () => {
    const first = pending<{ id: string }>(),
      second = pending<{ id: string }>()
    api.toRegressionCase.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise)
    const { host } = renderPage()
    await ready(host)
    await click(host, '创建回归用例')
    await click(host, '下一条反馈')
    await click(host, '创建回归用例')
    await act(async () => first.resolve({ id: 'case-A' }))
    expect(host.querySelector('a[title="用例 case-A"]')).toBeNull()
    expect(button(host, '正在创建…').disabled).toBe(true)
    expect(notices.success).not.toHaveBeenCalled()
    await act(async () => second.resolve({ id: 'case-B' }))
    expect(host.querySelector('a[title="用例 case-B"]')).not.toBeNull()
  })
  it('retires a same-account replacement and accepts an ordinary access-token refresh', async () => {
    const first = pending<{ id: string }>()
    api.toRegressionCase.mockReturnValueOnce(first.promise)
    const { host } = renderPage()
    await ready(host)
    await click(host, '创建回归用例')
    setAuthSession(session)
    await act(async () => first.resolve({ id: 'retired-case' }))
    expect(host.querySelector('a[title="用例 retired-case"]')).toBeNull()
    expect(notices.success).not.toHaveBeenCalled()
    expect(button(host, '创建回归用例').disabled).toBe(false)
    const second = pending<{ id: string }>()
    api.toRegressionCase.mockReturnValueOnce(second.promise)
    await click(host, '创建回归用例')
    setAccessToken({ access_token: 'refreshed', token_type: 'bearer', expires_in: 3600 })
    await act(async () => second.resolve({ id: 'current-case' }))
    expect(host.querySelector('a[title="用例 current-case"]')).not.toBeNull()
  })
  it('refreshes the original exhaustive feedback query while preserving a newer local filter', async () => {
    const response = pending<MessageFeedbackEnriched>()
    api.update.mockReturnValueOnce(response.promise)
    const { host, client } = renderPage()
    await ready(host)
    await click(host, '归档反馈')
    const search = host.querySelector('input')!
    await act(async () => {
      search.value = 'question-B'
      search.dispatchEvent(new Event('input', { bubbles: true }))
    })
    const count = api.listEnriched.mock.calls.length
    await act(async () => {
      response.resolve(feedback('A'))
      await vi.waitFor(() => expect(api.listEnriched).toHaveBeenCalledTimes(count + 1))
    })
    expect(client.getQueryState(['feedback-enriched'])?.status).toBe('success')
    expect(search.value).toBe('question-B')
    expect(host.querySelectorAll('[data-feedback-item]')).toHaveLength(1)
    expect(host.querySelector('[data-feedback-reader]')?.textContent).toContain('answer-B')
  })
  it('shows a primary query failure instead of an empty queue', async () => {
    api.listEnriched.mockRejectedValueOnce(new Error('feedback unavailable'))
    const { host } = renderPage()
    await act(async () =>
      vi.waitFor(() => expect(host.querySelector('[role="alert"]')?.textContent).toContain('feedback unavailable')),
    )
  })
})
