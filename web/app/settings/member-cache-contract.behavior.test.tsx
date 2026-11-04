// @vitest-environment happy-dom

import React, { act } from 'react'
import { createRoot } from 'react-dom/client'
import { useQueryClient, type QueryClient } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { TenantMemberListResponse } from '@/lib/api/access'
import { waitForAssertion } from '@/test/hook-harness'

const api = vi.hoisted(() => ({
  members: vi.fn(),
  access: vi.fn(),
  role: vi.fn(),
  remove: vi.fn(),
  preview: vi.fn(),
  status: vi.fn(),
  success: vi.fn(),
  error: vi.fn(),
}))
vi.hoisted(() => vi.stubGlobal('BroadcastChannel', undefined))
vi.mock('@/lib/api/access', () => ({
  rbacApi: {
    listTenantMembers: api.members,
    getCurrentTenantAccess: api.access,
    patchTenantMemberRole: api.role,
    removeTenantMember: api.remove,
  },
}))
vi.mock('@/lib/api', () => ({
  rbacApi: {
    listTenantMembers: api.members,
    getCurrentTenantAccess: api.access,
    patchTenantMemberRole: api.role,
    removeTenantMember: api.remove,
  },
}))
vi.mock('@/lib/api/rtbf', () => ({ rtbfApi: { request: api.preview, getStatus: api.status } }))
vi.mock('@/components/settings/governance-ops-panel', () => ({ GovernanceOpsPanel: () => null }))
vi.mock('@/components/settings/saml-ops-panel', () => ({ SamlOpsPanel: () => null }))
vi.mock('@/components/settings/scim-provisioning-panel', () => ({ ScimProvisioningPanel: () => null }))
vi.mock('sonner', () => ({ toast: { success: api.success, error: api.error } }))
vi.mock('next-intl', () => ({ useTranslations: () => (key: string) => key }))
vi.mock('@/components/auth/tenant-permission-gate', () => ({
  TenantPermissionGate: ({ children }: React.PropsWithChildren) => <>{children}</>,
}))
vi.mock('@/components/app-frame', () => ({ AppFrame: ({ children }: React.PropsWithChildren) => <>{children}</> }))
vi.mock('@/components/ui/page-scaffold', () => ({
  PageScaffold: ({
    title,
    top,
    actions,
    children,
  }: React.PropsWithChildren<{ title: string; top?: React.ReactNode; actions?: React.ReactNode }>) => (
    <main>
      <h1>{title}</h1>
      {top}
      {actions}
      {children}
    </main>
  ),
}))

import { QueryProvider } from '@/components/providers/query-provider'
import { setAuthSession } from '@/lib/auth-storage'
import { queryKeys } from '@/lib/query-keys'
import { GovernanceSection } from './_sections/governance-section'
import RbacPage from './rbac/page'

type Mode = 'rtbf' | 'rbac' | 'rtbf-rbac' | 'rbac-rtbf'
const SELF = 'self@example.com'
const OTHER = 'operator@example.com'
const cleanup: Array<() => void> = []
let snapshot: TenantMemberListResponse

class ConsumerBoundary extends React.Component<React.PropsWithChildren, { error: Error | null }> {
  override state: { error: Error | null } = { error: null }
  static getDerivedStateFromError(error: Error) {
    return { error }
  }
  override render() {
    return this.state.error ? <div data-cache-contract-error>{this.state.error.message}</div> : this.props.children
  }
}

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((res) => {
    resolve = res
  })
  return { promise, resolve }
}

function mount(initial: Mode) {
  let mode = initial
  let client!: QueryClient
  const errors: unknown[] = []
  const container = document.createElement('div')
  document.body.appendChild(container)
  const root = createRoot(container, {
    onCaughtError: (error) => {
      errors.push(error)
    },
  })
  function Screen() {
    client = useQueryClient()
    const rtbf = (
      <section key="rtbf" data-member-view="rtbf">
        <ConsumerBoundary>
          <GovernanceSection
            isGovernanceEnabled
            isPiiAnonymizeEnabled
            isSecretsRedactEnabled
            isQuarantineOnDropEnabled
            updateGovernance={() => {}}
          />
        </ConsumerBoundary>
      </section>
    )
    const rbac = (
      <section key="rbac" data-member-view="rbac">
        <ConsumerBoundary>
          <RbacPage />
        </ConsumerBoundary>
      </section>
    )
    switch (mode) {
      case 'rtbf':
        return rtbf
      case 'rbac':
        return rbac
      case 'rtbf-rbac':
        return (
          <>
            {rtbf}
            {rbac}
          </>
        )
      case 'rbac-rtbf':
        return (
          <>
            {rbac}
            {rtbf}
          </>
        )
    }
  }
  const render = () =>
    act(() =>
      root.render(
        <QueryProvider>
          <Screen />
        </QueryProvider>,
      ),
    )
  render()
  cleanup.push(() => {
    act(() => root.unmount())
    client.clear()
    container.remove()
  })
  return {
    container,
    client,
    errors,
    navigate(next: Mode) {
      mode = next
      render()
    },
  }
}

