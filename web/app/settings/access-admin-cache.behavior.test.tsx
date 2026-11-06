// @vitest-environment happy-dom

import { act } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useQuery } from '@tanstack/react-query'
import { waitForAssertion } from '@/test/hook-harness'
import { queryKeys } from '@/lib/query-keys'
import {
  A,
  B,
  MEMBER,
  adminAccess,
  cleanupAdmin,
  deferred,
  group,
  login,
  member,
  mountAdmin,
} from './access-admin-test-harness'
import { groupDirectoryKey, groupMemberKey, useGroupDirectory } from './groups/use-group-directory'
import { useMembers } from './rbac/use-members'

const api = vi.hoisted(() => ({
  list: vi.fn(),
  get: vi.fn(),
  create: vi.fn(),
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
}))
vi.mock('@/lib/api/access', () => ({
  groupApi: {
    listGroups: api.list,
    getGroup: api.get,
    createGroup: api.create,
    patchGroup: api.patch,
    deleteGroup: api.delete,
    listGroupMembers: api.members,
    addGroupMembers: api.add,
    removeGroupMembers: api.remove,
  },
  rbacApi: { listTenantMembers: api.tenantList, patchTenantMemberRole: api.role, removeTenantMember: api.tenantRemove },
}))
vi.mock('@/hooks/use-tenant-access', () => ({ useTenantAccess: () => ({ data: adminAccess }) }))
vi.mock('sonner', () => ({ toast: { success: api.success, error: api.error, info: vi.fn(), dismiss: vi.fn() } }))

let groups = [group(A, 'Alpha'), group(B, 'Beta')]
let ids = [MEMBER]
let members = [member(MEMBER)]
const trigger = () => document.createElement('button')
async function openGroups() {
  const view = mountAdmin(useGroupDirectory)
  await waitForAssertion(() => expect(view.result.current.group?.id).toBe(A))
  await waitForAssertion(() => expect(view.result.current.members).toHaveLength(1))
  return view
}
function rename(view: Awaited<ReturnType<typeof openGroups>>, value: string) {
  act(() => view.result.current.openEditor('edit', trigger()))
  act(() => view.result.current.changeEditor({ name: value }))
  act(() => {
    void view.result.current.saveEditor()
  })
}
beforeEach(() => {
  vi.resetAllMocks()
  login()
  window.history.replaceState({}, '', `/settings/groups?group=${A}`)
  groups = [group(A, 'Alpha'), group(B, 'Beta')]
  ids = [MEMBER]
  members = [member(MEMBER)]
  api.list.mockImplementation(async () => ({ items: groups, total: groups.length }))
  api.get.mockImplementation(async (id) => {
    const found = groups.find((item) => item.id === id)
    if (!found) throw new Error('group not found')
    return found
  })
  api.members.mockImplementation(async () => ({
    items: ids.map((user_id) => ({ user_id, created_at: '2026-11-05' })),
    total: ids.length,
  }))
  api.tenantList.mockImplementation(async () => ({ items: members, total: members.length }))
})
afterEach(cleanupAdmin)

