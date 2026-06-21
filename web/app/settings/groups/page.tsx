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
type PageSizeOption = (typeof PAGE_SIZE_OPTIONS)[number]
const GROUP_PAGE_LIST_PARAMS = { limit: 500 } as const
const OUTLINE_BUTTON =
  'h-9 rounded-full border-border/60 bg-card/88 px-3.5 text-[12px] font-semibold text-foreground shadow-[0_6px_16px_hsl(var(--primary)/0.04)] hover:bg-muted/45'
const PRIMARY_BUTTON =
  'h-9 rounded-full bg-info px-3.5 text-[12px] font-semibold text-primary-foreground shadow-[0_8px_20px_hsl(var(--info)/0.24)] hover:bg-info/90'
const INPUT_CLASS =
  'h-10 rounded-xl border-border/60 bg-background/76 text-[13px] shadow-none placeholder:text-muted-foreground/60 focus-visible:border-primary/35 focus-visible:ring-2 focus-visible:ring-primary/10'
const CARD_CLASS =
  'rounded-[1.35rem] border border-border/60 bg-card/90 shadow-[0_14px_36px_hsl(var(--primary)/0.05)]'
const ICON_BUTTON =
  'size-8 rounded-xl text-muted-foreground hover:bg-destructive/10 hover:text-destructive'

function isPageSizeOption(value: number): value is PageSizeOption {
  return PAGE_SIZE_OPTIONS.includes(value as PageSizeOption)
}

type SummaryTone = 'primary' | 'info' | 'success' | 'muted'

type SummaryItem = {
  label: string
  value: string | number
  icon: ComponentType<{ className?: string }>
  tone: SummaryTone
  valueClassName?: string
}

const SUMMARY_TONE_CLASS: Record<SummaryTone, string> = {
  primary: 'border-primary/20 bg-primary/10 text-primary',
  info: 'border-info/20 bg-info/10 text-info',
  success: 'border-success/20 bg-success/10 text-success',
  muted: 'border-border/70 bg-muted/45 text-muted-foreground',
}

function getCreateStatusLabel(creating: boolean, createOpen: boolean): string {
  if (creating) return '创建中'
  if (createOpen) return '待创建'
  return '空闲'
}

function getListStatusLabel(loading: boolean, groupCount: number): string {
  if (loading) return '加载中'
  if (groupCount > 0) return '已就绪'
  return '无数据'
}

