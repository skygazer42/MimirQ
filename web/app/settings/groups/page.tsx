/**
 * 设置 - 租户组
 *
 * 用于列表/创建/删除组（group），服务于基于组的访问控制（ACL）
 */
'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useState, type ComponentType } from 'react'
import {
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Database,
  Filter,
  Plus,
  RefreshCw,
  Search,
  Trash2,
  Users,
  UsersRound,
} from 'lucide-react'
import { toast } from 'sonner'

import { TenantPermissionGate } from '@/components/auth/tenant-permission-gate'
import { AppFrame } from '@/components/app-frame'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { PageScaffold } from '@/components/ui/page-scaffold'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { cn } from '@/lib/utils'
import { formatApiError } from '@/lib/api-errors'
import { TENANT_PERMISSIONS } from '@/lib/tenant-permissions'
import { groupApi } from '@/lib/api'
import { useRouter } from '@/i18n/navigation'
import type { TenantGroupOut } from '@/types/backend'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import { queryKeys } from '@/lib/query-keys'

const PAGE_SIZE_OPTIONS = [10, 20, 50] as const
const GROUP_PAGE_LIST_PARAMS = { limit: 500 } as const
const OUTLINE_BUTTON =
  'h-9 rounded-xl border-slate-200 bg-card px-3.5 text-[12px] font-semibold text-slate-700 shadow-sm hover:bg-slate-50'
const PRIMARY_BUTTON =
  'h-9 rounded-xl bg-info px-3.5 text-[12px] font-semibold text-primary-foreground shadow-[0_8px_20px_hsl(var(--info)/0.24)] hover:bg-info/90'
const INPUT_CLASS =
  'h-10 rounded-xl border-slate-200 bg-card text-[13px] shadow-sm placeholder:text-slate-400 focus-visible:ring-blue-500/30'
const CARD_CLASS =
  'rounded-[20px] border border-slate-200/80 bg-card/92 shadow-[0_18px_44px_rgba(15,23,42,0.06)]'
const ICON_BUTTON =
  'size-7 rounded-lg text-slate-500 hover:bg-slate-100 hover:text-slate-900'

type SummaryTone = 'indigo' | 'blue' | 'green' | 'slate'

type SummaryItem = {
  label: string
  value: string | number
  icon: ComponentType<{ className?: string }>
  tone: SummaryTone
  valueClassName?: string
}

const SUMMARY_TONE_CLASS: Record<SummaryTone, string> = {
  indigo: 'bg-indigo-50 text-indigo-600',
  blue: 'bg-blue-50 text-blue-600',
  green: 'bg-emerald-50 text-emerald-600',
  slate: 'bg-slate-100 text-slate-500',
}

export default function SettingsGroupsPage() {
  return (
    <TenantPermissionGate
      permission={TENANT_PERMISSIONS.SETTINGS_READ}
      pageName="组管理"
    >
      <SettingsGroupsPageContent />
    </TenantPermissionGate>
  )
}

function GroupSummaryStrip({ items }: Readonly<{ items: SummaryItem[] }>) {
  return (
    <div
      className={cn(
        CARD_CLASS,
        'grid min-h-[112px] grid-cols-1 overflow-hidden md:grid-cols-2 xl:grid-cols-4'
      )}
    >
      {items.map((item, index) => {
        const Icon = item.icon
        return (
          <div
            key={item.label}
            className={cn(
              'flex items-center justify-between gap-3.5 px-6 py-5',
              index > 0 && 'border-t border-slate-100 md:border-l md:border-t-0'
            )}
          >
            <div className="min-w-0">
              <p className="text-[12px] font-semibold text-slate-500">
                {item.label}
              </p>
              <p
                className={cn(
                  'mt-2.5 text-[23px] font-semibold leading-none tracking-[-0.04em] text-slate-950',
                  item.valueClassName
                )}
              >
                {item.value}
              </p>
            </div>
            <div
              className={cn(
                'flex size-11 shrink-0 items-center justify-center rounded-2xl',
                SUMMARY_TONE_CLASS[item.tone]
              )}
            >
              <Icon className="size-5" />
            </div>
          </div>
        )
      })}
    </div>
  )
}

