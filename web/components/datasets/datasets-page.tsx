'use client'

import { useCallback, useEffect, useMemo, useState, type Dispatch, type SetStateAction } from 'react'
import { toast } from 'sonner'
import { BarChart3, Database, FileSearch, Layers, Loader2, Pencil, Plus, RefreshCw, Settings2, ShieldCheck, Table2, Trash2 } from 'lucide-react'

import { AppFrame } from '@/components/app-frame'
import { useRouter } from '@/i18n/navigation'
import { PageScaffold } from '@/components/ui/page-scaffold'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
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
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Panel } from '@/components/ui/panel'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { datasetApi } from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'
import { cn, detachPromise } from '@/lib/utils'
import type { Dataset, PermissionEnum, DocumentPipelineOptions } from '@/types'
import { PipelineOptionsPanel } from '@/components/pipeline-options-panel'
import { GovernanceProfileSelector } from '@/components/governance-profile-selector'
import { usePipelineOptions } from '@/contexts/pipeline-options-context'
import { DatasetCategoryTree } from '@/components/dataset-categories/category-tree'
import { DatasetCategoryMultiSelect } from '@/components/dataset-categories/category-multi-select'
import { GroupChipsInput } from '@/components/groups/group-chips-input'

type DatasetFormState = {
  name: string
  description: string
  permission: PermissionEnum
  partialMembersText: string
  partialGroupIds: string[]
  pipelineEnabled: boolean
  pipelineOptions: DocumentPipelineOptions
}

function permissionLabel(p: PermissionEnum) {
  if (p === 'only_me') return '仅自己'
  if (p === 'partial_members') return '部分成员'
  return '全员'
}

function permissionBadgeVariant(p: PermissionEnum): 'secondary' | 'outline' | 'soft' {
  if (p === 'only_me') return 'secondary'
  if (p === 'partial_members') return 'outline'
  return 'soft'
}

function parseMembers(text: string): string[] {
  return (text || '')
    .split(/[\n,]/g)
    .map((s) => s.trim())
    .filter(Boolean)
}

function mergePipelineOptions(
  defaults: DocumentPipelineOptions,
  overrides?: DocumentPipelineOptions | null
): DocumentPipelineOptions {
  if (!overrides) return { ...defaults }
  return { ...defaults, ...overrides }
}

function applyPipelinePatch(
  current: DocumentPipelineOptions,
  patch?: DocumentPipelineOptions | null
): DocumentPipelineOptions {
  if (!patch) return { ...current }
  return { ...current, ...patch }
}

