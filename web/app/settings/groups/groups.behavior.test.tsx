// @vitest-environment happy-dom

import React, { act } from 'react'
import { createRoot } from 'react-dom/client'
import { useQueryClient, type QueryClient } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { waitForAssertion } from '@/test/hook-harness'
import type { TenantGroupOut } from '@/types/backend'

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
  push: vi.fn(),
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
}))
vi.mock('next/navigation', () => ({ useParams: () => ({ id: boundary.id }) }))
vi.mock('@/i18n/navigation', () => ({ useRouter: () => ({ push: boundary.push }) }))
vi.mock('sonner', () => ({ toast: { success: boundary.success, error: boundary.error, message: boundary.message } }))
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
import { setAccessToken, setAuthSession } from '@/lib/auth-storage'
import { queryKeys } from '@/lib/query-keys'
import GroupsPage from './page'
import GroupDetailPage from './[id]/page'

const A = '11111111-1111-4111-8111-111111111111'
const B = '22222222-2222-4222-8222-222222222222'
const MEMBER = 'member@example.com'
const cleanup: Array<() => void> = []
let groups: TenantGroupOut[]

function group(id: string, name: string): TenantGroupOut {
  return {
    id,
    name,
    tenant_id: '33333333-3333-4333-8333-333333333333',
    external_id: null,
    created_at: '2026-11-05T00:00:00Z',
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
    token: { access_token: 'groups-token', token_type: 'bearer', expires_in: 3600 },
    user: { id, username: id, email: `${id}@example.com`, is_active: true, created_at: '2026-11-05T00:00:00Z' },
  })
}

