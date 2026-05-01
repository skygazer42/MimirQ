'use client'

import { useCallback, useEffect, useMemo, useState, type Dispatch, type ReactNode, type SetStateAction } from 'react'
import { toast } from 'sonner'
import { motion, AnimatePresence } from 'framer-motion'
import {
  AlertCircle, BarChart3, CheckCircle2, ChevronRight, Clock3, Database, FileSearch,
  Filter, FolderOpen, Layers, Loader2, MoreHorizontal, Pencil, RefreshCw, Search, Settings2,
  ShieldCheck, Table2, Trash2, Users, type LucideIcon,
} from 'lucide-react'

import { AppFrame } from '@/components/app-frame'
import { useRouter } from '@/i18n/navigation'
import { PageScaffold } from '@/components/ui/page-scaffold'
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
import type { Dataset, PermissionEnum, DocumentPipelineOptions, DatasetIngestionStats } from '@/types'
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

function getDatasetAnomalyCount(stats?: DatasetIngestionStats | null): number {
  const byStatus = stats?.by_status || {}
  return Number(byStatus.failed || 0) + Number(byStatus.quarantined || 0)
}

function getDatasetPendingCount(stats?: DatasetIngestionStats | null): number {
  const byStatus = stats?.by_status || {}
  return Number(byStatus.pending || 0) + Number(byStatus.processing || 0)
}

function getDatasetOperationalStatus(dataset: Dataset, stats?: DatasetIngestionStats | null): 'active' | 'anomaly' | 'pending' | 'testing' {
  const name = String(dataset.name || '').toLowerCase()
  if (name.includes('test') || name.includes('demo') || name.includes('测试')) return 'testing'
  if (getDatasetAnomalyCount(stats) > 0) return 'anomaly'
  if (getDatasetPendingCount(stats) > 0) return 'pending'
  return 'active'
}

function formatRelativeTime(value?: string | null): string {
  if (!value) return '刚刚'
  const timestamp = new Date(value).getTime()
  if (!Number.isFinite(timestamp)) return value
  const diffMs = Date.now() - timestamp
  const diffHours = Math.max(0, Math.floor(diffMs / (1000 * 60 * 60)))
  if (diffHours < 1) return '刚刚'
  if (diffHours < 24) return `${diffHours} 小时前`
  const diffDays = Math.floor(diffHours / 24)
  return `${diffDays} 天前`
}

function getDatasetStatusBadgeConfig(status: 'active' | 'anomaly' | 'pending' | 'testing') {
  switch (status) {
    case 'active':
      return {
        label: '正常',
        className: 'border-emerald-500/20 bg-emerald-500/10 text-emerald-600',
        dotClassName: 'bg-emerald-500',
      }
    case 'anomaly':
      return {
        label: '异常',
        className: 'border-red-500/20 bg-red-500/10 text-red-600',
        dotClassName: 'bg-red-500',
      }
    case 'pending':
      return {
        label: '处理中',
        className: 'border-amber-500/20 bg-amber-500/10 text-amber-600',
        dotClassName: 'bg-amber-500',
      }
    case 'testing':
      return {
        label: '测试集',
        className: 'border-blue-500/20 bg-blue-500/10 text-blue-600',
        dotClassName: 'bg-blue-500',
      }
  }
}

function getDatasetStatusIconConfig(status: 'active' | 'anomaly' | 'pending' | 'testing') {
  switch (status) {
    case 'active':
      return {
        defaultClassName: 'border-emerald-200/80 bg-emerald-50 text-emerald-600',
        activeClassName: 'border-emerald-300/90 bg-emerald-100 text-emerald-700',
      }
    case 'anomaly':
      return {
        defaultClassName: 'border-red-200/80 bg-red-50 text-red-500',
        activeClassName: 'border-red-300/90 bg-red-100 text-red-600',
      }
    case 'pending':
      return {
        defaultClassName: 'border-amber-200/80 bg-amber-50 text-amber-600',
        activeClassName: 'border-amber-300/90 bg-amber-100 text-amber-700',
      }
    case 'testing':
      return {
        defaultClassName: 'border-blue-200/80 bg-blue-50 text-blue-600',
        activeClassName: 'border-blue-300/90 bg-blue-100 text-blue-700',
      }
  }
}

function estimateDatasetHealthScore(dataset: Dataset, stats?: DatasetIngestionStats | null): number {
  const anomalyPenalty = getDatasetAnomalyCount(stats) * 12
  const pendingPenalty = getDatasetPendingCount(stats) * 4
  const testingPenalty = getDatasetOperationalStatus(dataset, stats) === 'testing' ? 6 : 0
  return Math.max(62, Math.min(96, 94 - anomalyPenalty - pendingPenalty - testingPenalty))
}

