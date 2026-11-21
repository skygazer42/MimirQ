// @vitest-environment happy-dom

import { act } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { waitForAssertion } from '@/test/hook-harness'
import { queryKeys } from '@/lib/query-keys'
import { setAccessToken } from '@/lib/auth-storage'
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
} from '../access-admin-test-harness'
import { groupDirectoryKey, groupMemberKey, useGroupDirectory } from './use-group-directory'

const api = vi.hoisted(() => ({
  list: vi.fn(),
  get: vi.fn(),
  create: vi.fn(),
  patch: vi.fn(),
  delete: vi.fn(),
  members: vi.fn(),
  add: vi.fn(),
  remove: vi.fn(),
  success: vi.fn(),
  error: vi.fn(),
  info: vi.fn(),
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
  rbacApi: { listTenantMembers: async () => ({ items: [member(MEMBER)], total: 1 }) },
}))
vi.mock('@/hooks/use-tenant-access', () => ({ useTenantAccess: () => ({ data: adminAccess }) }))
vi.mock('sonner', () => ({ toast: { success: api.success, error: api.error, info: api.info, dismiss: vi.fn() } }))

let groups = [group(A, 'Alpha'), group(B, 'Beta')]
const trigger = () => document.createElement('button')
async function open() {
  const view = mountAdmin(useGroupDirectory)
  await waitForAssertion(() => expect(view.result.current.group?.id).toBe(A))
  return view
}
function edit(view: Awaited<ReturnType<typeof open>>, name: string, mode: 'create' | 'edit' = 'edit') {
  act(() => view.result.current.openEditor(mode, trigger()))
  act(() => view.result.current.changeEditor({ name }))
}
beforeEach(() => {
  vi.resetAllMocks()
  login()
  window.history.replaceState({}, '', `/settings/groups?group=${A}`)
  groups = [group(A, 'Alpha'), group(B, 'Beta')]
  api.list.mockImplementation(async () => ({ items: groups, total: groups.length }))
  api.get.mockImplementation(async (id: string) => groups.find((item) => item.id === id))
  api.members.mockResolvedValue({ items: [{ user_id: MEMBER, created_at: '2026-11-05' }], total: 1 })
  api.add.mockResolvedValue({ updated: 1 })
  api.remove.mockResolvedValue({ updated: 1 })
  api.delete.mockResolvedValue(undefined)
})
afterEach(cleanupAdmin)