describe('access writes complete their original cache responsibilities', () => {
  it.each(['resolve on B', 'return to A first'] as const)(
    'rereads saved group truth without old feedback: %s',
    async (mode) => {
      const pending = deferred<ReturnType<typeof group>>()
      api.patch.mockReturnValue(pending.promise)
      const view = await openGroups()
      rename(view, 'Submitted')
      view.navigate(true, B)
      await waitForAssertion(() => expect(view.result.current.group?.id).toBe(B))
      if (mode === 'return to A first') {
        view.navigate(false)
        view.navigate(true, A)
        await waitForAssertion(() => expect(view.result.current.group?.id).toBe(A))
        act(() => view.result.current.openEditor('edit', trigger()))
        act(() => view.result.current.changeEditor({ name: 'New A draft' }))
      }
      groups = [group(A, 'Server truth'), group(B, 'Beta')]
      await act(async () => pending.resolve(group(A, 'Old response payload')))
      if (mode === 'resolve on B') {
        view.navigate(true, A)
        await waitForAssertion(() => expect(view.result.current.group?.name).toBe('Server truth'))
      } else {
        await waitForAssertion(() => expect(view.result.current.group?.name).toBe('Server truth'))
        expect(view.result.current.editor?.name).toBe('New A draft')
      }
      expect(api.success).not.toHaveBeenCalled()
    },
  )
  it.each(['create', 'delete'] as const)(
    'invalidates the original group list after %s finishes away from the page',
    async (kind) => {
      const pending = deferred<ReturnType<typeof group> | void>()
      api[kind].mockReturnValue(pending.promise)
      const view = await openGroups()
      if (kind === 'create') {
        act(() => view.result.current.openEditor('create', trigger()))
        act(() => view.result.current.changeEditor({ name: 'Created' }))
      } else act(() => view.result.current.openDeletion(trigger()))
      act(() => {
        void (kind === 'create' ? view.result.current.saveEditor() : view.result.current.deleteGroup())
      })
      view.navigate(false)
      groups = kind === 'create' ? [...groups, group('created', 'Created')] : groups.filter((item) => item.id !== A)
      await act(async () => pending.resolve(kind === 'create' ? group('created', 'Created') : undefined))
      expect(view.client.getQueryState(groupDirectoryKey)?.isInvalidated).toBe(true)
      expect(api.success).not.toHaveBeenCalled()
      view.navigate(true)
      await waitForAssertion(() => expect(view.result.current.groups).toEqual(groups))
    },
  )
  it.each(['add', 'remove'] as const)(
    'invalidates the original member collection after %s finishes away',
    async (kind) => {
      const pending = deferred<{ updated: number }>()
      api[kind].mockReturnValue(pending.promise)
      const view = await openGroups()
      if (kind === 'add') {
        act(() => view.result.current.openAddition(trigger()))
        act(() => view.result.current.changeAddition({ raw: 'new-member' }))
      }
      act(() => {
        void (kind === 'add' ? view.result.current.addMembers() : view.result.current.removeMember(MEMBER))
      })
      view.navigate(false)
      ids = kind === 'add' ? [MEMBER, 'new-member'] : []
      await act(async () => pending.resolve({ updated: 1 }))
      expect(view.client.getQueryState(groupMemberKey(A))?.isInvalidated).toBe(true)
      expect(api.success).not.toHaveBeenCalled()
      view.navigate(true)
      await waitForAssertion(() => expect(view.result.current.members.map((item) => item.user_id)).toEqual(ids))
    },
  )
  it.each(['role', 'remove'] as const)(
    'invalidates the original tenant collection after %s finishes away',
    async (kind) => {
      const pending = deferred<ReturnType<typeof member> | { removed: boolean }>()
      if (kind === 'role') api.role.mockReturnValue(pending.promise)
      else api.tenantRemove.mockReturnValue(pending.promise)
      const view = mountAdmin(useMembers)
      await waitForAssertion(() => expect(view.result.current.members).toHaveLength(1))
      if (kind === 'remove') act(() => view.result.current.openDeletion(members[0], trigger()))
      act(() => {
        void (kind === 'role'
          ? view.result.current.saveRole({ member: members[0], desired: 'editor' })
          : view.result.current.removeMember())
      })
      await waitForAssertion(() => expect(kind === 'role' ? api.role : api.tenantRemove).toHaveBeenCalledOnce())
      view.navigate(false)
      members = kind === 'role' ? [member(MEMBER, 'admin')] : []
      await act(async () => pending.resolve(kind === 'role' ? member(MEMBER, 'editor') : { removed: true }))
      expect(view.client.getQueryState(queryKeys.rbac.members({ all: true }))?.isInvalidated).toBe(true)
      expect(api.success).not.toHaveBeenCalled()
      view.navigate(true)
      await waitForAssertion(() => expect(view.result.current.members).toEqual(members))
    },
  )
  it('refreshes the actual1000-item selector cache after a rename and preserves unrelated group caches', async () => {
    const pending = deferred<ReturnType<typeof group>>()
    api.patch.mockReturnValue(pending.promise)
    const view = await openGroups()
    const selectorKey = queryKeys.groups.list({ limit: 1000 })
    await view.client.fetchQuery({ queryKey: selectorKey, queryFn: () => api.list({ limit: 1000 }) })
    const bDetail = group(B, 'Beta'),
      bMembers = [{ user_id: 'beta-member', created_at: '2026-11-05' }]
    view.client.setQueryData(queryKeys.groups.detail(B), bDetail)
    view.client.setQueryData(groupMemberKey(B), bMembers)
    rename(view, 'Submitted')
    view.navigate(false)
    groups = [group(A, 'Renamed'), group(B, 'Beta')]
    await act(async () => pending.resolve(group(A, 'Stale response')))
    expect(view.client.getQueryState(selectorKey)?.isInvalidated).toBe(true)
    const fresh = await view.client.fetchQuery({ queryKey: selectorKey, queryFn: () => api.list({ limit: 1000 }) })
    expect(fresh.items[0].name).toBe('Renamed')
    expect(view.client.getQueryData(queryKeys.groups.detail(B))).toBe(bDetail)
    expect(view.client.getQueryData(groupMemberKey(B))).toBe(bMembers)
    expect(api.success).not.toHaveBeenCalled()
  })
  it('refreshes an active selector observer using server truth rather than the old payload', async () => {
    const pending = deferred<ReturnType<typeof group>>()
    api.patch.mockReturnValue(pending.promise)
    function useDirectoryAndSelector() {
      const directory = useGroupDirectory()
      const selector = useQuery({
        queryKey: queryKeys.groups.list({ limit: 1000 }),
        queryFn: () => api.list({ limit: 1000 }),
      })
      return { directory, selector }
    }
    const view = mountAdmin(useDirectoryAndSelector)
    await waitForAssertion(() => expect(view.result.current.directory.group?.id).toBe(A))
    act(() => view.result.current.directory.openEditor('edit', trigger()))
    act(() => view.result.current.directory.changeEditor({ name: 'Submitted' }))
    act(() => {
      void view.result.current.directory.saveEditor()
    })
    view.navigate(false)
    view.navigate(true, B)
    await waitForAssertion(() => expect(view.result.current.directory.group?.id).toBe(B))
    groups = [group(A, 'Newest server value'), group(B, 'Beta')]
    await act(async () => pending.resolve(group(A, 'Old response')))
    await waitForAssertion(() => expect(view.result.current.selector.data.items[0].name).toBe('Newest server value'))
    expect(api.success).not.toHaveBeenCalled()
  })
})
