import { describe, expect, it } from 'vitest'
import type { TenantMember } from '@/lib/api/access'
import { activeAdminCount, filterMembers, isCurrentAccount, memberIdentity, pageMembers, readAllMembers, removalRestriction, roleChangeRestriction, roleLabel } from './members-model'

const person = (overrides: Partial<TenantMember> = {}): TenantMember => ({ id: 'record-a', tenant_id: 'tenant-a', user_id: 'account-a', username: '林澈', email: 'lin@example.com', role: 'admin', is_active: true, is_current: true, ...overrides })

describe('member permissions boundaries', () => {
  it('identifies the login account even when several memberships are marked current', () => {
    const rows = [person(), person({ id: 'record-b', user_id: 'account-b', role: 'viewer' })]
    expect(rows.filter(row => isCurrentAccount(row, 'account-b')).map(row => row.id)).toEqual(['record-b'])
    expect(isCurrentAccount(rows[0], undefined)).toBe(false)
    expect(filterMembers(rows, '', 'all', 'current', 'account-b')).toEqual([rows[1]])
    expect(filterMembers(rows, '', 'all', 'others', 'account-b')).toEqual([rows[0]])
  })
  it('preserves actual identities, unknown roles and missing account associations', () => {
    expect(memberIdentity(person({ username: null })).name).toBe('lin@example.com')
    expect(memberIdentity(person({ username: null, email: null, user_id: 'external@company.org' })).name).toBe('external@company.org')
    expect(memberIdentity(person({ username: null, email: null, user_id: null })).name).toBe('未关联账号')
    expect(roleLabel('custom')).toBe('custom')
    const missingId = person({ user_id: null, role: 'viewer' }), noRole = person({ role: '' })
    expect(filterMembers([missingId, noRole], '', 'all', 'unassigned', 'account-a')).toEqual([noRole])
  })
  it('matches last-administrator and self-removal rules without inventing owner privileges', () => {
    const admin = person(), inactive = person({ id: 'inactive', user_id: 'old-admin', is_active: false })
    expect(activeAdminCount([admin, inactive])).toBe(1)
    expect(roleChangeRestriction(admin, 'viewer', 1)).toBeTruthy()
    expect(roleChangeRestriction(admin, 'owner', 1)).toBe('')
    expect(roleChangeRestriction(inactive, 'viewer', 1)).toBeTruthy()
    expect(removalRestriction(admin, 'account-a', 2)).toContain('当前账号')
    expect(removalRestriction(admin, 'another', 1)).toContain('管理员')
    expect(removalRestriction(inactive, 'another', 1)).toBe('')
    expect(removalRestriction(person({ user_id: null }), 'another', 2)).toContain('未关联')
  })
  it('filters real fields and clamps pagination after removals', () => {
    const rows = [person(), person({ id: 'b', username: '季禾', email: 'ji.he@example.com', user_id: 'account-b', role: 'viewer' })]
    expect(filterMembers(rows, 'JI.HE', 'viewer', 'all', 'account-a')).toEqual([rows[1]])
    expect(pageMembers(rows, 5, 20)).toMatchObject({ page: 1, pages: 1, total: 2, start: 1, end: 2 })
    expect(pageMembers([], 5, 20)).toMatchObject({ page: 1, pages: 1, start: 0, end: 0 })
  })
  it('reads beyond the first 500 members', async () => {
    const all = Array.from({ length: 507 }, (_, index) => person({ id: `record-${index}`, user_id: `user-${index}` }))
    const calls: number[] = []
    const result = await readAllMembers(async ({ skip = 0, limit = 500 }) => { calls.push(skip); return { total: all.length, items: all.slice(skip, skip + limit) } })
    expect(calls).toEqual([0, 500]); expect(result).toHaveLength(507)
  })
  it('does not disguise read failures or incomplete pagination as an empty directory', async () => {
    await expect(readAllMembers(async () => { throw new Error('成员不可用') })).rejects.toThrow('成员不可用')
    await expect(readAllMembers(async () => ({ total: 1, items: [] }))).rejects.toThrow('分页')
    await expect(readAllMembers(async () => ({ total: 2, items: [person()] }))).rejects.toThrow('重复')
    expect(await readAllMembers(async () => ({ total: 0 }))).toEqual([])
  })
})
