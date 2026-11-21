// @vitest-environment happy-dom

import { act } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { waitForAssertion } from '@/test/hook-harness'
import { queryKeys } from '@/lib/query-keys'
import { setAccessToken } from '@/lib/auth-storage'
import { adminAccess, cleanupAdmin, deferred, login, member, mountAdmin } from '../access-admin-test-harness'
import { useMembers } from './use-members'

const api = vi.hoisted(() => ({ list: vi.fn(), patch: vi.fn(), remove: vi.fn(), success: vi.fn(), error: vi.fn() }))
vi.mock('@/lib/api/access', () => ({
  rbacApi: { listTenantMembers: api.list, patchTenantMemberRole: api.patch, removeTenantMember: api.remove },
}))
vi.mock('@/hooks/use-tenant-access', () => ({ useTenantAccess: () => ({ data: adminAccess }) }))
vi.mock('sonner', () => ({ toast: { success: api.success, error: api.error } }))

const A = 'alpha@example.com',
  B = 'beta@example.com'
const key = queryKeys.rbac.members({ all: true })
let members = [member(A), member(B)]
async function open() {
  const view = mountAdmin(useMembers)
  await waitForAssertion(() => expect(view.result.current.members).toHaveLength(2))
  return view
}
beforeEach(() => {
  vi.resetAllMocks()
  login()
  members = [member(A), member(B)]
  api.list.mockImplementation(async () => ({ items: members, total: members.length }))
  api.patch.mockImplementation(async (id, patch) => {
    const updated = { ...member(id), role: patch.role }
    members = members.map((item) => (item.user_id === id ? updated : item))
    return updated
  })
  api.remove.mockImplementation(async (id) => {
    members = members.filter((item) => item.user_id !== id)
    return { removed: true }
  })
})
afterEach(cleanupAdmin)

