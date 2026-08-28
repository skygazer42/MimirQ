'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import {
  ChevronLeft,
  ChevronRight,
  ListChecks,
  Loader2,
  RefreshCw,
  Search,
  ShieldCheck,
  Trash2,
  UserCog,
  UserPlus,
  Users,
  type LucideIcon,
} from 'lucide-react'
import { toast } from 'sonner'

import { TenantPermissionGate } from '@/components/auth/tenant-permission-gate'
import { AppFrame } from '@/components/app-frame'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { PageScaffold } from '@/components/ui/page-scaffold'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { formatApiError } from '@/lib/api-errors'
import { TENANT_PERMISSIONS } from '@/lib/tenant-permissions'
import { cn } from '@/lib/utils'
import { rbacApi, type TenantMember } from '@/lib/api'
import { queryKeys } from '@/lib/query-keys'
import { EmptyState } from '@/components/ui/empty-state'
import { SamlOpsPanel } from '@/components/settings/saml-ops-panel'
import { ScimProvisioningPanel } from '@/components/settings/scim-provisioning-panel'
import { useTenantAccess } from '@/hooks/use-tenant-access'

const ROLE_OPTIONS = [
  {
    key: 'owner',
    label: 'Owner',
    cn: 'border-primary/20 bg-primary/10 text-primary',
  },
  {
    key: 'admin',
    label: '管理员',
    cn: 'border-info/25 bg-info/10 text-info',
  },
  {
    key: 'auditor',
    label: '审计员',
    cn: 'border-warning/20 bg-warning/10 text-warning',
  },
  { key: 'editor', label: '编辑者', cn: 'border-info/25 bg-info/10 text-info' },
  {
    key: 'dataset_operator',
    label: '数据集运维',
    cn: 'border-success/20 bg-success/10 text-success',
  },
  {
    key: 'viewer',
    label: '查看者',
    cn: 'border-border/60 bg-muted/45 text-muted-foreground',
  },
]

const PAGE_SIZE_OPTIONS = [7, 10, 20, 50]
const RBAC_MEMBERS_PARAMS = { limit: 500 } as const
const CARD_CLASS =
  'rounded-xl border border-info/20 bg-background/72 shadow-none'
const RBAC_FIELD_LABEL_CLASS =
  'text-[10px] font-semibold uppercase tracking-[0.12em] text-muted-foreground'
const RBAC_INPUT_CLASS =
  'h-9 rounded-xl border-border/70 bg-muted/60 text-[12px] shadow-none focus-visible:border-info/35 focus-visible:ring-info/15'
const RBAC_SOFT_BUTTON_CLASS =
  'h-8 rounded-full border-border/60 bg-background/70 px-3 text-[11px] font-medium text-foreground shadow-none hover:border-info/25 hover:bg-info/[0.07] hover:text-info'
const RBAC_MUTED_CHIP_CLASS =
  'h-9 w-fit rounded-full border border-border/60 bg-background/65 px-3 text-[11px] font-medium text-muted-foreground'
const ROLE_DOT_TONES: Record<string, string> = {
  owner: 'bg-primary',
  admin: 'bg-info',
  auditor: 'bg-warning',
  editor: 'bg-info',
  dataset_operator: 'bg-success',
  viewer: 'bg-muted-foreground/55',
}

type RbacMembersSnapshot = {
  items: TenantMember[]
  total: number
}

function userDisplay(userId?: string | null) {
  const value = String(userId || '').trim()
  if (!value) return { primary: '未知成员', secondary: '缺少 user_id' }
  const [name, domain] = value.includes('@')
    ? value.split('@')
    : [value, 'user_id']
  return { primary: name || value, secondary: domain || value }
}

function initials(userId?: string | null) {
  const value = String(userId || '').trim()
  if (!value) return '?'
  const head = value.includes('@') ? value.split('@')[0] : value
  return head.slice(0, 1).toUpperCase()
}

