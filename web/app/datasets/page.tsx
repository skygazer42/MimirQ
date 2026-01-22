'use client'

import { useEffect, useMemo, useState } from 'react'
import { toast } from 'sonner'
import { Layers, Loader2, Pencil, Plus, RefreshCw, Trash2 } from 'lucide-react'

import { AppFrame } from '@/components/app-frame'
import { PageScaffold } from '@/components/ui/page-scaffold'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { datasetApi } from '@/lib/api-client'
import { formatApiError } from '@/lib/api-errors'
import { cn } from '@/lib/utils'
import type { Dataset, PermissionEnum, DocumentPipelineOptions } from '@/types'
import { PipelineOptionsPanel } from '@/components/pipeline-options-panel'
import { usePipelineOptions } from '@/contexts/pipeline-options-context'

type DatasetFormState = {
  name: string
  description: string
  permission: PermissionEnum
  partialMembersText: string
  pipelineEnabled: boolean
  pipelineOptions: DocumentPipelineOptions
}

function permissionLabel(p: PermissionEnum) {
  if (p === 'only_me') return '仅自己'
  if (p === 'partial_members') return '部分成员'
  return '全员'
}

function permissionBadgeVariant(p: PermissionEnum): 'default' | 'secondary' | 'outline' {
  if (p === 'only_me') return 'secondary'
  if (p === 'partial_members') return 'outline'
  return 'default'
}

function parseMembers(text: string): string[] {
  return (text || '')
    .split(/[\n,]/g)
    .map((s) => s.trim())
    .filter(Boolean)
}

