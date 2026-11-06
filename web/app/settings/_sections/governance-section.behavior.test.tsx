// @vitest-environment happy-dom

import React, { act } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { waitForAssertion } from '@/test/hook-harness'

const api = vi.hoisted(() => ({ access: vi.fn(), members: vi.fn(), request: vi.fn(), status: vi.fn() }))
const notices = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }))
vi.hoisted(() => vi.stubGlobal('BroadcastChannel', undefined))
vi.mock('@/lib/api/access', () => ({ rbacApi: { getCurrentTenantAccess: api.access, listTenantMembers: api.members } }))
vi.mock('@/lib/api/rtbf', () => ({ rtbfApi: { request: api.request, getStatus: api.status } }))
vi.mock('@/components/settings/governance-ops-panel', () => ({ GovernanceOpsPanel: () => null }))
vi.mock('sonner', () => ({ toast: notices }))

import { setAuthSession } from '@/lib/auth-storage'
import { GovernanceSection } from './governance-section'

const cleanup: Array<() => void> = []
const token = { access_token: 'rtbf-session', token_type: 'bearer', expires_in: 3600 }
const profile = {
  id: 'account-a',
  username: 'account-a',
  email: 'rtbf@example.com',
  is_active: true,
  created_at: '2026-11-05T00:00:00Z',
}

function result() {
  return {
    subject_account_id: 'account-a',
    ticket_id: 'ticket-response',
    dry_run: true,
    eligible: 0,
    deleted: 0,
    errors: 0,
    cache_invalidations: 0,
    documents: [],
  }
}

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (error: unknown) => void
  const promise = new Promise<T>((accept, fail) => {
    resolve = accept
    reject = fail
  })
  return { promise, resolve, reject }
}

async function mount() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: 10_000, gcTime: Infinity, refetchOnWindowFocus: false } },
  })
  const container = document.createElement('div')
  document.body.appendChild(container)
  const root = createRoot(container)
  const updateGovernance = vi.fn()
  await act(async () =>
    root.render(
      <QueryClientProvider client={client}>
        <GovernanceSection
          isGovernanceEnabled
          isPiiAnonymizeEnabled
          isSecretsRedactEnabled
          isQuarantineOnDropEnabled
          updateGovernance={updateGovernance}
        />
      </QueryClientProvider>,
    ),
  )
  let mounted = true
  const unmount = () => {
    if (!mounted) return
    mounted = false
    act(() => root.unmount())
    client.clear()
    container.remove()
  }
  cleanup.push(unmount)
  await waitForAssertion(() => expect(button(container, '开始安全预演').disabled).toBe(false))
  return { container, client, unmount, updateGovernance }
}

function button(container: ParentNode, label: string) {
  const match = [...container.querySelectorAll<HTMLButtonElement>('button')].find(
    (node) =>
      node.textContent?.trim() === label ||
      node.getAttribute('aria-label') === label ||
      node.querySelector('div')?.textContent?.trim() === label,
  )
  expect(match, label).toBeDefined()
  return match!
}

function input(container: ParentNode, label: string) {
  const node = [...container.querySelectorAll('div')].find(
    (node) => node.textContent?.trim() === label && node.parentElement?.querySelector('input'),
  )
  const target = node?.querySelector('input') ?? node?.parentElement?.querySelector('input')
  expect(target, label).toBeDefined()
  return target!
}

function fill(target: HTMLInputElement, value: string) {
  act(() => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(target, value)
    target.dispatchEvent(new Event('input', { bubbles: true }))
  })
}

beforeEach(() => {
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  vi.resetAllMocks()
  localStorage.clear()
  sessionStorage.clear()
  setAuthSession({ token, user: profile })
  api.access.mockResolvedValue({
    tenant_id: 'tenant-a',
    account_id: 'account-a',
    role: 'owner',
    permissions: ['lifecycle:manage'],
    is_active: true,
    is_current: true,
  })
  api.members.mockResolvedValue({ items: [] })
  api.request.mockResolvedValue(result())
  api.status.mockImplementation(async (ticket: string) => ({
    ticket_id: ticket,
    status: 'accepted',
    note: 'RTBF status persistence is not enabled in this scaffold',
  }))
})
afterEach(() => {
  for (const dispose of cleanup.splice(0).reverse()) dispose()
  document.body.innerHTML = ''
})

