/**
 * Settings - Tenant Group detail
 *
 * View/edit group and manage membership.
 */
'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { useParams } from 'next/navigation'
import { ArrowLeft, Loader2, RefreshCw, Save, Trash2, UserPlus, Users } from 'lucide-react'
import { toast } from 'sonner'

import { TenantPermissionGate } from '@/components/auth/tenant-permission-gate'
import { AppFrame } from '@/components/app-frame'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { PageScaffold } from '@/components/ui/page-scaffold'
import { Textarea } from '@/components/ui/textarea'
import { cn, formatDate } from '@/lib/utils'
import { formatApiError } from '@/lib/api-errors'
import { TENANT_PERMISSIONS } from '@/lib/tenant-permissions'
import { groupApi } from '@/lib/api'
import { queryKeys } from '@/lib/query-keys'
import { useRouter } from '@/i18n/navigation'
import type { TenantGroupMemberListResponse, TenantGroupMemberOut, TenantGroupOut } from '@/types/backend'
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

const GROUP_MEMBERS_PARAMS = { limit: 500 } as const

type GroupDraft = {
  groupId: string
  name: string
  externalId: string
}

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
  return (
    <TenantPermissionGate permission={TENANT_PERMISSIONS.SETTINGS_READ} pageName="组管理">
      <SettingsGroupDetailPageContent />
    </TenantPermissionGate>
  )
}

