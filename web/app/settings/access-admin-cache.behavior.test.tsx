// @vitest-environment happy-dom

import React, { act } from 'react'
import { createRoot } from 'react-dom/client'
import { useQueryClient, type QueryClient, type QueryKey } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { TenantGroupOut } from '@/types/backend'
import type { TenantMember } from '@/lib/api/access'
import { waitForAssertion } from '@/test/hook-harness'

const boundary = vi.hoisted(() => ({
  id: '11111111-1111-4111-8111-111111111111',
  list: vi.fn(),
  create: vi.fn(),
  get: vi.fn(),
  patch: vi.fn(),
  delete: vi.fn(),
  members: vi.fn(),
  add: vi.fn(),
  remove: vi.fn(),
  tenantList: vi.fn(),
  role: vi.fn(),
  tenantRemove: vi.fn(),
  success: vi.fn(),
  error: vi.fn(),
  message: vi.fn(),
}))
vi.hoisted(() => vi.stubGlobal('BroadcastChannel', undefined))
vi.mock('@/lib/api', () => ({
  groupApi: {
    listGroups: boundary.list,
    createGroup: boundary.create,
    getGroup: boundary.get,
    patchGroup: boundary.patch,
    deleteGroup: boundary.delete,
    listGroupMembers: boundary.members,
    addGroupMembers: boundary.add,
    removeGroupMembers: boundary.remove,
  },
  rbacApi: {
    listTenantMembers: boundary.tenantList,
    patchTenantMemberRole: boundary.role,
    removeTenantMember: boundary.tenantRemove,
  },
}))
vi.mock('next/navigation', () => ({ useParams: () => ({ id: boundary.id }) }))
vi.mock('@/i18n/navigation', () => ({ useRouter: () => ({ push: vi.fn() }) }))
vi.mock('next-intl', () => ({ useTranslations: () => (key: string) => key }))
vi.mock('sonner', () => ({ toast: { success: boundary.success, error: boundary.error, message: boundary.message } }))
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
import { GroupChipsInput } from '@/components/groups/group-chips-input'
import { setAuthSession } from '@/lib/auth-storage'
import { queryKeys } from '@/lib/query-keys'
import GroupsPage from './groups/page'
import GroupDetailPage from './groups/[id]/page'
import RbacPage from './rbac/page'

const A = '11111111-1111-4111-8111-111111111111'
const B = '22222222-2222-4222-8222-222222222222'
const C = '44444444-4444-4444-8444-444444444444'
const MEMBER = 'member@example.com'
const CREATED_AT = '2026-11-05T00:00:00Z'
const cleanup: Array<() => void> = []
let groups: TenantGroupOut[]
let groupMembers: Record<string, string[]>
let tenantMembers: TenantMember[]

function group(id: string, name: string): TenantGroupOut {
  return { id, name, external_id: null, tenant_id: '33333333-3333-4333-8333-333333333333', created_at: CREATED_AT }
}

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((res) => {
    resolve = res
  })
  return { promise, resolve }
}

function mount(initial: 'groups' | 'detail' | 'rbac' | 'selector') {
  let screen: typeof initial | 'away' = initial
  let client!: QueryClient
  const container = document.createElement('div')
  document.body.appendChild(container)
  const root = createRoot(container)
  function Screen() {
    client = useQueryClient()
    if (screen === 'groups') return <GroupsPage />
    if (screen === 'detail') return <GroupDetailPage />
    if (screen === 'rbac') return <RbacPage />
    if (screen === 'selector') return <GroupChipsInput value={[A]} onChange={() => {}} />
    return <div>其他页面</div>
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
    navigate(next: typeof screen, id?: string) {
      screen = next
      if (id) boundary.id = id
      render()
    },
  }
}

function button(scope: ParentNode, text: string) {
  const found = [...scope.querySelectorAll<HTMLButtonElement>('button')].find(
    (item) => item.textContent?.trim() === text,
  )
  expect(found, text).toBeDefined()
  return found!
}

function click(target: HTMLElement) {
  act(() => target.click())
}

function fill(id: string, value: string) {
  const input = document.getElementById(id) as HTMLInputElement | HTMLTextAreaElement
  act(() => {
    const prototype = input instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype
    Object.getOwnPropertyDescriptor(prototype, 'value')!.set!.call(input, value)
    input.dispatchEvent(new Event('input', { bubbles: true }))
  })
}

