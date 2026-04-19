'use client'

import { useCallback, useEffect, useMemo, useState, type Dispatch, type ReactNode, type SetStateAction } from 'react'
import { toast } from 'sonner'
import { motion, AnimatePresence } from 'framer-motion'
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
import { Switch } from '@/components/ui/switch'
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
  const [pipelineTogglePendingId, setPipelineTogglePendingId] = useState<string | null>(null)
  const [permissionUpdatePendingId, setPermissionUpdatePendingId] = useState<string | null>(null)
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

  const replaceDataset = useCallback((next: Dataset) => {
    setItems((prev) => prev.map((item) => (item.id === next.id ? next : item)))
  }, [])

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

  const openEdit = useCallback((ds: Dataset, permissionOverride?: PermissionEnum) => {
    setEditing(ds)
    const mergedPipeline = mergePipelineOptions(defaultPipelineOptions, ds.pipeline)
    setForm({
      name: ds.name || '', description: ds.description || '',
      permission: permissionOverride ?? ds.permission ?? 'all_team_members',
      partialMembersText: (ds.partial_member_list || []).join('\n'),
      partialGroupIds: (ds.partial_group_list || []).map(String),
      pipelineEnabled: !!ds.pipeline,
      pipelineOptions: mergedPipeline,
    })
    setEditOpen(true)
  }, [defaultPipelineOptions])

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

  const handleToggleDefaultPipeline = useCallback(async (dataset: Dataset, nextEnabled: boolean) => {
    setPipelineTogglePendingId(dataset.id)
    try {
      const updated = await datasetApi.update(dataset.id, {
        pipeline: nextEnabled ? mergePipelineOptions(defaultPipelineOptions, dataset.pipeline) : {},
      })
      replaceDataset(updated)
      toast.success(nextEnabled ? '已启用默认管线' : '已关闭默认管线')
    } catch (e: any) {
      toast.error(formatApiError(e, nextEnabled ? '启用默认管线失败' : '关闭默认管线失败'))
    } finally {
      setPipelineTogglePendingId((current) => (current === dataset.id ? null : current))
    }
  }, [defaultPipelineOptions, replaceDataset])

  const handleInspectorPermissionChange = useCallback(async (dataset: Dataset, nextPermission: PermissionEnum) => {
    if (nextPermission === dataset.permission) return
    if (nextPermission === 'partial_members') {
      openEdit(dataset, 'partial_members')
      return
    }

    setPermissionUpdatePendingId(dataset.id)
    try {
      const updated = await datasetApi.update(dataset.id, { permission: nextPermission })
      replaceDataset(updated)
      toast.success(nextPermission === 'only_me' ? '已切换为仅自己' : '已切换为全员可见')
    } catch (e: any) {
      toast.error(formatApiError(e, '更新访问权限失败'))
    } finally {
      setPermissionUpdatePendingId((current) => (current === dataset.id ? null : current))
    }
  }, [openEdit, replaceDataset])

  const pipelineTogglePending = selectedDataset ? pipelineTogglePendingId === selectedDataset.id : false
  const permissionUpdatePending = selectedDataset ? permissionUpdatePendingId === selectedDataset.id : false

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
              <DialogContent className="max-w-xl p-0 sm:rounded-2xl">
                <div className="flex max-h-[min(88vh,860px)] flex-col">
                  <DialogHeader className="border-b border-border/60 px-6 pt-6 pb-4">
                    <DialogTitle>新建数据集</DialogTitle>
                    <DialogDescription>为文档分组并设置访问权限</DialogDescription>
                  </DialogHeader>
                  <div className="flex-1 overflow-y-auto custom-scrollbar px-6 py-5">
                    <DatasetForm form={form} setForm={setForm} />
                  </div>
                  <DialogFooter className="border-t border-border/60 px-6 py-4">
                    <Button variant="ghost" onClick={() => setCreateOpen(false)}>取消</Button>
                    <Button onClick={handleCreate} disabled={!canSubmit}>确认创建</Button>
                  </DialogFooter>
                </div>
              </DialogContent>
            </Dialog>
          </div>
        }
      >
        <div className="flex min-h-[calc(100vh-11.5rem)] flex-col overflow-hidden rounded-3xl border border-border/60 bg-card/90 shadow-soft">
          <div className="border-b border-border/60 bg-background/70 px-4 py-4 backdrop-blur supports-[backdrop-filter]:bg-background/55 md:px-5">
            <div className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
              <div className="space-y-1">
                <div className="inline-flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
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
                <div className="inline-flex items-center gap-1.5 self-start text-xs text-muted-foreground">
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
                    className="min-h-[360px] flex-1 rounded-3xl border border-dashed border-border/60 bg-background/50 shadow-none"
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

                    <motion.div 
                      initial="hidden"
                      animate="visible"
                      variants={{
                        hidden: { opacity: 0 },
                        visible: { 
                          opacity: 1,
                          transition: { staggerChildren: 0.04 }
                        }
                      }}
                      className="space-y-4 px-4 py-5 md:px-6 relative"
                    >
                      {/* 装饰性背景光感 */}
                      <div className="absolute top-0 left-1/4 w-64 h-64 bg-primary/5 rounded-full blur-[100px] pointer-events-none -z-10" />

                      {filteredItems.map((ds) => {
                        const isActive = selectedDataset?.id === ds.id
                        const memberCount = ds.partial_member_list?.length ?? 0
                        const groupCount = ds.partial_group_list?.length ?? 0

                        return (
                          <motion.button
                            key={ds.id}
                            variants={{
                              hidden: { opacity: 0, y: 10 },
                              visible: { opacity: 1, y: 0 }
                            }}
                            type="button"
                            whileHover={{ scale: 1.01, y: -2 }}
                            whileTap={{ scale: 0.995 }}
                            className={cn(
                              'focus-ring group w-full rounded-3xl p-5 text-left transition-all duration-300 relative overflow-hidden',
                              isActive
                                ? 'border-primary/30 bg-background shadow-[0_8px_30px_rgb(var(--primary),0.08)] ring-1 ring-primary/20'
                                : 'border-border/50 bg-card/40 hover:bg-card hover:shadow-xl hover:border-border/80'
                            )}
                            onClick={() => setSelectedDatasetId(ds.id)}
                          >
                            {/* 选中态的侧边品牌色装饰 */}
                            {isActive && (
                              <div className="absolute left-0 top-0 bottom-0 w-1 bg-primary shadow-[0_0_12px_rgba(var(--primary),0.4)]" />
                            )}

                            <div className="flex items-start gap-4">
                              <div
                                className={cn(
                                  'flex size-12 shrink-0 items-center justify-center rounded-2xl transition-all duration-500 shadow-sm border',
                                  isActive 
                                    ? 'bg-gradient-to-br from-primary to-primary/80 text-primary-foreground border-primary/20 scale-105' 
                                    : 'bg-background text-muted-foreground/40 border-border/40 group-hover:border-primary/20 group-hover:text-primary/60 group-hover:bg-primary/5'
                                )}
                              >
                                <Layers className={cn('size-6', ds.pipeline ? '' : 'opacity-60')} />
                              </div>

                              <div className="min-w-0 flex-1">
                                <div className="flex flex-wrap items-center gap-2">
                                  <span className={cn(
                                    "truncate text-base font-bold tracking-tight transition-colors duration-300",
                                    isActive ? "text-foreground" : "text-foreground/90"
                                  )}>
                                    {ds.name}
                                  </span>
                                  <PermissionBadge permission={perm(ds)} />
                                  {ds.pipeline && (
                                    <div className="flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-emerald-500/10 border border-emerald-500/20 text-emerald-600 dark:text-emerald-400 text-[11px] font-bold animate-in fade-in zoom-in duration-500">
                                      <div className="size-1 rounded-full bg-emerald-500 shadow-[0_0_8px_#10b981]" />
                                      CONNECTED
                                    </div>
                                  )}
                                </div>

                                <p className="mt-2 line-clamp-2 text-[13px] leading-relaxed text-muted-foreground/70 group-hover:text-muted-foreground transition-colors">
                                  {ds.description || '暂无描述。可在右侧检视器进入预检、画像和入库策略配置。'}
                                </p>

                                <div className="mt-5 flex flex-wrap items-center gap-3">
                                  <DatasetMetaPill icon={Database} className="bg-indigo-500/5 text-indigo-600 dark:text-indigo-400 border-indigo-500/10">
                                    ID {ds.id.slice(0, 8)}
                                  </DatasetMetaPill>
                                  {groupCount > 0 && (
                                    <DatasetMetaPill icon={Users} className="bg-amber-500/5 text-amber-600 dark:text-amber-400 border-amber-500/10">
                                      {groupCount} 组
                                    </DatasetMetaPill>
                                  )}
                                  {memberCount > 0 && (
                                    <DatasetMetaPill icon={ShieldCheck} className="bg-sky-500/5 text-sky-600 dark:text-sky-400 border-sky-500/10">
                                      {memberCount} 成员
                                    </DatasetMetaPill>
                                  )}
                                </div>
                              </div>
                            </div>
                          </motion.button>
                        )
                      })}
                    </motion.div>
                  </div>

                  <aside className="border-t border-border/60 bg-muted/5 xl:border-t-0">
                    <div className="sticky top-0 space-y-4 p-4 md:p-6 overflow-hidden">
                      <AnimatePresence mode="wait">
                        {selectedDataset ? (
                          <motion.div
                            key={selectedDataset.id}
                            initial={{ opacity: 0, x: 15 }}
                            animate={{ opacity: 1, x: 0 }}
                            exit={{ opacity: 0, x: -15 }}
                            transition={{ duration: 0.3, ease: [0.16, 1, 0.3, 1] }}
                            className="space-y-4"
                          >
                            <div className="rounded-[2.25rem] border border-border/60 bg-background/90 p-5 shadow-soft relative overflow-hidden group/main-card">
                              {/* Enhanced Background Decoration */}
                              <div className="absolute top-0 right-0 w-40 h-40 bg-gradient-to-br from-primary/15 to-transparent rounded-full blur-[80px] pointer-events-none opacity-40 group-hover/main-card:opacity-60 transition-opacity duration-700" />

                              <div className="flex items-start justify-between gap-4 mb-5 relative px-1">
                                <div className="flex flex-col">
                                  <div className="text-[11px] font-bold uppercase tracking-[0.25em] text-primary/40 leading-tight mb-1">数据集详情</div>
                                  <h3 className="text-xl font-bold tracking-tight text-foreground leading-[1.15]">
                                    {selectedDataset.name}
                                  </h3>
                                </div>
                                <div className="flex items-center gap-1.5 shrink-0 pt-1">
                                  <Button
                                    variant="ghost"
                                    size="icon"
                                    className="size-8 rounded-xl border border-border/50 bg-background/40 hover:bg-muted hover:border-primary/20 transition-all duration-300"
                                    onClick={() => openEdit(selectedDataset)}
                                    aria-label="编辑数据集"
                                  >
                                    <Pencil className="size-3.5" />
                                  </Button>
                                  <Button
                                    variant="ghost"
                                    size="icon"
                                    className="size-8 rounded-xl border border-destructive/20 bg-background/40 text-destructive/60 hover:text-destructive hover:bg-destructive/10 hover:border-destructive/30 transition-all duration-300"
                                    onClick={() => setDeleteTarget(selectedDataset)}
                                    aria-label="删除数据集"
                                  >
                                    <Trash2 className="size-3.5" />
                                  </Button>
                                </div>
                              </div>

                              <div className="mt-5 border-t border-border/40 pt-5 relative">
                                <div className="mb-4 flex items-center justify-between px-1">
                                  <div className="flex flex-col">
                                    <div className="text-[11px] font-bold uppercase tracking-[0.15em] text-foreground/90">
                                      元信息与状态
                                    </div>
                                    <div className="text-[9px] font-medium text-muted-foreground/40 leading-none mt-0.5">
                                      Global Status
                                    </div>
                                  </div>
                                  <div className="h-4 w-[1px] bg-border/40" />
                                </div>                                <div className="space-y-0.5 rounded-3xl border border-border/40 bg-muted/15 p-2.5 backdrop-blur-sm shadow-inner-soft">
                                  <DatasetInspectorMetric icon={Database} label="数据集 ID" value={selectedDataset.id.slice(0, 8)} mono />
                                  <DatasetInspectorMetric
                                    icon={FolderOpen}
                                    label="当前范围"
                                    value={selectedCategoryId ? '当前分类筛选' : '全部分类视图'}
                                  />
                                  <div className="flex items-center justify-between py-1.5 group/metric px-2 -mx-1 rounded-lg hover:bg-muted/50 transition-colors">
                                    <div className="flex min-w-0 items-center gap-2">
                                      <ShieldCheck className="size-3 text-muted-foreground/30 group-hover/metric:text-primary transition-colors" />
                                      <span className="text-[11px] font-bold uppercase tracking-wider text-muted-foreground/60 group-hover/metric:text-muted-foreground transition-colors">
                                        访问权限
                                      </span>
                                    </div>
                                    <div className="ml-3 flex items-center gap-2">
                                      {permissionUpdatePending ? <Loader2 className="size-3 animate-spin text-muted-foreground/50" /> : null}
                                      <div className="w-[132px]">
                                        <Select
                                          value={selectedDataset.permission}
                                          disabled={permissionUpdatePending}
                                          onValueChange={(value) => detachPromise(handleInspectorPermissionChange(selectedDataset, value as PermissionEnum))}
                                        >
                                          <SelectTrigger
                                            aria-label="访问权限"
                                            className={cn(
                                              'ml-auto h-8 w-auto min-w-[88px] max-w-full justify-end gap-1.5 rounded-xl border pl-2 pr-2 text-[11px] font-semibold shadow-none [&>span]:truncate [&>span]:text-right [&>svg]:h-3 [&>svg]:w-3 [&>svg]:shrink-0',
                                              perm(selectedDataset).className
                                            )}
                                          >
                                            <SelectValue />
                                          </SelectTrigger>
                                          <SelectContent>
                                            <SelectItem value="only_me">仅自己</SelectItem>
                                            <SelectItem value="all_team_members">全员可见</SelectItem>
                                            <SelectItem value="partial_members">部分成员</SelectItem>
                                          </SelectContent>
                                        </Select>
                                      </div>
                                    </div>
                                  </div>
                                  <div className="flex items-center justify-between py-1.5 group/metric px-2 -mx-1 rounded-lg hover:bg-muted/50 transition-colors">
                                    <div className="flex min-w-0 items-center gap-2">
                                      <Settings2 className="size-3 text-muted-foreground/30 group-hover/metric:text-primary transition-colors" />
                                      <div className="flex min-w-0 flex-col">
                                        <span className="text-[11px] font-bold uppercase tracking-wider text-muted-foreground/60 group-hover/metric:text-muted-foreground transition-colors">
                                          默认管线
                                        </span>
                                        <span
                                          className={cn(
                                            'text-[11px] font-semibold leading-relaxed transition-colors',
                                            selectedDataset.pipeline
                                              ? 'text-emerald-600 dark:text-emerald-400'
                                              : 'text-muted-foreground/70'
                                          )}
                                        >
                                          {selectedDataset.pipeline ? '已启用' : '未启用'}
                                        </span>
                                      </div>
                                    </div>
                                    <div className="ml-3 flex items-center gap-2">
                                      {pipelineTogglePending ? <Loader2 className="size-3 animate-spin text-muted-foreground/50" /> : null}
                                      <Switch
                                        checked={Boolean(selectedDataset.pipeline)}
                                        disabled={pipelineTogglePending}
                                        onCheckedChange={(nextChecked) => detachPromise(handleToggleDefaultPipeline(selectedDataset, nextChecked))}
                                        aria-label={selectedDataset.pipeline ? '关闭默认管线' : '启用默认管线'}
                                        title={selectedDataset.pipeline ? '关闭默认管线' : '启用默认管线'}
                                      />
                                    </div>
                                  </div>
                                  <div className="grid grid-cols-2 gap-2 mt-2">
                                    <DatasetInspectorMetric
                                      variant="stat"
                                      icon={Users}
                                      label="成员"
                                      value={`${selectedDataset.partial_member_list?.length ?? 0} 人`}
                                      valueClassName="text-amber-600 dark:text-amber-400"
                                    />
                                    <DatasetInspectorMetric
                                      variant="stat"
                                      icon={Users}
                                      label="白名单组"
                                      value={`${selectedDataset.partial_group_list?.length ?? 0} 组`}
                                      valueClassName="text-indigo-600 dark:text-indigo-400"
                                    />
                                  </div>
                                </div>
                              </div>
                            </div>
                            <div className="rounded-[2.25rem] border border-border/60 bg-background/80 p-5 shadow-soft relative overflow-hidden group/console">
                              {/* Background subtle decoration */}
                              <div className="absolute -top-12 -right-12 size-48 bg-primary/5 rounded-full blur-[60px] pointer-events-none group-hover/console:bg-primary/10 transition-colors duration-700" />
                              
                              <div className="relative mb-5 flex items-center justify-between px-1">
                                <div className="flex flex-col">
                                  <div className="text-sm font-bold text-foreground tracking-tight">操作台</div>
                                  <div className="text-[11px] font-semibold text-muted-foreground/50 uppercase tracking-widest leading-none mt-0.5">
                                    Command Center
                                  </div>
                                </div>
                                <div className="flex items-center gap-1.5 px-2 py-1 rounded-full bg-muted/30 border border-border/10 text-[11px] font-bold text-muted-foreground/60">
                                  <div className="size-1 rounded-full bg-primary/40" />
                                  常用入口
                                </div>
                              </div>

                              <div className="grid gap-2 relative">
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

                              <div className="mt-6 border-t border-border/40 pt-5 relative">
                                <div className="mb-4 flex items-center justify-between px-1">
                                  <div className="flex items-center gap-1.5">
                                    <div className="size-1.5 rounded-full bg-muted-foreground/20" />
                                    <span className="text-[11px] font-bold uppercase tracking-[0.15em] text-muted-foreground/60">
                                      扩展能力
                                    </span>
                                  </div>
                                  <div className="h-px flex-1 mx-3 bg-gradient-to-r from-border/40 to-transparent" />
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
                                    title="DB 目录"
                                    description="浏览数据库映射"
                                    onClick={() => router.push(`/datasets/${selectedDataset.id}/db-catalog`)}
                                  />
                                </div>
                              </div>
                            </div>
                          </motion.div>
                        ) : (
                          <motion.div
                            key="empty"
                            initial={{ opacity: 0 }}
                            animate={{ opacity: 1 }}
                            exit={{ opacity: 0 }}
                            className="flex min-h-[400px] flex-col items-center justify-center rounded-3xl border border-dashed border-border/60 bg-background/40 p-8 text-center"
                          >
                            <Layers className="size-10 text-muted-foreground/20 mb-4" />
                            <div className="space-y-2">
                              <div className="text-sm font-semibold text-foreground/80">检视器就绪</div>
                              <div className="text-xs leading-relaxed text-muted-foreground/60 max-w-[200px] mx-auto">
                                从左侧列表中选择一个数据集，即可预览配置、访问权限以及开启高级功能入口。
                              </div>
                            </div>
                          </motion.div>
                        )}
                      </AnimatePresence>
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
        <DialogContent className="max-w-xl p-0 sm:rounded-2xl">
          <div className="flex max-h-[min(88vh,860px)] flex-col">
            <DialogHeader className="border-b border-border/60 px-6 pt-6 pb-4">
              <DialogTitle>编辑数据集</DialogTitle>
              <DialogDescription>更新名称、描述与访问权限</DialogDescription>
            </DialogHeader>
            <div className="flex-1 overflow-y-auto custom-scrollbar px-6 py-5">
              <DatasetForm form={form} setForm={setForm} />
              {editing?.id ? <DatasetCategoryMultiSelect datasetId={editing.id} /> : null}
            </div>
            <DialogFooter className="border-t border-border/60 px-6 py-4">
              <Button variant="ghost" onClick={() => setEditOpen(false)}>取消</Button>
              <Button onClick={handleUpdate} disabled={!canSubmit || !editing}>保存变更</Button>
            </DialogFooter>
          </div>
        </DialogContent>
      </Dialog>
    </AppFrame>
  )
}

