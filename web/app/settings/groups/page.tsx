/**
 * Settings - Tenant Groups
 *
 * List/create/delete groups for group-based ACL.
 */
'use client'

import { useEffect, useMemo, useState } from 'react'
import { Plus, RefreshCw, Trash2, Users, UsersRound } from 'lucide-react'
import { toast } from 'sonner'

import { AppFrame } from '@/components/app-frame'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { PageScaffold } from '@/components/ui/page-scaffold'
import { cn, detachPromise } from '@/lib/utils'
import { formatApiError } from '@/lib/api-errors'
import { groupApi } from '@/lib/api'
import { useRouter } from '@/i18n/navigation'
import type { TenantGroupOut } from '@/types/backend'
import { EmptyState } from '@/components/ui/empty-state'
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

  async function refresh(): Promise<void> {
    setLoading(true)
    try {
      const res = await groupApi.listGroups({ limit: 500 })
      setGroups(Array.isArray(res.items) ? res.items : [])
    } catch (err) {
      toast.error(formatApiError(err, '加载组失败（需要 owner/admin 权限）'))
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
        title="组（Groups）"
        description="管理 tenant 内的组目录，用于数据集/文档 ACL 与企业身份同步（OIDC/SCIM）。"
        icon={Users}
        iconColor="text-indigo-600 dark:text-indigo-400"
        size="6xl"
        actions={
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              className="gap-2 rounded-xl"
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
                <Button size="sm" className="gap-2 rounded-xl">
                  <Plus className="size-4" />
                  新建组
                </Button>
              </DialogTrigger>
              <DialogContent className="max-w-lg">
                <DialogHeader>
                  <DialogTitle>新建组</DialogTitle>
                  <DialogDescription className="text-sm">
                    建议使用稳定的命名；如需与外部 IdP 对齐，可填写 external_id。
                  </DialogDescription>
                </DialogHeader>

                <div className="grid gap-4">
                  <div className="grid gap-2">
                    <Label htmlFor="group-name">名称</Label>
                    <Input
                      id="group-name"
                      value={nameDraft}
                      onChange={(e) => setNameDraft(e.target.value)}
                      placeholder="例如：engineering / legal / finance"
                      autoComplete="off"
                    />
                  </div>
                  <div className="grid gap-2">
                    <Label htmlFor="group-external-id">external_id（可选）</Label>
                    <Input
                      id="group-external-id"
                      value={externalIdDraft}
                      onChange={(e) => setExternalIdDraft(e.target.value)}
                      placeholder="例如：Okta/AzureAD group id"
                      autoComplete="off"
                    />
                    <div className="text-xs text-muted-foreground">
                      该字段用于 OIDC groups claim / SCIM 等外部同步场景；留空不影响 ACL 使用。
                    </div>
                  </div>
                </div>

                <DialogFooter className="mt-4">
                  <Button variant="ghost" onClick={() => setCreateOpen(false)} disabled={creating}>
                    取消
                  </Button>
                  <Button onClick={() => detachPromise(createGroup())} disabled={!canCreate || creating}>
                    {creating ? '创建中…' : '创建'}
                  </Button>
                </DialogFooter>
              </DialogContent>
            </Dialog>
          </div>
        }
      >
        <div className="grid grid-cols-1 gap-6">
          <Card>
            <CardHeader className="space-y-2">
              <CardTitle className="flex items-center justify-between gap-3">
                <span className="flex items-center gap-2">
                  <Users className="size-5" />
                  Groups
                </span>
                <span className="text-xs font-mono text-muted-foreground">{filtered.length} items</span>
              </CardTitle>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                <div className="space-y-2">
                  <Label>搜索</Label>
                  <Input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="按 name / external_id / id 过滤" />
                </div>
              </div>
            </CardHeader>

            <CardContent>
              <div className="rounded-2xl border border-border overflow-hidden">
                <div className="grid grid-cols-12 text-xs font-semibold text-muted-foreground bg-muted/40 px-3 py-2">
                  <div className="col-span-5">name</div>
                  <div className="col-span-4">external_id</div>
                  <div className="col-span-2">id</div>
                  <div className="col-span-1 text-right">actions</div>
                </div>

                {(filtered || []).length ? (
                  (filtered || []).map((g) => {
                    const gid = String(g.id || '').trim()
                    const deleting = Boolean(deletingId && deletingId === gid)
                    return (
                      <div
                        key={gid}
                        className="grid grid-cols-12 px-3 py-2 text-sm border-t border-border items-center gap-2 hover:bg-muted/20 transition-colors"
                      >
                        <button
                          type="button"
                          className="col-span-5 text-left min-w-0"
                          onClick={() => router.push(`/settings/groups/${encodeURIComponent(gid)}`)}
                        >
                          <div className="font-semibold truncate">{g.name}</div>
                        </button>
                        <div className="col-span-4 min-w-0 text-muted-foreground truncate font-mono text-xs">
                          {g.external_id || '-'}
                        </div>
                        <div className="col-span-2 min-w-0 font-mono text-xs text-muted-foreground truncate">
                          {gid.slice(0, 8)}
                        </div>
                        <div className="col-span-1 flex justify-end">
                          <AlertDialog>
                            <AlertDialogTrigger asChild>
                              <Button
                                variant="ghost"
                                size="icon"
                                className="h-9 w-9"
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
                                    注意：若该组被用于数据集/文档 allowlist，删除前请先移除引用。
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
            </CardContent>
          </Card>
        </div>
      </PageScaffold>
    </AppFrame>
  )
}