export default function DatasetsPage() {
  const router = useRouter()
  const { options: defaultPipelineOptions } = usePipelineOptions()
  const [items, setItems] = useState<Dataset[]>([])
  const [total, setTotal] = useState(0)
  const [isLoading, setIsLoading] = useState(false)
  const [selectedCategoryId, setSelectedCategoryId] = useState<string | null>(null)

  const [createOpen, setCreateOpen] = useState(false)
  const [editOpen, setEditOpen] = useState(false)
  const [editing, setEditing] = useState<Dataset | null>(null)

  const [form, setForm] = useState<DatasetFormState>({
    name: '',
    description: '',
    permission: 'all_team_members',
    partialMembersText: '',
    partialGroupIds: [],
    pipelineEnabled: false,
    pipelineOptions: { ...defaultPipelineOptions },
  })

  const resetForm = () => {
    setForm({
      name: '',
      description: '',
      permission: 'all_team_members',
      partialMembersText: '',
      partialGroupIds: [],
      pipelineEnabled: false,
      pipelineOptions: { ...defaultPipelineOptions },
    })
  }

  const load = useCallback(async () => {
    setIsLoading(true)
    try {
      const res = await datasetApi.list({
        skip: 0,
        limit: 200,
        category_id: selectedCategoryId || undefined,
        include_descendants: true,
      })
      setItems(res.items || [])
      setTotal(Number(res.total || 0))
    } catch (e: any) {
      console.error('Failed to load datasets', e)
      toast.error(formatApiError(e, '加载数据集失败'))
    } finally {
      setIsLoading(false)
    }
  }, [selectedCategoryId])

  useEffect(() => {
    detachPromise(load())
  }, [load])

  const canSubmit = useMemo(() => form.name.trim().length > 0, [form.name])

  const buildPayload = (mode: 'create' | 'update') => {
    const payload: any = {
      name: form.name.trim(),
      description: form.description.trim() || undefined,
      permission: form.permission,
    }
    if (form.permission === 'partial_members') {
      payload.partial_member_list = parseMembers(form.partialMembersText)
      payload.partial_group_list = (form.partialGroupIds || []).map(String)
    } else {
      // Fail-closed: when switching away from partial, explicitly clear allowlists.
      payload.partial_member_list = null
      payload.partial_group_list = null
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
    const mergedPipeline = mergePipelineOptions(defaultPipelineOptions, ds.pipeline)
    setForm({
      name: ds.name || '',
      description: ds.description || '',
      permission: ds.permission || 'all_team_members',
      partialMembersText: (ds.partial_member_list || []).join('\n'),
      partialGroupIds: (ds.partial_group_list || []).map(String),
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
        iconColor="text-primary"
        description={
          <span className="flex items-center gap-2">
            <span className="w-1.5 h-1.5 rounded-full bg-primary/50" />
            <span>管理知识库集合与访问权限</span>
            <span className="ml-4 text-xs font-mono text-primary/70 uppercase ">
              Total Archives: <span className="text-primary font-bold">{total}</span>
            </span>
          </span>
        }
        actions={
          <div className="flex items-center gap-3">
            <Button
              variant="outline"
              className="gap-2 rounded-lg bg-card/80 font-mono text-xs uppercase "
              onClick={() => load()}
              disabled={isLoading}
	            >
	              <RefreshCw className={cn('w-3.5 h-3.5', isLoading && 'animate-spin motion-reduce:animate-none')} />
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
                <Button className="gap-2 rounded-lg shadow-sm border border-primary/20">
                  <Plus className="w-4 h-4" />
                  新建数据集
                </Button>
              </DialogTrigger>
              <DialogContent className="max-w-xl sm:rounded-2xl">
                <DialogHeader>
                  <DialogTitle className="text-xl font-bold text-foreground">新建数据集</DialogTitle>
                  <DialogDescription className="text-muted-foreground">为文档分组并设置访问权限</DialogDescription>
                </DialogHeader>

                <DatasetForm form={form} setForm={setForm} />

                <DialogFooter className="mt-4">
                  <Button
                    variant="ghost"
                    onClick={() => setCreateOpen(false)}
                  >
                    取消
                  </Button>
                  <Button onClick={handleCreate} disabled={!canSubmit}>
                    确认创建
                  </Button>
                </DialogFooter>
              </DialogContent>
            </Dialog>
          </div>
        }
      >
        <div className="grid grid-cols-1 lg:grid-cols-[280px_1fr] gap-6">
          <Panel variant="muted" padding="lg" className="rounded-3xl h-fit">
            <DatasetCategoryTree selectedId={selectedCategoryId} onSelect={(id) => setSelectedCategoryId(id)} />
          </Panel>

          <div className="bg-card border border-border rounded-3xl overflow-hidden shadow-sm min-h-[500px] flex flex-col">
            <div className="px-6 py-4 border-b border-border/60 flex items-center justify-between bg-muted/20">
              <div className="text-xs font-bold text-muted-foreground uppercase ">Dataset Registry</div>
	              {isLoading && (
	                <div className="flex items-center gap-2 text-xs text-muted-foreground font-mono">
	                  <Loader2 className="w-3.5 h-3.5 animate-spin motion-reduce:animate-none" />
	                  LOADING_ARCHIVES...
	                </div>
	              )}
            </div>

            {items.length === 0 && !isLoading ? (
              <div className="flex-1 p-6">
                <EmptyState
                  icon={Layers}
                  title="暂无数据集"
                  description="点击“新建数据集”开始构建知识库。"
                  className="min-h-[420px]"
                >
                  <Button
                    className="gap-2 rounded-lg"
                    onClick={() => {
                      resetForm()
                      setCreateOpen(true)
                    }}
                  >
                    <Plus className="w-4 h-4" />
                    新建数据集
                  </Button>
                </EmptyState>
              </div>
            ) : (
              <div className="divide-y divide-border/60">
                {items.map((ds) => (
                  <div key={ds.id} className="group px-6 py-5 flex items-start justify-between gap-6 hover:bg-muted/20 transition-colors">
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-3 mb-1.5">
                        <div className="font-bold text-lg text-foreground group-hover:text-primary transition-colors truncate ">{ds.name}</div>
                        <Badge variant={permissionBadgeVariant(ds.permission)} className="text-[10px] uppercase  font-mono">
                          {permissionLabel(ds.permission)}
                        </Badge>
                      </div>
                      {ds.description && (
                        <div className="text-sm text-muted-foreground group-hover:text-foreground/80 line-clamp-2 leading-relaxed">
                          {ds.description}
                        </div>
                      )}

                      <div className="mt-3 flex items-center gap-4 text-xs font-mono text-muted-foreground">
                        {ds.permission === 'partial_members' && (ds.partial_member_list || []).length > 0 && (
                          <span className="flex items-center gap-1.5">
                            <span className="w-1 h-1 rounded-full bg-primary/50" />
                            MEMBERS: {(ds.partial_member_list || []).length}
                          </span>
                        )}
                        {ds.permission === 'partial_members' && (ds.partial_group_list || []).length > 0 && (
                          <span className="flex items-center gap-1.5">
                            <span className="w-1 h-1 rounded-full bg-primary/50" />
                            GROUPS: {(ds.partial_group_list || []).length}
                          </span>
                        )}
                        <span>ID: {ds.id.slice(0, 8)}</span>
                      </div>
                    </div>

                    <div className="flex items-center gap-2 flex-shrink-0 opacity-0 group-hover:opacity-100 translate-x-4 group-hover:translate-x-0 transition-opacity transition-transform duration-200 motion-reduce:transition-none">
                      <Button
                        variant="outline"
                        size="sm"
                        className="gap-2"
                        onClick={() => router.push(`/datasets/${ds.id}/precheck`)}
                      >
                        <FileSearch className="w-3.5 h-3.5" />
                        预检扫描
                      </Button>
                      <Button
                        variant="outline"
                        size="sm"
                        className="gap-2"
                        onClick={() => router.push(`/datasets/${ds.id}/profile`)}
                      >
                        <BarChart3 className="w-3.5 h-3.5" />
                        数据画像
                      </Button>
                      <Button
                        variant="outline"
                        size="sm"
                        className="gap-2"
                        onClick={() => router.push(`/datasets/${ds.id}/ingestion`)}
                      >
                        <Settings2 className="w-3.5 h-3.5" />
                        入库策略
                      </Button>
                      <Button
                        variant="outline"
                        size="sm"
                        className="gap-2"
                        onClick={() => router.push(`/datasets/${ds.id}/workflow`)}
                      >
                        <Layers className="w-3.5 h-3.5" />
                        Workflow
                      </Button>
                      <Button
                        variant="outline"
                        size="sm"
                        className="gap-2"
                        onClick={() => router.push(`/datasets/${ds.id}/tables`)}
                      >
                        <Table2 className="w-3.5 h-3.5" />
                        表格 / TAG
                      </Button>
                      <Button
                        variant="outline"
                        size="sm"
                        className="gap-2"
                        onClick={() => router.push(`/datasets/${ds.id}/evidence`)}
                      >
                        <ShieldCheck className="w-3.5 h-3.5" />
                        证据库
                      </Button>
                      <Button
                        variant="outline"
                        size="sm"
                        className="gap-2"
                        onClick={() => router.push(`/datasets/${ds.id}/db-catalog`)}
                      >
                        <Database className="w-3.5 h-3.5" />
                        数据库目录
                      </Button>
                      <Button
                        variant="outline"
                        size="sm"
                        className="gap-2"
                        onClick={() => openEdit(ds)}
                      >
                        <Pencil className="w-3.5 h-3.5" />
                        编辑
                      </Button>
                      <AlertDialog>
                        <AlertDialogTrigger asChild>
                          <Button variant="destructive" size="sm" className="gap-2">
                            <Trash2 className="w-3.5 h-3.5" aria-hidden="true" />
                            删除
                          </Button>
                        </AlertDialogTrigger>
                        <AlertDialogContent>
                          <AlertDialogHeader>
                            <AlertDialogTitle>删除数据集？</AlertDialogTitle>
                            <AlertDialogDescription>
                              你将删除 <span className="font-mono">{ds.name}</span>。此操作不可撤销。
                            </AlertDialogDescription>
                          </AlertDialogHeader>
                          <AlertDialogFooter>
                            <AlertDialogCancel>取消</AlertDialogCancel>
                            <AlertDialogAction onClick={() => handleDelete(ds)}>删除</AlertDialogAction>
                          </AlertDialogFooter>
                        </AlertDialogContent>
                      </AlertDialog>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </PageScaffold>

        <Dialog open={editOpen} onOpenChange={(open) => {
          setEditOpen(open)
          if (!open) {
            setEditing(null)
            resetForm()
          }
        }}>
          <DialogContent className="max-w-xl sm:rounded-2xl">
            <DialogHeader>
              <DialogTitle className="text-xl font-bold text-foreground">编辑数据集</DialogTitle>
              <DialogDescription className="text-muted-foreground">更新名称、描述与访问权限</DialogDescription>
            </DialogHeader>

            <DatasetForm form={form} setForm={setForm} />
            {editing?.id ? <DatasetCategoryMultiSelect datasetId={editing.id} /> : null}

            <DialogFooter className="mt-4">
              <Button
                variant="ghost"
                onClick={() => setEditOpen(false)}
              >
                取消
              </Button>
              <Button onClick={handleUpdate} disabled={!canSubmit || !editing}>保存变更</Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
    </AppFrame>
  )
}

function DatasetForm({
  form,
  setForm,
}: Readonly<{
  form: DatasetFormState
  setForm: Dispatch<SetStateAction<DatasetFormState>>
}>) {
  return (
    <div className="grid gap-5">
      <div className="grid gap-2">
        <Label htmlFor="ds-name">名称</Label>
        <Input
          id="ds-name"
          value={form.name}
          onChange={(e) => setForm({ ...form, name: e.target.value })}
          placeholder="例如：产品文档 / 技术周报 / 合同资料"
        />
      </div>

      <div className="grid gap-2">
        <Label htmlFor="ds-desc">描述（可选）</Label>
        <Textarea
          id="ds-desc"
          value={form.description}
          onChange={(e) => setForm({ ...form, description: e.target.value })}
          placeholder="用于说明该数据集包含哪些文档、用途是什么..."
          className="resize-none"
        />
      </div>

      <div className="grid gap-2">
        <Label>权限</Label>
        <Select value={form.permission} onValueChange={(v) => setForm({ ...form, permission: v as PermissionEnum })}>
          <SelectTrigger>
            <SelectValue placeholder="选择权限" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all_team_members">全员可见</SelectItem>
            <SelectItem value="only_me">仅自己</SelectItem>
            <SelectItem value="partial_members">部分成员</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {form.permission === 'partial_members' && (
        <div className="grid gap-4">
          <div className="grid gap-2">
            <Label>允许组（可选）</Label>
            <GroupChipsInput
              value={form.partialGroupIds}
              onChange={(next) => setForm({ ...form, partialGroupIds: next })}
              placeholder="选择组（组内成员将自动获得访问权限）"
            />
            <div className="text-xs text-muted-foreground">
              组 allowlist 与成员 allowlist 同时生效（满足任一即可访问）。
            </div>
          </div>

          <div className="grid gap-2">
            <Label htmlFor="ds-members">允许成员（account_id，一行一个或逗号分隔）</Label>
            <Textarea
              id="ds-members"
              value={form.partialMembersText}
              onChange={(e) => setForm({ ...form, partialMembersText: e.target.value })}
              placeholder="user_1\nuser_2"
              className="font-mono text-sm"
            />
          </div>
        </div>
      )}

      <Panel variant="muted" padding="none" className="rounded-xl overflow-hidden">
        <div className="px-4 py-3 border-b border-border/60 flex items-start gap-3 bg-background/40">
          <Checkbox
            checked={form.pipelineEnabled}
            onCheckedChange={(v) => setForm({ ...form, pipelineEnabled: v === true })}
            className="mt-1"
          />
          <div className="min-w-0">
            <div className="text-sm font-bold text-foreground">数据集默认管线</div>
            <div className="text-xs text-muted-foreground mt-1 leading-relaxed">
              启用后，该数据集下的文档默认使用此治理/索引配置；上传文档时的“文档级配置”仍可覆盖。
            </div>
          </div>
        </div>
        {form.pipelineEnabled && (
          <div className="p-4 bg-card/60">
            <div className="mb-4">
              <div className="text-xs font-medium text-muted-foreground mb-2">治理预设（Profiles/脚本）</div>
              <GovernanceProfileSelector
                compact={true}
                onApplyPatch={(patch) => {
                  setForm({
                    ...form,
                    pipelineOptions: applyPipelinePatch(form.pipelineOptions, patch),
                  })
                }}
              />
            </div>
            <PipelineOptionsPanel
              compact={true}
              hideEnabledToggle={true}
              enabled={true}
              value={form.pipelineOptions}
              onEnabledChange={() => {
                // dataset panel is always "enabled" when visible; ignore
              }}
              onOptionChange={(key, value) => {
                setForm((prev) => ({
                  ...prev,
                  pipelineOptions: {
                    ...prev.pipelineOptions,
                    [key]: value,
                  },
                }))
              }}
            />
          </div>
        )}
      </Panel>
    </div>
  )
}
