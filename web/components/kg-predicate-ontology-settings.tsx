'use client'

import { useEffect, useMemo, useState } from 'react'
import { toast } from 'sonner'
import { Edit, Plus, RefreshCw, Save, Trash2 } from 'lucide-react'

import { kgApi, settingsApi } from '@/lib/api'
import { formatApiError, toApiErrorInfo } from '@/lib/api-errors'
import { cn } from '@/lib/utils'
import type { KGPredicateOntologyItem } from '@/types'

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
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

export function KgPredicateOntologySettings() {
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [kgEnabled, setKgEnabled] = useState<boolean | null>(null)

  const [rows, setRows] = useState<KGPredicateOntologyItem[]>([])
  const [editingId, setEditingId] = useState<string | null>(null)

  const [formPredicate, setFormPredicate] = useState('')
  const [formDisplayName, setFormDisplayName] = useState('')
  const [formDescription, setFormDescription] = useState('')
  const [formEnabled, setFormEnabled] = useState(true)

  const [deleteOpen, setDeleteOpen] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState<KGPredicateOntologyItem | null>(null)

  const load = async () => {
    setLoading(true)
    try {
      const settings = await settingsApi.get()
      const enabled = Boolean(settings.feature_flags?.kg_enabled)
      setKgEnabled(enabled)
      if (!enabled) {
        setRows([])
        return
      }

      const data = await kgApi.listPredicateOntology()
      setRows(data.predicates || [])
    } catch (err) {
      const info = toApiErrorInfo(err, '')
      if (info.status === 503 && /kg is disabled/i.test(info.message)) {
        setKgEnabled(false)
        setRows([])
        return
      }
      toast.error(formatApiError(err, '加载 Predicate Ontology 失败'))
      setRows([])
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [])

  const hasForm = useMemo(() => {
    return Boolean(formPredicate.trim())
  }, [formPredicate])

  const resetForm = () => {
    setEditingId(null)
    setFormPredicate('')
    setFormDisplayName('')
    setFormDescription('')
    setFormEnabled(true)
  }

  const saveForm = async () => {
    const predicate = formPredicate.trim()
    if (!predicate) {
      toast.error('请输入 predicate key（snake_case）')
      return
    }

    setSaving(true)
    try {
      await kgApi.upsertPredicateOntology({
        predicate,
        display_name: formDisplayName.trim() || null,
        description: formDescription.trim() || null,
        is_enabled: formEnabled,
      })
      toast.success(editingId ? '已更新 predicate' : '已添加 predicate')
      resetForm()
      await load()
    } catch (err) {
      toast.error(formatApiError(err, '保存失败'))
    } finally {
      setSaving(false)
    }
  }

  const toggleEnabled = async (row: KGPredicateOntologyItem, next: boolean) => {
    setSaving(true)
    try {
      const updated = await kgApi.updatePredicateOntology(String(row.id), { is_enabled: next })
      setRows((prev) => prev.map((r) => (r.id === updated.id ? (updated as any) : r)))
    } catch (err) {
      toast.error(formatApiError(err, '更新失败'))
    } finally {
      setSaving(false)
    }
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

  const confirmDelete = async () => {
    const target = deleteTarget
    if (!target) return
    setSaving(true)
    try {
      const next = await kgApi.deletePredicateOntology(String(target.id))
      setRows(next.predicates || [])
      toast.success('已删除 predicate')
    } catch (err) {
      toast.error(formatApiError(err, '删除失败'))
    } finally {
      setSaving(false)
      setDeleteOpen(false)
      setDeleteTarget(null)
    }
  }

  return (
    <Card className={cn(loading ? 'opacity-60' : '')}>
      <CardHeader>
        <CardTitle>KG Predicate Ontology（谓词治理）</CardTitle>
        <CardDescription>
          管理 KG triples 的 predicate allowlist。启用的 predicates 会被用于 KG relation 抽取（优先于环境变量与默认列表）。
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {kgEnabled === false ? (
          <>
            <div className="flex items-center justify-between gap-2">
              <div className="text-xs text-muted-foreground">KG 开关：关闭</div>
              <Button type="button" size="sm" variant="outline" onClick={load} disabled={loading || saving} className="gap-2">
                <RefreshCw className="w-3 h-3" />
                重新检查
              </Button>
            </div>

            <div className="rounded-xl border border-dashed border-border bg-muted/50 p-4">
              <div className="text-sm font-medium">KG 功能当前未启用</div>
              <div className="mt-1 text-xs leading-5 text-muted-foreground">
                当前环境未开启知识图谱能力，Predicate Ontology 不可编辑。请先在系统设置中开启 `KG_ENABLED`，再返回此处配置谓词治理规则。
              </div>
            </div>
          </>
        ) : (
          <>
            <div className="flex items-center justify-between gap-2">
              <div className="text-xs text-muted-foreground">
                共 {rows.length} 条（enabled: {rows.filter((r) => r.is_enabled).length}）
              </div>
              <Button type="button" size="sm" variant="outline" onClick={load} disabled={loading || saving} className="gap-2">
                <RefreshCw className="w-3 h-3" />
                刷新
              </Button>
            </div>

            <div className="rounded-xl border border-border bg-muted p-4 space-y-3">
              <div className="flex items-center justify-between gap-2">
                <div className="text-sm font-medium">{editingId ? '编辑 predicate' : '新增 predicate'}</div>
                <div className="flex items-center gap-2">
                  <Button type="button" size="sm" variant="outline" onClick={resetForm} disabled={saving}>
                    重置
                  </Button>
                  <Button type="button" size="sm" onClick={saveForm} disabled={saving || !hasForm} className="gap-2">
                    {editingId ? <Save className="w-3 h-3" /> : <Plus className="w-3 h-3" />}
                    保存
                  </Button>
                </div>
              </div>

              <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                <div className="space-y-2">
                  <Label htmlFor="kg-onto-predicate">predicate key</Label>
                  <Input
                    id="kg-onto-predicate"
                    value={formPredicate}
                    onChange={(e) => setFormPredicate(e.target.value)}
                    placeholder="例如：works_for"
                    className="font-mono"
                  />
                  <div className="text-[11px] text-muted-foreground">系统会自动 normalize（snake_case + 同义词映射）。</div>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="kg-onto-display">display name（可选）</Label>
                  <Input
                    id="kg-onto-display"
                    value={formDisplayName}
                    onChange={(e) => setFormDisplayName(e.target.value)}
                    placeholder="例如：Works For / 就职于"
                  />
                </div>
                <div className="space-y-2 md:col-span-2">
                  <Label htmlFor="kg-onto-desc">description（可选）</Label>
                  <Input
                    id="kg-onto-desc"
                    value={formDescription}
                    onChange={(e) => setFormDescription(e.target.value)}
                    placeholder="用于解释该 predicate 的语义与方向性"
                  />
                </div>
                <div className="flex items-center justify-between gap-2 md:col-span-2">
                  <div className="text-sm">
                    <div className="font-medium">Enabled</div>
                    <div className="text-xs text-muted-foreground">禁用后 extractor 会将其归一化为 unknown（或丢弃）。</div>
                  </div>
                  <Switch checked={formEnabled} onCheckedChange={setFormEnabled} />
                </div>
              </div>
            </div>

            <div className="overflow-hidden rounded-xl border border-border">
              <div className="grid grid-cols-[1fr_auto] gap-2 bg-muted px-4 py-2 text-xs text-muted-foreground">
                <div>predicate</div>
                <div>enabled</div>
              </div>
              <div className="divide-y divide-border">
                {rows.length === 0 ? (
                  <div className="p-4 text-xs text-muted-foreground">暂无条目。可先添加常用 predicates（alias_of、part_of、works_for…）。</div>
                ) : (
                  rows.map((r) => (
                    <div key={r.id} className="grid grid-cols-[1fr_auto] items-center gap-2 px-4 py-3">
                      <div className="min-w-0">
                        <div className="flex min-w-0 items-center gap-2">
                          <span className="truncate font-mono text-xs" title={r.predicate}>
                            {r.predicate}
                          </span>
                          {r.display_name ? (
                            <span className="truncate text-[11px] text-muted-foreground" title={r.display_name}>
                              {r.display_name}
                            </span>
                          ) : null}
                        </div>
                        {r.description ? (
                          <div className="truncate text-[11px] text-muted-foreground" title={r.description}>
                            {r.description}
                          </div>
                        ) : null}
                        <div className="mt-1 flex items-center gap-2">
                          <Button type="button" size="sm" variant="outline" onClick={() => startEdit(r)} className="h-7 gap-1 px-2 text-[11px]">
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
                        <Switch checked={Boolean(r.is_enabled)} onCheckedChange={(v) => toggleEnabled(r, v)} />
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
            <AlertDialogTitle>删除 predicate？</AlertDialogTitle>
            <AlertDialogDescription>
              你将删除 <span className="font-mono">{deleteTarget?.predicate || '-'}</span>。此操作不可撤销（但可以重新创建）。
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
