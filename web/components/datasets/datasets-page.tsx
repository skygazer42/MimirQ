'use client'

import { useCallback, useEffect, useMemo, useState, type Dispatch, type SetStateAction } from 'react'
import { toast } from 'sonner'
import {
  BarChart3, Database, FileSearch, FolderOpen, Layers, Loader2,
  MoreHorizontal, Pencil, Plus, RefreshCw, Search, Settings2, ShieldCheck,
  Table2, Trash2, Users,
} from 'lucide-react'

import { AppFrame } from '@/components/app-frame'
import { useRouter } from '@/i18n/navigation'
import { PageScaffold } from '@/components/ui/page-scaffold'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { EmptyState } from '@/components/ui/empty-state'
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader,
  DialogTitle, DialogTrigger,
} from '@/components/ui/dialog'
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
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

const PERMISSION_CONFIG: Record<PermissionEnum, { label: string; variant: 'soft' | 'secondary' | 'outline'; color: string }> = {
  all_team_members: { label: '全员', variant: 'soft', color: 'text-success' },
  only_me: { label: '仅自己', variant: 'secondary', color: 'text-warning' },
  partial_members: { label: '部分成员', variant: 'outline', color: 'text-info' },
}

function parseMembers(text: string): string[] {
  return (text || '').split(/[\n,]/g).map((s) => s.trim()).filter(Boolean)
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
  const [searchQuery, setSearchQuery] = useState('')
  const [deleteTarget, setDeleteTarget] = useState<Dataset | null>(null)

  const [createOpen, setCreateOpen] = useState(false)
  const [editOpen, setEditOpen] = useState(false)
  const [editing, setEditing] = useState<Dataset | null>(null)

  const [form, setForm] = useState<DatasetFormState>({
    name: '', description: '', permission: 'all_team_members',
    partialMembersText: '', partialGroupIds: [],
    pipelineEnabled: false, pipelineOptions: { ...defaultPipelineOptions },
  })

  const resetForm = () => {
    setForm({
      name: '', description: '', permission: 'all_team_members',
      partialMembersText: '', partialGroupIds: [],
      pipelineEnabled: false, pipelineOptions: { ...defaultPipelineOptions },
    })
  }

  const load = useCallback(async () => {
    setIsLoading(true)
    try {
      const res = await datasetApi.list({
        skip: 0, limit: 200,
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

  useEffect(() => { detachPromise(load()) }, [load])

  const filteredItems = useMemo(() => {
    const q = searchQuery.trim().toLowerCase()
    if (!q) return items
    return items.filter((ds) =>
      (ds.name || '').toLowerCase().includes(q) ||
      (ds.description || '').toLowerCase().includes(q)
    )
  }, [items, searchQuery])

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
      payload.partial_member_list = null
      payload.partial_group_list = null
    }
    if (mode === 'create') {
      if (form.pipelineEnabled) payload.pipeline = form.pipelineOptions
    } else {
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
      toast.error(formatApiError(e, '创建失败'))
    }
  }

  const openEdit = (ds: Dataset) => {
    setEditing(ds)
    const mergedPipeline = mergePipelineOptions(defaultPipelineOptions, ds.pipeline)
    setForm({
      name: ds.name || '', description: ds.description || '',
      permission: ds.permission || 'all_team_members',
      partialMembersText: (ds.partial_member_list || []).join('\n'),
      partialGroupIds: (ds.partial_group_list || []).map(String),
      pipelineEnabled: !!ds.pipeline,
      pipelineOptions: mergedPipeline,
    })
    setEditOpen(true)
  }

  const handleUpdate = async () => {
    if (!editing?.id || !canSubmit) return
    try {
      await datasetApi.update(editing.id, buildPayload('update'))
      toast.success('已更新数据集')
      setEditOpen(false)
      setEditing(null)
      resetForm()
      await load()
    } catch (e: any) {
      toast.error(formatApiError(e, '更新失败'))
    }
  }

  const handleDelete = async () => {
    if (!deleteTarget?.id) return
    try {
      await datasetApi.delete(deleteTarget.id)
      toast.success('已删除数据集')
      setItems((prev) => prev.filter((x) => x.id !== deleteTarget.id))
      setTotal((prev) => Math.max(0, prev - 1))
    } catch (e: any) {
      toast.error(formatApiError(e, '删除失败'))
    } finally {
      setDeleteTarget(null)
    }
  }

  const perm = (ds: Dataset) => PERMISSION_CONFIG[ds.permission] || PERMISSION_CONFIG.all_team_members

  return (
    <AppFrame>
      <PageScaffold
        title="数据集"
        icon={Layers}
        iconColor="text-primary"
        compact
        description="管理知识库集合与访问权限"
        actions={
          <div className="flex items-center gap-2">
            <Button
              variant="ghost" size="sm"
              onClick={() => load()} disabled={isLoading}
            >
              <RefreshCw className={cn('w-4 h-4', isLoading && 'animate-spin motion-reduce:animate-none')} />
            </Button>
            <Dialog open={createOpen} onOpenChange={(open) => { setCreateOpen(open); if (open) resetForm() }}>
              <DialogTrigger asChild>
                <Button size="sm" className="gap-1.5">
                  <Plus className="w-4 h-4" />
                  新建数据集
                </Button>
              </DialogTrigger>
              <DialogContent className="max-w-xl sm:rounded-2xl">
                <DialogHeader>
                  <DialogTitle>新建数据集</DialogTitle>
                  <DialogDescription>为文档分组并设置访问权限</DialogDescription>
                </DialogHeader>
                <DatasetForm form={form} setForm={setForm} />
                <DialogFooter className="mt-4">
                  <Button variant="ghost" onClick={() => setCreateOpen(false)}>取消</Button>
                  <Button onClick={handleCreate} disabled={!canSubmit}>确认创建</Button>
                </DialogFooter>
              </DialogContent>
            </Dialog>
          </div>
        }
      >
        {/* Search + stats bar */}
        <div className="flex items-center gap-3 mb-5">
          <div className="relative flex-1 max-w-sm">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
            <Input
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="搜索数据集..."
              className="pl-9 h-9"
            />
          </div>
          <div className="flex items-center gap-4 text-sm text-muted-foreground">
            <span className="flex items-center gap-1.5">
              <FolderOpen className="w-3.5 h-3.5" />
              <span className="font-medium tabular-nums">{total}</span> 个数据集
            </span>
            {isLoading && <Loader2 className="w-4 h-4 animate-spin motion-reduce:animate-none text-primary" />}
          </div>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-[240px_1fr] gap-5">
          {/* Category sidebar */}
          <div className="hidden lg:block">
            <Panel variant="muted" padding="md" className="rounded-xl sticky top-0">
              <DatasetCategoryTree selectedId={selectedCategoryId} onSelect={(id) => setSelectedCategoryId(id)} />
            </Panel>
          </div>

          {/* Dataset list */}
          {filteredItems.length === 0 && !isLoading ? (
            <EmptyState
              icon={Layers}
              title={searchQuery ? '未找到匹配的数据集' : '暂无数据集'}
              description={searchQuery ? '尝试更换关键词' : '点击"新建数据集"开始构建知识库'}
            >
              {!searchQuery && (
                <Button className="gap-1.5" onClick={() => { resetForm(); setCreateOpen(true) }}>
                  <Plus className="w-4 h-4" /> 新建数据集
                </Button>
              )}
            </EmptyState>
          ) : (
            <div className="rounded-xl border border-border overflow-hidden bg-card">
              {/* Table header */}
              <div className="grid grid-cols-[1fr_100px_80px_100px_40px] gap-3 px-4 py-2.5 text-[11px] font-medium text-muted-foreground uppercase tracking-wider border-b border-border/60 bg-muted/30">
                <div>名称</div>
                <div>权限</div>
                <div>管线</div>
                <div className="hidden sm:block">ID</div>
                <div />
              </div>

              {/* Table rows */}
              <div className="divide-y divide-border/40">
                {filteredItems.map((ds) => (
                  <div
                    key={ds.id}
                    className="group grid grid-cols-[1fr_100px_80px_100px_40px] gap-3 items-center px-4 py-3 cursor-pointer transition-colors hover:bg-muted/30"
                    onClick={() => router.push(`/datasets/${ds.id}/precheck`)}
                  >
                    {/* Name + description */}
                    <div className="min-w-0">
                      <div className="flex items-center gap-2 min-w-0">
                        <Layers className={cn("w-4 h-4 flex-shrink-0", ds.pipeline ? 'text-primary' : 'text-muted-foreground/50')} />
                        <span className="text-sm font-medium text-foreground truncate group-hover:text-primary transition-colors">
                          {ds.name}
                        </span>
                      </div>
                      {ds.description && (
                        <p className="mt-0.5 ml-6 text-xs text-muted-foreground truncate">{ds.description}</p>
                      )}
                    </div>

                    {/* Permission */}
                    <div>
                      <Badge variant={perm(ds).variant} className="text-[10px] px-1.5 py-0">
                        {perm(ds).label}
                      </Badge>
                    </div>

                    {/* Pipeline status */}
                    <div className="text-xs text-muted-foreground">
                      {ds.pipeline ? (
                        <span className="inline-flex items-center gap-1">
                          <span className="size-1.5 rounded-full bg-success" />
                          启用
                        </span>
                      ) : (
                        <span className="text-muted-foreground/40">--</span>
                      )}
                    </div>

                    {/* ID */}
                    <div className="hidden sm:block text-xs font-mono text-muted-foreground/60 tabular-nums truncate">
                      {ds.id.slice(0, 8)}
                    </div>

                    {/* Actions */}
                    <div className="flex justify-end">
                      <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                          <Button
                            variant="ghost" size="icon"
                            className="size-7 opacity-0 group-hover:opacity-100 transition-opacity"
                            onClick={(e) => e.stopPropagation()}
                            aria-label="操作菜单"
                          >
                            <MoreHorizontal className="w-4 h-4" />
                          </Button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end" className="w-44" onClick={(e) => e.stopPropagation()}>
                          <DropdownMenuItem onClick={() => router.push(`/datasets/${ds.id}/precheck`)}>
                            <FileSearch className="w-3.5 h-3.5 mr-2" /> 预检扫描
                          </DropdownMenuItem>
                          <DropdownMenuItem onClick={() => router.push(`/datasets/${ds.id}/profile`)}>
                            <BarChart3 className="w-3.5 h-3.5 mr-2" /> 数据画像
                          </DropdownMenuItem>
                          <DropdownMenuItem onClick={() => router.push(`/datasets/${ds.id}/ingestion`)}>
                            <Settings2 className="w-3.5 h-3.5 mr-2" /> 入库策略
                          </DropdownMenuItem>
                          <DropdownMenuItem onClick={() => router.push(`/datasets/${ds.id}/workflow`)}>
                            <Layers className="w-3.5 h-3.5 mr-2" /> Workflow
                          </DropdownMenuItem>
                          <DropdownMenuItem onClick={() => router.push(`/datasets/${ds.id}/tables`)}>
                            <Table2 className="w-3.5 h-3.5 mr-2" /> 表格 / TAG
                          </DropdownMenuItem>
                          <DropdownMenuItem onClick={() => router.push(`/datasets/${ds.id}/evidence`)}>
                            <ShieldCheck className="w-3.5 h-3.5 mr-2" /> 证据库
                          </DropdownMenuItem>
                          <DropdownMenuItem onClick={() => router.push(`/datasets/${ds.id}/db-catalog`)}>
                            <Database className="w-3.5 h-3.5 mr-2" /> 数据库目录
                          </DropdownMenuItem>
                          <DropdownMenuSeparator />
                          <DropdownMenuItem onClick={() => openEdit(ds)}>
                            <Pencil className="w-3.5 h-3.5 mr-2" /> 编辑
                          </DropdownMenuItem>
                          <DropdownMenuItem
                            className="text-destructive focus:text-destructive"
                            onClick={() => setDeleteTarget(ds)}
                          >
                            <Trash2 className="w-3.5 h-3.5 mr-2" /> 删除
                          </DropdownMenuItem>
                        </DropdownMenuContent>
                      </DropdownMenu>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </PageScaffold>

      {/* Delete confirmation */}
      <AlertDialog open={!!deleteTarget} onOpenChange={(open) => { if (!open) setDeleteTarget(null) }}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>删除数据集？</AlertDialogTitle>
            <AlertDialogDescription>
              你将删除 <span className="font-medium">{deleteTarget?.name}</span>。此操作不可撤销。
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>取消</AlertDialogCancel>
            <AlertDialogAction onClick={handleDelete}>删除</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Edit dialog */}
      <Dialog open={editOpen} onOpenChange={(open) => {
        setEditOpen(open)
        if (!open) { setEditing(null); resetForm() }
      }}>
        <DialogContent className="max-w-xl sm:rounded-2xl">
          <DialogHeader>
            <DialogTitle>编辑数据集</DialogTitle>
            <DialogDescription>更新名称、描述与访问权限</DialogDescription>
          </DialogHeader>
          <DatasetForm form={form} setForm={setForm} />
          {editing?.id ? <DatasetCategoryMultiSelect datasetId={editing.id} /> : null}
          <DialogFooter className="mt-4">
            <Button variant="ghost" onClick={() => setEditOpen(false)}>取消</Button>
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
              placeholder="user_1&#10;user_2"
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
            <div className="text-sm font-medium text-foreground">数据集默认管线</div>
            <div className="text-xs text-muted-foreground mt-0.5 leading-relaxed">
              启用后，该数据集下的文档默认使用此治理/索引配置
            </div>
          </div>
        </div>
        {form.pipelineEnabled && (
          <div className="p-4 bg-card/60">
            <div className="mb-4">
              <div className="text-xs font-medium text-muted-foreground mb-2">治理预设</div>
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
              onEnabledChange={() => {}}
              onOptionChange={(key, value) => {
                setForm((prev) => ({
                  ...prev,
                  pipelineOptions: { ...prev.pipelineOptions, [key]: value },
                }))
              }}
            />
          </div>
        )}
      </Panel>
    </div>
  )
}