describe('RTBF input and wire policy', () => {
  it('preserves allowed zero retries and the original preview/body defaults', async () => {
    const view = await mount()
    fill(input(view.container, '失败重试'), '0')
    await act(async () => button(view.container, '开始安全预演').click())

    expect(api.request).toHaveBeenCalledExactlyOnceWith({
      subject_account_id: 'account-a',
      dry_run: true,
      max_docs: 100,
      max_retries: 0,
    })
    expect(api.members).toHaveBeenCalledWith({ limit: 500 })
  })

  it.each([
    ['最多扫描文档', '12oops'],
    ['最多扫描文档', ''],
    ['最多扫描文档', '0'],
    ['最多扫描文档', '1001'],
    ['最多扫描文档', '1.2'],
    ['失败重试', '-1'],
    ['失败重试', '11'],
    ['失败重试', '0.5'],
  ])('keeps invalid %s=%s visible and does not send a destructive request', async (label, raw) => {
    const view = await mount()
    const target = input(view.container, label)
    fill(target, raw)
    await act(async () => button(view.container, '开始安全预演').click())

    expect(api.request).not.toHaveBeenCalled()
    expect(notices.error).toHaveBeenCalledOnce()
    expect(target.value).toBe(raw)
  })

  it('retains the explicit two-step delete mode and exact false/zero payload', async () => {
    const view = await mount()
    act(() => button(view.container, '执行删除').click())
    expect(api.request).not.toHaveBeenCalled()
    fill(input(view.container, '失败重试'), '0')
    await act(async () => button(view.container, '确认执行删除').click())

    expect(api.request).toHaveBeenCalledWith({
      subject_account_id: 'account-a',
      dry_run: false,
      max_docs: 100,
      max_retries: 0,
    })
  })

  it('shows the existing backend permission failure without clearing user input', async () => {
    api.request.mockRejectedValueOnce(new Error('No permission to execute RTBF deletion'))
    const view = await mount()
    const manual = view.container.querySelector<HTMLInputElement>('input[placeholder^="例如 user-123"]')!
    fill(manual, 'manual-subject')
    await act(async () => button(view.container, '开始安全预演').click())

    expect(notices.error).toHaveBeenCalledWith('No permission to execute RTBF deletion')
    expect(manual.value).toBe('manual-subject')
  })
})

describe('RTBF result lifetime', () => {
  it('does not overwrite a ticket entered while a request is pending', async () => {
    const pending = deferred<ReturnType<typeof result>>()
    api.request.mockReturnValueOnce(pending.promise)
    const view = await mount()
    act(() => button(view.container, '开始安全预演').click())
    await waitForAssertion(() => expect(api.request).toHaveBeenCalledOnce())
    const ticket = view.container.querySelector<HTMLInputElement>('input[placeholder^="提交请求后自动回填"]')!
    fill(ticket, 'ticket-entered-after-submit')
    await act(async () => pending.resolve(result()))
    await waitForAssertion(() => expect(button(view.container, '查询工单状态').disabled).toBe(false))

    expect(ticket.value).toBe('ticket-entered-after-submit')
    await act(async () => button(view.container, '查询工单状态').click())
    expect(api.status).toHaveBeenCalledWith('ticket-entered-after-submit')
  })

  it('submits only one request before the pending render is committed', async () => {
    const pending = deferred<ReturnType<typeof result>>()
    api.request.mockReturnValue(pending.promise)
    const view = await mount()
    act(() => {
      button(view.container, '开始安全预演').click()
      button(view.container, '开始安全预演').click()
    })
    expect(api.request).toHaveBeenCalledOnce()
    await act(async () => pending.resolve(result()))
  })

  it.each(['resolve', 'reject'] as const)('does not notify a request %s after leaving the owner', async (outcome) => {
    const pending = deferred<ReturnType<typeof result>>()
    api.request.mockReturnValueOnce(pending.promise)
    const view = await mount()
    act(() => button(view.container, '开始安全预演').click())
    await waitForAssertion(() => expect(api.request).toHaveBeenCalledOnce())
    view.unmount()
    await act(async () => {
      if (outcome === 'resolve') pending.resolve(result())
      else pending.reject(new Error('old request failed'))
    })
    expect(notices.success).not.toHaveBeenCalled()
    expect(notices.error).not.toHaveBeenCalled()
  })

  it('discards a response after silent same-account replacement and releases its busy flag', async () => {
    const pending = deferred<ReturnType<typeof result>>()
    api.request.mockReturnValueOnce(pending.promise)
    const view = await mount()
    act(() => button(view.container, '开始安全预演').click())
    await waitForAssertion(() => expect(api.request).toHaveBeenCalledOnce())
    act(() => setAuthSession({ token, user: profile }))
    await act(async () => pending.resolve(result()))
    await waitForAssertion(() => expect(button(view.container, '开始安全预演').disabled).toBe(false))

    expect(notices.success).not.toHaveBeenCalled()
    expect(view.container.querySelector<HTMLInputElement>('input[placeholder^="提交请求后自动回填"]')?.value).toBe('')
  })

  it('keeps explicit false governance patches and zero response metrics', async () => {
    const view = await mount()
    act(() => button(view.container, '切换数据治理开关（governance.enabled）').click())
    expect(view.updateGovernance).toHaveBeenCalledWith({ enabled: false })
    await act(async () => button(view.container, '开始安全预演').click())
    expect(view.container.querySelector('[data-testid="rtbf-result-summary"]')?.textContent).toContain(
      '命中 0 个候选文档',
    )
    expect(input(view.container, '状态查询工单').value).toBe('ticket-response')
  })
})
