/**
 * Settings - Tenant Group detail
 *
 * View/edit group and manage membership.
 */
'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { useParams } from 'next/navigation'
import { ArrowLeft, Loader2, RefreshCw, Save, Trash2, UserPlus, Users } from 'lucide-react'
import { toast } from 'sonner'

import { AppFrame } from '@/components/app-frame'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { PageScaffold } from '@/components/ui/page-scaffold'
import { Textarea } from '@/components/ui/textarea'
import { cn, formatDate, detachPromise } from '@/lib/utils'
import { formatApiError } from '@/lib/api-errors'
import { groupApi } from '@/lib/api'
import { useRouter } from '@/i18n/navigation'
import type { TenantGroupMemberOut, TenantGroupOut } from '@/types/backend'
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

function asGroupId(raw: unknown): string | null {
  if (typeof raw === 'string' && raw.trim()) return raw
  if (Array.isArray(raw) && typeof raw[0] === 'string') return raw[0]
  return null
}

function normalizeMemberIds(raw: string): { ids: string[]; error?: string } {
  const parts = (raw || '')
    .split(/[\n,;]+/g)
    .map((s) => s.trim())
    .filter(Boolean)

  const out: string[] = []
  const seen = new Set<string>()
  for (const p of parts) {
    if (seen.has(p)) continue
    seen.add(p)
    if (p.length > 255) {
      return { ids: [], error: 'member id 过长（max=255）' }
    }
    out.push(p)
    if (out.length >= 200) break
  }
  return { ids: out }
}