function getDatasetIconTone(icon: LucideIcon) {
  if (icon === Database) {
    return {
      iconClassName: 'text-violet-600',
      softIconClassName: 'text-violet-500',
      containerClassName: 'border-violet-200/80 bg-violet-50 text-violet-600',
      chipClassName: 'text-violet-600',
    }
  }

  if (icon === FolderOpen || icon === FileSearch || icon === Search) {
    return {
      iconClassName: 'text-sky-600',
      softIconClassName: 'text-sky-500',
      containerClassName: 'border-sky-200/80 bg-sky-50 text-sky-600',
      chipClassName: 'text-sky-600',
    }
  }

  if (icon === Layers || icon === Table2) {
    return {
      iconClassName: 'text-indigo-600',
      softIconClassName: 'text-indigo-500',
      containerClassName: 'border-indigo-200/80 bg-indigo-50 text-indigo-600',
      chipClassName: 'text-indigo-600',
    }
  }

  if (icon === ShieldCheck || icon === Users) {
    return {
      iconClassName: 'text-blue-600',
      softIconClassName: 'text-blue-500',
      containerClassName: 'border-blue-200/80 bg-blue-50 text-blue-600',
      chipClassName: 'text-blue-600',
    }
  }

  if (icon === Settings2 || icon === Clock3) {
    return {
      iconClassName: 'text-amber-600',
      softIconClassName: 'text-amber-500',
      containerClassName: 'border-amber-200/80 bg-amber-50 text-amber-600',
      chipClassName: 'text-amber-600',
    }
  }

  if (icon === AlertCircle) {
    return {
      iconClassName: 'text-red-500',
      softIconClassName: 'text-red-400',
      containerClassName: 'border-red-200/80 bg-red-50 text-red-500',
      chipClassName: 'text-red-500',
    }
  }

  if (icon === BarChart3 || icon === CheckCircle2) {
    return {
      iconClassName: 'text-emerald-600',
      softIconClassName: 'text-emerald-500',
      containerClassName: 'border-emerald-200/80 bg-emerald-50 text-emerald-600',
      chipClassName: 'text-emerald-600',
    }
  }

  return {
    iconClassName: 'text-slate-600',
    softIconClassName: 'text-slate-500',
    containerClassName: 'border-slate-200/80 bg-slate-50 text-slate-600',
    chipClassName: 'text-slate-600',
  }
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
  const [collectionFilter, setCollectionFilter] = useState<'all' | 'active' | 'anomaly' | 'pending' | 'testing'>('all')
  const [selectedDatasetId, setSelectedDatasetId] = useState<string | null>(null)
  const [pageSize, setPageSize] = useState(20)
  const [currentPage, setCurrentPage] = useState(1)
  const [deleteTarget, setDeleteTarget] = useState<Dataset | null>(null)
  const [statsByDatasetId, setStatsByDatasetId] = useState<Record<string, DatasetIngestionStats>>({})

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

  useEffect(() => {
    const missingIds = items
      .map((dataset) => dataset.id)
      .filter((id) => !statsByDatasetId[id])

    if (missingIds.length === 0) return

    let cancelled = false
    detachPromise((async () => {
      const statsEntries = await Promise.all(
        missingIds.map(async (datasetId) => {
          try {
            const stats = await datasetApi.getIngestionStats(datasetId)
            return [datasetId, stats] as const
          } catch {
            return null
          }
        })
      )

      if (cancelled) return

      setStatsByDatasetId((prev) => {
        const next = { ...prev }
        for (const entry of statsEntries) {
          if (!entry) continue
          const [datasetId, stats] = entry
          next[datasetId] = stats
        }
        return next
      })
    })())

    return () => {
      cancelled = true
    }
  }, [items, statsByDatasetId])

  const filteredItems = useMemo(() => {
    const q = searchQuery.trim().toLowerCase()
    if (!q) return items
    return items.filter((ds) =>
      (ds.name || '').toLowerCase().includes(q) ||
      (ds.description || '').toLowerCase().includes(q) ||
      (ds.id || '').toLowerCase().includes(q)
    )
  }, [items, searchQuery])

  const statusCounts = useMemo(() => {
    return filteredItems.reduce(
      (acc, dataset) => {
        const status = getDatasetOperationalStatus(dataset, statsByDatasetId[dataset.id])
        acc[status] += 1
        return acc
      },
      { active: 0, anomaly: 0, pending: 0, testing: 0 }
    )
  }, [filteredItems, statsByDatasetId])

  const displayedItems = useMemo(() => {
    if (collectionFilter === 'all') return filteredItems
    return filteredItems.filter((dataset) => getDatasetOperationalStatus(dataset, statsByDatasetId[dataset.id]) === collectionFilter)
  }, [collectionFilter, filteredItems, statsByDatasetId])

  const totalPages = displayedItems.length === 0 ? 0 : Math.ceil(displayedItems.length / pageSize)

  const pagedItems = useMemo(() => {
    const start = (currentPage - 1) * pageSize
    return displayedItems.slice(start, start + pageSize)
  }, [currentPage, displayedItems, pageSize])

  useEffect(() => {
    setCurrentPage(1)
  }, [searchQuery, collectionFilter, selectedCategoryId])

  useEffect(() => {
    const nextTotalPages = displayedItems.length === 0 ? 1 : Math.ceil(displayedItems.length / pageSize)
    if (currentPage > nextTotalPages) {
      setCurrentPage(nextTotalPages)
    }
  }, [currentPage, displayedItems.length, pageSize])

  useEffect(() => {
    if (pagedItems.length === 0) {
      if (selectedDatasetId !== null) setSelectedDatasetId(null)
      return
    }

    if (!selectedDatasetId || !pagedItems.some((item) => item.id === selectedDatasetId)) {
      setSelectedDatasetId(pagedItems[0]?.id ?? null)
    }
  }, [pagedItems, selectedDatasetId])

  const canSubmit = useMemo(() => form.name.trim().length > 0, [form.name])
  const selectedDataset = useMemo(
    () => pagedItems.find((item) => item.id === selectedDatasetId) ?? pagedItems[0] ?? null,
    [pagedItems, selectedDatasetId]
  )
  const selectedDatasetStats = selectedDataset ? statsByDatasetId[selectedDataset.id] : undefined
  const selectedDatasetStatus = selectedDataset ? getDatasetOperationalStatus(selectedDataset, selectedDatasetStats) : 'active'
  const selectedStatusBadge = getDatasetStatusBadgeConfig(selectedDatasetStatus)
  const selectedStatusIcon = getDatasetStatusIconConfig(selectedDatasetStatus)
  const collectionFilterLabel = {
    all: '全部数据集',
    active: '活跃集合',
    anomaly: '异常集合',
    pending: '处理中集合',
    testing: '测试集合',
  }[collectionFilter]

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
        density="system-dense"
        bodyClassName="pt-2 pb-4"
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
        {/* flex min-h-[calc(100vh-11.5rem)] flex-col overflow-hidden rounded-3xl border border-border/60 bg-card/90 shadow-soft */}
        {/* lg:grid-cols-[176px_minmax(0,1fr)] */}
        {/* xl:grid-cols-[minmax(0,1.15fr)_320px] */}
        {/* Dataset Inspector */}
        {/* 选择一个数据集以查看快捷入口与访问配置 */}
        {/* <DatasetShortcutButton */}
        <div className="flex min-h-[calc(100vh-11.5rem)] flex-col overflow-hidden rounded-3xl border border-border/60 bg-card/90 shadow-soft xl:h-[calc(100vh-9.25rem)] xl:min-h-0">
          <div className="border-b border-border/60 bg-background/80 px-3 py-2.5 backdrop-blur">
            <div className="grid gap-1.5 xl:grid-cols-[minmax(0,1fr)_276px] xl:items-start">
              <div className="grid gap-1.5 sm:grid-cols-2 xl:grid-cols-4">
                <DatasetSummaryCard title="全部数据集" value={String(total)} icon={Layers} tone="slate" />
                <DatasetSummaryCard title="活跃" value={String(statusCounts.active)} icon={CheckCircle2} tone="green" />
                <DatasetSummaryCard title="异常" value={String(statusCounts.anomaly)} icon={AlertCircle} tone="red" />
                <DatasetSummaryCard title="待处理" value={String(statusCounts.pending)} icon={Clock3} tone="amber" />
              </div>

              <div className="flex flex-col gap-1.5">
                <div className="flex flex-wrap items-center gap-1 text-[9px] font-medium text-muted-foreground/72">
                  <span className="inline-flex items-center gap-1 rounded-full border border-border/60 bg-background px-2 py-0.5 text-foreground/76">
                    <Filter className="size-3 text-primary/70" />
                    {collectionFilterLabel}
                  </span>
                  <span className="inline-flex items-center rounded-full border border-border/60 bg-background px-2 py-0.5">
                    {selectedCategoryId ? '分类已筛选' : '全部分类'}
                  </span>
                  <span className="inline-flex items-center rounded-full border border-border/60 bg-background px-2 py-0.5">
                    当前显示 {displayedItems.length} / {filteredItems.length}
                  </span>
                  {isLoading ? <Loader2 className="size-3.5 animate-spin text-primary motion-reduce:animate-none" /> : null}
                </div>

                <div className="flex flex-col gap-1.5 sm:flex-row">
                  <div className="relative min-w-0 flex-1">
                    <Search className="absolute left-3 top-1/2 -translate-y-1/2 size-3.5 text-muted-foreground" />
                    <Input
                      value={searchQuery}
                      onChange={(e) => setSearchQuery(e.target.value)}
                      placeholder="搜索数据集、描述或 ID..."
                      className="h-8 rounded-2xl border-border/60 bg-background pl-8.5 text-[11px] shadow-none"
                    />
                  </div>
                  <Button
                    type="button"
                    variant="outline"
                    className="h-8 rounded-2xl border-border/60 bg-background px-2.5 text-[10px] font-medium"
                    onClick={() => {
                      setSearchQuery('')
                      setCollectionFilter('all')
                      setSelectedCategoryId(null)
                    }}
                  >
                    重置视图
                  </Button>
                </div>
              </div>
            </div>
          </div>

          <div className="grid flex-1 gap-2.5 px-2.5 py-2.5 xl:grid-cols-[208px_minmax(0,1.2fr)_284px]">
            <aside className="min-h-0 overflow-hidden rounded-[22px] border border-border/60 bg-background/88 p-2.5 shadow-[0_18px_36px_-28px_rgba(15,23,42,0.12)]">
              <div className="border-b border-border/60 pb-2">
                <div className="text-[9px] font-semibold uppercase tracking-[0.18em] text-primary/70">Collections</div>
                <div className="mt-0.5 text-[11px] font-semibold text-foreground">分类与筛选</div>
              </div>

              <div className="mt-2">
                <div className="mb-1.5 text-[9px] font-semibold uppercase tracking-[0.14em] text-foreground/54">状态视图</div>
                <div className="space-y-1">
                <DatasetFilterButton
                  label="全部分类"
                  count={total}
                  active={collectionFilter === 'all'}
                  onClick={() => setCollectionFilter('all')}
                  icon={Layers}
                />
                <DatasetFilterButton
                  label="活跃"
                  count={statusCounts.active}
                  active={collectionFilter === 'active'}
                  onClick={() => setCollectionFilter('active')}
                  dotClassName="bg-emerald-500"
                />
                <DatasetFilterButton
                  label="异常"
                  count={statusCounts.anomaly}
                  active={collectionFilter === 'anomaly'}
                  onClick={() => setCollectionFilter('anomaly')}
                  dotClassName="bg-red-500"
                />
                <DatasetFilterButton
                  label="待处理"
                  count={statusCounts.pending}
                  active={collectionFilter === 'pending'}
                  onClick={() => setCollectionFilter('pending')}
                  dotClassName="bg-blue-500"
                />
                <DatasetFilterButton
                  label="测试集"
                  count={statusCounts.testing}
                  active={collectionFilter === 'testing'}
                  onClick={() => setCollectionFilter('testing')}
                  icon={FileSearch}
                />
                </div>
              </div>

              <div className="mt-3 border-t border-border/60 pt-2">
                <div className="mb-1.5 text-[9px] font-semibold uppercase tracking-[0.14em] text-foreground/54">分类树</div>
                <DatasetCategoryTree
                  className="max-h-[420px] overflow-y-auto pr-1 xl:max-h-[calc(100vh-23.5rem)]"
                  selectedId={selectedCategoryId}
                  onSelect={(id) => setSelectedCategoryId(id)}
                />
              </div>
            </aside>

            <section className="min-w-0">
              <div className="flex h-full min-h-0 flex-col rounded-[24px] border border-border/60 bg-background/88 shadow-[0_18px_36px_-28px_rgba(15,23,42,0.12)]">
                <div className="flex items-center justify-between gap-3 border-b border-border/60 px-4 py-3">
                  <div className="min-w-0">
                    <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-primary/70">Dataset Catalog</div>
                    <div className="mt-1 flex items-center gap-2 text-[13px] font-semibold text-foreground">
                      <span className="truncate">{selectedCategoryId ? '当前分类数据集' : '全部数据集'}</span>
                      <span className="inline-flex items-center rounded-full bg-muted px-2.5 py-0.5 text-[11px] font-semibold text-muted-foreground">
                        {displayedItems.length}
                      </span>
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <Select value="updated_desc" onValueChange={() => {}}>
                      <SelectTrigger className="h-9 w-[132px] rounded-xl border-border/60 bg-background px-3 text-[11px] font-medium">
                        <SelectValue placeholder="按更新时间" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="updated_desc">按更新时间</SelectItem>
                        <SelectItem value="name_asc">按名称</SelectItem>
                      </SelectContent>
                    </Select>
                    <Button variant="outline" size="icon" className="size-8 rounded-xl border-border/60 bg-background" aria-label="切换表格视图" title="切换表格视图">
                      <Table2 className="size-4" />
                    </Button>
                  </div>
                </div>

                <div className="flex-1 overflow-y-auto px-3.5 py-3">
                  {displayedItems.length === 0 && !isLoading ? (
                    <EmptyState
                      icon={Layers}
                      title={searchQuery ? '未找到匹配的数据集' : '暂无数据集'}
                      description={searchQuery ? '尝试更换关键词或清空筛选。' : '点击“新建数据集”开始构建知识库。'}
                      className="min-h-full rounded-[22px] border-dashed border-border/60 bg-background/40"
                    />
                  ) : (
                    <motion.div
                      initial="hidden"
                      animate="visible"
                      variants={{ hidden: { opacity: 0 }, visible: { opacity: 1, transition: { staggerChildren: 0.04 } } }}
                      className="space-y-3"
                    >
                      {pagedItems.map((dataset) => {
                        const stats = statsByDatasetId[dataset.id]
                        const isActive = selectedDataset?.id === dataset.id
                        const memberCount = dataset.partial_member_list?.length ?? 0
                        const status = getDatasetOperationalStatus(dataset, stats)
                        const statusBadge = getDatasetStatusBadgeConfig(status)
                        const statusIcon = getDatasetStatusIconConfig(status)
                        const anomalyCount = getDatasetAnomalyCount(stats)

                        return (
                          <motion.div
                            key={dataset.id}
                            variants={{ hidden: { opacity: 0, y: 10 }, visible: { opacity: 1, y: 0 } }}
                            role="button"
                            tabIndex={0}
                            onClick={() => setSelectedDatasetId(dataset.id)}
                            onKeyDown={(event) => {
                              if (event.key === 'Enter' || event.key === ' ') {
                                event.preventDefault()
                                setSelectedDatasetId(dataset.id)
                              }
                            }}
                            whileHover={{ y: -2 }}
                            className={cn(
                              'focus-ring group w-full cursor-pointer rounded-[20px] border px-4 py-3 text-left transition-all duration-200 active:scale-[0.998]',
                              isActive
                                ? 'border-blue-300/80 bg-blue-50/50 shadow-[0_14px_26px_-20px_rgba(37,99,235,0.22)] ring-2 ring-blue-200/70'
                                : 'border-border/60 bg-background/80 shadow-[0_10px_18px_-18px_rgba(15,23,42,0.1)] hover:border-slate-300/80 hover:bg-background hover:shadow-[0_16px_28px_-22px_rgba(15,23,42,0.12)]'
                            )}
                          >
                            <div className={cn(
                              'grid gap-3 xl:items-start',
                              isActive && 'xl:grid-cols-[minmax(0,1fr)_auto]'
                            )}>
                              <div className="flex min-w-0 items-start gap-3.5">
                                <div
                                  className={cn(
                                    'flex size-10 shrink-0 items-center justify-center rounded-[14px] border',
                                    isActive
                                      ? statusIcon.activeClassName
                                      : statusIcon.defaultClassName
                                  )}
                                >
                                  <Layers className="size-4" />
                                </div>
                                <div className="min-w-0">
                                  <div className="flex flex-wrap items-center gap-2">
                                    <div className="truncate text-[13px] font-semibold text-foreground">{dataset.name}</div>
                                    <span className={cn('inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-[11px] font-semibold', statusBadge.className)}>
                                      <span className={cn('size-1.5 rounded-full', statusBadge.dotClassName)} />
                                      {statusBadge.label}
                                    </span>
                                  </div>
                                  <div className="mt-1 text-[11px] leading-[1.25rem] text-muted-foreground/72">
                                    {dataset.description || '暂无描述。可在右侧继续配置预检、画像与入库策略。'}
                                  </div>
                                </div>
                              </div>

                              {isActive ? (
                                <div className="inline-flex shrink-0 items-center gap-1 rounded-full border border-blue-200 bg-blue-100/80 p-0.5">
                                  <button
                                    type="button"
                                    onClick={(e) => {
                                      e.stopPropagation()
                                      setSelectedDatasetId(dataset.id)
                                    }}
                                    className="rounded-full bg-card px-2.5 py-1 text-[11px] font-medium text-blue-600 shadow-sm transition-all duration-200 hover:bg-blue-50 hover:text-blue-700 active:scale-[0.98]"
                                  >
                                    详情
                                  </button>
                                  <button
                                    type="button"
                                    onClick={(e) => {
                                      e.stopPropagation()
                                      router.push(`/knowledge?tab=retrieval&dataset=${dataset.id}`)
                                    }}
                                    className="rounded-full bg-card px-2.5 py-1 text-[11px] font-medium text-blue-600 shadow-sm transition-all duration-200 hover:bg-blue-50 hover:text-blue-700 active:scale-[0.98]"
                                  >
                                    检索
                                  </button>
                                  <Button
                                    size="sm"
                                    className="h-8 rounded-full bg-blue-600 px-3 text-[11px] font-medium text-primary-foreground shadow-[0_10px_20px_-14px_rgba(37,99,235,0.65)] transition-transform duration-200 hover:bg-blue-700 active:scale-[0.98]"
                                    onClick={(e) => {
                                      e.stopPropagation()
                                      router.push(`/datasets/${dataset.id}/ingestion`)
                                    }}
                                  >
                                    入库
                                  </Button>
                                  <Button
                                    variant="ghost"
                                    size="icon"
                                    aria-label="编辑数据集"
                                    title="编辑数据集"
                                    className="size-8 rounded-full bg-card/90 transition-all duration-200 hover:bg-card hover:shadow-sm active:scale-[0.96]"
                                    onClick={(e) => {
                                      e.stopPropagation()
                                      openEdit(dataset)
                                    }}
                                  >
                                    <MoreHorizontal className="size-3.5" />
                                  </Button>
                                </div>
                              ) : null}
                            </div>

                            <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1.5 border-t border-border/50 pt-2">
                              <DatasetMetaPill icon={Database} label="ID" value={dataset.id.slice(0, 8)} className="font-mono text-violet-600" valueClassName="text-violet-600" />
                              <DatasetMetaPill icon={Clock3} label="更新" value={formatRelativeTime(stats?.last_processed_at)} />
                              <DatasetMetaPill icon={FileSearch} label="文档" value={String(Number(stats?.total_documents || 0))} />
                              <DatasetMetaPill icon={Layers} label="Chunk" value={Number(stats?.total_chunks || 0).toLocaleString()} />
                              <DatasetMetaPill icon={AlertCircle} label="异常" value={String(anomalyCount)} className={anomalyCount > 0 ? 'text-red-500' : undefined} />
                              <DatasetMetaPill icon={Users} label="成员" value={memberCount > 0 ? String(memberCount) : '0'} />
                            </div>
                          </motion.div>
                        )
                      })}
                    </motion.div>
                  )}
                </div>

                <div className="flex items-center justify-between border-t border-border/60 px-4 py-3 text-[11px] text-muted-foreground/72">
                  <span>共 {displayedItems.length} 条 · 共 {totalPages} 页</span>
                  <div className="flex items-center gap-2">
                    <Select
                      value={String(pageSize)}
                      onValueChange={(value) => {
                        setPageSize(Number(value))
                        setCurrentPage(1)
                      }}
                    >
                      <SelectTrigger className="h-8 w-[98px] rounded-[11px] border border-slate-200/80 bg-slate-50/80 px-2.5 text-[11px] font-medium shadow-none transition-all duration-200 hover:border-slate-300 hover:bg-card">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="10">10 条/页</SelectItem>
                        <SelectItem value="20">20 条/页</SelectItem>
                        <SelectItem value="50">50 条/页</SelectItem>
                      </SelectContent>
                    </Select>
                    <div className="inline-flex items-center gap-1.5">
                      <button
                        type="button"
                        disabled={currentPage <= 1}
                        onClick={() => setCurrentPage((page) => Math.max(1, page - 1))}
                        className="size-8 rounded-[11px] border border-slate-200/80 bg-slate-50/80 text-muted-foreground/50 transition-all duration-200 hover:border-slate-300 hover:bg-card hover:text-foreground active:scale-[0.96] disabled:cursor-not-allowed disabled:opacity-45"
                      >
                        ‹
                      </button>
                      <span className="inline-flex min-w-[60px] items-center justify-center rounded-[11px] bg-primary px-2.5 text-[11px] font-semibold text-primary-foreground shadow-[0_10px_18px_-16px_rgba(37,99,235,0.6)]">
                        {totalPages === 0 ? '0 / 0' : `${currentPage} / ${totalPages}`}
                      </span>
                      <button
                        type="button"
                        disabled={totalPages === 0 || currentPage >= totalPages}
                        onClick={() => setCurrentPage((page) => Math.min(totalPages, page + 1))}
                        className="size-8 rounded-[11px] border border-slate-200/80 bg-slate-50/80 text-muted-foreground/50 transition-all duration-200 hover:border-slate-300 hover:bg-card hover:text-foreground active:scale-[0.96] disabled:cursor-not-allowed disabled:opacity-45"
                      >
                        ›
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            </section>

            <aside className="min-h-0 overflow-hidden rounded-[24px] border border-border/60 bg-background/88 p-3 shadow-[0_18px_36px_-28px_rgba(15,23,42,0.12)]">
              <AnimatePresence mode="wait" initial={false}>
                {selectedDataset ? (
                  <motion.div
                    key={selectedDataset.id}
                    initial={{ opacity: 0, x: 12 }}
                    animate={{ opacity: 1, x: 0 }}
                    exit={{ opacity: 0, x: -12 }}
                    transition={{ duration: 0.22 }}
                    className="flex h-full flex-col gap-1.5 overflow-y-auto pr-1 custom-scrollbar"
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <div className="text-[10px] font-semibold uppercase tracking-[0.18em] text-primary/70">Dataset Inspector</div>
                        <div className="mt-0.5 text-[11px] font-semibold text-foreground">当前选中数据集</div>
                      </div>
                      <div className="flex items-center gap-2">
                        <Button variant="ghost" size="icon" aria-label="编辑数据集" title="编辑数据集" className="size-7 rounded-full border border-slate-200/80 bg-slate-50 text-slate-500 transition-all duration-200 hover:border-slate-300 hover:bg-card hover:text-foreground active:scale-[0.96]" onClick={() => openEdit(selectedDataset)}>
                          <Pencil className="size-3" />
                        </Button>
                        <Button variant="ghost" size="icon" aria-label="删除数据集" title="删除数据集" className="size-7 rounded-full border border-destructive/20 bg-red-50 text-destructive/70 transition-all duration-200 hover:border-destructive/30 hover:bg-red-100 active:scale-[0.96]" onClick={() => setDeleteTarget(selectedDataset)}>
                          <Trash2 className="size-3" />
                        </Button>
                      </div>
                    </div>

                    <div className="rounded-[18px] border border-border/60 bg-background px-2 py-1.5">
                      <div className="flex items-start gap-1.5">
                        <div className={cn(
                          'flex size-7 shrink-0 items-center justify-center rounded-[10px] border',
                          selectedStatusIcon.activeClassName
                        )}>
                          <Layers className="size-3" />
                        </div>
                        <div className="min-w-0 flex-1">
                          <div className="flex flex-wrap items-center gap-1.5">
                            <div className="truncate text-[10px] font-semibold text-foreground">{selectedDataset.name}</div>
                            <span className={cn('inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-semibold', selectedStatusBadge.className)}>
                              <span className={cn('size-1.5 rounded-full', selectedStatusBadge.dotClassName)} />
                              {selectedStatusBadge.label}
                            </span>
                          </div>
                        </div>
                      </div>

                      <div className="mt-1 grid grid-cols-3 gap-1">
                        <DetailStat
                          label="健康度"
                          value={`${estimateDatasetHealthScore(selectedDataset, selectedDatasetStats)} 分`}
                          meta=""
                          tone="neutral"
                        />
                        <DetailStat
                          label="状态"
                          value={getDatasetStatusBadgeConfig(selectedDatasetStatus).label}
                          meta=""
                          tone={selectedDatasetStatus === 'anomaly' ? 'danger' : selectedDatasetStatus === 'pending' ? 'warning' : 'success'}
                        />
                        <DetailStat
                          label="最近更新"
                          value={formatRelativeTime(selectedDatasetStats?.last_processed_at)}
                          meta=""
                          tone="neutral"
                        />
                      </div>
                    </div>

                    <div className="space-y-0.5 rounded-[18px] border border-border/60 bg-background px-2 py-1.5">
                      <InspectorRow icon={Database} label="数据集 ID">
                        <span className="font-mono text-violet-600">{selectedDataset.id.slice(0, 8)}</span>
                      </InspectorRow>
                      <InspectorRow icon={FolderOpen} label="当前范围">
                        <span>{selectedCategoryId ? '当前分类范围' : '全部分类范围'}</span>
                      </InspectorRow>
                      <InspectorRow icon={ShieldCheck} label="访问权限">
                        <div className="ml-3 flex items-center gap-2">
                          {permissionUpdatePending ? <Loader2 className="size-3 animate-spin text-muted-foreground/50" /> : null}
                          <div className="w-[116px]">
                            <Select
                              value={selectedDataset.permission}
                              disabled={permissionUpdatePending}
                              onValueChange={(value) => detachPromise(handleInspectorPermissionChange(selectedDataset, value as PermissionEnum))}
                            >
                              {/* keep source-test anchor: <div className="w-[132px]"> */}
                              {/* keep source-test anchor: ml-auto h-8 w-auto min-w-[88px] max-w-full justify-end */}
                              <SelectTrigger
                                aria-label="访问权限"
                                className={cn(
                                  'ml-auto h-7 w-auto min-w-[80px] max-w-full justify-end gap-1 rounded-lg border pl-1.5 pr-1.5 text-[10px] font-semibold shadow-none [&>span]:truncate [&>span]:text-right [&>svg]:h-3 [&>svg]:w-3 [&>svg]:shrink-0',
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
                      </InspectorRow>
                      <InspectorRow icon={Settings2} label="默认嵌入模型">
                        <div className="ml-3 flex items-center gap-2">
                          <span className="text-[10px] font-medium text-foreground/80">{selectedDataset.pipeline ? '已启用' : '未启用'}</span>
                          {pipelineTogglePending ? <Loader2 className="size-3 animate-spin text-muted-foreground/50" /> : null}
                          <Switch
                            checked={Boolean(selectedDataset.pipeline)}
                            disabled={pipelineTogglePending}
                            onCheckedChange={(nextChecked) => detachPromise(handleToggleDefaultPipeline(selectedDataset, nextChecked))}
                            aria-label={selectedDataset.pipeline ? '关闭默认管线' : '启用默认管线'}
                            title={selectedDataset.pipeline ? '关闭默认管线' : '启用默认管线'}
                          />
                        </div>
                      </InspectorRow>
                      <div className="space-y-0.5 border-t border-border/60 pt-1.5">
                        <InspectorRow icon={FileSearch} label="文档数">
                          <span>{String(Number(selectedDatasetStats?.total_documents || 0))}</span>
                        </InspectorRow>
                        <InspectorRow icon={Layers} label="Chunk 数">
                          <span>{String(Number(selectedDatasetStats?.total_chunks || 0).toLocaleString())}</span>
                        </InspectorRow>
                        <InspectorRow icon={Users} label="活跃成员">
                          <span>{`${selectedDataset.partial_member_list?.length ?? 0} 人`}</span>
                        </InspectorRow>
                        <InspectorRow icon={AlertCircle} label="异常项">
                          <span className={getDatasetAnomalyCount(selectedDatasetStats) > 0 ? 'text-destructive' : undefined}>
                            {`${getDatasetAnomalyCount(selectedDatasetStats)} 项`}
                          </span>
                        </InspectorRow>
                      </div>
                    </div>

                    <div className="border-t border-border/60 pt-2">
                      <div className="mb-1 text-[10px] font-semibold uppercase tracking-[0.14em] text-foreground/72">操作中心</div>
                      <div className="grid grid-cols-2 gap-1">
                        <DatasetOperationTile
                          icon={FileSearch}
                          title="预检扫描"
                          description="检查文档质量、重复与结构风险"
                          onClick={() => router.push(`/datasets/${selectedDataset.id}/precheck`)}
                        />
                        <DatasetOperationTile
                          icon={BarChart3}
                          title="数据画像"
                          description="查看规模、分布和结构特征"
                          onClick={() => router.push(`/datasets/${selectedDataset.id}/profile`)}
                        />
                        <DatasetOperationTile
                          icon={Search}
                          title="检索测试"
                          description="验证检索召回与命中质量"
                          onClick={() => router.push(`/knowledge?tab=retrieval&dataset=${selectedDataset.id}`)}
                        />
                        <DatasetOperationTile
                          icon={Settings2}
                          title="入库策略"
                          description="调整默认入库与治理配置"
                          onClick={() => router.push(`/datasets/${selectedDataset.id}/ingestion`)}
                        />
                      </div>
                    </div>

                    <div className="border-t border-border/60 pt-2">
                      <div className="mb-1 text-[10px] font-semibold uppercase tracking-[0.14em] text-foreground/72">扩展能力</div>
                      <div className="grid grid-cols-4 gap-1">
                        <DatasetCapabilityItem
                          icon={Layers}
                          title="Workflow"
                          description="查看流程编排与阶段状态"
                          onClick={() => router.push(`/datasets/${selectedDataset.id}/workflow`)}
                        />
                        <DatasetCapabilityItem
                          icon={Table2}
                          title="标签 / TAG"
                          description="管理结构化标签与表格资产"
                          onClick={() => router.push(`/datasets/${selectedDataset.id}/tables`)}
                        />
                        <DatasetCapabilityItem
                          icon={Database}
                          title="DB 目录"
                          description="浏览数据库映射与资产目录"
                          onClick={() => router.push(`/datasets/${selectedDataset.id}/db-catalog`)}
                        />
                        <DatasetCapabilityItem
                          icon={ChevronRight}
                          title="更多"
                          description="进入更多数据集扩展入口"
                          onClick={() => router.push(`/datasets/${selectedDataset.id}/profile`)}
                        />
                      </div>
                    </div>
                  </motion.div>
                ) : (
                  <motion.div
                    key="empty"
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    className="flex h-full min-h-[320px] flex-col items-center justify-center rounded-[22px] border border-dashed border-border/60 bg-background/40 p-6 text-center"
                  >
                    <Layers className="mb-3 size-9 text-muted-foreground/20" />
                    <div className="text-sm font-semibold text-foreground/80">检视器就绪</div>
                    <div className="mt-2 max-w-[220px] text-[11px] leading-relaxed text-muted-foreground/60">
                      选择一个数据集以查看快捷入口与访问配置
                    </div>
                  </motion.div>
                )}
              </AnimatePresence>
            </aside>
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
  label,
  value,
  className,
  valueClassName,
}: Readonly<{
  icon: LucideIcon
  label: string
  value: string
  className?: string
  valueClassName?: string
}>) {
  const tone = getDatasetIconTone(Icon)
  return (
    <div className={cn('inline-flex min-w-0 items-start gap-1.5 px-0 py-0 text-[10px]', className)}>
      <div className={cn('mt-0.5 flex size-[18px] shrink-0 items-center justify-center rounded-md border', tone.containerClassName)}>
        <Icon className="size-2" />
      </div>
      <div className="min-w-0">
        <div className="truncate text-[8px] font-semibold uppercase tracking-[0.14em] text-muted-foreground/50">{label}</div>
        <div className={cn('truncate text-[10px] font-medium leading-none text-foreground/82', valueClassName)}>{value}</div>
      </div>
    </div>
  )
}

function DatasetSummaryCard({
  title,
  value,
  icon: Icon,
  tone,
}: Readonly<{
  title: string
  value: string
  icon: LucideIcon
  tone: 'slate' | 'green' | 'red' | 'amber'
}>) {
  return (
    <div className="rounded-[16px] border border-slate-200/80 bg-background/92 px-3 py-2 shadow-[0_8px_16px_-16px_rgba(15,23,42,0.12)] transition-all duration-200 hover:border-slate-300 hover:shadow-[0_12px_20px_-18px_rgba(15,23,42,0.14)]">
      <div className="flex items-start justify-between gap-2">
        <div>
          <div className="text-[9px] font-semibold uppercase tracking-[0.12em] text-muted-foreground/62">{title}</div>
          <div className="mt-0.5 text-[20px] font-semibold tracking-[-0.04em] text-foreground">{value}</div>
        </div>
        <div
          className={cn(
            'flex size-7 items-center justify-center rounded-[10px] border shadow-[inset_0_1px_0_rgba(255,255,255,0.72),0_8px_14px_-14px_rgba(15,23,42,0.22)]',
            tone === 'slate' && 'border-slate-200/80 bg-slate-50 text-slate-600',
            tone === 'green' && 'border-emerald-200/80 bg-emerald-50 text-emerald-600',
            tone === 'red' && 'border-red-200/80 bg-red-50 text-red-500',
            tone === 'amber' && 'border-amber-200/80 bg-amber-50 text-amber-600'
          )}
        >
          <Icon className="size-3.5" />
        </div>
      </div>
    </div>
  )
}

function DatasetFilterButton({
  label,
  count,
  active,
  onClick,
  icon: Icon,
  dotClassName,
}: Readonly<{
  label: string
  count: number
  active?: boolean
  onClick: () => void
  icon?: LucideIcon
  dotClassName?: string
}>) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        'flex w-full items-center justify-between rounded-[12px] border px-2.5 py-1.5 text-left transition-colors',
        active
          ? 'border-primary/15 bg-primary/10 text-primary shadow-inner-soft'
          : 'border-transparent text-foreground/78 hover:border-slate-200/80 hover:bg-slate-50/70'
      )}
    >
      <span className="flex min-w-0 items-center gap-2">
        {Icon ? (
          <span className={cn('flex size-4 shrink-0 items-center justify-center rounded-md border', getDatasetIconTone(Icon).containerClassName)}>
            <Icon className="size-2.5 shrink-0" />
          </span>
        ) : (
          <span className={cn('size-1.5 rounded-full shrink-0', dotClassName || 'bg-muted-foreground/40')} />
        )}
        <span className="truncate text-[11px] font-medium">{label}</span>
      </span>
      <span className={cn(
        'rounded-full px-1.5 py-0.5 text-[9px] font-semibold',
        active ? 'bg-card text-primary shadow-sm' : 'bg-background/80 text-foreground/76'
      )}>
        {count}
      </span>
    </button>
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
        'focus-ring group relative flex w-full items-center gap-3 overflow-hidden border transition-all duration-200 motion-reduce:transition-none active:scale-[0.99]',
        compact ? 'rounded-2xl px-3 py-2.5' : 'rounded-3xl px-5 py-4',
        emphasis
          ? 'border-primary/20 bg-primary/[0.03] hover:border-primary/35 hover:bg-primary/[0.06] hover:shadow-[0_12px_22px_-18px_rgba(37,99,235,0.22)]'
          : 'border-slate-200/80 bg-slate-50/75 hover:border-primary/20 hover:bg-primary/[0.03] hover:shadow-[0_12px_22px_-18px_rgba(15,23,42,0.14)]'
      )}
      onClick={onClick}
    >
      <div className="absolute inset-0 bg-primary/[0.05] opacity-0 transition-opacity duration-500 group-hover:opacity-100" />

      <div className={cn(
        'relative flex shrink-0 items-center justify-center rounded-xl transition-all duration-200 group-hover:scale-[1.04]',
        compact ? 'size-9' : 'size-11',
        emphasis
          ? 'bg-primary/10 text-primary shadow-sm shadow-primary/20'
          : `${getDatasetIconTone(Icon).containerClassName} group-hover:bg-primary/10 group-hover:text-primary`
      )}>
        <Icon className={compact ? 'size-4' : 'size-5'} />
      </div>

      <div className="relative min-w-0 flex-1 flex flex-col justify-center text-left">
        <div className="mb-0.5 text-[12px] font-semibold  text-foreground transition-colors group-hover:text-primary">
          {title}
        </div>
        <div
          className="text-[10px] font-medium text-muted-foreground/60 leading-relaxed truncate"
          title={description}
        >
          {description}
        </div>
      </div>

      <div className="relative flex size-4 items-center justify-center opacity-0 transition-all duration-300 group-hover:translate-x-0 group-hover:opacity-100">
        <ChevronRight className={cn(
          'size-3.5',
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
  const tone = getDatasetIconTone(Icon)
  if (variant === 'stat') {
    return (
      <div className="flex flex-col items-center justify-center gap-1 rounded-xl border border-slate-200/80 bg-slate-50/80 p-2.5 transition-all duration-200 hover:border-primary/15 hover:bg-primary/[0.03] hover:shadow-[0_12px_22px_-18px_rgba(15,23,42,0.14)]">
        <div className="flex items-center gap-1.5 text-[10px] font-bold uppercase  text-muted-foreground/50 transition-colors">
          <span className={cn('flex size-[18px] items-center justify-center rounded-md border', tone.containerClassName)}>
            <Icon className="size-3" />
          </span>
          <span className="truncate">{label}</span>
        </div>
        <div className={cn("text-[13px] font-bold  text-foreground/90 text-center", valueClassName)}>
          {value}
        </div>
      </div>
    )
  }

  return (
    <div className="flex items-center justify-between py-1.5 group/metric px-1.5 -mx-0.5 rounded-lg transition-colors hover:bg-slate-50/80">
      <div className="flex min-w-0 items-center gap-2">
        <span className={cn('flex size-[18px] items-center justify-center rounded-md border', tone.containerClassName)}>
          <Icon className="size-3" />
        </span>
        <span className="text-[11px] font-bold uppercase tracking-[0.14em] text-muted-foreground/60 group-hover/metric:text-muted-foreground transition-colors truncate">
          {label}
        </span>
      </div>
      <div className={cn(
        'ml-auto min-w-0 truncate rounded-md border border-slate-200/70 bg-card px-2.5 py-0.5 text-right text-[11px] font-semibold text-foreground/82 shadow-[inset_0_1px_0_rgba(255,255,255,0.92)]',
        mono && 'font-mono tabular-nums ',
        valueClassName
      )}>
        {value}
      </div>
    </div>
  )
}

function InspectorRow({
  icon: Icon,
  label,
  children,
}: Readonly<{
  icon: LucideIcon
  label: string
  children: ReactNode
}>) {
  const tone = getDatasetIconTone(Icon)
  return (
    <div className="flex items-center justify-between gap-2 py-1">
      <div className="flex min-w-0 items-center gap-2">
        <div className="flex items-center gap-1.5 text-[9px] font-bold uppercase tracking-[0.14em] text-muted-foreground/56">
          <span className={cn('flex size-4 items-center justify-center rounded-md border', tone.containerClassName)}>
            <Icon className="size-2.5" />
          </span>
          <span className="truncate">{label}</span>
        </div>
      </div>
      <div className="min-w-0 text-right text-[10px] font-semibold text-foreground/84">
        {children}
      </div>
    </div>
  )
}

function DatasetOperationTile({
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
  const tone = getDatasetIconTone(Icon)
  return (
    <button
      type="button"
      className="focus-ring group relative flex min-h-[62px] flex-col items-start justify-between rounded-[14px] border border-slate-200/80 bg-slate-50/75 px-2 py-1.5 transition-all duration-200 hover:border-primary/20 hover:bg-primary/[0.03] hover:shadow-[0_12px_22px_-18px_rgba(15,23,42,0.14)] active:scale-[0.98]"
      onClick={onClick}
      aria-label={`${title}：${description}`}
    >
      <div className={cn('flex size-5 items-center justify-center rounded-md border transition-all duration-200 group-hover:bg-primary/10 group-hover:text-primary', tone.containerClassName)}>
        <Icon className="size-3" />
      </div>
      <div className="min-w-0 text-left">
        <div className="truncate text-[9px] font-semibold text-foreground/84 transition-colors group-hover:text-primary">
          {title}
        </div>
        <div className="mt-0.5 line-clamp-2 text-[8px] leading-[0.95rem] text-muted-foreground/72">
          {description}
        </div>
      </div>
    </button>
  )
}

function DatasetCapabilityItem({
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
  const tone = getDatasetIconTone(Icon)
  return (
    <button
      type="button"
      onClick={onClick}
      title={description}
      className="focus-ring group relative flex min-h-[38px] items-center gap-1.5 rounded-[12px] border border-slate-200/80 bg-slate-50/75 px-2 py-1.5 transition-all duration-200 hover:border-primary/20 hover:bg-primary/[0.03] active:scale-[0.98]"
    >
      <div className={cn('flex size-4 shrink-0 items-center justify-center rounded-md border transition-colors duration-200 group-hover:text-primary', tone.containerClassName)}>
        <Icon className="size-2.5" />
      </div>
      <span className="truncate text-[9px] font-medium text-foreground/84 transition-colors duration-200 group-hover:text-primary">
        {title}
      </span>
      <div className="pointer-events-none absolute bottom-full left-1/2 z-20 mb-1.5 w-32 -translate-x-1/2 translate-y-1 rounded-lg border border-slate-200/80 bg-popover/95 px-2 py-1 text-center opacity-0 shadow-lg backdrop-blur transition-all duration-200 group-hover:translate-y-0 group-hover:opacity-100">
        <div className="text-[8px] leading-[1rem] text-foreground/84">{description}</div>
      </div>
    </button>
  )
}

function DetailStat({
  label,
  value,
  meta,
  tone,
}: Readonly<{
  label: string
  value: string
  meta?: string
  tone: 'success' | 'warning' | 'danger' | 'neutral'
}>) {
  return (
    <div className="rounded-[12px] border border-slate-200/80 bg-slate-50/80 px-2 py-1.5 transition-colors duration-200 hover:border-slate-300 hover:bg-card">
      <div className="flex items-center gap-1">
        <span
          className={cn(
            'size-1 rounded-full',
            tone === 'success' && 'bg-emerald-500',
            tone === 'warning' && 'bg-amber-500',
            tone === 'danger' && 'bg-red-500',
            tone === 'neutral' && 'bg-slate-300'
          )}
        />
        <span className="text-[9px] font-semibold uppercase tracking-[0.1em] text-foreground/72">{label}</span>
      </div>
      <div className="mt-1 text-[10px] font-semibold text-foreground/86">{value}</div>
      {meta ? <div className="mt-0.5 text-[9px] text-muted-foreground/56">{meta}</div> : null}
    </div>
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