function mount(Page: React.ComponentType) {
  const container = document.createElement('div')
  document.body.appendChild(container)
  const root = createRoot(container)
  let client!: QueryClient
  let mounted = true
  function Probe() {
    client = useQueryClient()
    return <Page />
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

function button(scope: ParentNode, text: string) {
  const result = [...scope.querySelectorAll<HTMLButtonElement>('button')].find(
    (item) => item.textContent?.trim() === text,
  )
  expect(result, `button ${text}`).toBeDefined()
  return result!
}

function click(target: HTMLElement) {
  act(() => target.click())
}

function fill(id: string, value: string) {
  const input = document.getElementById(id) as HTMLInputElement | HTMLTextAreaElement
  expect(input, id).not.toBeNull()
  act(() => {
    const prototype = input instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype
    Object.getOwnPropertyDescriptor(prototype, 'value')!.set!.call(input, value)
    input.dispatchEvent(new Event('input', { bubbles: true }))
  })
}

function openCreate(container: ParentNode) {
  click(button(container, '新建组'))
}

function confirmGroupDelete(container: ParentNode, name: string) {
  const row = [...container.querySelectorAll<HTMLDivElement>('div.grid.grid-cols-12.items-center')].find((item) =>
    item.textContent?.includes(name),
  )
  expect(row, name).toBeDefined()
  click(row!.querySelector<HTMLButtonElement>('button[aria-label="删除组"]')!)
  click(button(document.querySelector('[role="alertdialog"]')!, '删除'))
}

async function loadedDetail() {
  const view = mount(GroupDetailPage)
  await waitForAssertion(() => expect((document.getElementById('group-name') as HTMLInputElement)?.value).toBe('Alpha'))
  return view
}

beforeEach(() => {
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  vi.resetAllMocks()
  localStorage.clear()
  sessionStorage.clear()
  login('groups-user')
  boundary.id = A
  groups = [group(A, 'Alpha'), group(B, 'Beta')]
  boundary.list.mockImplementation(async () => ({ items: groups, total: groups.length }))
  boundary.get.mockImplementation(async (id: string) => groups.find((item) => item.id === id))
  boundary.members.mockResolvedValue({ items: [{ user_id: MEMBER, created_at: '2026-11-05T00:00:00Z' }], total: 1 })
  boundary.add.mockResolvedValue({ updated: 1 })
  boundary.remove.mockResolvedValue({ updated: 1 })
  boundary.delete.mockResolvedValue(undefined)
})

afterEach(() => {
  cleanup
    .splice(0)
    .reverse()
    .forEach((dispose) => dispose())
})

describe('group list requests and drafts', () => {
  it('creates a trimmed group and rereads the unchanged list contract', async () => {
    boundary.create.mockImplementation(async (payload: { name: string; external_id?: string }) => {
      const created = {
        ...group('44444444-4444-4444-8444-444444444444', payload.name),
        external_id: payload.external_id,
      }
      groups = [...groups, created]
      return created
    })
    const view = mount(GroupsPage)
    await waitForAssertion(() => expect(view.container.textContent).toContain('Alpha'))
    openCreate(view.container)
    fill('group-name', '  Legal  ')
    fill('group-external-id', '  directory-legal  ')
    click(button(document, '创建'))
    await waitForAssertion(() => expect(view.container.textContent).toContain('Legal'))
    expect(boundary.create).toHaveBeenCalledWith({ name: 'Legal', external_id: 'directory-legal' })
    expect(boundary.list).toHaveBeenLastCalledWith({ limit: 500 })
  })

  it('keeps a newer create draft when the submitted group succeeds', async () => {
    const pending = deferred<TenantGroupOut>()
    boundary.create.mockReturnValue(pending.promise)
    const view = mount(GroupsPage)
    await waitForAssertion(() => expect(view.container.textContent).toContain('Alpha'))
    openCreate(view.container)
    fill('group-name', 'Submitted')
    click(button(document, '创建'))
    await waitForAssertion(() => expect(boundary.create).toHaveBeenCalledTimes(1))
    fill('group-name', 'Next draft')
    await act(async () => pending.resolve(group(B, 'Submitted')))
    await waitForAssertion(() => expect(boundary.success).toHaveBeenCalled())
    expect((document.getElementById('group-name') as HTMLInputElement | null)?.value).toBe('Next draft')
  })

  it('starts one create request before the pending render', async () => {
    const pending = deferred<TenantGroupOut>()
    boundary.create.mockReturnValue(pending.promise)
    const view = mount(GroupsPage)
    await waitForAssertion(() => expect(view.container.textContent).toContain('Alpha'))
    openCreate(view.container)
    fill('group-name', 'Once')
    const create = button(document, '创建')
    act(() => {
      create.click()
      create.click()
    })
    await waitForAssertion(() => expect(boundary.create).toHaveBeenCalled())
    expect(boundary.create).toHaveBeenCalledTimes(1)
    await act(async () => pending.resolve(group(B, 'Once')))
  })

  it('keeps both pending group deletions busy independently', async () => {
    const first = deferred<void>()
    const second = deferred<void>()
    boundary.delete.mockImplementation((id: string) => (id === A ? first.promise : second.promise))
    const view = mount(GroupsPage)
    await waitForAssertion(() => expect(view.container.textContent).toContain('Alpha'))
    confirmGroupDelete(view.container, 'Alpha')
    await waitForAssertion(() => expect(boundary.delete).toHaveBeenCalledWith(A))
    confirmGroupDelete(view.container, 'Beta')
    await waitForAssertion(() => expect(boundary.delete).toHaveBeenCalledWith(B))
    const alpha = [...view.container.querySelectorAll<HTMLDivElement>('div.grid.grid-cols-12.items-center')].find(
      (row) => row.textContent?.includes('Alpha'),
    )!
    expect(alpha.querySelector<HTMLButtonElement>('button[aria-label="删除组"]')!.disabled).toBe(true)
    await act(async () => {
      first.resolve()
      second.resolve()
    })
  })

  it('does not apply an old delete result to a replacement login cache', async () => {
    const pending = deferred<void>()
    boundary.delete.mockReturnValue(pending.promise)
    const view = mount(GroupsPage)
    await waitForAssertion(() => expect(view.container.textContent).toContain('Alpha'))
    confirmGroupDelete(view.container, 'Alpha')
    await waitForAssertion(() => expect(boundary.delete).toHaveBeenCalled())
    groups = [group(A, 'Replacement login')]
    act(() => login('replacement-user'))
    view.client.setQueryData(queryKeys.groups.list({ limit: 500 }), groups)
    view.render()
    boundary.success.mockClear()
    await act(async () => pending.resolve())
    await new Promise((resolve) => setTimeout(resolve, 0))
    expect(view.client.getQueryData(queryKeys.groups.list({ limit: 500 }))).toEqual(groups)
    expect(boundary.success).not.toHaveBeenCalled()
  })

  it('mutes a list failure after the page unmounts', async () => {
    const pending = deferred<never>()
    boundary.list.mockReturnValue(pending.promise)
    const view = mount(GroupsPage)
    await waitForAssertion(() => expect(boundary.list).toHaveBeenCalled())
    view.unmount()
    await act(async () => pending.reject(new Error('late list failure')))
    expect(boundary.error).not.toHaveBeenCalled()
  })

  it('can create after an idle query cache clear', async () => {
    boundary.create.mockImplementation(async () => {
      const created = group('44444444-4444-4444-8444-444444444444', 'After clear')
      groups = [...groups, created]
      return created
    })
    const view = mount(GroupsPage)
    await waitForAssertion(() => expect(view.container.textContent).toContain('Alpha'))
    openCreate(view.container)
    fill('group-name', 'After clear')
    act(() => view.client.clear())
    click(button(document, '创建'))
    await waitForAssertion(() => expect(view.container.textContent).toContain('After clear'))
    expect(boundary.create).toHaveBeenCalledTimes(1)
  })
})

describe('group detail ownership', () => {
  it('keeps edits made while a group save is pending', async () => {
    const pending = deferred<TenantGroupOut>()
    boundary.patch.mockReturnValue(pending.promise)
    const view = await loadedDetail()
    fill('group-name', 'Submitted')
    click(button(view.container, '保存'))
    await waitForAssertion(() =>
      expect(boundary.patch).toHaveBeenCalledWith(A, { name: 'Submitted', external_id: null }),
    )
    fill('group-name', 'Newer edit')
    groups = [group(A, 'Submitted'), groups[1]]
    await act(async () => pending.resolve(groups[0]))
    await waitForAssertion(() => expect(boundary.success).toHaveBeenCalled())
    expect((document.getElementById('group-name') as HTMLInputElement).value).toBe('Newer edit')
  })

  it('keeps the failed save draft and reports the original failure', async () => {
    boundary.patch.mockRejectedValue(new Error('conflict'))
    const view = await loadedDetail()
    fill('group-name', 'Retained')
    click(button(view.container, '保存'))
    await waitForAssertion(() => expect(boundary.error).toHaveBeenCalled())
    expect((document.getElementById('group-name') as HTMLInputElement).value).toBe('Retained')
    expect(boundary.success).not.toHaveBeenCalled()
  })

  it('does not remove the same member from a newly visited group', async () => {
    const pending = deferred<{ updated: number }>()
    boundary.remove.mockReturnValue(pending.promise)
    const view = await loadedDetail()
    await waitForAssertion(() =>
      expect(view.container.querySelector(`button[aria-label="移除成员 ${MEMBER}"]`)).not.toBeNull(),
    )
    click(view.container.querySelector<HTMLButtonElement>(`button[aria-label="移除成员 ${MEMBER}"]`)!)
    click(button(document.querySelector('[role="alertdialog"]')!, '移除'))
    await waitForAssertion(() => expect(boundary.remove).toHaveBeenCalledWith(A, { member_ids: [MEMBER] }))
    boundary.id = B
    view.render()
    await waitForAssertion(() => expect((document.getElementById('group-name') as HTMLInputElement).value).toBe('Beta'))
    const key = queryKeys.groups.members(B, { limit: 500 })
    const replacement = view.client.getQueryData(key)
    boundary.members.mockReturnValue(new Promise(() => {}))
    boundary.success.mockClear()
    await act(async () => pending.resolve({ updated: 1 }))
    await new Promise((resolve) => setTimeout(resolve, 0))
    expect(view.client.getQueryData(key)).toEqual(replacement)
    expect(boundary.success).not.toHaveBeenCalled()
  })

  it('does not overwrite the next group draft with an old save result', async () => {
    const pending = deferred<TenantGroupOut>()
    boundary.patch.mockReturnValue(pending.promise)
    const view = await loadedDetail()
    fill('group-name', 'Saved Alpha')
    click(button(view.container, '保存'))
    await waitForAssertion(() => expect(boundary.patch).toHaveBeenCalled())
    boundary.id = B
    view.render()
    await waitForAssertion(() => expect((document.getElementById('group-name') as HTMLInputElement).value).toBe('Beta'))
    fill('group-name', 'Beta draft')
    await act(async () => pending.resolve(group(A, 'Saved Alpha')))
    expect((document.getElementById('group-name') as HTMLInputElement).value).toBe('Beta draft')
  })

  it('keeps new member IDs typed while an add request is pending', async () => {
    const pending = deferred<{ updated: number }>()
    boundary.add.mockReturnValue(pending.promise)
    const view = await loadedDetail()
    click(button(view.container, '添加成员'))
    fill('group-members', ' alice\nalice,bob; ')
    click(button(document.querySelector('[role="dialog"]')!, '添加'))
    await waitForAssertion(() => expect(boundary.add).toHaveBeenCalledWith(A, { member_ids: ['alice', 'bob'] }))
    fill('group-members', 'charlie')
    await act(async () => pending.resolve({ updated: 2 }))
    await waitForAssertion(() => expect(boundary.success).toHaveBeenCalled())
    expect((document.getElementById('group-members') as HTMLTextAreaElement | null)?.value).toBe('charlie')
  })

  it('keeps an ordinary edit across access-token rotation', async () => {
    const view = await loadedDetail()
    fill('group-name', 'Local draft')
    act(() => setAccessToken({ access_token: 'rotated-token', token_type: 'bearer', expires_in: 3600 }))
    view.render()
    expect((document.getElementById('group-name') as HTMLInputElement).value).toBe('Local draft')
    expect(boundary.patch).not.toHaveBeenCalled()
  })

  it('retires an old save after an explicit login with the same account', async () => {
    const pending = deferred<TenantGroupOut>()
    boundary.patch.mockReturnValue(pending.promise)
    const view = await loadedDetail()
    fill('group-name', 'Submitted')
    click(button(view.container, '保存'))
    await waitForAssertion(() => expect(boundary.patch).toHaveBeenCalled())
    act(() => login('groups-user'))
    fill('group-name', 'Same account new edit')
    await act(async () => pending.resolve(group(A, 'Submitted')))
    expect((document.getElementById('group-name') as HTMLInputElement).value).toBe('Same account new edit')
    expect(boundary.success).not.toHaveBeenCalled()
  })

  it('retires a pending save when its query is removed and rebuilt', async () => {
    const pending = deferred<TenantGroupOut>()
    boundary.patch.mockReturnValue(pending.promise)
    const view = await loadedDetail()
    fill('group-name', 'Submitted')
    click(button(view.container, '保存'))
    await waitForAssertion(() => expect(boundary.patch).toHaveBeenCalled())
    const replacement = group(A, 'Replacement cache')
    act(() => {
      view.client.clear()
      view.client.setQueryData(queryKeys.groups.detail(A), replacement)
    })
    view.render()
    fill('group-name', 'Replacement draft')
    await act(async () => pending.resolve(group(A, 'Submitted')))
    expect(view.client.getQueryData(queryKeys.groups.detail(A))).toEqual(replacement)
    expect((document.getElementById('group-name') as HTMLInputElement).value).toBe('Replacement draft')
    expect(boundary.success).not.toHaveBeenCalled()
  })

  it('does not publish an old save after unmounting and visiting the same group again', async () => {
    const pending = deferred<TenantGroupOut>()
    boundary.patch.mockReturnValue(pending.promise)
    const first = await loadedDetail()
    fill('group-name', 'Submitted')
    click(button(first.container, '保存'))
    await waitForAssertion(() => expect(boundary.patch).toHaveBeenCalled())
    first.unmount()
    const next = await loadedDetail()
    fill('group-name', 'New visit draft')
    await act(async () => pending.resolve(group(A, 'Submitted')))
    expect((document.getElementById('group-name') as HTMLInputElement).value).toBe('New visit draft')
    expect(next.container.textContent).toContain('Alpha')
    expect(boundary.success).not.toHaveBeenCalled()
  })
})
