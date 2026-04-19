/**
 * 设置 - 租户组
 *
 * 用于列表/创建/删除组（group），服务于基于组的访问控制（ACL）。
 */
'use client'

import { useEffect, useMemo, useState } from 'react'
import { Plus, RefreshCw, Trash2, Users, UsersRound } from 'lucide-react'
import { toast } from 'sonner'

import { AppFrame } from '@/components/app-frame'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { PageScaffold } from '@/components/ui/page-scaffold'
import { Panel } from '@/components/ui/panel'
import { SystemDataStrip } from '@/components/ui/system-data-strip'
import { cn, detachPromise } from '@/lib/utils'
import { formatApiError } from '@/lib/api-errors'
import { groupApi } from '@/lib/api'
import { useRouter } from '@/i18n/navigation'
import type { TenantGroupOut } from '@/types/backend'
import { EmptyState } from '@/components/ui/empty-state'
import { systemDenseControls, systemPageTokens, systemWorkbenchTokens } from '@/components/ui/system-page-tokens'
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
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog'

const DENSE_OUTLINE_BUTTON = systemDenseControls.outlineButton
const DENSE_PRIMARY_BUTTON = systemDenseControls.primaryButton
const DENSE_INPUT = systemDenseControls.input
const DENSE_ICON_GHOST = 'h-7 w-7 rounded-md'
const DENSE_PANEL = systemWorkbenchTokens.panel

