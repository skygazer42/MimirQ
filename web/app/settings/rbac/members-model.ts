import type { TenantMember, TenantMemberListResponse } from '@/lib/api/access'

export const MEMBER_ROLES = [
  { key: 'owner', label: '所有者', tone: 'ink', description: '管理成员、配置及租户运维；当前管理权限与管理员相同。' },
  { key: 'admin', label: '管理员', tone: 'blue', description: '管理成员、配置及租户运维。' },
  { key: 'auditor', label: '审计员', tone: 'amber', description: '读取审计记录，使用表格 SQL 查询。' },
  { key: 'editor', label: '编辑者', tone: 'blue', description: '可处理反馈；内容编辑范围由数据集和文档授权决定。' },
  { key: 'dataset_operator', label: '数据集运维', tone: 'green', description: '可处理反馈；数据集操作范围由单独授权决定。' },
  { key: 'viewer', label: '查看者', tone: 'neutral', description: '按数据集和文档授权访问内容。' },
] as const

export type MemberRole = typeof MEMBER_ROLES[number]['key']
export type MemberScope = 'all' | 'current' | 'others' | 'unassigned'
export const MEMBER_PAGE_SIZES = [10, 20, 50] as const

export function memberIdentity(member: TenantMember) {
  const name = member.username?.trim() || member.email?.trim() || member.user_id || '未关联账号'
  return { name, email: member.email?.trim() || '', initial: Array.from(name)[0].toUpperCase() }
}
export function roleLabel(role: string) { return MEMBER_ROLES.find(item => item.key === role)?.label ?? (role || '未分配角色') }
export function isAdministrator(role: string) { return role === 'owner' || role === 'admin' }
export function isCurrentAccount(member: TenantMember, accountId: string | undefined) { return Boolean(accountId && member.user_id === accountId) }
export function activeAdminCount(members: TenantMember[]) { return members.filter(member => member.is_active && isAdministrator(member.role)).length }
export function roleChangeRestriction(member: TenantMember, next: string, admins: number) {
  if (!member.user_id) return '未关联账号，无法修改角色。'
  if (isAdministrator(member.role) && !isAdministrator(next) && admins <= 1) return '至少保留一名有效管理员。'
  return ''
}
export function removalRestriction(member: TenantMember, accountId: string | undefined, admins: number) {
  if (!member.user_id) return '未关联账号，无法移除。'
  if (isCurrentAccount(member, accountId)) return '不能移除当前账号。'
  if (member.is_active && isAdministrator(member.role) && admins <= 1) return '不能移除最后一名有效管理员。'
  return ''
}
export function filterMembers(members: TenantMember[], query: string, role: string, scope: MemberScope, accountId: string | undefined) {
  const q = query.trim().toLocaleLowerCase()
  return members.filter(member => {
    const identityMatch = !q || [member.username, member.email, member.user_id, member.role, roleLabel(member.role)].some(value => value?.toLocaleLowerCase().includes(q))
    const scopeMatch = scope === 'all' || (scope === 'current' && isCurrentAccount(member, accountId)) || (scope === 'others' && Boolean(accountId) && !isCurrentAccount(member, accountId)) || (scope === 'unassigned' && !member.role.trim())
    return identityMatch && (role === 'all' || member.role === role) && scopeMatch
  })
}
export function pageMembers(members: TenantMember[], page: number, size: number) {
  const total = members.length, pages = Math.max(1, Math.ceil(total / size)), current = Math.min(Math.max(page, 1), pages)
  return { items: members.slice((current - 1) * size, current * size), page: current, pages, total, start: total ? (current - 1) * size + 1 : 0, end: Math.min(current * size, total) }
}
export function formatMemberDate(value: string | null | undefined) {
  if (!value) return '未记录'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }).format(date).replaceAll('/', '-')
}
export async function readAllMembers(fetchPage: (params: { skip: number; limit: number }) => Promise<TenantMemberListResponse>): Promise<TenantMember[]> {
  const result: TenantMember[] = [], seen = new Set<string>()
  let total: number | undefined
  for (let skip = 0; ;) {
    const response = await fetchPage({ skip, limit: 500 })
    // A default-empty collection is valid only when the API also reports zero.
    const items = response.items ?? (response.total === 0 ? [] : undefined)
    if (!items || (total !== undefined && response.total !== total)) throw new Error('成员分页发生变化，请重新读取。')
    total = response.total
    if (!items.length && result.length < total) throw new Error('成员分页不完整，请重新读取。')
    for (const member of items) {
      if (seen.has(member.id)) throw new Error('成员分页出现重复，请重新读取。')
      seen.add(member.id)
      result.push(member)
    }
    if (result.length > total) throw new Error('成员分页数量不一致，请重新读取。')
    if (result.length === total) return result
    skip += items.length
  }
}