function SettingsGroupDetailPageContent() {
  const router = useRouter()
  const queryClient = useQueryClient()
  const params = useParams<{ id?: string | string[] }>()
  const groupId = asGroupId(params?.id)

  const groupDetailQueryKey = queryKeys.groups.detail(groupId || '')
  const membersQueryKey = queryKeys.groups.members(groupId || '', GROUP_MEMBERS_PARAMS)

  const [draft, setDraft] = useState<GroupDraft | null>(null)
  const [memberQuery, setMemberQuery] = useState('')

  const [addOpen, setAddOpen] = useState(false)
  const [addText, setAddText] = useState('')

  const [removingUserId, setRemovingUserId] = useState<string | null>(null)

  const groupQuery = useQuery<TenantGroupOut | null>({
    queryKey: groupDetailQueryKey,
    enabled: Boolean(groupId),
    retry: false,
    queryFn: async () => {
      if (!groupId) return null
      try {
        return await groupApi.getGroup(groupId)
      } catch (err: unknown) {
        toast.error(formatApiError(err, '加载组详情失败'))
        throw err
      }
    },
  })

  const membersQuery = useQuery<TenantGroupMemberListResponse>({
    queryKey: membersQueryKey,
    enabled: Boolean(groupId),
    retry: false,
    queryFn: async () => {
      if (!groupId) return { items: [], total: 0 }
      try {
        return await groupApi.listGroupMembers(groupId, GROUP_MEMBERS_PARAMS)
      } catch (err: unknown) {
        toast.error(formatApiError(err, '加载成员失败'))
        throw err
      }
    },
  })

  const group = groupQuery.data
  const activeDraft = draft?.groupId === groupId ? draft : null
  const nameDraft = activeDraft?.name ?? String(group?.name || '')
  const externalIdDraft = activeDraft?.externalId ?? String(group?.external_id || '')
  const members = useMemo<TenantGroupMemberOut[]>(() => {
    const items = membersQuery.data?.items
    return Array.isArray(items) ? items : []
  }, [membersQuery.data?.items])
  const membersTotal = Number(membersQuery.data?.total ?? members.length)
  const loadingGroup = groupQuery.isFetching
  const loadingMembers = membersQuery.isFetching

  const updateDraft = (patch: Partial<Omit<GroupDraft, 'groupId'>>) => {
    setDraft({
      groupId: groupId || '',
      name: patch.name ?? nameDraft,
      externalId: patch.externalId ?? externalIdDraft,
    })
  }

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

  const saveGroupMutation = useMutation({
    mutationFn: async ({ name, externalId }: { name: string; externalId: string }) => {
      if (!groupId) throw new Error('缺少组 ID')
      return groupApi.patchGroup(groupId, {
        name,
        external_id: externalId || null,
      })
    },
    onSuccess: (updated) => {
      queryClient.setQueryData(queryKeys.groups.detail(updated.id), updated)
      setDraft({
        groupId: updated.id,
        name: String(updated.name || ''),
        externalId: String(updated.external_id || ''),
      })
      toast.success('已保存组信息')
      void queryClient.invalidateQueries({ queryKey: queryKeys.groups.all })
    },
    onError: (err: unknown) => {
      toast.error(formatApiError(err, '保存失败'))
    },
  })

  const addMembersMutation = useMutation({
    mutationFn: async (ids: string[]) => {
      if (!groupId) throw new Error('缺少组 ID')
      return groupApi.addGroupMembers(groupId, { member_ids: ids })
    },
    onSuccess: (res) => {
      toast.success(`已添加 ${res.updated} 个成员`)
      setAddText('')
      setAddOpen(false)
      void queryClient.invalidateQueries({ queryKey: membersQueryKey })
    },
    onError: (err: unknown) => {
      toast.error(formatApiError(err, '添加成员失败'))
    },
  })

  const removeMemberMutation = useMutation({
    mutationFn: async (userId: string) => {
      if (!groupId) throw new Error('缺少组 ID')
      return groupApi.removeGroupMembers(groupId, { member_ids: [userId] })
    },
    onMutate: (userId) => {
      setRemovingUserId(userId)
    },
    onSuccess: (res, userId) => {
      toast.success(`已移除 ${res.updated} 个成员`)
      queryClient.setQueryData<TenantGroupMemberListResponse>(membersQueryKey, (prev) => {
        const previousItems = Array.isArray(prev?.items) ? prev.items : []
        const nextItems = previousItems.filter((m) => String(m.user_id || '') !== userId)
        return {
          items: nextItems,
          total: Math.max(0, Number(prev?.total ?? previousItems.length) - 1),
        }
      })
      void queryClient.invalidateQueries({ queryKey: membersQueryKey })
    },
    onError: (err: unknown) => {
      toast.error(formatApiError(err, '移除成员失败'))
    },
    onSettled: () => {
      setRemovingUserId(null)
    },
  })

  const saveGroup = () => {
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

    saveGroupMutation.mutate({ name, externalId })
  }

  const addMembers = () => {
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

    addMembersMutation.mutate(ids)
  }

  const removeMember = (userId: string) => {
    if (!groupId) return
    const uid = String(userId || '').trim()
    if (!uid) return

    removeMemberMutation.mutate(uid)
  }

  const title = group?.name ? `组：${group.name}` : '组详情'
  const savingGroup = saveGroupMutation.isPending
  const adding = addMembersMutation.isPending

  return (
    <AppFrame>
      <PageScaffold
        title={title}
        description="编辑组信息，并维护组成员（user_id）"
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
                void groupQuery.refetch()
                void membersQuery.refetch()
              }}
            >
              <RefreshCw className={cn('size-4', (loadingGroup || loadingMembers) && 'animate-spin motion-reduce:animate-none')} />
              刷新
            </Button>
            <Button size="sm" className="gap-2 rounded-xl" disabled={!canSaveGroup || savingGroup} onClick={saveGroup}>
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
                  onChange={(e) => updateDraft({ name: e.target.value })}
                  placeholder="例如：研发 / 法务 / 财务"
                  disabled={loadingGroup}
                />
                <div className="text-xs text-muted-foreground">必填，最长 255 字符；名称在租户（tenant）内唯一</div>
              </div>

              <div className="grid gap-2">
                <Label htmlFor="group-external-id">外部组 ID</Label>
                <Input
                  id="group-external-id"
                  value={externalIdDraft}
                  maxLength={255}
                  onChange={(e) => updateDraft({ externalId: e.target.value })}
                  placeholder="例如：Okta/AzureAD 组 ID"
                  disabled={loadingGroup}
                />
                <div className="text-xs text-muted-foreground">
                  用于对齐外部身份提供方（IdP）/跨域身份管理（SCIM）的组标识（group）；留空表示不绑定
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
                          输入成员 ID（user_id，每行一个或逗号分隔）后端会失败关闭（fail-closed）：仅允许添加当前租户（tenant）已存在的成员
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
                        <div className="text-xs text-muted-foreground">最多 200 个；单个成员 ID 最长 255 字符；重复会自动去重</div>
                      </div>

                      <DialogFooter className="mt-4">
                        <Button variant="ghost" onClick={() => setAddOpen(false)} disabled={adding}>
                          取消
                        </Button>
                        <Button onClick={addMembers} disabled={adding}>
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
                                  将把 <span className="font-mono">{uid}</span> 从该组移除
                                </AlertDialogDescription>
                              </AlertDialogHeader>
                              <AlertDialogFooter>
                                <AlertDialogCancel>取消</AlertDialogCancel>
                                <AlertDialogAction onClick={() => removeMember(uid)} disabled={removing}>
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
                提示：成员使用租户成员 ID（tenant user_id）；添加时会校验租户成员关系（tenant membership，不存在则报错）
              </div>
            </CardContent>
          </Card>
        </div>
      </PageScaffold>
    </AppFrame>
  )
}