export default function SettingsGroupsPage() {
  const router = useRouter()
  const [loading, setLoading] = useState(false)
  const [groups, setGroups] = useState<TenantGroupOut[]>([])
  const [query, setQuery] = useState('')

  const [createOpen, setCreateOpen] = useState(false)
  const [creating, setCreating] = useState(false)
  const [nameDraft, setNameDraft] = useState('')
  const [externalIdDraft, setExternalIdDraft] = useState('')

  const [deletingId, setDeletingId] = useState<string | null>(null)

  const filtered = useMemo(() => {
    const q = String(query || '').trim().toLowerCase()
    if (!q) return groups
    return (groups || []).filter((g) => {
      const name = String(g.name || '').toLowerCase()
      const externalId = String(g.external_id || '').toLowerCase()
      const id = String(g.id || '').toLowerCase()
      return name.includes(q) || externalId.includes(q) || id.includes(q)
    })
  }, [groups, query])

  const canCreate = useMemo(() => String(nameDraft || '').trim().length > 0, [nameDraft])
  const stripItems = useMemo(
    () => [
      { label: '组总数', value: groups.length, mono: true },
      { label: '筛选后', value: filtered.length, mono: true },
      {
        label: '创建状态',
        value: creating ? '创建中' : createOpen ? '待创建' : '空闲',
        tone: creating ? 'warning' : createOpen ? 'default' : 'success',
      },
      {
        label: '列表状态',
        value: loading ? '加载中' : groups.length ? '已就绪' : '无数据',
        tone: loading ? 'warning' : groups.length ? 'success' : 'default',
      },
    ],
    [groups.length, filtered.length, creating, createOpen, loading]
  )

  async function refresh(): Promise<void> {
    setLoading(true)
    try {
      const res = await groupApi.listGroups({ limit: 500 })
      setGroups(Array.isArray(res.items) ? res.items : [])
    } catch (err) {
      toast.error(formatApiError(err, '加载组失败（需要管理员权限）'))
    } finally {
      setLoading(false)
    }
  }

  async function createGroup(): Promise<void> {
    if (!canCreate) return
    setCreating(true)
    try {
      const name = String(nameDraft || '').trim()
      const externalId = String(externalIdDraft || '').trim()
      const created = await groupApi.createGroup({
        name,
        external_id: externalId || undefined,
      })
      toast.success(`已创建组：${created.name}`)
      setCreateOpen(false)
      setNameDraft('')
      setExternalIdDraft('')
      await refresh()
    } catch (err) {
      toast.error(formatApiError(err, '创建组失败'))
    } finally {
      setCreating(false)
    }
  }

  async function deleteGroup(groupId: string): Promise<void> {
    const gid = String(groupId || '').trim()
    if (!gid) return
    setDeletingId(gid)
    try {
      await groupApi.deleteGroup(gid)
      toast.success('已删除组')
      setGroups((prev) => (prev || []).filter((g) => g.id !== gid))
    } catch (err) {
      toast.error(formatApiError(err, '删除组失败'))
    } finally {
      setDeletingId(null)
    }
  }

  useEffect(() => {
    detachPromise(refresh())
  }, [])

  return (
    <AppFrame>
      <PageScaffold
        title="组管理"
        description="管理租户组目录，用于数据集/文档访问控制与企业身份同步（开放ID连接 OIDC / 跨域身份管理 SCIM）。"
        icon={Users}
        iconColor="text-indigo-600 dark:text-indigo-400"
        size="full"
        density="system-dense"
        top={<SystemDataStrip items={stripItems} minColumnWidth={150} />}
        actions={
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              className={DENSE_OUTLINE_BUTTON}
              disabled={loading}
              onClick={() => detachPromise(refresh())}
            >
              <RefreshCw className={cn('size-4', loading && 'animate-spin motion-reduce:animate-none')} />
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
                <Button size="sm" className={DENSE_PRIMARY_BUTTON}>
                  <Plus className="size-4" />
                  新建组
                </Button>
              </DialogTrigger>
              <DialogContent className="max-w-lg">
                <DialogHeader>
                  <DialogTitle>新建组</DialogTitle>
                  <DialogDescription className="text-sm">
                    建议使用稳定命名；如需与外部身份提供方（IdP）对齐，可填写外部组 ID（`external_id`）。
                  </DialogDescription>
                </DialogHeader>

                <div className="grid gap-4">
                  <div className="grid gap-2">
                    <Label htmlFor="group-name">名称</Label>
                    <Input
                      className={DENSE_INPUT}
                      id="group-name"
                      value={nameDraft}
                      onChange={(e) => setNameDraft(e.target.value)}
                      placeholder="例如：研发 / 法务 / 财务"
                      autoComplete="off"
                    />
                  </div>
                  <div className="grid gap-2">
                    <Label htmlFor="group-external-id">外部组 ID（external_id，可选）</Label>
                    <Input
                      className={DENSE_INPUT}
                      id="group-external-id"
                      value={externalIdDraft}
                      onChange={(e) => setExternalIdDraft(e.target.value)}
                      placeholder="例如：Okta/AzureAD 组 ID"
                      autoComplete="off"
                    />
                    <div className={systemPageTokens.subtle}>
                      该字段用于开放ID连接组声明（OIDC groups claim）/ 跨域身份管理（SCIM）同步；留空不影响访问控制列表（ACL）使用。
                    </div>
                  </div>
                </div>

                <DialogFooter className="mt-4">
                  <Button variant="ghost" className="h-8 rounded-lg px-3 text-xs font-semibold" onClick={() => setCreateOpen(false)} disabled={creating}>
                    取消
                  </Button>
                  <Button className="h-8 rounded-lg px-3 text-xs font-semibold" onClick={() => detachPromise(createGroup())} disabled={!canCreate || creating}>
                    {creating ? '创建中…' : '创建'}
                  </Button>
                </DialogFooter>
              </DialogContent>
            </Dialog>
          </div>
        }
      >
        <div className="grid grid-cols-1 gap-4">
          <Panel padding="md" className={DENSE_PANEL}>
              <div className="mb-3 space-y-2">
              <div className="flex items-center justify-between gap-3">
                <span className={cn('flex items-center gap-2 text-sm', systemPageTokens.heading)}>
                  <Users className="size-5" />
                  组列表
                </span>
                <Badge variant="outline" className="font-mono text-[11px]">
                  {filtered.length} 条
                </Badge>
              </div>
              <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
                <div className="w-full space-y-1 sm:max-w-sm">
                  <Label className={systemPageTokens.microLabel}>搜索</Label>
                  <Input className={DENSE_INPUT} value={query} onChange={(e) => setQuery(e.target.value)} placeholder="按名称 / 外部组 ID（external_id）/ 组 ID 过滤" />
                </div>
                <div className={cn(systemPageTokens.subtle, 'hidden sm:block')}>
                  名称 / 外部组 ID（external_id）/ 组 ID
                </div>
              </div>
            </div>

            <div>
              <div className="overflow-hidden rounded-lg border border-border/70">
                <div className={cn('grid grid-cols-12 bg-muted/40 px-3 py-2', systemPageTokens.tableHead)}>
                  <div className="col-span-5">名称</div>
                  <div className="col-span-3">外部组 ID（external_id）</div>
                  <div className="col-span-3">组 ID</div>
                  <div className="col-span-1 text-right">操作</div>
                </div>

                {(filtered || []).length ? (
                  (filtered || []).map((g) => {
                    const gid = String(g.id || '').trim()
                    const deleting = Boolean(deletingId && deletingId === gid)
                    return (
                      <div
                        key={gid}
                        className="grid grid-cols-12 items-center gap-2 border-t border-border/70 px-3 py-1 text-[12px] transition-colors hover:bg-muted/20"
                      >
                        <button
                          type="button"
                          className="col-span-5 text-left min-w-0"
                          onClick={() => router.push(`/settings/groups/${encodeURIComponent(gid)}`)}
                        >
                          <div className="truncate font-semibold">{g.name}</div>
                        </button>
                        <div className="col-span-3 min-w-0 truncate font-mono text-[11px] text-muted-foreground" title={g.external_id || '-'}>
                          {g.external_id || '-'}
                        </div>
                        <div className="col-span-3 min-w-0 truncate font-mono text-[11px] text-muted-foreground" title={gid}>
                          {gid}
                        </div>
                        <div className="col-span-1 flex justify-end">
                          <AlertDialog>
                            <AlertDialogTrigger asChild>
                              <Button
                                variant="ghost"
                                size="icon"
                                className={DENSE_ICON_GHOST}
                                disabled={!gid || deleting}
                                aria-label="删除组"
                              >
                                <Trash2 className={cn('size-4', deleting && 'opacity-60')} />
                              </Button>
                            </AlertDialogTrigger>
                            <AlertDialogContent>
                              <AlertDialogHeader>
                                <AlertDialogTitle>删除组？</AlertDialogTitle>
                                <AlertDialogDescription>
                                  将删除组 <span className="font-mono">{g.name}</span>（{gid.slice(0, 8)}…）。此操作不可撤销。
                                  <div className="mt-2 text-xs text-muted-foreground">
                                    注意：若该组被用于数据集/文档允许列表（allowlist），删除前请先移除引用。
                                  </div>
                                </AlertDialogDescription>
                              </AlertDialogHeader>
                              <AlertDialogFooter>
                                <AlertDialogCancel>取消</AlertDialogCancel>
                                <AlertDialogAction onClick={() => detachPromise(deleteGroup(gid))} disabled={deleting}>
                                  {deleting ? '删除中…' : '删除'}
                                </AlertDialogAction>
                              </AlertDialogFooter>
                            </AlertDialogContent>
                          </AlertDialog>
                        </div>
                      </div>
                    )
                  })
                ) : (
                  loading ? (
                    <div className="px-3 py-8 text-sm text-muted-foreground">加载中…</div>
                  ) : (
                    <EmptyState
                      icon={UsersRound}
                      title="暂无组"
                      description="还没有创建任何组，或您没有查看权限。"
                      className="rounded-none border-0 border-t border-border shadow-none"
                    />
                  )
                )}
              </div>
            </div>
          </Panel>
        </div>
      </PageScaffold>
    </AppFrame>
  )
}
