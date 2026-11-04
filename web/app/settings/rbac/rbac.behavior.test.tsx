// @vitest-environment happy-dom

import React, { act } from 'react'
import { createRoot } from 'react-dom/client'
import { useQueryClient, type QueryClient } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { TenantMember } from '@/lib/api/access'
import { waitForAssertion } from '@/test/hook-harness'

const boundary = vi.hoisted(() => ({
  list: vi.fn(),
  patch: vi.fn(),
  remove: vi.fn(),
  success: vi.fn(),
  error: vi.fn(),
}))
vi.hoisted(() => vi.stubGlobal('BroadcastChannel', undefined))
vi.mock('@/lib/api', () => ({
  rbacApi: {
    listTenantMembers: boundary.list,
    patchTenantMemberRole: boundary.patch,
    removeTenantMember: boundary.remove,
  },
}))
vi.mock('sonner', () => ({ toast: { success: boundary.success, error: boundary.error } }))
vi.mock('next-intl', () => ({ useTranslations: () => (key: string) => key }))
vi.mock('@/hooks/use-tenant-access', () => ({ useTenantAccess: () => ({ data: { account_id: 'self@example.com' } }) }))
vi.mock('@/components/auth/tenant-permission-gate', () => ({
  TenantPermissionGate: ({ children }: React.PropsWithChildren) => <>{children}</>,
}))
vi.mock('@/components/app-frame', () => ({ AppFrame: ({ children }: React.PropsWithChildren) => <>{children}</> }))
vi.mock('@/components/settings/saml-ops-panel', () => ({ SamlOpsPanel: () => null }))
vi.mock('@/components/settings/scim-provisioning-panel', () => ({ ScimProvisioningPanel: () => null }))
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
import { setAccessToken, setAuthSession } from '@/lib/auth-storage'
import { queryKeys } from '@/lib/query-keys'
import RbacPage from './page'

const A = 'alpha@example.com'
const B = 'beta@example.com'
const cleanup: Array<() => void> = []
let members: TenantMember[]

function member(userId: string, role = 'viewer', isCurrent = false): TenantMember {
  return {
    id: userId,
    tenant_id: '33333333-3333-4333-8333-333333333333',
    user_id: userId,
    role,
    is_active: true,
    is_current: isCurrent,
  }
}

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (error: Error) => void
  const promise = new Promise<T>((res, rej) => {
    resolve = res
    reject = rej
  })
  return { promise, resolve, reject }
}

function login(id: string) {
  setAuthSession({
    token: { access_token: 'rbac-token', token_type: 'bearer', expires_in: 3600 },
    user: { id, username: id, email: `${id}@example.com`, is_active: true, created_at: '2026-11-05T00:00:00Z' },
  })
}

function mount() {
  const container = document.createElement('div')
  document.body.appendChild(container)
  const root = createRoot(container)
  let client!: QueryClient
  let mounted = true
  function Probe() {
    client = useQueryClient()
    return <RbacPage />
  }
  const render = () =>
    act(() =>
      root.render(
        <QueryProvider>
          <Probe />
        </QueryProvider>,
      ),
    )
  const unmount = () => {
    if (!mounted) return
    act(() => root.unmount())
    client.clear()
    container.remove()
    mounted = false
  }
  render()
  cleanup.push(unmount)
  return { container, client, render, unmount }
}

function row(container: ParentNode, userId = A) {
  const result = [...container.querySelectorAll<HTMLTableRowElement>('tbody tr')].find((item) =>
    item.querySelector(`[title="${userId}"]`),
  )
  expect(result, userId).toBeDefined()
  return result!
}

function button(scope: ParentNode, text: string) {
  const result = [...scope.querySelectorAll<HTMLButtonElement>('button')].find(
    (item) => item.textContent?.trim() === text,
  )
  expect(result, text).toBeDefined()
  return result!
}

function click(target: HTMLElement) {
  act(() => target.click())
}

function chooseRole(container: ParentNode, userId: string, label: string) {
  const trigger = row(container, userId).querySelector<HTMLButtonElement>('button[role="combobox"]')!
  act(() => trigger.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true })))
  const option = [...document.querySelectorAll<HTMLElement>('[role="option"]')].find(
    (item) => item.textContent?.trim() === label,
  )
  expect(option, label).toBeDefined()
  click(option!)
  expect(row(container, userId).querySelector('[role="combobox"]')!.textContent).toContain(label)
}

async function loaded() {
  const view = mount()
  await waitForAssertion(() => expect(view.container.textContent).toContain(A))
  return view
}

beforeEach(() => {
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  HTMLElement.prototype.scrollIntoView = vi.fn()
  vi.resetAllMocks()
  localStorage.clear()
  sessionStorage.clear()
  login('rbac-user')
  members = [member(A), member(B), member('self@example.com', 'owner', true)]
  boundary.list.mockImplementation(async () => ({ items: members, total: members.length }))
  boundary.remove.mockResolvedValue({
    user_id: A,
    removed: true,
    revoked_group_memberships: 0,
    revoked_dataset_permissions: 0,
    revoked_document_permissions: 0,
  })
})