function getListStatusValueClassName(
  loading: boolean,
  groupCount: number
): string {
  if (loading) return 'text-warning'
  if (groupCount > 0) return 'text-success'
  return 'text-foreground'
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
    <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-4">
      {items.map((item, index) => {
        const Icon = item.icon
        const isTextValue = typeof item.value === 'string'
        return (
          <div
            key={item.label}
            className={cn(
              CARD_CLASS,
              'group relative min-h-[92px] overflow-hidden px-4 py-3.5',
              index === 0 && 'ring-1 ring-primary/5'
            )}
          >
            <div className="pointer-events-none absolute inset-x-4 top-0 h-px bg-gradient-to-r from-primary/25 via-primary/8 to-transparent" />
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
                  {item.label}
                </p>
                <p
                  className={cn(
                    'mt-2 leading-none tracking-[-0.035em] text-foreground',
                    isTextValue
                      ? 'inline-flex rounded-full border border-border/60 bg-muted/45 px-2.5 py-1 text-[12px] font-semibold tracking-normal'
                      : 'text-[24px] font-semibold',
                    item.valueClassName
                  )}
                >
                  {item.value}
                </p>
              </div>
              <div
                className={cn(
                  'flex size-9 shrink-0 items-center justify-center rounded-2xl border shadow-inner',
                  SUMMARY_TONE_CLASS[item.tone]
                )}
              >
                <Icon className="size-4" />
              </div>
            </div>
            <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-muted/50">
              <div
                className={cn(
                  'h-full rounded-full transition-all',
                  item.tone === 'success'
                    ? 'bg-success/55'
                    : item.tone === 'muted'
                      ? 'bg-muted-foreground/35'
                      : 'bg-primary/55'
                )}
                style={{
                  width:
                    typeof item.value === 'number'
                      ? `${Math.max(10, Math.min(100, item.value || 0))}%`
                      : '42%',
                }}
              />
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
  const hasVisibleGroups = visibleGroups.length > 0
  const summaryItems = useMemo<SummaryItem[]>(
    () => [
      { label: '组总数', value: groups.length, icon: Users, tone: 'primary' },
      { label: '筛选后', value: filtered.length, icon: Filter, tone: 'info' },
      {
        label: '创建状态',
        value: getCreateStatusLabel(creating, createOpen),
        icon: CheckCircle2,
        tone: 'success',
        valueClassName:
          creating || createOpen ? 'text-warning' : 'text-success',
      },
      {
        label: '列表状态',
        value: getListStatusLabel(loading, groups.length),
        icon: Database,
        tone: 'muted',
        valueClassName: getListStatusValueClassName(loading, groups.length),
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
        iconColor="text-primary"
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
                    <div className="text-xs leading-relaxed text-muted-foreground">
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
            'flex min-h-[calc(100dvh-22rem)] flex-1 flex-col overflow-hidden p-4'
          )}
        >
          <div className="mb-4 flex flex-col gap-3.5 rounded-2xl border border-border/55 bg-muted/18 p-3">
            <div className="flex items-center justify-between gap-4">
              <div className="flex items-center gap-3">
                <div className="flex size-9 items-center justify-center rounded-2xl border border-primary/20 bg-primary/10 text-primary shadow-inner">
                  <Users className="size-4" />
                </div>
                <div>
                  <h2 className="text-base font-semibold tracking-[-0.025em] text-foreground">
                    组列表
                  </h2>
                  <p className="mt-0.5 text-[12px] leading-5 text-muted-foreground">
                    管理组目录与外部身份映射，支持按名称、外部组 ID 或组 ID
                    过滤
                  </p>
                </div>
              </div>
              <Select
                value={String(pageSize)}
                onValueChange={(value) => {
                  const next = Number(value)
                  if (isPageSizeOption(next)) {
                    setPageSize(next)
                  }
                }}
              >
                <SelectTrigger className="h-9 w-[122px] rounded-xl border-border/60 bg-card/88 text-[12px] font-semibold shadow-none">
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

            <div className="flex flex-col gap-2 lg:flex-row lg:items-center lg:justify-between">
              <div className="relative w-full max-w-[560px]">
                <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground/70" />
                <Input
                  className={cn(INPUT_CLASS, 'pl-10')}
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="按名称 / 外部组 ID（external_id） / 组 ID 过滤"
                />
              </div>
              <div className="flex items-center gap-2 text-[11px] font-medium text-muted-foreground">
                <span className="rounded-full border border-border/60 bg-card/70 px-2.5 py-1">
                  可见 {visibleGroups.length} / {filtered.length}
                </span>
                <span className="rounded-full border border-border/60 bg-card/70 px-2.5 py-1">
                  每页 {pageSize}
                </span>
              </div>
            </div>
          </div>

          <div className="flex min-h-[440px] flex-1 flex-col overflow-hidden rounded-2xl border border-border/55 bg-background/42">
            <div className="grid grid-cols-12 bg-muted/38 px-4 py-2.5 text-[11px] font-semibold uppercase tracking-[0.1em] text-muted-foreground">
              <div className="col-span-5 flex items-center gap-2">
                <span>名称</span>
              </div>
              <div className="col-span-3 flex items-center gap-2">
                <span>外部组 ID</span>
              </div>
              <div className="col-span-3">组 ID</div>
              <div className="col-span-1 text-right">操作</div>
            </div>

            <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">
              {hasVisibleGroups ? (
                visibleGroups.map((g) => {
                  const gid = String(g.id || '').trim()
                  const deleting = Boolean(deletingId && deletingId === gid)
                  const initial = String(g.name || gid || '?')
                    .trim()
                    .slice(0, 1)
                    .toUpperCase()
                  return (
                    <div
                      key={gid}
                      className="grid grid-cols-12 items-center gap-3 border-t border-border/45 px-4 py-2.5 text-[12px] transition-colors hover:bg-primary/5"
                    >
                      <button
                        type="button"
                        className="col-span-5 flex min-w-0 items-center gap-2.5 text-left"
                        onClick={() =>
                          router.push(
                            `/settings/groups/${encodeURIComponent(gid)}`
                          )
                        }
                      >
                        <span className="flex size-8 shrink-0 items-center justify-center rounded-xl border border-primary/15 bg-primary/8 text-[12px] font-semibold text-primary">
                          {initial}
                        </span>
                        <div className="min-w-0">
                          <div className="truncate font-semibold text-foreground">
                            {g.name}
                          </div>
                          <div className="mt-0.5 text-[11px] text-muted-foreground">
                            点击查看成员与权限映射
                          </div>
                        </div>
                      </button>
                      <div
                        className="col-span-3 min-w-0 truncate rounded-full border border-border/50 bg-muted/35 px-2 py-1 font-mono text-[11px] text-muted-foreground"
                        title={g.external_id || '-'}
                      >
                        {g.external_id || '-'}
                      </div>
                      <div
                        className="col-span-3 min-w-0 truncate font-mono text-[11px] text-muted-foreground"
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
              ) : null}
              {!hasVisibleGroups && loading ? (
                <div className="flex min-h-[360px] flex-1 items-center justify-center text-[13px] text-muted-foreground">
                  加载中…
                </div>
              ) : null}
              {!hasVisibleGroups && !loading ? (
                <div className="flex min-h-[360px] flex-1 flex-col items-center justify-center border-t border-border/45 px-6 text-center">
                  <div className="relative mb-4 flex size-[72px] items-center justify-center rounded-[22px] border border-primary/15 bg-primary/10 text-primary shadow-inner">
                    <UsersRound className="size-9" />
                    <span className="absolute -right-1 top-2 size-2 rounded-full bg-primary/35" />
                    <span className="absolute -left-2 top-8 size-1.5 rounded-full bg-primary/25" />
                  </div>
                  <h3 className="text-lg font-semibold tracking-[-0.03em] text-foreground">
                    暂无组
                  </h3>
                  <p className="mt-2.5 max-w-md text-[13px] leading-6 text-muted-foreground">
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
              ) : null}
            </div>

            <div className="flex items-center justify-between border-t border-border/45 bg-muted/18 px-4 py-3 text-[13px] text-muted-foreground">
              <span>共 {filtered.length} 条</span>
              <div className="flex items-center gap-2">
                <Button
                  variant="outline"
                  size="icon"
                  className="size-8 rounded-xl border-border/60 bg-card/88"
                  disabled={page <= 1}
                  onClick={() => setPage((current) => Math.max(1, current - 1))}
                  aria-label="上一页"
                >
                  <ChevronLeft className="size-4" />
                </Button>
                <span className="flex h-8 min-w-8 items-center justify-center rounded-xl border border-primary/25 bg-primary/10 px-3 text-[13px] font-semibold text-primary">
                  {page}
                </span>
                <Button
                  variant="outline"
                  size="icon"
                  className="size-8 rounded-xl border-border/60 bg-card/88"
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