describe('group directory operation ownership', () => {
  it('can create after idle cache removal without another user edit', async () => {
    api.create.mockImplementation(async (payload) => {
      const saved = group('new', payload.name)
      groups = [...groups, saved]
      return saved
    })
    const view = await open()
    edit(view, 'After clear', 'create')
    act(() => view.client.clear())
    await act(async () => view.result.current.saveEditor())
    expect(api.create).toHaveBeenCalledExactlyOnceWith({ name: 'After clear', external_id: '' })
    expect(view.result.current.editor).toBeNull()
  })
  it('mutes a directory load failure after leaving the page', async () => {
    const pending = deferred<{ items: ReturnType<typeof group>[]; total: number }>()
    api.list.mockReturnValue(pending.promise)
    const view = mountAdmin(useGroupDirectory)
    await waitForAssertion(() => expect(api.list).toHaveBeenCalledOnce())
    view.navigate(false)
    await act(async () => pending.reject(new Error('retired directory load')))
    expect(api.error).not.toHaveBeenCalled()
  })
  it('retires a rename after a silent explicit login with the same account', async () => {
    const pending = deferred<ReturnType<typeof group>>()
    api.patch.mockReturnValue(pending.promise)
    const view = await open()
    edit(view, 'Submitted')
    act(() => {
      void view.result.current.saveEditor()
    })
    act(() => login())
    const original = view.client.getQueryData(queryKeys.groups.detail(A))
    const reads = api.get.mock.calls.length
    await act(async () => pending.resolve(group(A, 'Retired response')))
    expect(view.client.getQueryData(queryKeys.groups.detail(A))).toBe(original)
    expect(api.get).toHaveBeenCalledTimes(reads)
    expect(api.success).not.toHaveBeenCalled()
  })
  it('creates trimmed input and reads the complete directory', async () => {
    api.create.mockImplementation(async (payload) => {
      const saved = { ...group('new', payload.name), external_id: payload.external_id }
      groups = [...groups, saved]
      return saved
    })
    const view = await open()
    edit(view, '  Legal  ', 'create')
    act(() => view.result.current.changeEditor({ external: '  legal  ' }))
    await act(async () => view.result.current.saveEditor())
    expect(api.create).toHaveBeenCalledWith({ name: 'Legal', external_id: 'legal' })
    expect(api.list).toHaveBeenLastCalledWith({ skip: 0, limit: 500 })
    expect(view.result.current.group?.name).toBe('Legal')
  })
  it('keeps the submitted fields frozen and starts one request synchronously', async () => {
    const pending = deferred<ReturnType<typeof group>>()
    api.create.mockReturnValue(pending.promise)
    const view = await open()
    edit(view, 'Submitted', 'create')
    act(() => {
      void view.result.current.saveEditor()
      void view.result.current.saveEditor()
      view.result.current.changeEditor({ name: 'Later' })
    })
    expect(api.create).toHaveBeenCalledOnce()
    expect(view.result.current.editor?.name).toBe('Submitted')
    await act(async () => pending.resolve(group('new', 'Submitted')))
  })
  it('retains the failed draft and actual failure', async () => {
    api.patch.mockRejectedValue(new Error('conflict'))
    const view = await open()
    edit(view, 'Retained')
    await act(async () => view.result.current.saveEditor())
    expect(view.result.current.editor).toMatchObject({ name: 'Retained', error: expect.stringContaining('conflict') })
    expect(api.success).not.toHaveBeenCalled()
  })
  it('serializes deletion and keeps its original target until completion', async () => {
    const pending = deferred<void>()
    api.delete.mockReturnValue(pending.promise)
    const view = await open()
    act(() => view.result.current.openDeletion(trigger()))
    act(() => {
      void view.result.current.deleteGroup()
      void view.result.current.deleteGroup()
      view.result.current.closeDeletion()
    })
    expect(api.delete).toHaveBeenCalledExactlyOnceWith(A)
    expect(view.result.current.deletion?.id).toBe(A)
    await act(async () => pending.resolve())
  })
  it.each(['create', 'delete'] as const)(
    'retires a %s result when an explicit login replaces its cache',
    async (kind) => {
      const pending = deferred<ReturnType<typeof group> | void>()
      api[kind].mockReturnValue(pending.promise)
      const view = await open()
      if (kind === 'create') edit(view, 'Submitted', 'create')
      else act(() => view.result.current.openDeletion(trigger()))
      act(() => {
        void (kind === 'create' ? view.result.current.saveEditor() : view.result.current.deleteGroup())
      })
      act(() => login('replacement'))
      await waitForAssertion(() => expect(view.result.current.groups).toHaveLength(2))
      const replacement = view.client.getQueryData(groupDirectoryKey)
      await act(async () => pending.resolve(kind === 'create' ? group('new', 'Submitted') : undefined))
      expect(view.client.getQueryData(groupDirectoryKey)).toBe(replacement)
      expect(api.success).not.toHaveBeenCalled()
    },
  )
  it('does not overwrite another visited group with a late save', async () => {
    const pending = deferred<ReturnType<typeof group>>()
    api.patch.mockReturnValue(pending.promise)
    const view = await open()
    edit(view, 'Saved Alpha')
    act(() => {
      void view.result.current.saveEditor()
    })
    view.navigate(true, B)
    await waitForAssertion(() => expect(view.result.current.group?.id).toBe(B))
    edit(view, 'Beta draft')
    await act(async () => pending.resolve(group(A, 'Saved Alpha')))
    expect(view.result.current.editor?.name).toBe('Beta draft')
    expect(api.success).not.toHaveBeenCalled()
  })
  it('keeps the member operation attached to its original group', async () => {
    const pending = deferred<{ updated: number }>()
    api.remove.mockReturnValue(pending.promise)
    const view = await open()
    act(() => {
      void view.result.current.removeMember(MEMBER)
    })
    view.navigate(true, B)
    await waitForAssertion(() => expect(view.result.current.group?.id).toBe(B))
    await waitForAssertion(() => expect(view.result.current.members).toHaveLength(1))
    const original = view.client.getQueryData(groupMemberKey(B))
    await act(async () => pending.resolve({ updated: 1 }))
    expect(view.client.getQueryData(groupMemberKey(B))).toBe(original)
    expect(api.success).not.toHaveBeenCalled()
  })
  it('deduplicates submitted member IDs and freezes them while adding', async () => {
    const pending = deferred<{ updated: number }>()
    api.add.mockReturnValue(pending.promise)
    const view = await open()
    act(() => view.result.current.openAddition(trigger()))
    act(() => view.result.current.changeAddition({ raw: ' alice\nalice,bob; ' }))
    act(() => {
      void view.result.current.addMembers()
      view.result.current.changeAddition({ raw: 'charlie' })
    })
    expect(api.add).toHaveBeenCalledExactlyOnceWith(A, { member_ids: ['alice', 'bob'] })
    expect(view.result.current.addition?.raw).toContain('alice')
    await act(async () => pending.resolve({ updated: 2 }))
  })
  it('preserves ordinary edits through token rotation and can save after idle cache removal', async () => {
    api.patch.mockResolvedValue(group(A, 'Local draft'))
    const view = await open()
    edit(view, 'Local draft')
    act(() => {
      setAccessToken({ access_token: 'rotated', token_type: 'bearer', expires_in: 3600 })
      view.client.clear()
    })
    expect(view.result.current.editor?.name).toBe('Local draft')
    await act(async () => view.result.current.saveEditor())
    expect(api.patch).toHaveBeenCalledExactlyOnceWith(A, { name: 'Local draft', external_id: '' })
  })
  it('retires a save when its original query entity is removed and rebuilt', async () => {
    const pending = deferred<ReturnType<typeof group>>()
    api.patch.mockReturnValue(pending.promise)
    const view = await open()
    edit(view, 'Submitted')
    act(() => {
      void view.result.current.saveEditor()
    })
    const replacement = group(A, 'Replacement')
    act(() => {
      view.client.removeQueries({ queryKey: queryKeys.groups.detail(A), exact: true })
      view.client.setQueryData(queryKeys.groups.detail(A), replacement)
    })
    await act(async () => pending.resolve(group(A, 'Old payload')))
    expect(view.client.getQueryData(queryKeys.groups.detail(A))).toBe(replacement)
    expect(api.success).not.toHaveBeenCalled()
  })
  it('does not publish old success or failure after leaving and revisiting the same group', async () => {
    const pending = deferred<ReturnType<typeof group>>()
    api.patch.mockReturnValue(pending.promise)
    const view = await open()
    edit(view, 'Submitted')
    act(() => {
      void view.result.current.saveEditor()
    })
    view.navigate(false)
    view.navigate(true)
    await waitForAssertion(() => expect(view.result.current.group?.id).toBe(A))
    edit(view, 'New visit')
    await act(async () => pending.reject(new Error('old failure')))
    expect(view.result.current.editor?.name).toBe('New visit')
    expect(api.error).not.toHaveBeenCalled()
    expect(api.success).not.toHaveBeenCalled()
  })
})