describe('member table operation ownership', () => {
  it('mutes a member load failure after leaving the table', async () => {
    const pending = deferred<{ items: ReturnType<typeof member>[]; total: number }>()
    api.list.mockReturnValue(pending.promise)
    const view = mountAdmin(useMembers)
    await waitForAssertion(() => expect(api.list).toHaveBeenCalledOnce())
    view.navigate(false)
    await act(async () => pending.reject(new Error('retired member load')))
    expect(api.error).not.toHaveBeenCalled()
  })
  it('retires a role response after a silent explicit login with the same account', async () => {
    const pending = deferred<ReturnType<typeof member>>()
    api.patch.mockReturnValue(pending.promise)
    const view = await open()
    act(() => {
      void view.result.current.saveRole({ member: members[0], desired: 'editor' })
    })
    await waitForAssertion(() => expect(api.patch).toHaveBeenCalledOnce())
    act(() => login())
    const original = view.client.getQueryData(key)
    await act(async () => pending.resolve(member(A, 'editor')))
    expect(view.client.getQueryData(key)).toBe(original)
    expect(api.success).not.toHaveBeenCalled()
  })
  it('saves the submitted role and confirms the current server member', async () => {
    const view = await open()
    await act(async () => view.result.current.saveRole({ member: members[0], desired: 'editor' }))
    expect(api.patch).toHaveBeenCalledExactlyOnceWith(A, { role: 'editor' })
    expect(view.result.current.members[0].role).toBe('editor')
    expect(view.result.current.busy).toBeNull()
  })
  it('starts one request before a pending render and blocks removal in the same lane', async () => {
    const pending = deferred<ReturnType<typeof member>>()
    api.patch.mockReturnValue(pending.promise)
    const view = await open()
    act(() => view.result.current.openDeletion(members[0], document.createElement('button')))
    act(() => {
      void view.result.current.saveRole({ member: members[0], desired: 'editor' })
      void view.result.current.saveRole({ member: members[0], desired: 'admin' })
      void view.result.current.removeMember()
    })
    await waitForAssertion(() => expect(api.patch).toHaveBeenCalledOnce())
    expect(api.remove).not.toHaveBeenCalled()
    await act(async () => pending.resolve(member(A, 'editor')))
  })
  it('blocks a role write in the same turn as removal and serializes different members', async () => {
    const pending = deferred<{ removed: boolean }>()
    api.remove.mockReturnValue(pending.promise)
    const view = await open()
    act(() => view.result.current.openDeletion(members[0], document.createElement('button')))
    act(() => {
      void view.result.current.removeMember()
      void view.result.current.saveRole({ member: members[1], desired: 'editor' })
    })
    await waitForAssertion(() => expect(api.remove).toHaveBeenCalledOnce())
    expect(api.patch).not.toHaveBeenCalled()
    await act(async () => pending.resolve({ removed: true }))
  })
  it('retains the failed role intent for retry and exposes the original error', async () => {
    api.patch.mockRejectedValueOnce(new Error('role conflict'))
    const view = await open()
    await act(async () => view.result.current.saveRole({ member: members[0], desired: 'editor' }))
    expect(view.result.current.roleFailure).toMatchObject({
      desired: 'editor',
      message: expect.stringContaining('role conflict'),
    })
    expect(api.success).not.toHaveBeenCalled()
    await act(async () => view.result.current.saveRole(view.result.current.roleFailure!))
    expect(view.result.current.members[0].role).toBe('editor')
  })
  it('keeps self-removal forbidden by the current access identity', async () => {
    const view = await open()
    act(() =>
      view.result.current.openDeletion(member(adminAccess.account_id, 'admin'), document.createElement('button')),
    )
    expect(view.result.current.deletion).toBeNull()
    expect(api.remove).not.toHaveBeenCalled()
    expect(api.error).toHaveBeenCalled()
  })
  it.each(['role', 'remove'] as const)('retires a pending %s when a new login replaces the cache', async (kind) => {
    const pending = deferred<ReturnType<typeof member> | { removed: boolean }>()
    if (kind === 'role') api.patch.mockReturnValue(pending.promise)
    else api.remove.mockReturnValue(pending.promise)
    const view = await open()
    if (kind === 'remove') act(() => view.result.current.openDeletion(members[0], document.createElement('button')))
    act(() => {
      void (kind === 'role'
        ? view.result.current.saveRole({ member: members[0], desired: 'editor' })
        : view.result.current.removeMember())
    })
    await waitForAssertion(() => expect(kind === 'role' ? api.patch : api.remove).toHaveBeenCalledOnce())
    act(() => login('replacement'))
    await waitForAssertion(() => expect(view.result.current.members).toHaveLength(2))
    const replacement = view.client.getQueryData(key)
    await act(async () => pending.resolve(kind === 'role' ? member(A, 'editor') : { removed: true }))
    expect(view.client.getQueryData(key)).toBe(replacement)
    expect(api.success).not.toHaveBeenCalled()
  })
  it('retires a response when its original query is removed and rebuilt', async () => {
    const pending = deferred<ReturnType<typeof member>>()
    api.patch.mockReturnValue(pending.promise)
    const view = await open()
    act(() => {
      void view.result.current.saveRole({ member: members[0], desired: 'editor' })
    })
    await waitForAssertion(() => expect(api.patch).toHaveBeenCalledOnce())
    const replacement = [member(A, 'admin')]
    act(() => {
      view.client.removeQueries({ queryKey: key, exact: true })
      view.client.setQueryData(key, replacement)
    })
    await act(async () => pending.resolve(member(A, 'editor')))
    expect(view.client.getQueryData(key)).toBe(replacement)
    expect(api.success).not.toHaveBeenCalled()
  })
  it('mutes a failure after leaving the table', async () => {
    const pending = deferred<ReturnType<typeof member>>()
    api.patch.mockReturnValue(pending.promise)
    const view = await open()
    act(() => {
      void view.result.current.saveRole({ member: members[0], desired: 'editor' })
    })
    await waitForAssertion(() => expect(api.patch).toHaveBeenCalledOnce())
    view.navigate(false)
    await act(async () => pending.reject(new Error('retired failure')))
    expect(api.error).not.toHaveBeenCalled()
    expect(api.success).not.toHaveBeenCalled()
  })
  it('keeps token rotation within the same operation and can save after idle clear', async () => {
    const view = await open()
    act(() => {
      setAccessToken({ access_token: 'rotated', token_type: 'bearer', expires_in: 3600 })
      view.client.clear()
    })
    await act(async () => view.result.current.saveRole({ member: members[0], desired: 'editor' }))
    expect(api.patch).toHaveBeenCalledExactlyOnceWith(A, { role: 'editor' })
    expect(view.result.current.roleFailure).toBeNull()
  })
  it('keeps the removal target and real failure until a successful retry', async () => {
    api.remove.mockRejectedValueOnce(new Error('remove conflict'))
    const view = await open()
    act(() => view.result.current.openDeletion(members[0], document.createElement('button')))
    await act(async () => view.result.current.removeMember())
    expect(view.result.current.deletion?.user_id).toBe(A)
    expect(view.result.current.deleteError).toContain('remove conflict')
    await act(async () => view.result.current.removeMember())
    expect(view.result.current.deletion).toBeNull()
    expect(view.result.current.members.some((item) => item.user_id === A)).toBe(false)
  })
})