function avatarTone(userId?: string | null) {
  const tones = [
    'border-primary/20 bg-primary/10 text-primary',
    'border-success/20 bg-success/10 text-success',
    'border-warning/20 bg-warning/10 text-warning',
    'border-info/25 bg-info/10 text-info',
    'border-border/60 bg-muted/55 text-muted-foreground',
  ]
  const raw = String(userId || '')
  const sum = raw.split('').reduce((acc, char) => acc + (char.codePointAt(0) ?? 0), 0)
  return tones[sum % tones.length]
}

function roleDotTone(roleKey: string): string {
  return ROLE_DOT_TONES[roleKey] ?? ROLE_DOT_TONES.viewer
}

function removeMemberDescription({
  canRemove,
  isSelf,
  displayName,
}: {
  canRemove: boolean
  isSelf: boolean
  displayName: string
}): string {
  if (canRemove) {
    return `将把 ${displayName} 从当前租户移除，并撤销组和显式访问授权`
  }
  if (isSelf) return '不能移除当前用户。请切换到其他管理员账号后再操作'
  return '缺少成员 ID，无法移除'
}

function fmtDateTime(value?: string | null) {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  })
    .format(date)
    .replaceAll('/', '-')
}

export default function SettingsRbacPage() {
  return (
    <TenantPermissionGate
      permission={TENANT_PERMISSIONS.SETTINGS_READ}
      pageName="成员权限"
    >
      <SettingsRbacPageContent />
    </TenantPermissionGate>
  )
}