export default function DatasetsPage() {
  const { options: defaultPipelineOptions } = usePipelineOptions()
  const [items, setItems] = useState<Dataset[]>([])
  const [total, setTotal] = useState(0)
  const [isLoading, setIsLoading] = useState(false)

  const [createOpen, setCreateOpen] = useState(false)
  const [editOpen, setEditOpen] = useState(false)
  const [editing, setEditing] = useState<Dataset | null>(null)

  const [form, setForm] = useState<DatasetFormState>({
    name: '',
    description: '',
    permission: 'all_team_members',
    partialMembersText: '',
    pipelineEnabled: false,
    pipelineOptions: { ...defaultPipelineOptions },
  })

  const resetForm = () => {
    setForm({
      name: '',
      description: '',
      permission: 'all_team_members',
      partialMembersText: '',
      pipelineEnabled: false,
      pipelineOptions: { ...defaultPipelineOptions },
    })
  }

  const load = async () => {
    setIsLoading(true)
    try {
      const res = await datasetApi.list({ skip: 0, limit: 200 })
      setItems(res.items || [])
      setTotal(Number(res.total || 0))
    } catch (e: any) {
      console.error('Failed to load datasets', e)
      toast.error(formatApiError(e, '加载数据集失败'))
    } finally {
      setIsLoading(false)
    }
  }

  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const canSubmit = useMemo(() => form.name.trim().length > 0, [form.name])

  const buildPayload = (mode: 'create' | 'update') => {
    const payload: any = {
      name: form.name.trim(),
      description: form.description.trim() || undefined,
      permission: form.permission,
    }
    if (form.permission === 'partial_members') {
      payload.partial_member_list = parseMembers(form.partialMembersText)
    }
    if (mode === 'create') {
      if (form.pipelineEnabled) {
        payload.pipeline = form.pipelineOptions
      }
    } else {
      // For update: send an empty object to explicitly clear dataset pipeline when disabled.
      payload.pipeline = form.pipelineEnabled ? form.pipelineOptions : {}
    }
    return payload
  }

  const handleCreate = async () => {
    if (!canSubmit) return
    try {
      await datasetApi.create(buildPayload('create'))
      toast.success('已创建数据集')
      setCreateOpen(false)
      resetForm()
      await load()
    } catch (e: any) {
      console.error('Failed to create dataset', e)
      toast.error(formatApiError(e, '创建失败'))
    }
  }

  const openEdit = (ds: Dataset) => {
    setEditing(ds)
    const mergedPipeline = { ...defaultPipelineOptions, ...(ds.pipeline || {}) }
    setForm({
      name: ds.name || '',
      description: ds.description || '',
      permission: ds.permission || 'all_team_members',
      partialMembersText: (ds.partial_member_list || []).join('\n'),
      pipelineEnabled: !!ds.pipeline,
      pipelineOptions: mergedPipeline,
    })
    setEditOpen(true)
  }

  const handleUpdate = async () => {
    if (!editing?.id) return
    if (!canSubmit) return
    try {
      await datasetApi.update(editing.id, buildPayload('update'))
      toast.success('已更新数据集')
      setEditOpen(false)
      setEditing(null)
      resetForm()
      await load()
    } catch (e: any) {
      console.error('Failed to update dataset', e)
      toast.error(formatApiError(e, '更新失败'))
    }
  }

  const handleDelete = async (ds: Dataset) => {
    if (!ds?.id) return
    if (!confirm(`确定删除数据集 “${ds.name}” 吗？此操作不可恢复。`)) return
    try {
      await datasetApi.delete(ds.id)
      toast.success('已删除数据集')
      setItems((prev) => prev.filter((x) => x.id !== ds.id))
      setTotal((prev) => Math.max(0, prev - 1))
    } catch (e: any) {
      console.error('Failed to delete dataset', e)
      toast.error(formatApiError(e, '删除失败'))
    }
  }

  return (
    <AppFrame>
      <PageScaffold
        title="数据集"
        badge="Archive"
        icon={Layers}
        iconColor="text-cyan-600 dark:text-cyan-400"
        description={
          <span className="flex items-center gap-2">
            <span className="w-1.5 h-1.5 rounded-full bg-cyan-500/50 animate-pulse" />
            管理知识库集合与访问权限
            <span className="ml-4 text-xs font-mono text-cyan-700/60 dark:text-cyan-300/60 uppercase tracking-widest">
              Total Archives: <span className="text-cyan-600 dark:text-cyan-400 font-bold">{total}</span>
            </span>
          </span>
        }
        actions={
          <div className="flex items-center gap-3">
            <Button
              variant="outline"
              className="gap-2 rounded-lg bg-white/50 dark:bg-slate-900/50 border-slate-200 dark:border-slate-800 hover:bg-white dark:hover:bg-slate-800 hover:border-slate-300 dark:hover:border-slate-700 text-slate-600 dark:text-slate-300 hover:text-cyan-600 dark:hover:text-cyan-400 transition-all font-mono text-xs uppercase tracking-wider shadow-sm"
              onClick={() => load()}
              disabled={isLoading}
            >
              <RefreshCw className={cn('w-3.5 h-3.5', isLoading && 'animate-spin')} />
              Sync
            </Button>

            <Dialog
              open={createOpen}
              onOpenChange={(open) => {
                setCreateOpen(open)
                if (open) resetForm()
              }}
            >
              <DialogTrigger asChild>
                <Button className="gap-2 rounded-lg bg-cyan-600 hover:bg-cyan-500 text-white shadow-[0_0_20px_-5px_rgba(6,182,212,0.4)] border border-cyan-400/20 font-medium">
                  <Plus className="w-4 h-4" />
                  新建数据集
                </Button>
              </DialogTrigger>
              <DialogContent className="max-w-xl border-border bg-background/95 dark:bg-slate-950/95 backdrop-blur-xl shadow-2xl sm:rounded-2xl">
                <DialogHeader>
                  <DialogTitle className="text-xl font-bold text-foreground">新建数据集</DialogTitle>
                  <DialogDescription className="text-muted-foreground">为文档分组并设置访问权限</DialogDescription>
                </DialogHeader>

                <DatasetForm form={form} setForm={setForm} />

                <DialogFooter className="mt-4">
                  <Button
                    variant="ghost"
                    onClick={() => setCreateOpen(false)}
                    className="text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800"
                  >
                    取消
                  </Button>
                  <Button onClick={handleCreate} disabled={!canSubmit} className="bg-cyan-600 hover:bg-cyan-500 text-white">
                    确认创建
                  </Button>
                </DialogFooter>
              </DialogContent>
            </Dialog>
          </div>
        }
      >
        <div className="bg-card border border-border rounded-3xl overflow-hidden shadow-sm min-h-[500px] flex flex-col">
            <div className="px-6 py-4 border-b border-border/60 flex items-center justify-between bg-muted/20 dark:bg-slate-900/40">
              <div className="text-xs font-bold text-muted-foreground uppercase tracking-wider">Dataset Registry</div>
              {isLoading && (
                <div className="flex items-center gap-2 text-xs text-cyan-700/70 dark:text-cyan-300/80 font-mono">
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  LOADING_ARCHIVES...
                </div>
              )}
            </div>

            {items.length === 0 && !isLoading ? (
              <div className="flex-1 flex flex-col items-center justify-center p-10 text-center space-y-4">
                <div className="w-20 h-20 rounded-full bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-800 flex items-center justify-center animate-pulse">
                  <Layers className="w-8 h-8 text-slate-600 dark:text-slate-300" />
                </div>
                <div>
                  <div className="text-slate-500 dark:text-slate-300 font-medium">暂无数据集</div>
                  <div className="text-slate-600 dark:text-slate-400 text-sm mt-1">点击右上角“新建数据集”开始构建知识库</div>
                </div>
              </div>
            ) : (
              <div className="divide-y divide-border/60">
                {items.map((ds) => (
                  <div key={ds.id} className="group px-6 py-5 flex items-start justify-between gap-6 hover:bg-slate-50 dark:hover:bg-white/[0.03] transition-colors">
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-3 mb-1.5">
                        <div className="font-bold text-lg text-slate-900 dark:text-slate-100 group-hover:text-cyan-600 dark:group-hover:text-cyan-400 transition-colors truncate tracking-tight">{ds.name}</div>
                        <Badge variant={permissionBadgeVariant(ds.permission)} className="bg-transparent border-slate-200 dark:border-slate-700 text-slate-600 dark:text-slate-300 text-[10px] uppercase tracking-wider font-mono">
                          {permissionLabel(ds.permission)}
                        </Badge>
                      </div>
                      {ds.description && (
                        <div className="text-sm text-slate-600 dark:text-slate-400 group-hover:text-slate-700 dark:group-hover:text-slate-300 line-clamp-2 leading-relaxed">
                          {ds.description}
                        </div>
                      )}

                      <div className="mt-3 flex items-center gap-4 text-xs font-mono text-slate-500 dark:text-slate-400">
                        {ds.permission === 'partial_members' && (ds.partial_member_list || []).length > 0 && (
                          <span className="flex items-center gap-1.5">
                            <span className="w-1 h-1 rounded-full bg-cyan-500/50" />
                            MEMBERS: {(ds.partial_member_list || []).length}
                          </span>
                        )}
                        <span className="text-slate-600 dark:text-slate-300">ID: {ds.id.slice(0, 8)}</span>
                      </div>
                    </div>

                    <div className="flex items-center gap-2 flex-shrink-0 opacity-0 group-hover:opacity-100 transition-opacity translate-x-4 group-hover:translate-x-0 duration-300">
                      <Button
                        variant="outline"
                        size="sm"
                        className="gap-2 border-slate-200 dark:border-slate-700 bg-transparent text-slate-600 dark:text-slate-300 hover:text-slate-900 dark:hover:text-white hover:bg-slate-50 dark:hover:bg-white/5"
                        onClick={() => openEdit(ds)}
                      >
                        <Pencil className="w-3.5 h-3.5" />
                        编辑
                      </Button>
                      <Button
                        variant="destructive"
                        size="sm"
                        className="gap-2 bg-red-500/10 border border-red-500/20 text-red-600 dark:text-red-400 hover:bg-red-500/20"
                        onClick={() => handleDelete(ds)}
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                        删除
                      </Button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
      </PageScaffold>

        <Dialog open={editOpen} onOpenChange={(open) => {
          setEditOpen(open)
          if (!open) {
            setEditing(null)
            resetForm()
          }
        }}>
          <DialogContent className="max-w-xl border-cyan-500/20 bg-background/95 dark:bg-slate-950/95 backdrop-blur-xl shadow-2xl sm:rounded-2xl">
            <DialogHeader>
              <DialogTitle className="text-xl font-bold text-foreground">编辑数据集</DialogTitle>
              <DialogDescription className="text-muted-foreground">更新名称、描述与访问权限</DialogDescription>
            </DialogHeader>

            <DatasetForm form={form} setForm={setForm} />

            <DialogFooter className="mt-4">
              <Button
                variant="ghost"
                onClick={() => setEditOpen(false)}
                className="text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800"
              >
                取消
              </Button>
              <Button onClick={handleUpdate} disabled={!canSubmit || !editing} className="bg-cyan-600 hover:bg-cyan-500 text-white">保存变更</Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
    </AppFrame>
  )
}

function DatasetForm({
  form,
  setForm,
}: {
  form: DatasetFormState
  setForm: (next: DatasetFormState) => void
}) {
  return (
    <div className="grid gap-5">
      <div className="grid gap-2">
        <Label htmlFor="ds-name" className="text-slate-700 dark:text-slate-300">名称</Label>
        <Input
          id="ds-name"
          value={form.name}
          onChange={(e) => setForm({ ...form, name: e.target.value })}
          placeholder="例如：产品文档 / 技术周报 / 合同资料"
          className="bg-white dark:bg-slate-900/50 border-slate-200 dark:border-slate-800 focus:border-cyan-500/50 focus:ring-cyan-500/20 text-slate-900 dark:text-slate-200 placeholder:text-slate-400 dark:placeholder:text-slate-600"
        />
      </div>

      <div className="grid gap-2">
        <Label htmlFor="ds-desc" className="text-slate-700 dark:text-slate-300">描述（可选）</Label>
        <Textarea
          id="ds-desc"
          value={form.description}
          onChange={(e) => setForm({ ...form, description: e.target.value })}
          placeholder="用于说明该数据集包含哪些文档、用途是什么..."
          className="min-h-[96px] bg-white dark:bg-slate-900/50 border-slate-200 dark:border-slate-800 focus:border-cyan-500/50 focus:ring-cyan-500/20 text-slate-900 dark:text-slate-200 placeholder:text-slate-400 dark:placeholder:text-slate-600 resize-none"
        />
      </div>

      <div className="grid gap-2">
        <Label className="text-slate-700 dark:text-slate-300">权限</Label>
        <Select value={form.permission} onValueChange={(v) => setForm({ ...form, permission: v as PermissionEnum })}>
          <SelectTrigger className="bg-white dark:bg-slate-900/50 border-slate-200 dark:border-slate-800 text-slate-900 dark:text-slate-200">
            <SelectValue placeholder="选择权限" />
          </SelectTrigger>
          <SelectContent className="bg-white dark:bg-slate-900 border-slate-200 dark:border-slate-800 text-slate-900 dark:text-slate-200">
            <SelectItem value="all_team_members">全员可见</SelectItem>
            <SelectItem value="only_me">仅自己</SelectItem>
            <SelectItem value="partial_members">部分成员</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {form.permission === 'partial_members' && (
        <div className="grid gap-2">
          <Label htmlFor="ds-members" className="text-slate-700 dark:text-slate-300">成员列表（account_id，一行一个或逗号分隔）</Label>
          <Textarea
            id="ds-members"
            value={form.partialMembersText}
            onChange={(e) => setForm({ ...form, partialMembersText: e.target.value })}
            placeholder="user_1\nuser_2"
            className="min-h-[96px] bg-white dark:bg-slate-900/50 border-slate-200 dark:border-slate-800 text-slate-900 dark:text-slate-200 font-mono text-sm"
          />
        </div>
      )}

      <div className="border border-slate-200 dark:border-slate-800 rounded-xl overflow-hidden bg-slate-50/40 dark:bg-slate-900/30">
        <div className="px-4 py-3 bg-white/50 dark:bg-slate-900/50 border-b border-slate-200 dark:border-slate-800 flex items-start gap-3">
          <Checkbox
            checked={form.pipelineEnabled}
            onCheckedChange={(v) => setForm({ ...form, pipelineEnabled: v === true })}
            className="mt-1 border-slate-300 dark:border-slate-600 data-[state=checked]:bg-cyan-600 data-[state=checked]:border-cyan-600"
          />
          <div className="min-w-0">
            <div className="text-sm font-bold text-slate-900 dark:text-slate-200">数据集默认管线</div>
            <div className="text-xs text-slate-600 dark:text-slate-400 mt-1 leading-relaxed">
              启用后，该数据集下的文档默认使用此治理/索引配置；上传文档时的“文档级配置”仍可覆盖。
            </div>
          </div>
        </div>
        {form.pipelineEnabled && (
          <div className="p-4 bg-white/60 dark:bg-slate-950/50">
            <PipelineOptionsPanel
              compact={true}
              hideEnabledToggle={true}
              enabled={true}
              value={form.pipelineOptions}
              onEnabledChange={() => {
                // dataset panel is always "enabled" when visible; ignore
              }}
              onOptionChange={(key, value) => {
                setForm({
                  ...form,
                  pipelineOptions: {
                    ...form.pipelineOptions,
                    [key]: value,
                  },
                })
              }}
            />
          </div>
        )}
      </div>
    </div>
  )
}