function SettingsGroupsPageContent() {
  const router = useRouter()
  const queryClient = useQueryClient()
  const [query, setQuery] = useState('')
  const [pageSize, setPageSize] =
    useState<(typeof PAGE_SIZE_OPTIONS)[number]>(10)
  const [page, setPage] = useState(1)

  const [createOpen, setCreateOpen] = useState(false)
  const [nameDraft, setNameDraft] = useState('')
  const [externalIdDraft, setExternalIdDraft] = useState('')

  const [deletingId, setDeletingId] = useState<string | null>(null)
  const groupsQuery = useQuery<TenantGroupOut[]>({
    queryKey: queryKeys.groups.list(GROUP_PAGE_LIST_PARAMS),
    retry: false,
    queryFn: async () => {
      try {
        const res = await groupApi.listGroups(GROUP_PAGE_LIST_PARAMS)
        return Array.isArray(res.items) ? res.items : []
      } catch (err: unknown) {
        toast.error(formatApiError(err, '加载组失败（需要管理员权限）'))
        throw err
      }
    },
  })
  const groups = useMemo(() => groupsQuery.data || [], [groupsQuery.data])
  const loading = groupsQuery.isFetching
  const createMutation = useMutation({
    mutationFn: async () => {
      const name = String(nameDraft || '').trim()
      const externalId = String(externalIdDraft || '').trim()
      return groupApi.createGroup({
        name,
        external_id: externalId || undefined,
      })
    },
    onSuccess: (created) => {
      toast.success(`已创建组：${created.name}`)
      setCreateOpen(false)
      setNameDraft('')
      setExternalIdDraft('')
      queryClient.invalidateQueries({ queryKey: queryKeys.groups.all })
    },
    onError: (err: unknown) => {
      toast.error(formatApiError(err, '创建组失败'))
    },
  })
  const deleteMutation = useMutation({
    mutationFn: async (groupId: string) => {
      await groupApi.deleteGroup(groupId)
      return groupId
    },
    onMutate: (groupId) => {
      setDeletingId(groupId)
    },
    onSuccess: (groupId) => {
      toast.success('已删除组')
      queryClient.setQueryData<TenantGroupOut[]>(
        queryKeys.groups.list(GROUP_PAGE_LIST_PARAMS),
        (prev) => (prev || []).filter((g) => g.id !== groupId)
      )
      queryClient.invalidateQueries({ queryKey: queryKeys.groups.all })
    },
    onError: (err: unknown) => {
      toast.error(formatApiError(err, '删除组失败'))
    },
    onSettled: () => {
      setDeletingId(null)
    },
  })
  const creating = createMutation.isPending

  const filtered = useMemo(() => {
    const q = String(query || '')
      .trim()
      .toLowerCase()
    if (!q) return groups
    return (groups || []).filter((g) => {
      const name = String(g.name || '').toLowerCase()
      const externalId = String(g.external_id || '').toLowerCase()
      const id = String(g.id || '').toLowerCase()
      return name.includes(q) || externalId.includes(q) || id.includes(q)
    })
  }, [groups, query])

  const canCreate = useMemo(
    () => String(nameDraft || '').trim().length > 0,
    [nameDraft]
  )
  const pageCount = useMemo(
    () => Math.max(1, Math.ceil(filtered.length / pageSize)),
    [filtered.length, pageSize]
  )
  const visibleGroups = useMemo(() => {
    const start = (page - 1) * pageSize
    return filtered.slice(start, start + pageSize)
  }, [filtered, page, pageSize])
  const summaryItems = useMemo<SummaryItem[]>(
    () => [
      { label: '组总数', value: groups.length, icon: Users, tone: 'indigo' },
      { label: '筛选后', value: filtered.length, icon: Filter, tone: 'blue' },
      {
        label: '创建状态',
        value: creating ? '创建中' : createOpen ? '待创建' : '空闲',
        icon: CheckCircle2,
        tone: 'green',
        valueClassName:
          creating || createOpen ? 'text-amber-600' : 'text-emerald-600',
      },
      {
        label: '列表状态',
        value: loading ? '加载中' : groups.length ? '已就绪' : '无数据',
        icon: Database,
        tone: 'slate',
        valueClassName: loading
          ? 'text-amber-600'
          : groups.length
            ? 'text-emerald-600'
            : 'text-slate-950',
      },
    ],
    [groups.length, filtered.length, creating, createOpen, loading]
  )

  useEffect(() => {
    setPage(1)
  }, [query, pageSize])

  useEffect(() => {
    setPage((current) => Math.min(Math.max(1, current), pageCount))
  }, [pageCount])

  return (
    <AppFrame>
      <PageScaffold
        title="组管理"
        description="管理组织目录、成员归属和访问范围"
        iconImage="group-management"
        icon={Users}
        iconColor="text-indigo-600 dark:text-indigo-400"
        size="full"
        compact={false}
        headerClassName="[&_h1]:!text-[27px] [&_h1]:md:!text-[29px] [&_h1]:!leading-tight [&_h1]:!tracking-[-0.035em]"
        topClassName="pb-2.5"
        bodyClassName="pt-1.5"
        bodyContainerClassName="flex min-h-full flex-col"
        top={<GroupSummaryStrip items={summaryItems} />}
        actions={
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              className={OUTLINE_BUTTON}
              disabled={loading}
              onClick={() => {
                groupsQuery.refetch()
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

            <Dialog
              open={createOpen}
              onOpenChange={(open) => {
                setCreateOpen(open)
                if (open) {
                  setNameDraft('')
                  setExternalIdDraft('')
                }
              }}
            >
              <DialogTrigger asChild>
                <Button
                  size="sm"
                  data-settings-groups-create-action="true"
                  className={PRIMARY_BUTTON}
                >
                  <Plus className="size-4" />
                  新建组
                </Button>
              </DialogTrigger>
              <DialogContent className="max-w-lg">
                <DialogHeader>
                  <DialogTitle>新建组</DialogTitle>
                  <DialogDescription className="text-sm">
                    建议使用稳定命名；需要对接企业身份目录时填写外部组 ID
                  </DialogDescription>
                </DialogHeader>

                <div className="grid gap-4">
                  <div className="grid gap-2">
                    <Label htmlFor="group-name">名称</Label>
                    <Input
                      className={INPUT_CLASS}
                      id="group-name"
                      value={nameDraft}
                      onChange={(e) => setNameDraft(e.target.value)}
                      placeholder="例如：研发 / 法务 / 财务"
                      autoComplete="off"
                    />
                  </div>
                  <div className="grid gap-2">
                    <Label htmlFor="group-external-id">
                      外部组 ID（external_id）
                    </Label>
                    <Input
                      className={INPUT_CLASS}
                      id="group-external-id"
                      value={externalIdDraft}
                      onChange={(e) => setExternalIdDraft(e.target.value)}
                      placeholder="例如：Okta/AzureAD 组 ID"
                      autoComplete="off"
                    />
                    <div className="text-xs leading-relaxed text-slate-500">
                      用于企业身份同步；留空不影响组权限
                    </div>
                  </div>
                </div>

                <DialogFooter className="mt-4">
                  <Button
                    variant="ghost"
                    className="h-8 rounded-lg px-3 text-xs font-semibold"
                    onClick={() => setCreateOpen(false)}
                    disabled={creating}
                  >
                    取消
                  </Button>
                  <Button
                    className="h-8 rounded-lg px-3 text-xs font-semibold"
                    onClick={() => {
                      if (!canCreate) return
                      createMutation.mutate()
                    }}
                    disabled={!canCreate || creating}
                  >
                    {creating ? '创建中…' : '创建'}
                  </Button>
                </DialogFooter>
              </DialogContent>
            </Dialog>
          </div>
        }
      >
        <div
          className={cn(
            CARD_CLASS,
            'flex min-h-[calc(100dvh-22rem)] flex-1 flex-col p-5'
          )}
        >
          <div className="mb-5 flex flex-col gap-3.5">
            <div className="flex items-center justify-between gap-4">
              <div className="flex items-center gap-3">
                <div className="flex size-8 items-center justify-center rounded-xl bg-slate-100 text-slate-700">
                  <Users className="size-4" />
                </div>
                <div>
                  <h2 className="text-base font-semibold tracking-[-0.02em] text-slate-950">
                    组列表
                  </h2>
                  <p className="mt-1 text-[13px] text-slate-500">
                    管理组目录与外部身份映射，支持按名称、外部组 ID 或组 ID
                    过滤
                  </p>
                </div>
              </div>
              <Select
                value={String(pageSize)}
                onValueChange={(value) => {
                  const next = Number(value)
                  if (
                    PAGE_SIZE_OPTIONS.includes(
                      next as (typeof PAGE_SIZE_OPTIONS)[number]
                    )
                  ) {
                    setPageSize(next as (typeof PAGE_SIZE_OPTIONS)[number])
                  }
                }}
              >
                <SelectTrigger className="h-9 w-[122px] rounded-xl border-slate-200 bg-card text-[13px] font-medium shadow-sm">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent align="end">
                  {PAGE_SIZE_OPTIONS.map((size) => (
                    <SelectItem key={size} value={String(size)}>
                      每页 {size} 条
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="relative max-w-[500px]">
              <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-slate-400" />
              <Input
                className={cn(INPUT_CLASS, 'pl-10')}
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="按名称 / 外部组 ID（external_id） / 组 ID 过滤"
              />
            </div>
          </div>

          <div className="flex min-h-[440px] flex-1 flex-col overflow-hidden rounded-2xl border border-slate-200">
            <div className="grid grid-cols-12 bg-slate-50 px-4 py-2.5 text-[12px] font-semibold text-slate-800">
              <div className="col-span-5 flex items-center gap-2">
                <span>名称</span>
                <span className="text-slate-400">↕</span>
              </div>
              <div className="col-span-3 flex items-center gap-2">
                <span>外部组 ID</span>
                <span className="text-slate-400">↕</span>
              </div>
              <div className="col-span-3">组 ID</div>
              <div className="col-span-1 text-right">操作</div>
            </div>

            <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">
              {visibleGroups.length ? (
                visibleGroups.map((g) => {
                  const gid = String(g.id || '').trim()
                  const deleting = Boolean(deletingId && deletingId === gid)
                  return (
                    <div
                      key={gid}
                      className="grid grid-cols-12 items-center gap-3 border-t border-slate-100 px-4 py-2.5 text-[12px] transition-colors hover:bg-blue-50/40"
                    >
                      <button
                        type="button"
                        className="col-span-5 text-left min-w-0"
                        onClick={() =>
                          router.push(
                            `/settings/groups/${encodeURIComponent(gid)}`
                          )
                        }
                      >
                        <div className="truncate font-semibold text-slate-900">
                          {g.name}
                        </div>
                      </button>
                      <div
                        className="col-span-3 min-w-0 truncate font-mono text-[11px] text-slate-500"
                        title={g.external_id || '-'}
                      >
                        {g.external_id || '-'}
                      </div>
                      <div
                        className="col-span-3 min-w-0 truncate font-mono text-[11px] text-slate-500"
                        title={gid}
                      >
                        {gid}
                      </div>
                      <div className="col-span-1 flex justify-end">
                        <AlertDialog>
                          <AlertDialogTrigger asChild>
                            <Button
                              variant="ghost"
                              size="icon"
                              className={ICON_BUTTON}
                              disabled={!gid || deleting}
                              aria-label="删除组"
                            >
                              <Trash2
                                className={cn(
                                  'size-4',
                                  deleting && 'opacity-60'
                                )}
                              />
                            </Button>
                          </AlertDialogTrigger>
                          <AlertDialogContent>
                            <AlertDialogHeader>
                              <AlertDialogTitle>删除组？</AlertDialogTitle>
                              <AlertDialogDescription>
                                将删除组{' '}
                                <span className="font-mono">{g.name}</span>（
                                {gid.slice(0, 8)}…）此操作不可撤销
                                <div className="mt-2 text-xs text-muted-foreground">
                                  注意：若该组被用于数据集/文档允许列表（allowlist），删除前请先移除引用
                                </div>
                              </AlertDialogDescription>
                            </AlertDialogHeader>
                            <AlertDialogFooter>
                              <AlertDialogCancel>取消</AlertDialogCancel>
                              <AlertDialogAction
                                onClick={() => {
                                  if (!gid) return
                                  deleteMutation.mutate(gid)
                                }}
                                disabled={deleting}
                              >
                                {deleting ? '删除中…' : '删除'}
                              </AlertDialogAction>
                            </AlertDialogFooter>
                          </AlertDialogContent>
                        </AlertDialog>
                      </div>
                    </div>
                  )
                })
              ) : loading ? (
                <div className="flex min-h-[360px] flex-1 items-center justify-center text-[13px] text-slate-500">
                  加载中…
                </div>
              ) : (
                <div className="flex min-h-[360px] flex-1 flex-col items-center justify-center border-t border-slate-100 px-6 text-center">
                  <div className="relative mb-4 flex size-[72px] items-center justify-center rounded-[22px] bg-blue-50 text-blue-500 shadow-inner">
                    <UsersRound className="size-9" />
                    <span className="absolute -right-1 top-2 size-2 rounded-full bg-blue-300" />
                    <span className="absolute -left-2 top-8 size-1.5 rounded-full bg-blue-200" />
                  </div>
                  <h3 className="text-lg font-semibold tracking-[-0.03em] text-slate-950">
                    暂无组
                  </h3>
                  <p className="mt-2.5 max-w-md text-[13px] leading-6 text-slate-500">
                    还没有创建任何组，或您没有查看权限
                  </p>
                  <Button
                    data-settings-groups-create-action="true"
                    className={cn(PRIMARY_BUTTON, 'mt-5')}
                    onClick={() => setCreateOpen(true)}
                  >
                    <Plus className="size-4" />
                    新建组
                  </Button>
                </div>
              )}
            </div>

            <div className="flex items-center justify-between border-t border-slate-100 px-4 py-3 text-[13px] text-slate-500">
              <span>共 {filtered.length} 条</span>
              <div className="flex items-center gap-2">
                <Button
                  variant="outline"
                  size="icon"
                  className="size-8 rounded-lg border-slate-200 bg-card"
                  disabled={page <= 1}
                  onClick={() => setPage((current) => Math.max(1, current - 1))}
                  aria-label="上一页"
                >
                  <ChevronLeft className="size-4" />
                </Button>
                <span className="flex h-8 min-w-8 items-center justify-center rounded-lg border border-blue-500 bg-card px-3 text-[13px] font-semibold text-blue-600">
                  {page}
                </span>
                <Button
                  variant="outline"
                  size="icon"
                  className="size-8 rounded-lg border-slate-200 bg-card"
                  disabled={page >= pageCount}
                  onClick={() =>
                    setPage((current) => Math.min(pageCount, current + 1))
                  }
                  aria-label="下一页"
                >
                  <ChevronRight className="size-4" />
                </Button>
              </div>
            </div>
          </div>
        </div>
      </PageScaffold>
    </AppFrame>
  )
}