async function finish<T>(pending: ReturnType<typeof deferred<T>>, value: T) {
  await act(async () => {
    pending.resolve(value)
  })
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0))
  })
}

function cacheState(client: QueryClient, key: QueryKey) {
  const query = client.getQueryCache().find({ queryKey: key, exact: true })!
  const queryDefaults = client.getDefaultOptions().queries
  expect(queryDefaults?.staleTime).toBe(10_000)
  expect(query.options.gcTime).toBe(15 * 60_000)
  return {
    data: query.state.data,
    invalidated: query.state.isInvalidated,
    withinTenSeconds: Date.now() - query.state.dataUpdatedAt < 10_000,
    staleTime: queryDefaults?.staleTime,
    gcTime: query.options.gcTime,
  }
}

async function readyGroup(expected: string) {
  await waitForAssertion(() =>
    expect((document.getElementById('group-name') as HTMLInputElement)?.value).toBe(expected),
  )
}

function tenantRow(container: ParentNode) {
  return [...container.querySelectorAll<HTMLTableRowElement>('tbody tr')].find((row) =>
    row.textContent?.includes(MEMBER),
  )!
}

function chooseAdmin(container: ParentNode) {
  const trigger = tenantRow(container).querySelector<HTMLButtonElement>('[role="combobox"]')!
  act(() => trigger.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true })))
  click(
    [...document.querySelectorAll<HTMLElement>('[role="option"]')].find(
      (item) => item.textContent?.trim() === '管理员',
    )!,
  )
}

beforeEach(() => {
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  vi.resetAllMocks()
  HTMLElement.prototype.scrollIntoView = vi.fn()
  localStorage.clear()
  sessionStorage.clear()
  setAuthSession({
    token: { access_token: 'cache-token', token_type: 'bearer', expires_in: 3600 },
    user: {
      id: 'cache-user',
      username: 'cache-user',
      email: 'cache-user@example.com',
      is_active: true,
      created_at: CREATED_AT,
    },
  })
  boundary.id = A
  groups = [group(A, 'Alpha'), group(B, 'Beta')]
  groupMembers = { [A]: [MEMBER], [B]: [MEMBER] }
  tenantMembers = [{ id: C, tenant_id: C, user_id: MEMBER, role: 'viewer', is_active: true, is_current: false }]
  boundary.list.mockImplementation(async () => ({ items: groups.map((item) => ({ ...item })), total: groups.length }))
  boundary.get.mockImplementation(async (id: string) => ({ ...groups.find((item) => item.id === id)! }))
  boundary.members.mockImplementation(async (id: string) => ({
    items: groupMembers[id].map((user_id) => ({ user_id, created_at: CREATED_AT })),
    total: groupMembers[id].length,
  }))
  boundary.tenantList.mockImplementation(async () => ({
    items: tenantMembers.map((item) => ({ ...item })),
    total: tenantMembers.length,
  }))
})

afterEach(() => {
  cleanup
    .splice(0)
    .reverse()
    .forEach((dispose) => dispose())
})

