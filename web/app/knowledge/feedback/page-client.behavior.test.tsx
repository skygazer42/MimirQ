// @vitest-environment happy-dom

import React, { act } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { setAccessToken, setAuthSession } from '@/lib/auth-storage'
import type { MessageFeedbackEnriched } from '@/types/feedback'
import type { RegressionCase } from '@/types/evaluation'

const route = vi.hoisted(() => ({ pathname: '/knowledge/feedback', search: '' }))
const api = vi.hoisted(() => ({
  listEnriched: vi.fn(),
  loopCandidates: vi.fn(),
  toRegressionCase: vi.fn(),
  update: vi.fn(),
}))
const notices = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }))
const router = vi.hoisted(() => ({ push: vi.fn(), replace: vi.fn() }))
vi.mock('@/lib/api', () => ({ feedbackApi: api }))
vi.mock('@/lib/api/feedback', () => ({ feedbackApi: api }))

vi.mock('sonner', () => ({ toast: notices }))
vi.mock('next-intl', () => ({ useTranslations: () => (key: string) => key }))
vi.mock('next/navigation', () => ({ useSearchParams: () => new URLSearchParams(route.search) }))
vi.mock('@/i18n/navigation', () => ({ usePathname: () => route.pathname, useRouter: () => router }))
vi.mock('@/components/app-frame', () => ({
  AppFrame: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}))