function SettingsRbacPageContent() {
  const queryClient = useQueryClient()
  const tenantAccessQuery = useTenantAccess()
  const [roleDraft, setRoleDraft] = useState<Record<string, string>>({})
  const [savingIds, setSavingIds] = useState<Record<string, boolean>>({})
  const [removingIds, setRemovingIds] = useState<Record<string, boolean>>({})
  const [query, setQuery] = useState('')
  const [roleFilter, setRoleFilter] = useState('all')
  const [statusFilter, setStatusFilter] = useState('all')
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(7)

  const membersQuery = useQuery<RbacMembersSnapshot>({
    queryKey: queryKeys.rbac.members(RBAC_MEMBERS_PARAMS),
    retry: false,
    queryFn: async () => {
      try {
        const res = await rbacApi.listTenantMembers(RBAC_MEMBERS_PARAMS)
        const items = Array.isArray(res.items) ? res.items : []
        return {
          items,
          total: Number(res.total || items.length || 0),
        }
      } catch (err: unknown) {
        toast.error(formatApiError(err, '加载成员失败（需要管理员权限）'))
        throw err
      }
    },
  })

  const members = useMemo(
    () => membersQuery.data?.items || [],
    [membersQuery.data?.items]
  )
  const currentAccountId = String(tenantAccessQuery.data?.account_id || '').trim()
  const totalMembers = Number(membersQuery.data?.total ?? members.length)
  const loading = membersQuery.isFetching

  const filtered = useMemo(() => {
    const q = String(query || '')
      .trim()
      .toLowerCase()
    return (members || []).filter((m) => {
      const uid = String(m.user_id || '').toLowerCase()
      const role = String(m.role || '').toLowerCase()
      const matchesQuery = !q || uid.includes(q) || role.includes(q)
      const matchesRole = roleFilter === 'all' || role === roleFilter
      const matchesStatus =
        statusFilter === 'all' ||
        (statusFilter === 'current' && m.is_current) ||
        (statusFilter === 'members' && !m.is_current) ||
        (statusFilter === 'unassigned' && !role)
      return matchesQuery && matchesRole && matchesStatus
    })
  }, [members, query, roleFilter, statusFilter])

  const adminCount = useMemo(
    () =>
      members.filter((member) =>
        ['owner', 'admin'].includes(String(member.role || '').toLowerCase())
      ).length,
    [members]
  )
  const unassignedCount = useMemo(
    () => members.filter((member) => !String(member.role || '').trim()).length,
    [members]
  )
  const currentUserCount = useMemo(
    () => members.filter((member) => member.is_current).length,
    [members]
  )
  const pageCount = Math.max(1, Math.ceil(filtered.length / pageSize))
  const safePage = Math.min(page, pageCount)
  const pagedMembers = filtered.slice(
    (safePage - 1) * pageSize,
    safePage * pageSize
  )

  const saveRoleMutation = useMutation({
    mutationFn: async ({
      uid,
      desired,
    }: {
      uid: string
      desired: string
    }) => {
      return rbacApi.patchTenantMemberRole(uid, { role: desired })
    },
    onMutate: ({ uid }) => {
      setSavingIds((prev) => ({ ...prev, [uid]: true }))
    },
    onSuccess: (updated, { uid, desired }) => {
      queryClient.setQueryData<RbacMembersSnapshot>(
        queryKeys.rbac.members(RBAC_MEMBERS_PARAMS),
        (prev) => {
          const previousItems = Array.isArray(prev?.items) ? prev.items : []
          const nextItems = previousItems.map((member) =>
            String(member.user_id || '') === uid ? updated : member
          )
          return {
            items: nextItems.length ? nextItems : [updated],
            total: Number(prev?.total ?? (nextItems.length || 1)),
          }
        }
      )
      setRoleDraft((prev) => {
        const next = { ...prev }
        delete next[uid]
        return next
      })
      const roleLabel =
        ROLE_OPTIONS.find((option) => option.key === desired)?.label ??
        `角色键（${desired}）`
      toast.success(`已更新角色：${uid} -> ${roleLabel}`)
      queryClient.invalidateQueries({
        queryKey: queryKeys.rbac.members(RBAC_MEMBERS_PARAMS),
      })
    },
    onError: (err: unknown) => {
      toast.error(formatApiError(err, '更新角色失败'))
    },
    onSettled: (_data, _error, variables) => {
      if (!variables?.uid) return
      setSavingIds((prev) => ({ ...prev, [variables.uid]: false }))
    },
  })

  function saveRole(userId: string): void {
    const uid = String(userId || '').trim()
    if (!uid) return
    const currentRole =
      members.find((member) => String(member.user_id || '') === uid)?.role ||
      'viewer'
    const desired = String(roleDraft[uid] || currentRole || 'viewer').trim()
    saveRoleMutation.mutate({ uid, desired: desired || 'viewer' })
  }

  const removeMemberMutation = useMutation({
    mutationFn: async (uid: string) => rbacApi.removeTenantMember(uid),
    onMutate: (uid) => {
      setRemovingIds((prev) => ({ ...prev, [uid]: true }))
    },
    onSuccess: (_result, uid) => {
      queryClient.setQueryData<RbacMembersSnapshot>(
        queryKeys.rbac.members(RBAC_MEMBERS_PARAMS),
        (prev) => {
          const previousItems = Array.isArray(prev?.items) ? prev.items : []
          const nextItems = previousItems.filter(
            (member) => String(member.user_id || '') !== uid
          )
          return {
            items: nextItems,
            total: Math.max(0, Number(prev?.total ?? previousItems.length) - 1),
          }
        }
      )
      setRoleDraft((prev) => {
        const next = { ...prev }
        delete next[uid]
        return next
      })
      toast.success(`已移除成员：${uid}`)
      queryClient.invalidateQueries({
        queryKey: queryKeys.rbac.members(RBAC_MEMBERS_PARAMS),
      })
    },
    onError: (err: unknown) => {
      toast.error(formatApiError(err, '移除成员失败'))
    },
    onSettled: (_data, _error, uid) => {
      if (!uid) return
      setRemovingIds((prev) => ({ ...prev, [uid]: false }))
    },
  })

  function removeMember(userId: string): void {
    const uid = String(userId || '').trim()
    if (!uid) return
    removeMemberMutation.mutate(uid)
  }

  return (
    <AppFrame>
      <PageScaffold
        title="成员权限"
        description="管理成员角色、访问范围和权限状态"
        iconImage="members-rbac"
        icon={ShieldCheck}
        iconColor="text-primary"
        size="full"
        compact
        bodyGutter="dense"
        bodyClassName="bg-info/[0.035] !pb-3"
        headerClassName="[&_.text-muted-foreground]:text-muted-foreground"
        top={
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-4">
            <StatCard
              icon={Users}
              label="总成员"
              value={String(totalMembers || members.length)}
              detail="可管理成员"
              tone="blue"
            />
            <StatCard
              icon={UserCog}
              label="管理员"
              value={String(adminCount)}
              detail="高权限成员"
              tone="green"
            />
            <StatCard
              icon={UserPlus}
              label="未分配角色"
              value={String(unassignedCount)}
              detail="待补齐角色"
              tone="orange"
            />
            <StatCard
              icon={ListChecks}
              label="列表状态"
              value={loading ? '加载中' : '已就绪'}
              detail={
                currentUserCount
                  ? `当前登录账号 ${currentUserCount}`
                  : '成员列表状态'
              }
              tone={loading ? 'orange' : 'purple'}
              variant="status"
            />
          </div>
        }
        actions={
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              className={cn(RBAC_SOFT_BUTTON_CLASS, 'gap-2')}
              disabled={loading}
              onClick={() => {
                membersQuery.refetch()
              }}
            >
              <RefreshCw
                className={cn(
                  'size-4',
                  loading && 'animate-spin motion-reduce:animate-none'
                )}
              />
              刷新
            </Button>
          </div>
        }
      >
        <div className="grid grid-cols-1 gap-4">
          <section className={cn(CARD_CLASS, 'overflow-hidden')}>
            <div className="flex flex-col gap-3 border-b border-border/50 px-5 py-3 lg:flex-row lg:items-center lg:justify-between">
              <div className="flex items-center gap-3">
                <div className="flex size-9 items-center justify-center rounded-xl border border-info/20 bg-info/10 text-info">
                  <Users className="size-4" />
                </div>
                <div>
                  <h2 className="text-[15px] font-semibold tracking-[-0.01em] text-foreground">
                    成员管理
                  </h2>
                  <p className="mt-0.5 text-[12px] text-muted-foreground">
                    调整角色、移除成员，并同步当前访问控制状态
                  </p>
                </div>
              </div>
              <Button
                variant="outline"
                size="sm"
                className={cn(RBAC_SOFT_BUTTON_CLASS, 'w-fit gap-2')}
                disabled={loading}
                onClick={() => {
                  membersQuery.refetch()
                }}
              >
                <RefreshCw
                  className={cn(
                    'size-4',
                    loading && 'animate-spin motion-reduce:animate-none'
                  )}
                />
                刷新
              </Button>
            </div>

            <div className="px-5 py-3">
              <div className="grid gap-3 xl:grid-cols-[minmax(260px,1.1fr)_220px_220px_auto] xl:items-end">
                <div className="space-y-1.5">
                  <Label className={RBAC_FIELD_LABEL_CLASS}>
                    搜索成员
                  </Label>
                  <div className="relative">
                    <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
                    <Input
                      className={cn(RBAC_INPUT_CLASS, 'pl-9 placeholder:text-muted-foreground')}
                      value={query}
                      onChange={(e) => {
                        setQuery(e.target.value)
                        setPage(1)
                      }}
                      placeholder="搜索成员（名称 / 邮箱 / ID）"
                    />
                  </div>
                </div>
                <div className="space-y-1.5">
                  <Label className={RBAC_FIELD_LABEL_CLASS}>
                    角色
                  </Label>
                  <Select
                    value={roleFilter}
                    onValueChange={(value) => {
                      setRoleFilter(value)
                      setPage(1)
                    }}
                  >
                    <SelectTrigger className={RBAC_INPUT_CLASS}>
                      <SelectValue placeholder="全部角色" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="all">全部角色</SelectItem>
                      {ROLE_OPTIONS.map((role) => (
                        <SelectItem key={role.key} value={role.key}>
                          {role.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-1.5">
                  <Label className={RBAC_FIELD_LABEL_CLASS}>
                    状态
                  </Label>
                  <Select
                    value={statusFilter}
                    onValueChange={(value) => {
                      setStatusFilter(value)
                      setPage(1)
                    }}
                  >
                    <SelectTrigger className={RBAC_INPUT_CLASS}>
                      <SelectValue placeholder="全部状态" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="all">全部状态</SelectItem>
                      <SelectItem value="current">当前用户</SelectItem>
                      <SelectItem value="members">普通成员</SelectItem>
                      <SelectItem value="unassigned">未分配角色</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <Badge
                  variant="outline"
                  className={RBAC_MUTED_CHIP_CLASS}
                >
                  可见 {filtered.length} / {totalMembers || members.length}
                </Badge>
              </div>

              <div className="mt-3 overflow-hidden rounded-xl border border-border/60">
                <div className="overflow-x-auto">
                  <table className="min-w-[900px] w-full table-fixed border-collapse text-left">
                    <thead>
                      <tr className="border-b border-border/60 bg-info/[0.035] text-[10px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
                        <th className="w-[31%] px-3 py-2.5">成员</th>
                        <th className="w-[28%] px-3 py-2.5">邮箱 / ID</th>
                        <th className="w-[15%] px-3 py-2.5">角色</th>
                        <th className="w-[9%] px-3 py-2.5">状态</th>
                        <th className="w-[10%] px-3 py-2.5">最近更新</th>
                        <th className="w-[7%] px-3 py-2.5 text-right">操作</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-border/40 bg-background/45">
                      {pagedMembers.length ? (
                        pagedMembers.map((m) => {
                          const uid = String(m.user_id || '').trim()
                          const key = uid || String(m.id || '')
                          const draft = uid
                            ? String(roleDraft[uid] || m.role || 'viewer')
                            : String(m.role || 'viewer')
                          const saving = uid ? Boolean(savingIds[uid]) : false
                          const removing = uid ? Boolean(removingIds[uid]) : false
                          const display = userDisplay(uid)
                          const isSelf = Boolean(uid) && (
                            uid === currentAccountId ||
                            (!currentAccountId && m.is_current)
                          )
                          const canRemove = Boolean(uid) && !isSelf
                          const removeDescription = removeMemberDescription({
                            canRemove,
                            isSelf,
                            displayName: display.primary,
                          })
                          return (
                            <tr
                              key={key}
                              className="text-[13px] text-foreground transition-colors hover:bg-info/[0.04]"
                            >
                              <td className="px-3 py-2">
                                <div className="flex items-center gap-3">
                                  <div
                                    className={cn(
                                      'flex size-8 shrink-0 items-center justify-center rounded-full border text-[12px] font-semibold',
                                      avatarTone(uid)
                                    )}
                                  >
                                    {initials(uid)}
                                  </div>
                                  <div className="min-w-0">
                                    <div className="truncate font-semibold text-foreground" title={display.primary}>
                                      {display.primary}
                                    </div>
                                    <div className="truncate text-[12px] text-muted-foreground">
                                      {display.secondary}
                                    </div>
                                  </div>
                                </div>
                              </td>
                              <td className="px-3 py-2">
                                <div
                                  className="truncate font-mono text-[12px] text-muted-foreground"
                                  title={uid || '(无用户 ID / user_id)'}
                                >
                                  {uid || '(无用户 ID / user_id)'}
                                </div>
                              </td>
                              <td className="px-3 py-2">
                                <Select
                                  value={draft}
                                  onValueChange={(v) => {
                                    if (!uid) return
                                    setRoleDraft((prev) => ({
                                      ...prev,
                                      [uid]: v,
                                    }))
                                  }}
                                  disabled={!uid}
                                >
                                  <SelectTrigger className="h-8 min-w-0 rounded-full border-border/60 bg-background/70 text-[12px] shadow-none hover:border-info/25">
                                    <SelectValue placeholder="选择角色" />
                                  </SelectTrigger>
                                  <SelectContent>
                                    {ROLE_OPTIONS.map((r) => (
                                      <SelectItem key={r.key} value={r.key}>
                                        <span className="flex items-center gap-2">
                                          <span
                                            className={cn(
                                              'size-2 rounded-full',
                                              roleDotTone(r.key)
                                            )}
                                          />
                                          {r.label}
                                        </span>
                                      </SelectItem>
                                    ))}
                                  </SelectContent>
                                </Select>
                              </td>
                              <td className="px-3 py-2">
                                <Badge
                                  className={cn(
                                    'rounded-full border px-2 py-0.5 text-[11px] font-semibold shadow-none',
                                    isSelf
                                      ? 'border-info/25 bg-info/10 text-info'
                                      : 'border-success/20 bg-success/10 text-success'
                                  )}
                                >
                                  {isSelf ? '当前用户' : '已同步'}
                                </Badge>
                              </td>
                              <td className="px-3 py-2 text-[12px] text-muted-foreground">
                                {fmtDateTime(m.updated_at || m.created_at)}
                              </td>
                              <td className="px-3 py-2">
                                <div className="flex justify-end gap-1.5">
                                  <Button
                                    size="sm"
                                    data-rbac-save-role-action="true"
                                    aria-label={`保存 ${display.primary} 的角色`}
                                    className="h-8 rounded-full bg-info px-3 text-[12px] font-semibold text-info-foreground shadow-none hover:bg-info/90 disabled:bg-muted disabled:text-muted-foreground disabled:opacity-100"
                                    disabled={!uid || saving || removing}
                                    onClick={() => saveRole(uid)}
                                  >
                                    {saving ? '保存中' : '保存'}
                                  </Button>
                                  <ConfirmDialog
                                    title="移除成员？"
                                    description={removeDescription}
                                    confirmLabel="确认移除"
                                    confirmDisabled={!canRemove || removing}
                                    onConfirm={() => removeMember(uid)}
                                  >
                                    <Button
                                      variant="outline"
                                      size="icon"
                                      className="size-8 rounded-full border-destructive/20 bg-destructive/10 text-destructive hover:bg-destructive/15 hover:text-destructive disabled:opacity-50"
                                      disabled={!uid || removing}
                                      title={isSelf ? '查看不能移除当前用户的原因' : '移除成员'}
                                      aria-label={isSelf ? '不能移除当前用户' : `移除成员 ${display.primary}`}
                                    >
                                      {removing ? (
                                        <Loader2 className="size-3.5 animate-spin motion-reduce:animate-none" />
                                      ) : (
                                        <Trash2 className="size-3.5" />
                                      )}
                                    </Button>
                                  </ConfirmDialog>
                                </div>
                              </td>
                            </tr>
                          )
                        })
                      ) : (
                        <tr>
                          <td colSpan={6}>
                            {loading ? (
                              <div className="px-4 py-10 text-sm text-muted-foreground">
                                加载中...
                              </div>
                            ) : (
                              <EmptyState
                                icon={Users}
                                title="暂无成员"
                                description="还没有添加任何成员，或您没有查看权限"
                                className="rounded-none border-0 shadow-none"
                              />
                            )}
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>

                <div className="flex flex-col gap-3 border-t border-border/60 bg-info/[0.025] px-4 py-2.5 sm:flex-row sm:items-center sm:justify-between">
                  <div className="text-[12px] font-medium text-muted-foreground">
                    共 {filtered.length} 条
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <Select
                      value={String(pageSize)}
                      onValueChange={(value) => {
                        setPageSize(Number(value))
                        setPage(1)
                      }}
                    >
                      <SelectTrigger className="h-8 w-[116px] rounded-full border-border/60 bg-background/70 text-[12px] shadow-none">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {PAGE_SIZE_OPTIONS.map((option) => (
                          <SelectItem key={option} value={String(option)}>
                            {option} 条/页
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    <Button
                      variant="outline"
                      size="icon"
                      aria-label="上一页"
                      className="size-8 rounded-full border-border/60 bg-background/70 hover:border-info/25 hover:bg-info/[0.07] hover:text-info"
                      disabled={safePage <= 1}
                      onClick={() => setPage((value) => Math.max(1, value - 1))}
                    >
                      <ChevronLeft className="size-4" />
                    </Button>
                    <span className="rounded-full bg-info px-3 py-1.5 text-[12px] font-semibold text-info-foreground">
                      {safePage}
                    </span>
                    <Button
                      variant="outline"
                      size="icon"
                      aria-label="下一页"
                      className="size-8 rounded-full border-border/60 bg-background/70 hover:border-info/25 hover:bg-info/[0.07] hover:text-info"
                      disabled={safePage >= pageCount}
                      onClick={() =>
                        setPage((value) => Math.min(pageCount, value + 1))
                      }
                    >
                      <ChevronRight className="size-4" />
                    </Button>
                    <span className="text-[12px] text-muted-foreground">
                      / {pageCount} 页
                    </span>
                  </div>
                </div>
              </div>
            </div>
          </section>

          <ScimProvisioningPanel />
          <SamlOpsPanel />
        </div>
      </PageScaffold>
    </AppFrame>
  )
}

function StatCard({
  icon: Icon,
  label,
  value,
  detail,
  tone,
  variant = 'metric',
}: Readonly<{
  icon: LucideIcon
  label: string
  value: string
  detail: string
  tone: 'blue' | 'green' | 'orange' | 'purple'
  variant?: 'metric' | 'status'
}>) {
  const toneClass = {
    blue: 'border-info/25 bg-info/10 text-info',
    green: 'border-success/25 bg-success/10 text-success',
    orange: 'border-warning/25 bg-warning/10 text-warning',
    purple: 'border-info/25 bg-info/10 text-info',
  }[tone]
  const valueToneClass = {
    blue: 'text-info',
    green: 'text-success',
    orange: 'text-warning',
    purple: 'text-info',
  }[tone]
  const statusClass =
    value === '已就绪'
      ? 'border-success/20 bg-success/10 text-success'
      : 'border-warning/20 bg-warning/10 text-warning'

  return (
    <div
      className={cn(
        CARD_CLASS,
        'flex min-h-[58px] items-center gap-3 px-4 py-3'
      )}
    >
      <div
        className={cn(
          'flex size-8 shrink-0 items-center justify-center rounded-xl border',
          toneClass
        )}
      >
        <Icon className="size-4" />
      </div>
      <div className="min-w-0 flex-1">
        <p className="truncate text-[11px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
          {label}
        </p>
        {variant === 'status' ? (
          <div className="mt-1.5 flex min-w-0 items-center gap-2">
            <span
              className={cn(
                'inline-flex shrink-0 items-center gap-1.5 rounded-full border px-2.5 py-1 text-[13px] font-semibold leading-none',
                statusClass
              )}
            >
              <span className="size-1.5 rounded-full bg-current" />
              {value}
            </span>
          </div>
        ) : (
          <p
            className={cn(
              'mt-1 font-mono text-[22px] font-semibold leading-none tracking-[-0.045em] tabular-nums',
              valueToneClass
            )}
          >
            {value}
          </p>
        )}
        <p className="mt-1.5 truncate text-[10px] font-medium text-muted-foreground">
          {detail}
        </p>
      </div>
    </div>
  )
}