function diagnostic(view: ReturnType<typeof mount>) {
  return JSON.stringify({
    cache: view.client.getQueryData(queryKeys.rbac.members({ limit: 500 })),
    errors: view.errors.map(String),
    reads: api.members.mock.calls.length,
  })
}

function button(scope: ParentNode, label: string) {
  const found = [...scope.querySelectorAll<HTMLButtonElement>('button')].find(
    (item) => item.textContent?.trim() === label,
  )
  expect(found, label).toBeDefined()
  return found!
}

function click(target: HTMLElement) {
  act(() => target.click())
}

async function readReady(view: ReturnType<typeof mount>) {
  await waitForAssertion(() =>
    expect(view.client.getQueryState(queryKeys.rbac.members({ limit: 500 }))?.status).toBe('success'),
  )
}

async function rbacReady(view: ReturnType<typeof mount>) {
  await waitForAssertion(() => {
    expect(view.errors.map(String), diagnostic(view)).toEqual([])
    expect(
      view.container.querySelector('[data-member-view="rbac"] [title="operator@example.com"]'),
      diagnostic(view),
    ).not.toBeNull()
  })
}

async function chooseRtbfMember(view: ReturnType<typeof mount>) {
  const scope = view.container.querySelector<HTMLElement>('[data-member-view="rtbf"]')!
  await waitForAssertion(() => {
    expect(view.errors.map(String), diagnostic(view)).toEqual([])
    expect(scope.querySelector('[data-testid="danger-zone-panel"]'), diagnostic(view)).not.toBeNull()
  })
  const details = scope.querySelector<HTMLDetailsElement>('[data-testid="danger-zone-panel"]')!
  if (!details.open) click(details.querySelector('summary')!)
  const trigger = details.querySelector<HTMLButtonElement>('[role="combobox"]')!
  act(() => trigger.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true })))
  let option: HTMLElement | undefined
  await waitForAssertion(() => {
    option = [...document.querySelectorAll<HTMLElement>('[role="option"]')].find(
      (item) => item.textContent?.trim() === 'operator · example.com',
    )
    expect(
      option,
      JSON.stringify({
        state: diagnostic(view),
        options: [...document.querySelectorAll('[role="option"]')].map((item) => item.textContent),
      }),
    ).toBeDefined()
  })
  click(option!)
  await waitForAssertion(() => expect(details.textContent).toContain(`将提交：${OTHER}`))
  return details
}

function canonicalCache(view: ReturnType<typeof mount>) {
  expect(view.client.getQueryData(queryKeys.rbac.members({ limit: 500 })), diagnostic(view)).toEqual(snapshot)
  expect(api.members).toHaveBeenCalledWith({ limit: 500 })
}

beforeEach(() => {
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  vi.resetAllMocks()
  HTMLElement.prototype.scrollIntoView = vi.fn()
  localStorage.clear()
  sessionStorage.clear()
  setAuthSession({
    token: { access_token: 'member-cache-token', token_type: 'bearer', expires_in: 3600 },
    user: { id: SELF, username: 'self', email: SELF, is_active: true, created_at: '2026-11-05T00:00:00Z' },
  })
  snapshot = {
    total: 2,
    items: [
      {
        id: '11111111-1111-4111-8111-111111111111',
        tenant_id: '33333333-3333-4333-8333-333333333333',
        user_id: SELF,
        role: 'owner',
        is_active: true,
        is_current: true,
      },
      {
        id: '22222222-2222-4222-8222-222222222222',
        tenant_id: '33333333-3333-4333-8333-333333333333',
        user_id: OTHER,
        role: 'editor',
        is_active: true,
        is_current: false,
      },
    ],
  }
  api.members.mockImplementation(async () => snapshot)
  api.access.mockResolvedValue({
    tenant_id: '33333333-3333-4333-8333-333333333333',
    account_id: SELF,
    role: 'owner',
    permissions: ['settings:read', 'settings:write', 'lifecycle:manage'],
    is_active: true,
    is_current: true,
    navigation_user_visible_modules: [],
  })
  api.preview.mockImplementation(async (payload: { subject_account_id: string }) => ({
    subject_account_id: payload.subject_account_id,
    ticket_id: 'preview-ticket',
    dry_run: true,
    eligible: 0,
    deleted: 0,
    errors: 0,
    documents: [],
  }))
})