function DatasetMetaPill({
  icon: Icon,
  children,
  className,
}: Readonly<{
  icon: LucideIcon
  children: ReactNode
  className?: string
}>) {
  return (
    <div className={cn('inline-flex items-center gap-1 text-[11px] text-muted-foreground', className)}>
      <Icon className="size-3 text-muted-foreground/50" />
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
        'gap-1.5 px-2 py-0.5 text-[11px] font-semibold shadow-sm',
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
        'focus-ring group relative flex w-full items-center gap-3.5 overflow-hidden border transition-all duration-300 motion-reduce:transition-none',
        compact ? 'rounded-2xl px-3.5 py-3' : 'rounded-3xl px-5 py-4',
        emphasis
          ? 'border-primary/20 bg-primary/[0.03] hover:border-primary/40 hover:bg-primary/[0.06] hover:shadow-[0_8px_30px_-12px_rgba(var(--primary),0.2)]'
          : 'border-border/60 bg-background/50 hover:border-primary/30 hover:bg-muted/30 hover:shadow-soft'
      )}
      onClick={onClick}
    >
      {/* Interactive Background Shine */}
      <div className="absolute inset-0 bg-gradient-to-br from-primary/[0.05] via-transparent to-transparent opacity-0 group-hover:opacity-100 transition-opacity duration-500" />
      
      <div className={cn(
        'relative flex shrink-0 items-center justify-center rounded-xl transition-all duration-500 group-hover:scale-110 group-hover:rotate-3',
        compact ? 'size-10' : 'size-11',
        emphasis 
          ? 'bg-primary/10 text-primary shadow-sm shadow-primary/20' 
          : 'bg-muted/50 text-muted-foreground group-hover:bg-primary/10 group-hover:text-primary'
      )}>
        <Icon className={compact ? 'size-5' : 'size-5.5'} />
      </div>
      
      <div className="relative min-w-0 flex-1 flex flex-col justify-center text-left">
        <div className="text-[13px] font-bold tracking-tight text-foreground leading-normal mb-0.5 group-hover:text-primary transition-colors">
          {title}
        </div>
        <div
          className="text-[11px] font-medium text-muted-foreground/60 leading-relaxed truncate"
          title={description}
        >
          {description}
        </div>
      </div>
      
      <div className="relative flex items-center justify-center size-5 opacity-0 -translate-x-2 group-hover:opacity-100 group-hover:translate-x-0 transition-all duration-300">
        <ChevronRight className={cn(
          'size-4',
          emphasis ? 'text-primary' : 'text-primary/60'
        )} />
      </div>
    </button>
  )
}

