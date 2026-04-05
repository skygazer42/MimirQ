'use client'

import { useCallback, useEffect, useMemo, useState, type Dispatch, type ReactNode, type SetStateAction } from 'react'
import { toast } from 'sonner'
import {
  BarChart3, ChevronRight, Database, FileSearch, FolderOpen, Layers, Loader2,
  Pencil, Plus, RefreshCw, Search, Settings2, ShieldCheck,
  Table2, Trash2, Users, type LucideIcon,
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
import { CreateDatasetButton } from '@/components/datasets/create-dataset-button'
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

const PERMISSION_CONFIG: Record<PermissionEnum, {
  label: string
  className: string
  metricClassName: string
  dotClassName: string
}> = {
  all_team_members: {
    label: '全员',
    className: 'border-accent/20 bg-accent/10 text-accent dark:text-accent',
    metricClassName: 'text-accent dark:text-accent',
    dotClassName: 'bg-accent dark:bg-accent',
  },
  only_me: {
    label: '仅自己',
    className: 'border-info/20 bg-info/10 text-info dark:text-info',
    metricClassName: 'text-info dark:text-info',
    dotClassName: 'bg-info dark:bg-info',
  },
  partial_members: {
    label: '部分成员',
    className: 'border-warning/20 bg-warning/10 text-warning dark:text-warning',
    metricClassName: 'text-warning dark:text-warning',
    dotClassName: 'bg-warning dark:bg-warning',
  },
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
  const [selectedDatasetId, setSelectedDatasetId] = useState<string | null>(null)
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

  useEffect(() => {
    if (filteredItems.length === 0) {
      if (selectedDatasetId !== null) setSelectedDatasetId(null)
      return
    }

    if (!selectedDatasetId || !filteredItems.some((item) => item.id === selectedDatasetId)) {
      setSelectedDatasetId(filteredItems[0]?.id ?? null)
    }
  }, [filteredItems, selectedDatasetId])

  const canSubmit = useMemo(() => form.name.trim().length > 0, [form.name])
  const selectedDataset = useMemo(
    () => filteredItems.find((item) => item.id === selectedDatasetId) ?? filteredItems[0] ?? null,
    [filteredItems, selectedDatasetId]
  )

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
        size="full"
        compact
        description={<span>管理知识库集合与访问权限</span>}
        actions={
          <div className="flex items-center gap-2">
            <Button
              variant="ghost" size="sm"
              onClick={() => load()} disabled={isLoading}
            >
              <RefreshCw className={cn('size-4', isLoading && 'animate-spin motion-reduce:animate-none')} />
            </Button>
            <Dialog open={createOpen} onOpenChange={(open) => { setCreateOpen(open); if (open) resetForm() }}>
              <DialogTrigger asChild>
                <CreateDatasetButton />
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
        <div className="flex min-h-[calc(100vh-11.5rem)] flex-col overflow-hidden rounded-[1.75rem] border border-border/60 bg-card/90 shadow-soft">
          <div className="border-b border-border/60 bg-background/70 px-4 py-4 backdrop-blur supports-[backdrop-filter]:bg-background/55 md:px-5">
            <div className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
              <div className="space-y-1">
                <div className="inline-flex items-center gap-2 rounded-full border border-border/60 bg-card px-3 py-1 text-[11px] font-semibold tracking-[0.14em] text-muted-foreground shadow-sm">
                  <FolderOpen className="size-3.5 text-primary" />
                  <span>数据集目录</span>
                </div>
                <div className="flex flex-wrap items-center gap-3 text-sm text-muted-foreground">
                  <span className="flex items-center gap-1.5">
                    <Layers className="size-3.5" />
                    <span className="font-medium tabular-nums text-foreground">{total}</span>
                    <span>个数据集</span>
                  </span>
                  <span className="flex items-center gap-1.5">
                    <FolderOpen className="size-3.5" />
                    <span className="text-foreground">{selectedCategoryId ? '已筛选分类' : '全部分类'}</span>
                  </span>
                  {isLoading ? <Loader2 className="size-4 animate-spin motion-reduce:animate-none text-primary" /> : null}
                </div>
              </div>

              <div className="flex w-full flex-col gap-3 md:flex-row xl:w-auto">
                <div className="relative min-w-0 flex-1 xl:w-[360px]">
                  <Search className="absolute left-3 top-1/2 -translate-y-1/2 size-4 text-muted-foreground" />
                  <Input
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    placeholder="搜索数据集..."
                    className="h-10 rounded-full border-border/60 bg-card pl-9 shadow-sm"
                  />
                </div>
                <div className="inline-flex items-center gap-2 self-start rounded-full border border-border/60 bg-card px-3 py-2 text-xs text-muted-foreground shadow-sm">
                  <span className="font-medium text-foreground tabular-nums">{filteredItems.length}</span>
                  <span>条结果</span>
                </div>
              </div>
            </div>
          </div>

          <div className="grid flex-1 grid-cols-1 lg:grid-cols-[176px_minmax(0,1fr)]">
            <aside className="border-b border-border/60 bg-muted/15 px-2 py-3 lg:border-b-0 lg:border-r lg:px-2.5">
              <DatasetCategoryTree
                className="sticky top-0"
                selectedId={selectedCategoryId}
                onSelect={(id) => setSelectedCategoryId(id)}
              />
            </aside>

            <section className="min-w-0 bg-card/45">
              {filteredItems.length === 0 && !isLoading ? (
                <div className="flex min-h-full px-4 py-8 md:px-5">
                  <EmptyState
                    icon={Layers}
                    title={searchQuery ? '未找到匹配的数据集' : '暂无数据集'}
                    description={searchQuery ? '尝试更换关键词' : '点击“新建数据集”开始构建知识库'}
                    className="min-h-[360px] flex-1 rounded-[1.5rem] border border-dashed border-border/60 bg-background/50 shadow-none"
                  >
                    {!searchQuery && (
                      <Button className="gap-1.5" onClick={() => { resetForm(); setCreateOpen(true) }}>
                        <Plus className="size-4" /> 新建数据集
                      </Button>
                    )}
                  </EmptyState>
                </div>
              ) : (
                <div className="grid min-h-full grid-cols-1 xl:grid-cols-[minmax(0,1.15fr)_320px]">
                  <div className="min-w-0 xl:border-r xl:border-border/60">
                    <div className="flex items-end justify-between gap-4 border-b border-border/60 bg-muted/20 px-4 py-4 md:px-5">
                      <div className="space-y-1">
                        <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">
                          Datasets
                        </div>
                        <div className="text-sm font-semibold text-foreground">
                          {selectedCategoryId ? '当前分类目录' : '全部数据集'}
                        </div>
                      </div>
                      <div className="text-xs text-muted-foreground">
                        选择一个数据集以查看快捷入口与访问配置
                      </div>
                    </div>

                    <div className="space-y-3 px-4 py-4 md:px-5">
                      {filteredItems.map((ds) => {
                        const isActive = selectedDataset?.id === ds.id
                        const memberCount = ds.partial_member_list?.length ?? 0
                        const groupCount = ds.partial_group_list?.length ?? 0

                        return (
                          <button
                            key={ds.id}
                            type="button"
                            className={cn(
                              'focus-ring group w-full rounded-[1.5rem] border p-4 text-left transition-all duration-200 motion-reduce:transition-none',
                              isActive
                                ? 'border-primary/20 bg-primary/[0.06] shadow-md'
                                : 'border-border/60 bg-background/85 shadow-sm hover:border-primary/20 hover:bg-card hover:shadow-md'
                            )}
                            onClick={() => setSelectedDatasetId(ds.id)}
                          >
                            <div className="flex items-start gap-3">
                              <div
                                className={cn(
                                  'flex size-11 shrink-0 items-center justify-center rounded-2xl border shadow-sm',
                                  isActive ? 'border-primary/20 bg-card text-primary' : 'border-border/60 bg-card text-muted-foreground/60'
                                )}
                              >
                                <Layers className={cn('size-5', ds.pipeline ? 'text-primary' : 'text-muted-foreground/60')} />
                              </div>

                              <div className="min-w-0 flex-1">
                                <div className="flex flex-wrap items-center gap-2">
                                  <span className="truncate text-base font-semibold text-foreground">
                                    {ds.name}
                                  </span>
                                  <PermissionBadge permission={perm(ds)} />
                                  <DatasetMetaPill icon={Settings2}>
                                    {ds.pipeline ? '已配置管线' : '未配置管线'}
                                  </DatasetMetaPill>
                                </div>

                                <p className="mt-1 line-clamp-2 text-sm leading-6 text-muted-foreground">
                                  {ds.description || '暂无描述。可在右侧检视器进入预检、画像和入库策略配置。'}
                                </p>

                                <div className="mt-4 flex flex-wrap items-center gap-2">
                                  <DatasetMetaPill icon={Database}>ID {ds.id.slice(0, 8)}</DatasetMetaPill>
                                  <DatasetMetaPill icon={FolderOpen}>
                                    {selectedCategoryId ? '当前分类筛选' : '全部分类视图'}
                                  </DatasetMetaPill>
                                  {groupCount > 0 ? <DatasetMetaPill icon={Users}>组 {groupCount}</DatasetMetaPill> : null}
                                  {memberCount > 0 ? <DatasetMetaPill icon={ShieldCheck}>成员 {memberCount}</DatasetMetaPill> : null}
                                </div>
                              </div>
                            </div>

                            <div className="mt-4 flex items-center justify-between gap-3 border-t border-border/60 pt-3 text-xs">
                              <div className="text-muted-foreground">
                                {isActive ? '当前查看中' : '点击展开右侧检视器'}
                              </div>
                              <span className={cn(
                                'inline-flex items-center gap-1 rounded-full px-2.5 py-1 font-medium',
                                isActive ? 'bg-primary/10 text-primary' : 'bg-muted/60 text-muted-foreground group-hover:text-foreground'
                              )}>
                                {isActive ? '已选中' : '查看详情'}
                                <ChevronRight className="size-3.5" />
                              </span>
                            </div>
                          </button>
                        )
                      })}
                    </div>
                  </div>

                  <aside className="border-t border-border/60 bg-muted/15 xl:border-t-0">
                    <div className="sticky top-0 space-y-3 p-4 md:p-5">
                      {selectedDataset ? (
                        <>
                          <div className="rounded-[1.5rem] border border-border/60 bg-background/85 p-4 shadow-sm">
                            <div className="flex items-start justify-between gap-3">
                              <div className="inline-flex items-center gap-2 rounded-full border border-border/60 bg-card px-3 py-1 text-[11px] font-semibold tracking-[0.14em] text-muted-foreground">
                                <Layers className="size-3.5 text-primary" />
                                <span>数据集检视器</span>
                              </div>
                              <div className="flex items-center gap-1">
                                <Button
                                  variant="ghost"
                                  size="icon"
                                  className="size-8 rounded-full border border-border/60 bg-card/80"
                                  onClick={() => openEdit(selectedDataset)}
                                  aria-label="编辑数据集"
                                >
                                  <Pencil className="size-3.5" />
                                </Button>
                                <Button
                                  variant="ghost"
                                  size="icon"
                                  className="size-8 rounded-full border border-destructive/20 bg-card/80 text-destructive hover:bg-destructive/5 hover:text-destructive"
                                  onClick={() => setDeleteTarget(selectedDataset)}
                                  aria-label="删除数据集"
                                >
                                  <Trash2 className="size-3.5" />
                                </Button>
                              </div>
                            </div>

                            <div className="mt-3 flex items-start gap-3">
                              <div className="flex size-10 shrink-0 items-center justify-center rounded-2xl border border-primary/15 bg-card text-primary shadow-sm">
                                <Layers className="size-4" />
                              </div>
                              <div className="min-w-0">
                                <div className="flex flex-wrap items-center gap-2">
                                  <h3 className="text-base font-semibold leading-6 text-foreground">
                                    {selectedDataset.name}
                                  </h3>
                                  <PermissionBadge permission={perm(selectedDataset)} />
                                </div>
                                <p className="mt-1 text-sm leading-6 text-muted-foreground">
                                  {selectedDataset.description || '暂无描述。这个数据集已经可以继续做预检、画像和入库策略配置。'}
                                </p>
                              </div>
                            </div>

                            <div className="mt-4 grid grid-cols-2 gap-2">
                              <DatasetInspectorMetric icon={Database} label="数据集 ID" value={selectedDataset.id.slice(0, 8)} mono />
                              <DatasetInspectorMetric
                                icon={FolderOpen}
                                label="当前范围"
                                value={selectedCategoryId ? '当前分类筛选' : '全部分类视图'}
                              />
                              <DatasetInspectorMetric
                                icon={ShieldCheck}
                                label="访问权限"
                                value={perm(selectedDataset).label}
                                valueClassName={perm(selectedDataset).metricClassName}
                              />
                              <DatasetInspectorMetric
                                icon={Settings2}
                                label="默认管线"
                                value={selectedDataset.pipeline ? '已启用' : '未启用'}
                              />
                              <DatasetInspectorMetric
                                icon={Users}
                                label="成员 allowlist"
                                value={`${selectedDataset.partial_member_list?.length ?? 0} 人`}
                              />
                              <DatasetInspectorMetric
                                icon={Users}
                                label="组 allowlist"
                                value={`${selectedDataset.partial_group_list?.length ?? 0} 组`}
                              />
                            </div>
                          </div>

                          <div className="rounded-[1.5rem] border border-border/60 bg-background/80 p-4 shadow-sm">
                            <div className="flex items-start justify-between gap-3">
                              <div>
                                <div className="text-sm font-semibold text-foreground">操作台</div>
                                <div className="mt-1 text-xs leading-5 text-muted-foreground">
                                  常用动作保持一级可见，次级能力压缩成更紧凑的入口区。
                                </div>
                              </div>
                              <div className="rounded-full border border-border/60 bg-card px-2.5 py-1 text-[11px] text-muted-foreground">
                                Dense
                              </div>
                            </div>

                            <div className="mt-3 grid gap-2">
                              <DatasetShortcutButton
                                icon={FileSearch}
                                title="预检扫描"
                                description="检查文档质量、重复与结构风险"
                                onClick={() => router.push(`/datasets/${selectedDataset.id}/precheck`)}
                                emphasis
                                compact
                              />
                              <DatasetShortcutButton
                                icon={BarChart3}
                                title="数据画像"
                                description="查看规模、分布和结构特征"
                                onClick={() => router.push(`/datasets/${selectedDataset.id}/profile`)}
                                compact
                              />
                              <DatasetShortcutButton
                                icon={Settings2}
                                title="入库策略"
                                description="调整解析、索引和治理管线"
                                onClick={() => router.push(`/datasets/${selectedDataset.id}/ingestion`)}
                                compact
                              />
                            </div>

                            <div className="mt-3 border-t border-border/60 pt-3">
                              <div className="mb-2 text-[11px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
                                扩展能力
                              </div>
                              <div className="grid grid-cols-4 gap-2">
                                <DatasetMiniAction
                                  icon={Layers}
                                  title="Workflow"
                                  description="查看流程编排"
                                  onClick={() => router.push(`/datasets/${selectedDataset.id}/workflow`)}
                                />
                                <DatasetMiniAction
                                  icon={Table2}
                                  title="表格 / TAG"
                                  description="管理结构化资产"
                                  onClick={() => router.push(`/datasets/${selectedDataset.id}/tables`)}
                                />
                                <DatasetMiniAction
                                  icon={ShieldCheck}
                                  title="证据库"
                                  description="查看证据与审计"
                                  onClick={() => router.push(`/datasets/${selectedDataset.id}/evidence`)}
                                />
                                <DatasetMiniAction
                                  icon={Database}
                                  title="数据库目录"
                                  description="浏览数据库映射"
                                  onClick={() => router.push(`/datasets/${selectedDataset.id}/db-catalog`)}
                                />
                              </div>
                              <div className="mt-2 text-[11px] leading-4 text-muted-foreground">
                                悬停可查看说明，点击直接进入。
                              </div>
                            </div>
                          </div>
                        </>
                      ) : (
                        <div className="flex min-h-[360px] items-center justify-center rounded-[1.5rem] border border-dashed border-border/60 bg-background/55 p-6 text-center">
                          <div className="space-y-2">
                            <div className="text-sm font-semibold text-foreground">数据集检视器</div>
                            <div className="text-sm text-muted-foreground">
                              选择一个数据集后，这里会展示快捷入口、访问权限和扩展能力。
                            </div>
                          </div>
                        </div>
                      )}
                    </div>
                  </aside>
                </div>
              )}
            </section>
          </div>
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

function DatasetMetaPill({
  icon: Icon,
  children,
}: Readonly<{
  icon: LucideIcon
  children: ReactNode
}>) {
  return (
    <div className="inline-flex items-center gap-1.5 rounded-full border border-border/60 bg-card px-2.5 py-1 text-[11px] text-muted-foreground shadow-sm">
      <Icon className="size-3.5 text-primary" />
      <span>{children}</span>
    </div>
  )
}

function PermissionBadge({
  permission,
}: Readonly<{
  permission: typeof PERMISSION_CONFIG[PermissionEnum]
}>) {
  return (
    <Badge
      variant="outline"
      className={cn(
        'gap-1.5 px-2 py-0.5 text-[10px] font-semibold shadow-sm',
        permission.className
      )}
    >
      <span className={cn('size-1.5 rounded-full', permission.dotClassName)} />
      <span>{permission.label}</span>
    </Badge>
  )
}

function DatasetShortcutButton({
  icon: Icon,
  title,
  description,
  onClick,
  emphasis = false,
  compact = false,
}: Readonly<{
  icon: LucideIcon
  title: string
  description: string
  onClick: () => void
  emphasis?: boolean
  compact?: boolean
}>) {
  return (
    <button
      type="button"
      className={cn(
        'focus-ring flex w-full items-center gap-3 border text-left transition-colors duration-200 motion-reduce:transition-none',
        compact ? 'rounded-[1rem] px-3 py-2.5' : 'rounded-[1.15rem] px-3.5 py-3',
        emphasis
          ? 'border-primary/20 bg-primary/[0.08] hover:bg-primary/[0.12]'
          : 'border-border/60 bg-card hover:bg-muted/45'
      )}
      onClick={onClick}
    >
      <span className={cn(
        'flex shrink-0 items-center justify-center rounded-2xl border shadow-sm',
        compact ? 'h-9 w-9' : 'h-10 w-10',
        emphasis ? 'border-primary/15 bg-card text-primary' : 'border-border/60 bg-background/85 text-muted-foreground'
      )}>
        <Icon className="size-4" />
      </span>
      <span className="min-w-0 flex-1">
        <span className="block text-sm font-semibold text-foreground">{title}</span>
        <span className={cn('block text-xs text-muted-foreground', compact ? 'mt-0.5 leading-[1.15rem]' : 'mt-0.5 leading-5')}>
          {description}
        </span>
      </span>
      <ChevronRight className={cn('size-4 shrink-0', emphasis ? 'text-primary' : 'text-muted-foreground')} />
    </button>
  )
}

function DatasetInspectorMetric({
  icon: Icon,
  label,
  value,
  mono = false,
  valueClassName,
}: Readonly<{
  icon: LucideIcon
  label: string
  value: string
  mono?: boolean
  valueClassName?: string
}>) {
  return (
    <div className="rounded-[1rem] border border-border/60 bg-card px-3 py-2.5 shadow-sm">
      <div className="flex items-center gap-1.5 text-[11px] font-medium text-muted-foreground">
        <Icon className="size-3.5 text-primary" />
        <span>{label}</span>
      </div>
      <div className={cn('mt-1 text-sm font-semibold text-foreground', mono && 'font-mono tabular-nums', valueClassName)}>
        {value}
      </div>
    </div>
  )
}

function DatasetMiniAction({
  icon: Icon,
  title,
  description,
  onClick,
}: Readonly<{
  icon: LucideIcon
  title: string
  description: string
  onClick: () => void
}>) {
  return (
    <button
      type="button"
      className="focus-ring group relative flex h-12 items-center justify-center rounded-[0.95rem] border border-border/60 bg-card text-left transition-colors duration-200 hover:border-primary/20 hover:bg-muted/45 motion-reduce:transition-none"
      onClick={onClick}
      title={title}
      aria-label={`${title}：${description}`}
    >
      <span className="flex size-8 shrink-0 items-center justify-center rounded-xl border border-border/60 bg-background/85 text-muted-foreground transition-colors group-hover:border-primary/20 group-hover:text-primary">
        <Icon className="size-3.5" />
      </span>
      <span className="pointer-events-none absolute bottom-full left-1/2 z-20 mb-2 w-[9.5rem] -translate-x-1/2 translate-y-1 rounded-[1rem] border border-border/70 bg-popover/95 px-3 py-2 text-left opacity-0 shadow-lg backdrop-blur transition-all duration-200 group-hover:translate-y-0 group-hover:opacity-100 group-focus-visible:translate-y-0 group-focus-visible:opacity-100 motion-reduce:transition-none">
        <span className="block text-xs font-semibold text-foreground">{title}</span>
        <span className="mt-1 block text-[11px] leading-4 text-muted-foreground">{description}</span>
      </span>
    </button>
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