vi.mock('@/components/ui/page-scaffold', () => ({
  PageScaffold: ({ top, children }: { top?: React.ReactNode; children: React.ReactNode }) => (
    <div>
      {top}
      {children}
    </div>
  ),
}))
vi.mock('@/components/ui/page-title-icon', () => ({ PageTitleIcon: () => null }))
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
      <div data-detail="true">
        <button onClick={() => onOpenChange(false)}>close detail</button>
        {children}
      </div>
    ) : null,
  DialogContent: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  DialogHeader: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  DialogTitle: ({ children }: { children: React.ReactNode }) => <h2>{children}</h2>,
}))
vi.mock('@/components/ui/dropdown-menu', () => ({
  DropdownMenu: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  DropdownMenuTrigger: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  DropdownMenuContent: () => null,
  DropdownMenuItem: () => null,
  DropdownMenuSeparator: () => null,
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

import FeedbackTriagePage from './page-client'

const session = {
  token: { access_token: 'token-a', token_type: 'bearer', expires_in: 3600 },
  user: { id: 'user-a', email: 'a@example.org', username: 'A', is_active: true, created_at: '2026-11-05T00:00:00Z' },
}
function feedback(id: string): MessageFeedbackEnriched {
  return {
    id,
    tenant_id: 'tenant-1',
    conversation_id: `conversation-${id}`,
    message_id: `message-${id}`,
    account_id: 'user-a',
    rating: 1,
    tags: [],
    reason: `${id} issue`,
    conversation_title: `${id} conversation`,
    message_content: `${id} answer`,
    created_at: '2026-11-05T00:00:00Z',
    updated_at: '2026-11-05T00:00:00Z',
  }
}
function caseDto(id: string): RegressionCase {
  return {
    id,
    tenant_id: 'tenant-1',
    document_ids: [],
    question: 'Original question',
    reference_sources: [],
    tags: [],
    extra: {},
    created_at: '2026-11-05T00:00:00Z',
    updated_at: '2026-11-05T00:00:00Z',
  }
}
function pending() {
  let resolve!: (value: RegressionCase) => void
  const promise = new Promise<RegressionCase>((yes) => {
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
function buttons(host: HTMLElement, text: string) {
  return Array.from(host.querySelectorAll('button')).filter((item) => item.textContent?.trim() === text)
}
async function openDetail(host: HTMLElement, index = 0) {
  await act(async () => {
    await vi.waitFor(() => expect(buttons(host, '查看详情').length).toBeGreaterThan(index))
    buttons(host, '查看详情')[index]!.click()
  })
}
beforeEach(() => {
  ;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  window.localStorage.clear()
  window.sessionStorage.clear()
  setAuthSession(session)
  route.pathname = '/knowledge/feedback'
  route.search = ''
  api.listEnriched.mockResolvedValue({ total: 2, items: [feedback('A'), feedback('B')] })
  api.loopCandidates.mockResolvedValue({
    schema: 'feedback-loop.v1',
    summary: {},
    hard_negative_records: [],
    training_triples: [],
    eval_case_candidates: [],
    rules_suggestions: {},
  })
  api.toRegressionCase.mockResolvedValue(caseDto('case-A'))
  api.update.mockImplementation(async (id: string) => feedback(id))
})
afterEach(() => {
  cleanups.splice(0).forEach((cleanup) => cleanup())
  vi.resetAllMocks()
})

describe('feedback triage ownership', () => {
  it('keeps regression generation in a demo detail local to the demo', async () => {
    route.pathname = '/demo/knowledge/feedback'
    route.search = 'demo=1'
    const { host } = renderPage()
    await openDetail(host)
    await act(async () => buttons(host, '生成回归用例')[0]!.click())
    expect(api.toRegressionCase).not.toHaveBeenCalled()
    expect(notices.success).toHaveBeenCalledWith('Demo 模式仅用于预览反馈分析布局，不写入真实回归用例')
  })
  it('submits one case for two synchronous detail clicks', async () => {
    const first = pending()
    api.toRegressionCase.mockReturnValue(first.promise)
    const { host } = renderPage()
    await openDetail(host)
    await act(async () => {
      buttons(host, '生成回归用例')[0]!.click()
      buttons(host, '生成回归用例')[0]!.click()
    })
    expect(api.toRegressionCase).toHaveBeenCalledTimes(1)
    await act(async () => first.resolve(caseDto('case-A')))
  })
  it('does not publish an A case or release a new B request after changing detail visits', async () => {
    const first = pending()
    const second = pending()
    api.toRegressionCase.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise)
    const { host } = renderPage()
    await openDetail(host)
    await act(async () => buttons(host, '生成回归用例')[0]!.click())
    await act(async () => buttons(host, 'close detail')[0]!.click())
    await openDetail(host, 1)
    await act(async () => buttons(host, '生成回归用例')[0]!.click())
    await act(async () => first.resolve(caseDto('case-A')))
    expect(host.querySelector('[title="case_id=case-A"]')).toBeNull()
    expect(buttons(host, '生成回归用例')[0]!.disabled).toBe(true)
    expect(notices.success).not.toHaveBeenCalled()
    await act(async () => second.resolve(caseDto('case-B')))
    expect(host.querySelector('[title="case_id=case-B"]')).not.toBeNull()
    expect(buttons(host, '生成回归用例')[0]!.disabled).toBe(false)
  })
  it('retires a same-account replacement while retaining the current token refresh success', async () => {
    const first = pending()
    api.toRegressionCase.mockReturnValueOnce(first.promise)
    const { host } = renderPage()
    await openDetail(host)
    await act(async () => buttons(host, '生成回归用例')[0]!.click())
    setAuthSession(session)
    await act(async () => first.resolve(caseDto('case-A')))
    expect(host.querySelector('[title="case_id=case-A"]')).toBeNull()
    expect(notices.success).not.toHaveBeenCalled()
    expect(buttons(host, '生成回归用例')[0]!.disabled).toBe(false)
    const second = pending()
    api.toRegressionCase.mockReturnValueOnce(second.promise)
    await act(async () => buttons(host, '生成回归用例')[0]!.click())
    setAccessToken({ access_token: 'refreshed', token_type: 'bearer', expires_in: 3600 })
    await act(async () => second.resolve(caseDto('case-current')))
    expect(host.querySelector('[title="case_id=case-current"]')).not.toBeNull()
  })
  it('refreshes the original rating query when an accepted archive finishes after filtering', async () => {
    let finish!: (value: MessageFeedbackEnriched) => void
    api.update.mockReturnValueOnce(
      new Promise((resolve) => {
        finish = resolve
      }),
    )
    const { host, client } = renderPage()
    await act(async () => {
      await vi.waitFor(() => expect(buttons(host, '标记已处理')).toHaveLength(2))
      buttons(host, '标记已处理')[0]!.click()
    })
    const ratingSelect = Array.from(host.querySelectorAll('select')).find((select) =>
      Array.from(select.options).some((option) => option.value === '1'),
    )!
    await act(async () => {
      ratingSelect.value = '1'
      ratingSelect.dispatchEvent(new Event('change', { bubbles: true }))
      await vi.waitFor(() =>
        expect(client.getQueryState(['feedback-enriched', { min_rating: 1, max_rating: 1 }])?.status).toBe('success'),
      )
    })
    const before = api.listEnriched.mock.calls.filter(([params]) => params.min_rating === undefined).length
    await act(async () => {
      finish(feedback('A'))
      await vi.waitFor(() =>
        expect(api.listEnriched.mock.calls.filter(([params]) => params.min_rating === undefined)).toHaveLength(
          before + 1,
        ),
      )
    })
    expect(api.listEnriched.mock.calls.filter(([params]) => params.min_rating === 1)).toHaveLength(1)
  })
  it('shows a primary query error', async () => {
    api.listEnriched.mockRejectedValueOnce(new Error('feedback unavailable'))
    const { host } = renderPage()
    await act(async () => {
      await vi.waitFor(() =>
        expect(host.querySelector('[role="alert"]')?.textContent ?? '').toContain('feedback unavailable'),
      )
    })
  })
  it('requires the demo pathname and flag together', async () => {
    route.search = 'demo=1'
    const { host } = renderPage()
    await openDetail(host)
    await act(async () => buttons(host, '生成回归用例')[0]!.click())
    expect(api.toRegressionCase).toHaveBeenCalledWith('A', { include_document_scope: true })
  })
})