export default function SettingsGroupDetailPage() {
  const router = useRouter()
  const params = useParams()
  const groupId = asGroupId((params as any)?.id)

  const [group, setGroup] = useState<TenantGroupOut | null>(null)
  const [loadingGroup, setLoadingGroup] = useState(false)
  const [savingGroup, setSavingGroup] = useState(false)

  const [nameDraft, setNameDraft] = useState('')
  const [externalIdDraft, setExternalIdDraft] = useState('')

  const [members, setMembers] = useState<TenantGroupMemberOut[]>([])
  const [membersTotal, setMembersTotal] = useState(0)
  const [loadingMembers, setLoadingMembers] = useState(false)
  const [memberQuery, setMemberQuery] = useState('')

  const [addOpen, setAddOpen] = useState(false)
  const [addText, setAddText] = useState('')
  const [adding, setAdding] = useState(false)

  const [removingUserId, setRemovingUserId] = useState<string | null>(null)

  const loadGroup = useCallback(async () => {
    if (!groupId) return
    setLoadingGroup(true)
    try {
      const g = await groupApi.getGroup(groupId)
      setGroup(g)
      setNameDraft(String(g.name || ''))
      setExternalIdDraft(String(g.external_id || ''))
    } catch (err) {
      toast.error(formatApiError(err, '加载组详情失败'))
    } finally {
      setLoadingGroup(false)
    }
  }, [groupId])

  const loadMembers = useCallback(async () => {
    if (!groupId) return
    setLoadingMembers(true)
    try {
      const res = await groupApi.listGroupMembers(groupId, { limit: 500 })
      const items = Array.isArray(res.items) ? res.items : []
      setMembers(items)
      setMembersTotal(Number(res.total || items.length || 0))
    } catch (err) {
      toast.error(formatApiError(err, '加载成员失败'))
    } finally {
      setLoadingMembers(false)
    }
  }, [groupId])

  useEffect(() => {
    detachPromise(loadGroup())
    detachPromise(loadMembers())
  }, [loadGroup, loadMembers])

  const canSaveGroup = useMemo(() => {
    const name = String(nameDraft || '').trim()
    if (!name) return false
    if (name.length > 255) return false
    if (String(externalIdDraft || '').trim().length > 255) return false
    return true
  }, [nameDraft, externalIdDraft])

  const filteredMembers = useMemo(() => {
    const q = String(memberQuery || '').trim().toLowerCase()
    if (!q) return members
    return (members || []).filter((m) => String(m.user_id || '').toLowerCase().includes(q))
  }, [members, memberQuery])

  const saveGroup = async () => {
    if (!groupId) return
    const name = String(nameDraft || '').trim()
    const externalId = String(externalIdDraft || '').trim()
    if (!name) {
      toast.error('名称不能为空（name）')
      return
    }
    if (name.length > 255) {
      toast.error('名称过长（name，max=255）')
      return
    }
    if (externalId.length > 255) {
      toast.error('外部组 ID 过长（external_id，max=255）')
      return
    }

    setSavingGroup(true)
    try {
      const updated = await groupApi.patchGroup(groupId, {
        name,
        external_id: externalId || null,
      })
      setGroup(updated)
      setNameDraft(String(updated.name || ''))
      setExternalIdDraft(String(updated.external_id || ''))
      toast.success('已保存组信息')
    } catch (err) {
      toast.error(formatApiError(err, '保存失败'))
    } finally {
      setSavingGroup(false)
    }
  }

  const addMembers = async () => {
    if (!groupId) return
    const { ids, error } = normalizeMemberIds(addText)
    if (error) {
      toast.error(error)
      return
    }
    if (!ids.length) {
      toast.message('请输入至少 1 个成员 ID（user_id）')
      return
    }

    setAdding(true)
    try {
      const res = await groupApi.addGroupMembers(groupId, { member_ids: ids })
      toast.success(`已添加 ${res.updated} 个成员`)
      setAddText('')
      setAddOpen(false)
      await loadMembers()
    } catch (err) {
      toast.error(formatApiError(err, '添加成员失败'))
    } finally {
      setAdding(false)
    }
  }

  const removeMember = async (userId: string) => {
    if (!groupId) return
    const uid = String(userId || '').trim()
    if (!uid) return

    setRemovingUserId(uid)
    try {
      const res = await groupApi.removeGroupMembers(groupId, { member_ids: [uid] })
      toast.success(`已移除 ${res.updated} 个成员`)
      setMembers((prev) => (prev || []).filter((m) => String(m.user_id || '') !== uid))
      setMembersTotal((prev) => Math.max(0, prev - 1))
    } catch (err) {
      toast.error(formatApiError(err, '移除成员失败'))
    } finally {
      setRemovingUserId(null)
    }
  }

  const title = group?.name ? `组：${group.name}` : '组详情'

  return (
    <AppFrame>
      <PageScaffold
        title={title}
        description="编辑组信息，并维护组成员（user_id）。"
        icon={Users}
        iconColor="text-indigo-600 dark:text-indigo-400"
        size="6xl"
        actions={
          <div className="flex items-center gap-2">
            <Button variant="outline" size="sm" className="gap-2 rounded-xl" onClick={() => router.push('/settings/groups')}>
              <ArrowLeft className="size-4" />
              返回列表
            </Button>
            <Button
              variant="outline"
              size="sm"
              className="gap-2 rounded-xl"
              disabled={loadingGroup || loadingMembers}
              onClick={() => {
                detachPromise(loadGroup())
                detachPromise(loadMembers())
              }}
            >
              <RefreshCw className={cn('size-4', (loadingGroup || loadingMembers) && 'animate-spin motion-reduce:animate-none')} />
              刷新
            </Button>
            <Button size="sm" className="gap-2 rounded-xl" disabled={!canSaveGroup || savingGroup} onClick={() => detachPromise(saveGroup())}>
              {savingGroup ? <Loader2 className="size-4 animate-spin motion-reduce:animate-none" /> : <Save className="size-4" />}
              保存
            </Button>
          </div>
        }
      >
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          <Card className="h-fit">
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Users className="size-5" />
                基本信息
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="grid gap-2">
                <Label htmlFor="group-name">名称</Label>
                <Input
                  id="group-name"
                  value={nameDraft}
                  maxLength={255}
                  onChange={(e) => setNameDraft(e.target.value)}
                  placeholder="例如：研发 / 法务 / 财务"
                  disabled={loadingGroup}
                />
                <div className="text-xs text-muted-foreground">必填，最长 255 字符；名称在租户（tenant）内唯一。</div>
              </div>

              <div className="grid gap-2">
                <Label htmlFor="group-external-id">外部组 ID（external_id，可选）</Label>
                <Input
                  id="group-external-id"
                  value={externalIdDraft}
                  maxLength={255}
                  onChange={(e) => setExternalIdDraft(e.target.value)}
                  placeholder="例如：Okta/AzureAD 组 ID"
                  disabled={loadingGroup}
                />
                <div className="text-xs text-muted-foreground">
                  用于对齐外部身份提供方（IdP）/跨域身份管理（SCIM）的组标识（group）；留空表示不绑定。
                </div>
              </div>

              <div className="rounded-2xl border border-border bg-muted/20 p-3 text-xs text-muted-foreground space-y-1">
                <div>
                  组 ID（id）：<span className="font-mono">{group?.id || '-'}</span>
                </div>
                <div>
                  创建时间（created_at）：<span className="font-mono">{group?.created_at ? formatDate(group.created_at) : '-'}</span>
                </div>
                <div>
                  更新时间（updated_at）：<span className="font-mono">{group?.updated_at ? formatDate(group.updated_at) : '-'}</span>
                </div>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="space-y-2">
              <CardTitle className="flex items-center justify-between gap-3">
                <span className="flex items-center gap-2">
                  <Users className="size-5" />
                  成员
                </span>
                <span className="text-xs font-mono text-muted-foreground">{membersTotal} 人</span>
              </CardTitle>

              <div className="grid grid-cols-1 md:grid-cols-[1fr_auto] gap-3">
                <div className="space-y-2">
                  <Label>搜索</Label>
                  <Input
                    value={memberQuery}
                    onChange={(e) => setMemberQuery(e.target.value)}
                    placeholder="按成员 ID（user_id）过滤"
                  />
                </div>
                <div className="flex items-end">
                  <Dialog
                    open={addOpen}
                    onOpenChange={(open) => {
                      setAddOpen(open)
                      if (open) setAddText('')
                    }}
                  >
                    <DialogTrigger asChild>
                      <Button size="sm" className="gap-2 rounded-xl" disabled={!groupId}>
                        <UserPlus className="size-4" />
                        添加成员
                      </Button>
                    </DialogTrigger>
                    <DialogContent className="max-w-lg">
                      <DialogHeader>
                        <DialogTitle>添加成员</DialogTitle>
                        <DialogDescription className="text-sm">
                          输入成员 ID（user_id，每行一个或逗号分隔）。后端会失败关闭（fail-closed）：仅允许添加当前租户（tenant）已存在的成员。
                        </DialogDescription>
                      </DialogHeader>

                      <div className="space-y-2">
                        <Label htmlFor="group-members">成员列表</Label>
                        <Textarea
                          id="group-members"
                          value={addText}
                          onChange={(e) => setAddText(e.target.value)}
                          placeholder="alice\nbob\ncharlie"
                          className="font-mono text-sm"
                        />
                        <div className="text-xs text-muted-foreground">最多 200 个；单个成员 ID 最长 255 字符；重复会自动去重。</div>
                      </div>

                      <DialogFooter className="mt-4">
                        <Button variant="ghost" onClick={() => setAddOpen(false)} disabled={adding}>
                          取消
                        </Button>
                        <Button onClick={() => detachPromise(addMembers())} disabled={adding}>
                          {adding ? <Loader2 className="mr-2 size-4 animate-spin motion-reduce:animate-none" /> : null}
                          添加
                        </Button>
                      </DialogFooter>
                    </DialogContent>
                  </Dialog>
                </div>
              </div>
            </CardHeader>

            <CardContent>
              <div className="rounded-2xl border border-border overflow-hidden">
                <div className="grid grid-cols-12 text-xs font-semibold text-muted-foreground bg-muted/40 px-3 py-2">
                  <div className="col-span-7">成员 ID（user_id）</div>
                  <div className="col-span-4">加入时间（created_at）</div>
                  <div className="col-span-1 text-right">操作（actions）</div>
                </div>

                {filteredMembers.length ? (
                  filteredMembers.map((m) => {
                    const uid = String(m.user_id || '').trim()
                    const removing = Boolean(removingUserId && removingUserId === uid)
                    return (
                      <div key={uid} className="grid grid-cols-12 px-3 py-2 text-sm border-t border-border items-center gap-2">
                        <div className="col-span-7 font-mono text-xs truncate">{uid}</div>
                        <div className="col-span-4 font-mono text-xs text-muted-foreground truncate">
                          {m.created_at ? formatDate(m.created_at) : '-'}
                        </div>
                        <div className="col-span-1 flex justify-end">
                            <AlertDialog>
                            <AlertDialogTrigger asChild>
                              <Button
                                variant="ghost"
                                size="icon"
                                className="h-9 w-9"
                                 disabled={!uid || removing}
                                 aria-label={removing ? `正在移除成员 ${uid}` : `移除成员 ${uid}`}
                               >
                                 {removing ? (
                                   <Loader2 className="size-4 animate-spin motion-reduce:animate-none" />
                                 ) : (
                                   <Trash2 className="h-4 w-4" />
                                 )}
                               </Button>
                            </AlertDialogTrigger>
                            <AlertDialogContent>
                              <AlertDialogHeader>
                                <AlertDialogTitle>移除成员？</AlertDialogTitle>
                                <AlertDialogDescription>
                                  将把 <span className="font-mono">{uid}</span> 从该组移除。
                                </AlertDialogDescription>
                              </AlertDialogHeader>
                              <AlertDialogFooter>
                                <AlertDialogCancel>取消</AlertDialogCancel>
                                <AlertDialogAction onClick={() => detachPromise(removeMember(uid))} disabled={removing}>
                                  {removing ? '移除中…' : '移除'}
                                </AlertDialogAction>
                              </AlertDialogFooter>
                            </AlertDialogContent>
                          </AlertDialog>
                        </div>
                      </div>
                    )
                  })
                ) : (
                  <div className="px-3 py-8 text-sm text-muted-foreground">
                    {loadingMembers ? '加载中…' : '暂无成员（或无权限）'}
                  </div>
                )}
              </div>

              <div className="mt-3 text-xs text-muted-foreground">
                提示：成员使用租户成员 ID（tenant user_id）；添加时会校验租户成员关系（tenant membership，不存在则报错）。
              </div>
            </CardContent>
          </Card>
        </div>
      </PageScaffold>
    </AppFrame>
  )
}
