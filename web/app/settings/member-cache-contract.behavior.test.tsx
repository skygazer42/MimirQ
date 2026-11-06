// @vitest-environment happy-dom

import React, { act } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { waitForAssertion } from '@/test/hook-harness'
import { queryKeys } from '@/lib/query-keys'
import { adminAccess, cleanupAdmin, login, member, mountAdmin } from './access-admin-test-harness'
import { GovernanceSection } from './_sections/governance-section'
import { useMembers } from './rbac/use-members'

const api = vi.hoisted(() => ({ list: vi.fn(), role: vi.fn() }))
vi.mock('@/lib/api/access', () => ({
  rbacApi: {
    listTenantMembers: api.list,
    patchTenantMemberRole: api.role,
    getCurrentTenantAccess: async () => adminAccess,
  },
}))
vi.mock('@/lib/api/rtbf', () => ({ rtbfApi: {} }))
vi.mock('@/hooks/use-tenant-access', () => ({ useTenantAccess: () => ({ data: adminAccess }) }))
vi.mock('@/components/settings/governance-ops-panel', () => ({ GovernanceOpsPanel: () => null }))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

let members = [member(adminAccess.account_id, 'admin'), member('other@example.com')]
const rawKey = queryKeys.rbac.members({ limit: 500 })
const tableKey = queryKeys.rbac.members({ all: true })
const governance = () => (
  <GovernanceSection
    isGovernanceEnabled={false}
    isPiiAnonymizeEnabled={false}
    isSecretsRedactEnabled={false}
    isQuarantineOnDropEnabled={false}
    updateGovernance={() => {}}
  />
)
beforeEach(() => {
  vi.resetAllMocks()
  login()
  members = [member(adminAccess.account_id, 'admin'), member('other@example.com')]
  api.list.mockImplementation(async () => ({ items: members.map((item) => ({ ...item })), total: members.length }))
  api.role.mockImplementation(async (id, patch) => {
    members = members.map((item) => (item.user_id === id ? { ...item, role: patch.role } : item))
    return members.find((item) => item.user_id === id)
  })
})
afterEach(cleanupAdmin)

describe('RTBF raw member DTO and complete member table cache', () => {
  it('keeps the raw response shape while showing the actual current subject', async () => {
    const view = mountAdmin(() => null, governance())
    await waitForAssertion(() => expect(view.container.textContent).toContain(adminAccess.account_id))
    expect(view.client.getQueryData(rawKey)).toEqual({ items: members, total: 2 })
    expect(Array.isArray(view.client.getQueryData(rawKey))).toBe(false)
    expect(api.list).toHaveBeenCalledWith({ limit: 500 })
  })
  it.each(['table first', 'governance first'] as const)(
    'keeps both consumers valid when mounting %s',
    async (order) => {
      const together =
        order === 'table first'
          ? mountAdmin<ReturnType<typeof useMembers> | null>(useMembers)
          : mountAdmin<ReturnType<typeof useMembers> | null>(() => null, governance())
      if (order === 'table first') {
        await waitForAssertion(() => expect(together.result.current?.members).toHaveLength(2))
        together.setChildren(governance())
      } else {
        await waitForAssertion(() => expect(together.client.getQueryData(rawKey)).toEqual({ items: members, total: 2 }))
        together.setController(useMembers)
      }
      await waitForAssertion(() => expect(together.result.current?.members).toHaveLength(2))
      await waitForAssertion(() => expect(together.client.getQueryData(rawKey)).toEqual({ items: members, total: 2 }))
      expect(together.client.getQueryData(tableKey)).toEqual(members)
      await waitForAssertion(() => expect(together.container.textContent).toContain(adminAccess.account_id))
    },
  )
  it('refreshes the original raw DTO and complete table together after a role write', async () => {
    const view = mountAdmin(useMembers, governance())
    await waitForAssertion(() => expect(view.client.getQueryData(rawKey)).toEqual({ items: members, total: 2 }))
    await waitForAssertion(() => expect(view.result.current.members).toHaveLength(2))
    await act(async () => view.result.current.saveRole({ member: view.result.current.members[1], desired: 'editor' }))
    await waitForAssertion(() => expect(view.client.getQueryData(rawKey)).toEqual({ items: members, total: 2 }))
    expect(view.result.current.members[1].role).toBe('editor')
    expect(Array.isArray(view.client.getQueryData(rawKey))).toBe(false)
    expect(Array.isArray(view.client.getQueryData(tableKey))).toBe(true)
  })
  it('keeps an optional-items empty DTO distinct from the complete empty table', async () => {
    members = []
    api.list.mockResolvedValue({ total: 0 })
    const view = mountAdmin(useMembers, governance())
    await waitForAssertion(() => expect(view.client.getQueryData(rawKey)).toEqual({ total: 0 }))
    await waitForAssertion(() => expect(view.client.getQueryData(tableKey)).toEqual([]))
    expect(view.result.current.members).toEqual([])
  })
})
