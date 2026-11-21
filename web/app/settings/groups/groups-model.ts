import type { TenantGroupOut, TenantGroupMemberOut } from '@/types/backend'
import type { TenantMember } from '@/lib/api/access'

export type GroupScope = {
  query: string
  external: 'all' | 'filled' | 'empty'
  page: number
  size: number
  groupId: string
  memberQuery: string
  memberPage: number
  view: 'directory' | 'detail'
}
export function formatGroupDate(value: string | null | undefined, short = false) {
  if (!value) return '未记录'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    ...(short ? {} : { hour: '2-digit', minute: '2-digit', hour12: false }),
  })
    .format(date)
    .replace(/\//g, '-')
}
function readPageNumber(value: string | null) {
  if (value === null || !/^\d+$/.test(value)) return 1
  return Math.max(1, Math.min(1_000_000, Number(value)))
}

export function parseGroupScope(search: string): GroupScope {
  const params = new URLSearchParams(search)
  const external = params.get('external')
  const size = Number(params.get('size'))
  const view = params.get('view')
  return {
    query: params.get('q') ?? '',
    external: external === 'filled' || external === 'empty' ? external : 'all',
    page: readPageNumber(params.get('page')),
    size: [10, 20, 50].includes(size) ? size : 20,
    groupId: params.get('group') ?? '',
    memberQuery: params.get('mq') ?? '',
    memberPage: readPageNumber(params.get('mp')),
    view: view === 'detail' || (view !== 'directory' && params.has('group')) ? 'detail' : 'directory',
  }
}
export function buildGroupLocation(href: string, scope: GroupScope): URL {
  const url = new URL(href)
  const values: Record<string, string> = {
    q: scope.query,
    external: scope.external === 'all' ? '' : scope.external,
    page: scope.page === 1 ? '' : String(scope.page),
    size: scope.size === 20 ? '' : String(scope.size),
    group: scope.groupId,
    mq: scope.memberQuery,
    mp: scope.memberPage === 1 ? '' : String(scope.memberPage),
    view: scope.view,
  }
  for (const [key, value] of Object.entries(values)) {
    if (value !== '') url.searchParams.set(key, value)
    else url.searchParams.delete(key)
  }
  return url
}
export function filterGroups(groups: TenantGroupOut[], scope: Pick<GroupScope, 'query' | 'external'>) {
  const searchText = scope.query.trim().toLocaleLowerCase()
  return groups.filter((group) => {
    const hasExternalId = Boolean(group.external_id?.trim())
    if (scope.external !== 'all' && hasExternalId !== (scope.external === 'filled')) return false
    if (searchText === '') return true
    return [group.name, group.external_id, group.id].some(
      (value) => value?.toLocaleLowerCase().includes(searchText) === true,
    )
  })
}
export function memberIdentity(userId: string, person: TenantMember | undefined) {
  const username = person?.username?.trim()
  const email = person?.email?.trim()
  return {
    label: [username, email].find((value) => value !== undefined && value !== '') ?? userId,
    email,
  }
}
export function filterMembers(
  members: TenantGroupMemberOut[],
  query: string,
  identitiesByUserId: ReadonlyMap<string, TenantMember>,
) {
  const searchText = query.trim().toLocaleLowerCase()
  if (searchText === '') return members

  return members.filter((member) => {
    const { label, email } = memberIdentity(member.user_id, identitiesByUserId.get(member.user_id))
    return [member.user_id, label, email].some((value) => value?.toLocaleLowerCase().includes(searchText) === true)
  })
}
export function groupDraft(name: string, externalId: string) {
  const groupName = name.trim()
  const externalGroupId = externalId.trim()
  const errors: { name?: string; external?: string } = {}
  if (groupName === '') errors.name = '请输入组名称。'
  else if (Array.from(groupName).length > 255) errors.name = '组名称不能超过255个字符。'
  if (Array.from(externalGroupId).length > 255) errors.external = '外部组 ID 不能超过255个字符。'
  return { errors, payload: { name: groupName, external_id: externalGroupId } }
}
export function memberIds(selected: string[], raw: string) {
  const ids = [...new Set([...selected, ...raw.split(/[\n,;，；]+/)].map((value) => value.trim()).filter(Boolean))]
  if (ids.length === 0) return { ids, error: '请选择成员或填写成员 ID。' }
  if (ids.length > 200) return { ids, error: '一次最多添加200名成员，请减少后重试。' }
  if (ids.some((id) => Array.from(id).length > 255)) return { ids, error: '成员 ID 不能超过255个字符。' }
  return { ids, error: '' }
}