describe('successful writes after leaving access-admin views', () => {
  it.each(['resolve while on B', 'return to A before resolution'] as const)(
    'refreshes the original group and list cache: %s',
    async (order) => {
      const pending = deferred<TenantGroupOut>()
      boundary.patch.mockReturnValue(pending.promise)
      const view = mount('groups')
      await waitForAssertion(() => expect(view.container.textContent).toContain('Alpha'))
      const listKey = queryKeys.groups.list({ limit: 500 })
      view.navigate('detail', A)
      await readyGroup('Alpha')
      const key = queryKeys.groups.detail(A)
      const origin = view.client.getQueryCache().find({ queryKey: key, exact: true })
      fill('group-name', 'Renamed Alpha')
      click(button(view.container, '保存'))
      await waitForAssertion(() =>
        expect(boundary.patch).toHaveBeenCalledWith(A, { name: 'Renamed Alpha', external_id: null }),
      )
      view.navigate('detail', B)
      await readyGroup('Beta')
      if (order === 'return to A before resolution') {
        view.navigate('detail', A)
        await waitForAssertion(() => expect(view.container.querySelector('h1')?.textContent).toBe('组：Alpha'))
      }
      groups = [group(A, 'Renamed Alpha'), groups[1]]
      await finish(pending, groups[0])
      const snapshot = cacheState(view.client, key)
      expect(view.client.getQueryCache().find({ queryKey: key, exact: true })).toBe(origin)
      expect(snapshot.withinTenSeconds).toBe(true)
      if (order === 'resolve while on B') view.navigate('detail', A)
      await waitForAssertion(() =>
        expect((document.getElementById('group-name') as HTMLInputElement).value, JSON.stringify(snapshot)).toBe(
          'Renamed Alpha',
        ),
      )
      const list = view.client.getQueryData<TenantGroupOut[]>(listKey)!
      expect(
        list.some((item) => item.name === 'Renamed Alpha') || view.client.getQueryState(listKey)?.isInvalidated,
      ).toBe(true)
    },
  )

  it('refreshes a group list after a create finishes while its page is unmounted', async () => {
    const pending = deferred<TenantGroupOut>()
    boundary.create.mockReturnValue(pending.promise)
    const view = mount('groups')
    await waitForAssertion(() => expect(view.container.textContent).toContain('Alpha'))
    click(button(view.container, '新建组'))
    fill('group-name', 'Created group')
    click(button(document.querySelector('[role="dialog"]')!, '创建'))
    await waitForAssertion(() => expect(boundary.create).toHaveBeenCalled())
    view.navigate('detail', B)
    await readyGroup('Beta')
    const created = group(C, 'Created group')
    groups = [...groups, created]
    await finish(pending, created)
    const snapshot = cacheState(view.client, queryKeys.groups.list({ limit: 500 }))
    expect(snapshot.withinTenSeconds).toBe(true)
    view.navigate('groups')
    await waitForAssertion(() =>
      expect(view.container.textContent, JSON.stringify(snapshot)).toContain('Created group'),
    )
  })

  it('refreshes a group list after a delete finishes while its page is unmounted', async () => {
    const pending = deferred<void>()
    boundary.delete.mockReturnValue(pending.promise)
    const view = mount('groups')
    await waitForAssertion(() => expect(view.container.textContent).toContain('Alpha'))
    const alpha = [...view.container.querySelectorAll<HTMLDivElement>('div.grid.grid-cols-12.items-center')].find(
      (row) => row.textContent?.includes('Alpha'),
    )!
    click(alpha.querySelector<HTMLButtonElement>('button[aria-label="删除组"]')!)
    click(button(document.querySelector('[role="alertdialog"]')!, '删除'))
    await waitForAssertion(() => expect(boundary.delete).toHaveBeenCalledWith(A))
    view.navigate('detail', B)
    await readyGroup('Beta')
    groups = groups.filter((item) => item.id !== A)
    await finish(pending, undefined)
    const snapshot = cacheState(view.client, queryKeys.groups.list({ limit: 500 }))
    expect(snapshot.withinTenSeconds).toBe(true)
    view.navigate('groups')
    await waitForAssertion(() => expect(view.container.textContent, JSON.stringify(snapshot)).not.toContain('Alpha'))
  })

  it.each(['add', 'remove'] as const)(
    'refreshes the original member list after %s finishes on another group',
    async (operation) => {
      const pending = deferred<{ updated: number }>()
      boundary[operation].mockReturnValue(pending.promise)
      const view = mount('detail')
      await readyGroup('Alpha')
      await waitForAssertion(() => expect(view.container.textContent).toContain(MEMBER))
      if (operation === 'add') {
        click(button(view.container, '添加成员'))
        fill('group-members', 'new@example.com')
        click(button(document.querySelector('[role="dialog"]')!, '添加'))
      } else {
        click(view.container.querySelector<HTMLButtonElement>(`button[aria-label="移除成员 ${MEMBER}"]`)!)
        click(button(document.querySelector('[role="alertdialog"]')!, '移除'))
      }
      await waitForAssertion(() => expect(boundary[operation]).toHaveBeenCalled())
      view.navigate('detail', B)
      await readyGroup('Beta')
      groupMembers[A] = operation === 'add' ? [MEMBER, 'new@example.com'] : []
      await finish(pending, { updated: 1 })
      const snapshot = cacheState(view.client, queryKeys.groups.members(A, { limit: 500 }))
      expect(snapshot.withinTenSeconds).toBe(true)
      view.navigate('detail', A)
      await readyGroup('Alpha')
      await waitForAssertion(() => {
        if (operation === 'add')
          expect(view.container.textContent, JSON.stringify(snapshot)).toContain('new@example.com')
        else
          expect(
            view.container.querySelector(`button[aria-label="移除成员 ${MEMBER}"]`),
            JSON.stringify(snapshot),
          ).toBeNull()
      })
    },
  )

  it.each(['save role', 'remove member'] as const)(
    'refreshes RBAC after an unmounted %s succeeds',
    async (operation) => {
      const role = deferred<TenantMember>()
      const removal = deferred<{ user_id: string; removed: boolean }>()
      boundary.role.mockReturnValue(role.promise)
      boundary.tenantRemove.mockReturnValue(removal.promise)
      const view = mount('rbac')
      await waitForAssertion(() => expect(view.container.textContent).toContain(MEMBER))
      if (operation === 'save role') {
        chooseAdmin(view.container)
        click(button(tenantRow(view.container), '保存'))
        await waitForAssertion(() => expect(boundary.role).toHaveBeenCalledWith(MEMBER, { role: 'admin' }))
      } else {
        click(tenantRow(view.container).querySelector<HTMLButtonElement>('button[aria-label="移除成员 member"]')!)
        click(button(document.querySelector('[role="alertdialog"]')!, '确认移除'))
        await waitForAssertion(() => expect(boundary.tenantRemove).toHaveBeenCalledWith(MEMBER))
      }
      view.navigate('away')
      const updated = { ...tenantMembers[0], role: 'admin' }
      tenantMembers = operation === 'save role' ? [updated] : []
      if (operation === 'save role') await finish(role, updated)
      else await finish(removal, { user_id: MEMBER, removed: true })
      const snapshot = cacheState(view.client, queryKeys.rbac.members({ limit: 500 }))
      expect(snapshot.withinTenSeconds).toBe(true)
      view.navigate('rbac')
      await waitForAssertion(() => {
        if (operation === 'save role')
          expect(
            tenantRow(view.container)?.querySelector('[role="combobox"]')?.textContent,
            JSON.stringify(snapshot),
          ).toContain('管理员')
        else expect(view.container.textContent, JSON.stringify(snapshot)).not.toContain(MEMBER)
      })
    },
  )

  it('does not overwrite a newer visit cache with an old response payload', async () => {
    const pending = deferred<TenantGroupOut>()
    boundary.patch
      .mockReturnValueOnce(pending.promise)
      .mockImplementation(async (_id: string, payload: { name: string }) => {
        groups = [group(A, payload.name), groups[1]]
        return groups[0]
      })
    const view = mount('detail')
    await readyGroup('Alpha')
    fill('group-name', 'Older saved value')
    click(button(view.container, '保存'))
    await waitForAssertion(() => expect(boundary.patch).toHaveBeenCalledTimes(1))
    view.navigate('away')
    view.navigate('detail', A)
    await readyGroup('Alpha')
    fill('group-name', 'Newest server value')
    click(button(view.container, '保存'))
    await waitForAssertion(() => expect(boundary.patch).toHaveBeenCalledTimes(2))
    await waitForAssertion(() =>
      expect(view.client.getQueryData<TenantGroupOut>(queryKeys.groups.detail(A))?.name).toBe('Newest server value'),
    )
    const publishedNames: Array<string | undefined> = []
    const unsubscribe = view.client.getQueryCache().subscribe(() => {
      publishedNames.push(view.client.getQueryData<TenantGroupOut>(queryKeys.groups.detail(A))?.name)
    })
    await finish(pending, group(A, 'Older saved value'))
    unsubscribe()
    expect(publishedNames).not.toContain('Older saved value')
    expect(view.client.getQueryData<TenantGroupOut>(queryKeys.groups.detail(A))?.name).toBe('Newest server value')
  })

  it('refreshes the real cached1000-item group selector after leaving a rename', async () => {
    const pending = deferred<TenantGroupOut>()
    boundary.patch.mockReturnValue(pending.promise)
    const view = mount('selector')
    await waitForAssertion(() => expect(view.container.textContent).toContain('Alpha'))
    expect(boundary.list).toHaveBeenCalledWith({ limit: 1000 })
    const selectorKey = queryKeys.groups.list({ limit: 1000 })
    const selectorQuery = view.client.getQueryCache().find({ queryKey: selectorKey, exact: true })
    view.navigate('detail', A)
    await readyGroup('Alpha')
    fill('group-name', 'Renamed selector label')
    click(button(view.container, '保存'))
    await waitForAssertion(() => expect(boundary.patch).toHaveBeenCalled())
    view.navigate('detail', B)
    await readyGroup('Beta')
    groups = [group(A, 'Renamed selector label'), groups[1]]
    await finish(pending, groups[0])
    const snapshot = cacheState(view.client, selectorKey)
    expect(snapshot.withinTenSeconds).toBe(true)
    expect(view.client.getQueryCache().find({ queryKey: selectorKey, exact: true })).toBe(selectorQuery)
    view.navigate('selector')
    await waitForAssertion(() =>
      expect(view.container.textContent, JSON.stringify(snapshot)).toContain('Renamed selector label'),
    )
  })

  it('keeps the new A visit draft and mute feedback while refreshing server truth', async () => {
    const pending = deferred<TenantGroupOut>()
    boundary.patch.mockReturnValue(pending.promise)
    const view = mount('detail')
    await readyGroup('Alpha')
    fill('group-name', 'Submitted Alpha')
    click(button(view.container, '保存'))
    await waitForAssertion(() => expect(boundary.patch).toHaveBeenCalled())
    view.navigate('detail', B)
    await readyGroup('Beta')
    view.navigate('detail', A)
    await waitForAssertion(() => expect(view.container.querySelector('h1')?.textContent).toBe('组：Alpha'))
    fill('group-name', 'New visit draft')
    groups = [group(A, 'Submitted Alpha'), groups[1]]
    await finish(pending, groups[0])
    await waitForAssertion(() =>
      expect(view.client.getQueryData<TenantGroupOut>(queryKeys.groups.detail(A))?.name).toBe('Submitted Alpha'),
    )
    expect((document.getElementById('group-name') as HTMLInputElement).value).toBe('New visit draft')
    expect(boundary.success).not.toHaveBeenCalled()
  })

  it('does not change B cache objects, read counts, draft or feedback after the old A success', async () => {
    const pending = deferred<TenantGroupOut>()
    boundary.patch.mockReturnValue(pending.promise)
    const view = mount('detail')
    await readyGroup('Alpha')
    fill('group-name', 'Submitted Alpha')
    click(button(view.container, '保存'))
    await waitForAssertion(() => expect(boundary.patch).toHaveBeenCalled())
    view.navigate('detail', B)
    await readyGroup('Beta')
    await waitForAssertion(() => expect(boundary.members).toHaveBeenCalledWith(B, { limit: 500 }))
    fill('group-name', 'B local draft')
    const detailKey = queryKeys.groups.detail(B)
    const membersKey = queryKeys.groups.members(B, { limit: 500 })
    await waitForAssertion(() => expect(view.client.getQueryData(membersKey)).toBeDefined())
    const detailQuery = view.client.getQueryCache().find({ queryKey: detailKey, exact: true })
    const membersQuery = view.client.getQueryCache().find({ queryKey: membersKey, exact: true })
    const detailData = view.client.getQueryData(detailKey)
    const membersData = view.client.getQueryData(membersKey)
    groups = [group(A, 'Submitted Alpha'), groups[1]]
    await finish(pending, groups[0])
    expect(view.client.getQueryCache().find({ queryKey: detailKey, exact: true })).toBe(detailQuery)
    expect(view.client.getQueryCache().find({ queryKey: membersKey, exact: true })).toBe(membersQuery)
    expect(view.client.getQueryData(detailKey)).toBe(detailData)
    expect(view.client.getQueryData(membersKey)).toBe(membersData)
    expect(boundary.get.mock.calls.filter(([id]) => id === B)).toHaveLength(1)
    expect(boundary.members.mock.calls.filter(([id]) => id === B)).toHaveLength(1)
    expect((document.getElementById('group-name') as HTMLInputElement).value).toBe('B local draft')
    expect(boundary.success).not.toHaveBeenCalled()
  })
})