function DatasetInspectorMetric({
  icon: Icon,
  label,
  value,
  mono = false,
  valueClassName,
  variant = 'default',
}: Readonly<{
  icon: LucideIcon
  label: string
  value: string
  mono?: boolean
  valueClassName?: string
  variant?: 'default' | 'stat'
}>) {
  if (variant === 'stat') {
    return (
      <div className="flex flex-col items-center justify-center gap-1 rounded-xl border border-border/30 bg-background/40 p-2.5 group/stat hover:bg-background/60 hover:border-primary/20 transition-all duration-200">
        <div className="flex items-center gap-1.5 text-[9px] font-bold uppercase tracking-wider text-muted-foreground/50 group-hover/stat:text-primary/70 transition-colors">
          <Icon className="size-2.5" />
          <span className="truncate">{label}</span>
        </div>
        <div className={cn("text-[13px] font-bold tracking-tight text-foreground/90 text-center", valueClassName)}>
          {value}
        </div>
      </div>
    )
  }

  return (
    <div className="flex items-center justify-between py-1.5 group/metric px-2 -mx-1 rounded-lg hover:bg-muted/50 transition-colors">
      <div className="flex min-w-0 items-center gap-2">
        <Icon className="size-3 text-muted-foreground/30 group-hover/metric:text-primary transition-colors" />
        <span className="text-[11px] font-bold uppercase tracking-wider text-muted-foreground/60 group-hover/metric:text-muted-foreground transition-colors truncate">
          {label}
        </span>
      </div>
      <div className={cn(
        'ml-auto min-w-0 truncate text-right text-[11px] font-semibold text-foreground/80 bg-muted/20 px-2 py-0.5 rounded-md border border-border/5',
        mono && 'font-mono tabular-nums tracking-tighter', 
        valueClassName
      )}>
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
      className="focus-ring group relative flex flex-col items-center justify-center gap-2 rounded-2xl border border-border/50 bg-background/40 py-2.5 transition-all duration-300 hover:border-primary/25 hover:bg-muted/40 hover:shadow-inner-soft group-hover:scale-[1.02]"
      onClick={onClick}
      aria-label={`${title}：${description}`}
    >
      <div className="flex size-7 items-center justify-center rounded-lg bg-muted/30 text-muted-foreground/50 transition-all duration-300 group-hover:bg-primary/10 group-hover:text-primary group-hover:scale-110">
        <Icon className="size-3.5" />
      </div>
      <div className="flex flex-col items-center text-center">
        <span className="block text-[11px] font-bold text-foreground/80 group-hover:text-primary transition-colors truncate w-full px-1">
          {title}
        </span>
      </div>
      
      {/* Tooltip on hover */}
      <div className="pointer-events-none absolute bottom-full left-1/2 z-20 mb-2 w-36 -translate-x-1/2 translate-y-1 rounded-xl border border-border/60 bg-popover/95 px-2.5 py-1.5 text-center opacity-0 shadow-xl backdrop-blur transition-all duration-300 group-hover:translate-y-0 group-hover:opacity-100">
        <div className="text-[11px] font-bold text-foreground mb-0.5">{title}</div>
        <div className="text-[9px] leading-tight text-muted-foreground/80">{description}</div>
      </div>
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