afterEach(() => {
  cleanup
    .splice(0)
    .reverse()
    .forEach((dispose) => dispose())
})

describe('one canonical members DTO for RTBF and RBAC', () => {
  it('keeps standalone RTBF member labels and the original preview body', async () => {
    const view = mount('rtbf')
    await readReady(view)
    const details = await chooseRtbfMember(view)
    click(button(details, '开始安全预演'))
    await waitForAssertion(() =>
      expect(api.preview).toHaveBeenCalledWith({
        subject_account_id: OTHER,
        dry_run: true,
        max_docs: 100,
        max_retries: 1,
      }),
    )
    expect(api.members).toHaveBeenCalledTimes(1)
  })

  it('supports RTBF then RBAC without a second members read', async () => {
    const view = mount('rtbf')
    await readReady(view)
    await chooseRtbfMember(view)
    view.navigate('rbac')
    await rbacReady(view)
    canonicalCache(view)
    expect(api.members).toHaveBeenCalledTimes(1)
  })

  it('supports RBAC then RTBF without a render error or second members read', async () => {
    const view = mount('rbac')
    await rbacReady(view)
    view.navigate('rtbf')
    await chooseRtbfMember(view)
    canonicalCache(view)
    expect(api.members).toHaveBeenCalledTimes(1)
  })

  it.each(['rtbf-rbac', 'rbac-rtbf'] as const)('supports simultaneous observation in order %s', async (mode) => {
    const pending = deferred<TenantMemberListResponse>()
    api.members.mockReturnValue(pending.promise)
    const view = mount(mode)
    await waitForAssertion(() => expect(api.members).toHaveBeenCalledTimes(1))
    expect(
      view.client
        .getQueryCache()
        .find({ queryKey: queryKeys.rbac.members({ limit: 500 }), exact: true })
        ?.getObserversCount(),
    ).toBe(2)
    await act(async () => pending.resolve(snapshot))
    await rbacReady(view)
    await chooseRtbfMember(view)
    canonicalCache(view)
    expect(api.members).toHaveBeenCalledTimes(1)
  })

  it('keeps the raw DTO after a role write and lets both views read the updated member', async () => {
    api.role.mockImplementation(async (uid: string, payload: { role: string }) => {
      const updated = { ...snapshot.items!.find((member) => member.user_id === uid)!, role: payload.role }
      snapshot = { ...snapshot, items: snapshot.items!.map((member) => (member.user_id === uid ? updated : member)) }
      return updated
    })
    const view = mount('rbac-rtbf')
    await readReady(view)
    await rbacReady(view)
    const scope = view.container.querySelector('[data-member-view="rbac"]')!
    const row = [...scope.querySelectorAll<HTMLTableRowElement>('tbody tr')].find((item) =>
      item.querySelector(`[title="${OTHER}"]`),
    )!
    const trigger = row.querySelector<HTMLButtonElement>('[role="combobox"]')!
    act(() => trigger.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true })))
    click(
      [...document.querySelectorAll<HTMLElement>('[role="option"]')].find(
        (item) => item.textContent?.trim() === '管理员',
      )!,
    )
    click(button(row, '保存'))
    await waitForAssertion(() => expect(api.role).toHaveBeenCalledWith(OTHER, { role: 'admin' }))
    await waitForAssertion(() =>
      expect(
        view.client
          .getQueryData<TenantMemberListResponse>(queryKeys.rbac.members({ limit: 500 }))
          ?.items?.find((member) => member.user_id === OTHER)?.role,
      ).toBe('admin'),
    )
    await waitForAssertion(() => expect(api.members).toHaveBeenCalledTimes(2))
    const details = await chooseRtbfMember(view)
    click(button(details, '开始安全预演'))
    await waitForAssertion(() =>
      expect(api.preview).toHaveBeenCalledWith({
        subject_account_id: OTHER,
        dry_run: true,
        max_docs: 100,
        max_retries: 1,
      }),
    )
    canonicalCache(view)
    expect(view.errors).toEqual([])
  })

  it('preserves an empty DTO with optional items instead of caching a projected array', async () => {
    snapshot = { total: 0 }
    const view = mount('rbac-rtbf')
    await readReady(view)
    await waitForAssertion(() => expect(view.errors.map(String), diagnostic(view)).toEqual([]))
    canonicalCache(view)
    expect(view.container.querySelector('[data-member-view="rbac"]')?.textContent).toContain('暂无成员')
    expect(api.members).toHaveBeenCalledTimes(1)
  })
})