afterEach(() => {
  cleanup
    .splice(0)
    .reverse()
    .forEach((dispose) => dispose())
})

describe('RBAC member writes', () => {
  it('retains a newer role selection after the submitted role is saved', async () => {
    const pending = deferred<TenantMember>()
    boundary.patch.mockReturnValue(pending.promise)
    const view = await loaded()
    chooseRole(view.container, A, '管理员')
    click(button(row(view.container), '保存'))
    await waitForAssertion(() => expect(boundary.patch).toHaveBeenCalledWith(A, { role: 'admin' }))
    chooseRole(view.container, A, '编辑者')
    members = [member(A, 'admin'), ...members.slice(1)]
    await act(async () => pending.resolve(members[0]))
    await waitForAssertion(() => expect(boundary.success).toHaveBeenCalled())
    expect(row(view.container).querySelector('[role="combobox"]')!.textContent).toContain('编辑者')
  })

  it('starts one same-member save before the pending render', async () => {
    const pending = deferred<TenantMember>()
    boundary.patch.mockReturnValue(pending.promise)
    const view = await loaded()
    const save = button(row(view.container), '保存')
    act(() => {
      save.click()
      save.click()
    })
    await waitForAssertion(() => expect(boundary.patch).toHaveBeenCalled())
    expect(boundary.patch).toHaveBeenCalledTimes(1)
    await act(async () => pending.resolve(members[0]))
  })

  it('does not remove a member while its role save is pending', async () => {
    const pending = deferred<TenantMember>()
    boundary.patch.mockReturnValue(pending.promise)
    const view = await loaded()
    click(button(row(view.container), '保存'))
    await waitForAssertion(() => expect(boundary.patch).toHaveBeenCalled())
    const remove = row(view.container).querySelector<HTMLButtonElement>('button[aria-label="移除成员 alpha"]')!
    click(remove)
    const confirm = [...document.querySelectorAll<HTMLButtonElement>('button')].find(
      (item) => item.textContent?.trim() === '确认移除',
    )
    if (confirm) click(confirm)
    await act(async () => {
      await Promise.resolve()
    })
    expect(boundary.remove).not.toHaveBeenCalled()
    await act(async () => pending.resolve(members[0]))
  })

  it('blocks a role write in the same turn as member removal', async () => {
    const pending = deferred<{ user_id: string; removed: boolean }>()
    boundary.remove.mockReturnValue(pending.promise)
    boundary.patch.mockResolvedValue(members[0])
    const view = await loaded()
    const save = button(row(view.container), '保存')
    click(row(view.container).querySelector<HTMLButtonElement>('button[aria-label="移除成员 alpha"]')!)
    const confirm = button(document.querySelector('[role="alertdialog"]')!, '确认移除')
    act(() => {
      confirm.click()
      save.click()
    })
    await waitForAssertion(() => expect(boundary.remove).toHaveBeenCalledWith(A))
    expect(boundary.patch).not.toHaveBeenCalled()
    await act(async () => pending.resolve({ user_id: A, removed: true }))
  })

  it('allows different members to save concurrently and releases only the finished row', async () => {
    const first = deferred<TenantMember>()
    const second = deferred<TenantMember>()
    boundary.patch.mockImplementation((uid: string) => (uid === A ? first.promise : second.promise))
    const view = await loaded()
    act(() => {
      button(row(view.container, A), '保存').click()
      button(row(view.container, B), '保存').click()
    })
    await waitForAssertion(() => expect(boundary.patch).toHaveBeenCalledTimes(2))
    await act(async () => first.resolve(members[0]))
    await waitForAssertion(() => expect(button(row(view.container, A), '保存').disabled).toBe(false))
    expect(button(row(view.container, B), '保存中').disabled).toBe(true)
    await act(async () => second.resolve(members[1]))
  })

  it('preserves the role draft and the real conflict failure', async () => {
    boundary.patch.mockRejectedValue(new Error('不能降级最后一个管理员'))
    const view = await loaded()
    chooseRole(view.container, A, '编辑者')
    click(button(row(view.container), '保存'))
    await waitForAssertion(() => expect(boundary.error).toHaveBeenCalledWith('不能降级最后一个管理员'))
    expect(row(view.container).querySelector('[role="combobox"]')!.textContent).toContain('编辑者')
    expect(boundary.success).not.toHaveBeenCalled()
  })

  it('retains the existing explanation and disabled confirmation for removing oneself', async () => {
    const view = await loaded()
    click(
      row(view.container, 'self@example.com').querySelector<HTMLButtonElement>(
        'button[aria-label="不能移除当前用户"]',
      )!,
    )
    expect(document.querySelector('[role="alertdialog"]')!.textContent).toContain('不能移除当前用户')
    expect(button(document.querySelector('[role="alertdialog"]')!, '确认移除').disabled).toBe(true)
    expect(boundary.remove).not.toHaveBeenCalled()
  })

  it('ignores a prior login save result after the members cache is replaced', async () => {
    const pending = deferred<TenantMember>()
    boundary.patch.mockReturnValue(pending.promise)
    const view = await loaded()
    click(button(row(view.container), '保存'))
    await waitForAssertion(() => expect(boundary.patch).toHaveBeenCalled())
    const replacement = { items: [member(A, 'editor')], total: 1 }
    boundary.list.mockReturnValue(new Promise(() => {}))
    act(() => login('new-rbac-user'))
    act(() => view.client.setQueryData(queryKeys.rbac.members({ limit: 500 }), replacement))
    view.render()
    await act(async () => pending.resolve(member(A, 'admin')))
    await new Promise((resolve) => setTimeout(resolve, 0))
    expect(view.client.getQueryData(queryKeys.rbac.members({ limit: 500 }))).toEqual(replacement)
    expect(boundary.success).not.toHaveBeenCalled()
  })

  it('mutes a write failure after unmount', async () => {
    const pending = deferred<TenantMember>()
    boundary.patch.mockReturnValue(pending.promise)
    const view = await loaded()
    click(button(row(view.container), '保存'))
    await waitForAssertion(() => expect(boundary.patch).toHaveBeenCalled())
    view.unmount()
    await act(async () => pending.reject(new Error('late role failure')))
    expect(boundary.error).not.toHaveBeenCalled()
  })

  it('does not apply an old removal to the replacement login members', async () => {
    const pending = deferred<{ user_id: string; removed: boolean }>()
    boundary.remove.mockReturnValue(pending.promise)
    const view = await loaded()
    click(row(view.container).querySelector<HTMLButtonElement>('button[aria-label="移除成员 alpha"]')!)
    click(button(document.querySelector('[role="alertdialog"]')!, '确认移除'))
    await waitForAssertion(() => expect(boundary.remove).toHaveBeenCalledWith(A))
    const replacement = { items: [member(A, 'editor')], total: 1 }
    boundary.list.mockReturnValue(new Promise(() => {}))
    act(() => login('replacement-member-session'))
    act(() => view.client.setQueryData(queryKeys.rbac.members({ limit: 500 }), replacement))
    view.render()
    await act(async () => pending.resolve({ user_id: A, removed: true }))
    expect(view.client.getQueryData(queryKeys.rbac.members({ limit: 500 }))).toEqual(replacement)
    expect(boundary.success).not.toHaveBeenCalled()
  })

  it('retires a role response when the members Query is removed and rebuilt', async () => {
    const pending = deferred<TenantMember>()
    boundary.patch.mockReturnValue(pending.promise)
    const view = await loaded()
    click(button(row(view.container), '保存'))
    await waitForAssertion(() => expect(boundary.patch).toHaveBeenCalled())
    const replacement = { items: [member(A, 'editor')], total: 1 }
    boundary.list.mockReturnValue(new Promise(() => {}))
    act(() => {
      view.client.clear()
      view.client.setQueryData(queryKeys.rbac.members({ limit: 500 }), replacement)
    })
    view.render()
    await act(async () => pending.resolve(member(A, 'admin')))
    expect(view.client.getQueryData(queryKeys.rbac.members({ limit: 500 }))).toEqual(replacement)
    expect(boundary.success).not.toHaveBeenCalled()
  })

  it('does not toast a members load failure after leaving the page', async () => {
    const pending = deferred<never>()
    boundary.list.mockReturnValue(pending.promise)
    const view = mount()
    await waitForAssertion(() => expect(boundary.list).toHaveBeenCalled())
    view.unmount()
    await act(async () => pending.reject(new Error('late members failure')))
    expect(boundary.error).not.toHaveBeenCalled()
  })

  it('keeps an ordinary role selection across token rotation and can save after idle clear', async () => {
    boundary.patch.mockImplementation(async (uid: string, payload: { role: string }) => {
      const updated = member(uid, payload.role)
      members = members.map((item) => (item.user_id === uid ? updated : item))
      return updated
    })
    const view = await loaded()
    chooseRole(view.container, A, '管理员')
    act(() => setAccessToken({ access_token: 'rotated-rbac-token', token_type: 'bearer', expires_in: 3600 }))
    view.render()
    expect(row(view.container).querySelector('[role="combobox"]')!.textContent).toContain('管理员')
    act(() => view.client.clear())
    click(button(row(view.container), '保存'))
    await waitForAssertion(() => expect(boundary.patch).toHaveBeenCalledWith(A, { role: 'admin' }))
    await waitForAssertion(() => expect(boundary.success).toHaveBeenCalled())
    expect(boundary.list).toHaveBeenLastCalledWith({ limit: 500 })
  })
})
