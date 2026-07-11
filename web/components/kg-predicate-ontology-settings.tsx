'use client'

import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Edit, Plus, RefreshCw, Save, Trash2 } from 'lucide-react'

import { kgApi, settingsApi } from '@/lib/api'
import { formatApiError, toApiErrorInfo } from '@/lib/api-errors'
import { queryKeys } from '@/lib/query-keys'
import { cn } from '@/lib/utils'
import type {
  KGPredicateOntologyCreateRequest,
  KGPredicateOntologyItem,
  KGPredicateOntologyUpdateRequest,
} from '@/types'

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'

type PredicateOntologySnapshot = {
  kgDisabled: boolean
  predicates: KGPredicateOntologyItem[]
}

export function KgPredicateOntologySettings() {
  const queryClient = useQueryClient()
  const [editingId, setEditingId] = useState<string | null>(null)

  const [formPredicate, setFormPredicate] = useState('')
  const [formDisplayName, setFormDisplayName] = useState('')
  const [formDescription, setFormDescription] = useState('')
  const [formEnabled, setFormEnabled] = useState(true)

  const [deleteOpen, setDeleteOpen] = useState(false)
  const [deleteTarget, setDeleteTarget] =
    useState<KGPredicateOntologyItem | null>(null)

  const settingsQuery = useQuery({
    queryKey: queryKeys.settings.snapshot,
    queryFn: settingsApi.get,
  })

  const settingsKgEnabled = Boolean(
    settingsQuery.data?.feature_flags?.kg_enabled
  )

  const predicateOntologyQuery = useQuery({
    queryKey: queryKeys.kg.predicateOntology,
    queryFn: async (): Promise<PredicateOntologySnapshot> => {
      try {
        const data = await kgApi.listPredicateOntology()
        return {
          kgDisabled: false,
          predicates: data.predicates || [],
        }
      } catch (err) {
        const info = toApiErrorInfo(err, '')
        if (info.status === 503 && /kg is disabled/i.test(info.message)) {
          return {
            kgDisabled: true,
            predicates: [],
          }
        }
        throw err
      }
    },
    enabled: settingsKgEnabled,
  })

  const kgEnabled =
    settingsQuery.isSuccess && settingsKgEnabled
      ? !predicateOntologyQuery.data?.kgDisabled
      : settingsQuery.isSuccess
        ? false
        : null

  const rows = kgEnabled ? predicateOntologyQuery.data?.predicates || [] : []
  const loading =
    settingsQuery.isPending ||
    (settingsKgEnabled && predicateOntologyQuery.isPending)

  const hasForm = useMemo(() => Boolean(formPredicate.trim()), [formPredicate])

  const resetForm = () => {
    setEditingId(null)
    setFormPredicate('')
    setFormDisplayName('')
    setFormDescription('')
    setFormEnabled(true)
  }

  const refreshStatus = () => {
    settingsQuery.refetch()
    if (settingsKgEnabled) {
      predicateOntologyQuery.refetch()
    }
  }

  const invalidatePredicateOntology = () => {
    queryClient.invalidateQueries({
      queryKey: queryKeys.kg.predicateOntology,
    })
  }

  const saveMutation = useMutation({
    mutationFn: (body: KGPredicateOntologyCreateRequest) =>
      kgApi.upsertPredicateOntology(body),
    onSuccess: () => {
      toast.success(editingId ? '已更新谓词' : '已添加谓词')
      resetForm()
      invalidatePredicateOntology()
    },
    onError: (err) => {
      toast.error(formatApiError(err, '保存失败'))
    },
  })

  const updateMutation = useMutation({
    mutationFn: ({
      predicateId,
      body,
    }: {
      predicateId: string
      body: KGPredicateOntologyUpdateRequest
    }) => kgApi.updatePredicateOntology(predicateId, body),
    onSuccess: () => {
      invalidatePredicateOntology()
    },
    onError: (err) => {
      toast.error(formatApiError(err, '更新失败'))
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (predicateId: string) =>
      kgApi.deletePredicateOntology(predicateId),
    onSuccess: () => {
      toast.success('已删除谓词')
      invalidatePredicateOntology()
    },
    onError: (err) => {
      toast.error(formatApiError(err, '删除失败'))
    },
    onSettled: () => {
      setDeleteOpen(false)
      setDeleteTarget(null)
    },
  })

  const saving =
    saveMutation.isPending ||
    updateMutation.isPending ||
    deleteMutation.isPending

  const saveForm = () => {
    const predicate = formPredicate.trim()
    if (!predicate) {
      toast.error('请输入谓词 key（snake_case）')
      return
    }

    saveMutation.mutate({
      predicate,
      display_name: formDisplayName.trim() || null,
      description: formDescription.trim() || null,
      is_enabled: formEnabled,
    })
  }

  const toggleEnabled = (row: KGPredicateOntologyItem, next: boolean) => {
    updateMutation.mutate({
      predicateId: String(row.id),
      body: {
        is_enabled: next,
      },
    })
  }

  const startEdit = (row: KGPredicateOntologyItem) => {
    setEditingId(String(row.id))
    setFormPredicate(row.predicate || '')
    setFormDisplayName(row.display_name || '')
    setFormDescription(row.description || '')
    setFormEnabled(Boolean(row.is_enabled))
  }

  const requestDelete = (row: KGPredicateOntologyItem) => {
    setDeleteTarget(row)
    setDeleteOpen(true)
  }

  const confirmDelete = () => {
    const target = deleteTarget
    if (!target) return
    deleteMutation.mutate(String(target.id))
  }

  return (
    <Card
      className={cn(
        'overflow-hidden rounded-xl border-border/60 bg-card shadow-none',
        loading ? 'opacity-60' : ''
      )}
    >
      <CardHeader className="space-y-1 border-b border-border/50 bg-muted/40 p-3">
        <div className="flex items-center justify-between gap-2">
          <CardTitle className="text-[13px] font-semibold text-foreground">
            KG 谓词治理
          </CardTitle>
          <span className="rounded-full border border-success/20 bg-success/10 px-2 py-0.5 text-[10px] font-semibold text-success">
            关系白名单
          </span>
        </div>
        <CardDescription className="text-[11px] leading-4 text-muted-foreground">
          限定关系抽取可输出的谓词，减少关系漂移和脏数据。
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3 p-3">
        {kgEnabled === false ? (
          <>
            <div className="flex items-center justify-between gap-3 rounded-lg border border-warning/30 bg-warning/5 px-3 py-2.5">
              <div className="min-w-0">
                <div className="text-[12px] font-semibold text-warning">
                  知识图谱未启用
                </div>
                <div className="mt-0.5 text-[11px] leading-4 text-warning">
                  启用后才能维护关系白名单。
                </div>
              </div>
              <Button
                type="button"
                size="sm"
                variant="outline"
                onClick={refreshStatus}
                disabled={loading || saving}
                className="h-7 shrink-0 gap-1.5 rounded-md border-warning/30 bg-card px-2.5 text-[11px] text-warning hover:bg-warning/10"
              >
                <RefreshCw className="w-3 h-3" />
                检查状态
              </Button>
            </div>

            <div className="rounded-lg border border-dashed border-border bg-muted/40 p-3">
              <div className="text-[12px] font-semibold text-foreground">
                当前不可编辑
              </div>
              <div className="mt-1 text-[11px] leading-4 text-muted-foreground">
                请先在系统设置中开启知识图谱能力，再返回这里配置谓词治理规则。
              </div>
            </div>
          </>
        ) : (
          <>
            <div className="flex items-center justify-between gap-2">
              <div className="text-[11px] text-muted-foreground">
                共 {rows.length} 条，已启用{' '}
                {rows.filter((r) => r.is_enabled).length} 条
              </div>
              <Button
                type="button"
                size="sm"
                variant="outline"
                onClick={refreshStatus}
                disabled={loading || saving}
                className="h-7 gap-1.5 rounded-md px-2.5 text-[11px]"
              >
                <RefreshCw className="w-3 h-3" />
                刷新
              </Button>
            </div>

            <div className="space-y-3 rounded-lg border border-border/60 bg-muted/40 p-3">
              <div className="flex items-center justify-between gap-2">
                <div className="text-[12px] font-semibold text-foreground">
                  {editingId ? '编辑谓词' : '新增谓词'}
                </div>
                <div className="flex items-center gap-2">
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    onClick={resetForm}
                    disabled={saving}
                    className="h-7 rounded-md px-2.5 text-[11px]"
                  >
                    重置
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    onClick={saveForm}
                    disabled={saving || !hasForm}
                    className="h-7 gap-1.5 rounded-md px-2.5 text-[11px]"
                  >
                    {editingId ? (
                      <Save className="w-3 h-3" />
                    ) : (
                      <Plus className="w-3 h-3" />
                    )}
                    保存
                  </Button>
                </div>
              </div>

              <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                <div className="space-y-1.5">
                  <Label
                    htmlFor="kg-onto-predicate"
                    className="text-[11px] font-medium text-muted-foreground"
                  >
                    谓词 key
                  </Label>
                  <Input
                    id="kg-onto-predicate"
                    value={formPredicate}
                    onChange={(e) => setFormPredicate(e.target.value)}
                    placeholder="例如：works_for"
                    className="h-8 font-mono text-[12px]"
                  />
                  <div className="text-[11px] text-muted-foreground">
                    系统会自动归一化为 snake_case。
                  </div>
                </div>
                <div className="space-y-1.5">
                  <Label
                    htmlFor="kg-onto-display"
                    className="text-[11px] font-medium text-muted-foreground"
                  >
                    展示名称
                  </Label>
                  <Input
                    id="kg-onto-display"
                    value={formDisplayName}
                    onChange={(e) => setFormDisplayName(e.target.value)}
                    placeholder="例如：Works For / 就职于"
                    className="h-8 text-[12px]"
                  />
                </div>
                <div className="space-y-1.5 md:col-span-2">
                  <Label
                    htmlFor="kg-onto-desc"
                    className="text-[11px] font-medium text-muted-foreground"
                  >
                    说明
                  </Label>
                  <Input
                    id="kg-onto-desc"
                    value={formDescription}
                    onChange={(e) => setFormDescription(e.target.value)}
                    placeholder="用于解释该 predicate 的语义与方向性"
                    className="h-8 text-[12px]"
                  />
                </div>
                <div className="flex items-center justify-between gap-2 md:col-span-2">
                  <div className="text-[12px]">
                    <div className="font-semibold text-foreground">
                      启用该谓词
                    </div>
                    <div className="text-[11px] text-muted-foreground">
                      关闭后抽取结果不会写入该关系。
                    </div>
                  </div>
                  <Switch
                    checked={formEnabled}
                    onCheckedChange={setFormEnabled}
                  />
                </div>
              </div>
            </div>

            <div className="overflow-hidden rounded-lg border border-border/60">
              <div className="grid grid-cols-[1fr_auto] gap-2 bg-muted/40 px-3 py-2 text-[10px] font-medium uppercase tracking-[0.12em] text-muted-foreground/70">
                <div>谓词</div>
                <div>状态</div>
              </div>
              <div className="divide-y divide-border/50">
                {rows.length === 0 ? (
                  <div className="p-3 text-[11px] text-muted-foreground">
                    暂无条目。可先添加常用关系，如
                    alias_of、part_of、works_for。
                  </div>
                ) : (
                  rows.map((r) => (
                    <div
                      key={r.id}
                      className="grid grid-cols-[1fr_auto] items-center gap-2 px-3 py-2.5"
                    >
                      <div className="min-w-0">
                        <div className="flex min-w-0 items-center gap-2">
                          <span
                            className="truncate font-mono text-xs"
                            title={r.predicate}
                          >
                            {r.predicate}
                          </span>
                          {r.display_name ? (
                            <span
                              className="truncate text-[11px] text-muted-foreground"
                              title={r.display_name}
                            >
                              {r.display_name}
                            </span>
                          ) : null}
                        </div>
                        {r.description ? (
                          <div
                            className="truncate text-[11px] text-muted-foreground"
                            title={r.description}
                          >
                            {r.description}
                          </div>
                        ) : null}
                        <div className="mt-1 flex items-center gap-2">
                          <Button
                            type="button"
                            size="sm"
                            variant="outline"
                            onClick={() => startEdit(r)}
                            className="h-7 gap-1 px-2 text-[11px]"
                          >
                            <Edit className="w-3 h-3" />
                            编辑
                          </Button>
                          <Button
                            type="button"
                            size="sm"
                            variant="outline"
                            onClick={() => requestDelete(r)}
                            className="h-7 gap-1 px-2 text-[11px] hover:bg-destructive/10 hover:text-destructive"
                          >
                            <Trash2 className="w-3 h-3" />
                            删除
                          </Button>
                        </div>
                      </div>

                      <div className="flex items-center justify-end">
                        <Switch
                          checked={Boolean(r.is_enabled)}
                          onCheckedChange={(v) => toggleEnabled(r, v)}
                        />
                      </div>
                    </div>
                  ))
                )}
              </div>
            </div>
          </>
        )}
      </CardContent>

      <AlertDialog
        open={deleteOpen}
        onOpenChange={(open) => {
          setDeleteOpen(open)
          if (!open) setDeleteTarget(null)
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>删除谓词？</AlertDialogTitle>
            <AlertDialogDescription>
              你将删除{' '}
              <span className="font-mono">
                {deleteTarget?.predicate || '-'}
              </span>
              <span>。此操作不可撤销（但可以重新创建）。</span>
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={saving}>取消</AlertDialogCancel>
            <AlertDialogAction onClick={confirmDelete} disabled={saving}>
              删除
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </Card>
  )
}
