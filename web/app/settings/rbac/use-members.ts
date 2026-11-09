'use client'

import { useMemo, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { rbacApi, type TenantMember } from '@/lib/api/access'
import { useTenantAccess } from '@/hooks/use-tenant-access'
import { queryKeys } from '@/lib/query-keys'
import { formatApiError } from '@/lib/api-errors'
import { TENANT_PERMISSIONS, tenantAccessAllows } from '@/lib/tenant-permissions'
import { activeAdminCount, filterMembers, isAdministrator, isCurrentAccount, memberIdentity, pageMembers, readAllMembers, removalRestriction, roleChangeRestriction, roleLabel, type MemberRole, type MemberScope } from './members-model'

const MEMBERS_KEY = queryKeys.rbac.members({ all: true })
type RoleTarget = { member: TenantMember; desired: MemberRole }
type RoleFailure = RoleTarget & { message: string }

export function useMembers() {
  const client = useQueryClient(), access = useTenantAccess()
  const membersQuery = useQuery({ queryKey: MEMBERS_KEY, queryFn: () => readAllMembers(params => rbacApi.listTenantMembers(params)), retry: false })
  const [query, setQuery] = useState(''), [role, setRole] = useState('all'), [scope, setScope] = useState<MemberScope>('all')
  const [page, setPage] = useState(1), [size, setSize] = useState(20)
  const [busy, setBusy] = useState<{ kind: 'role' | 'remove'; id: string } | null>(null)
  const lock = useRef(false), returnFocus = useRef<HTMLElement | null>(null)
  const [roleFailure, setRoleFailure] = useState<RoleFailure | null>(null)
  const [deletion, setDeletion] = useState<TenantMember | null>(null), [deleteError, setDeleteError] = useState('')
  const [demotion, setDemotion] = useState<RoleTarget | null>(null), [updatedId, setUpdatedId] = useState('')
  const members = useMemo(() => membersQuery.data ?? [], [membersQuery.data])
  const accountId = access.data?.account_id
  const canManage = tenantAccessAllows(access.data, TENANT_PERMISSIONS.SETTINGS_WRITE)
  const admins = activeAdminCount(members)
  const filtered = useMemo(() => filterMembers(members, query, role, scope, accountId), [members, query, role, scope, accountId])
  const paged = pageMembers(filtered, page, size)
  const blocked = Boolean(busy) || membersQuery.isFetching || membersQuery.isError

  async function refresh() {
    if (lock.current) return
    await membersQuery.refetch()
  }
  async function saveRole({ member, desired }: RoleTarget) {
    if (lock.current || !canManage || !member.user_id) return
    const restriction = roleChangeRestriction(member, desired, admins)
    if (restriction) { toast.error(restriction); return }
    lock.current = true
    setBusy({ kind: 'role', id: member.id }); setRoleFailure(null)
    try {
      await client.cancelQueries({ queryKey: MEMBERS_KEY })
      const updated = await rbacApi.patchTenantMemberRole(member.user_id, { role: desired })
      client.setQueryData<TenantMember[]>(MEMBERS_KEY, previous => previous?.map(item => item.id === member.id ? updated : item))
      setUpdatedId(member.id); setDemotion(null)
      toast.success(`${memberIdentity(updated).name}的角色已改为${roleLabel(updated.role)}`)
      // A successful write and a failed readback are different outcomes.
      await client.invalidateQueries({ queryKey: MEMBERS_KEY })
      if (isCurrentAccount(member, accountId)) await client.invalidateQueries({ queryKey: queryKeys.access.current })
    } catch (error) {
      setDemotion(null)
      setRoleFailure({ member, desired, message: formatApiError(error, '角色修改失败') })
    } finally { lock.current = false; setBusy(null) }
  }
  function requestRole(member: TenantMember, desired: MemberRole, trigger: HTMLElement) {
    if (blocked || desired === member.role) return
    returnFocus.current = trigger
    if (isCurrentAccount(member, accountId) && !isAdministrator(desired)) {
      setRoleFailure(null); setDemotion({ member, desired }); return
    }
    void saveRole({ member, desired })
  }
  function openDeletion(member: TenantMember, trigger: HTMLElement) {
    const reason = removalRestriction(member, accountId, admins)
    if (reason) { toast.error(reason); return }
    returnFocus.current = trigger; setDeleteError(''); setDeletion(member)
  }
  async function removeMember() {
    if (lock.current || !canManage || !deletion?.user_id) return
    const member = deletion, reason = removalRestriction(member, accountId, admins)
    if (reason) { setDeleteError(reason); return }
    lock.current = true; setBusy({ kind: 'remove', id: member.id }); setDeleteError('')
    try {
      await client.cancelQueries({ queryKey: MEMBERS_KEY })
      const response = await rbacApi.removeTenantMember(member.user_id!)
      if (response.removed === false) throw new Error('成员未被移除，请重新读取成员列表。')
      client.setQueryData<TenantMember[]>(MEMBERS_KEY, previous => previous?.filter(item => item.id !== member.id))
      if (roleFailure?.member.id === member.id) setRoleFailure(null)
      setDeletion(null); toast.success(`已移除${memberIdentity(member).name}`)
      await client.invalidateQueries({ queryKey: MEMBERS_KEY })
    } catch (error) { setDeleteError(formatApiError(error, '移除成员失败')) }
    finally { lock.current = false; setBusy(null) }
  }
  async function copyId(id: string) {
    try { await navigator.clipboard.writeText(id); toast.success('已复制成员 ID') }
    catch (error) { toast.error(formatApiError(error, '复制失败，请选择成员 ID 手动复制')) }
  }
  function restoreFocus() {
    const target = returnFocus.current
    if (target?.isConnected) target.focus()
    else document.querySelector<HTMLElement>('[data-members-search]')?.focus()
  }
  return {
    access, membersQuery, members, admins, accountId, canManage, busy, blocked, query, role, scope, paged, size, updatedId, setUpdatedId,
    setQuery: (value: string) => { setQuery(value); setPage(1) },
    setRole: (value: string) => { setRole(value); setPage(1) },
    setScope: (value: MemberScope) => { setScope(value); setPage(1) },
    setSize: (value: number) => { setSize(value); setPage(1) }, setPage,
    clearFilters: () => { setQuery(''); setRole('all'); setScope('all'); setPage(1) },
    refresh, requestRole, saveRole, roleFailure, setRoleFailure, openDeletion, deletion, setDeletion, deleteError, removeMember, demotion, setDemotion, restoreFocus, copyId,
  }
}
export type MembersController = ReturnType<typeof useMembers>
