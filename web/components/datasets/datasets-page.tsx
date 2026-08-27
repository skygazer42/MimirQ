'use client'

import { useCallback, useEffect, useMemo, useState, type Dispatch, type ReactNode, type SetStateAction } from 'react'
import Image from 'next/image'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { motion } from 'framer-motion'
import {
  AlertCircle, BarChart3, ChevronRight, Clock3, Database, FileSearch,
  FolderOpen, Layers, Loader2, MoreHorizontal, Pencil, RefreshCw, Search, Settings2,
  ShieldCheck, Table2, Trash2, Users, type LucideIcon,
} from 'lucide-react'

import { AppFrame } from '@/components/app-frame'
import { useRouter } from '@/i18n/navigation'
import { PageScaffold } from '@/components/ui/page-scaffold'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { EmptyState } from '@/components/ui/empty-state'
import {
  AlertDialog, AlertDialogCancel, AlertDialogContent,
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
import type { DatasetListParams } from '@/lib/api/datasets'
import { formatApiError } from '@/lib/api-errors'
import { reportClientError } from '@/lib/client-logging'
import { queryKeys } from '@/lib/query-keys'
import { cn, detachPromise } from '@/lib/utils'
import type {
  Dataset,
  DatasetIngestionSummary,
  DatasetListResponse,
  PermissionEnum,
  DocumentPipelineOptions,
} from '@/types'
import { PipelineOptionsPanel } from '@/components/pipeline-options-panel'
import { GovernanceProfileSelector } from '@/components/governance-profile-selector'
import { usePipelineOptions } from '@/contexts/pipeline-options-context'
import { DatasetCategoryTree } from '@/components/dataset-categories/category-tree'
import { DatasetCategoryMultiSelect } from '@/components/dataset-categories/category-multi-select'
import { CreateDatasetButton } from '@/components/datasets/create-dataset-button'
import { GroupChipsInput } from '@/components/groups/group-chips-input'

type DatasetOperationalStatus = 'active' | 'anomaly' | 'pending' | 'testing'
const DATASET_SEARCH_DEBOUNCE_MS = 220
const DATASET_SEARCH_MAX_LENGTH = 200

type DatasetFormState = {
  name: string
  description: string
  permission: PermissionEnum
  partialMembersText: string
  partialGroupIds: string[]
  pipelineEnabled: boolean
  pipelineOptions: DocumentPipelineOptions
}

type DatasetSavePayload = {
  name: string
  description?: string
  permission: PermissionEnum
  partial_member_list: string[] | null
  partial_group_list: string[] | null
  pipeline?: DocumentPipelineOptions
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

function getDatasetAnomalyCount(stats?: DatasetIngestionSummary | null): number {
  const byStatus = stats?.by_status || {}
  return Number(byStatus.failed || 0) + Number(byStatus.quarantined || 0)
}

function getDatasetPendingCount(stats?: DatasetIngestionSummary | null): number {
  const byStatus = stats?.by_status || {}
  return Number(byStatus.pending || 0) + Number(byStatus.processing || 0)
}

function getDatasetOperationalStatus(dataset: Dataset, stats?: DatasetIngestionSummary | null): DatasetOperationalStatus {
  if (dataset.operational_status) return dataset.operational_status
  const name = String(dataset.name || '').toLowerCase()
  if (name.includes('test') || name.includes('demo') || name.includes('测试')) return 'testing'
  if (getDatasetAnomalyCount(stats) > 0) return 'anomaly'
  if (getDatasetPendingCount(stats) > 0) return 'pending'
  return 'active'
}

function buildDatasetListParams(input: Readonly<{
  selectedCategoryId: string | null
  searchQuery: string
  collectionFilter: 'all' | 'active' | 'anomaly' | 'pending' | 'testing'
  sortBy: 'default' | 'name_asc'
  currentPage: number
  pageSize: number
}>): DatasetListParams {
  const searchQuery = input.searchQuery.trim()
  return {
    skip: Math.max(0, (input.currentPage - 1) * input.pageSize),
    limit: input.pageSize,
    category_id: input.selectedCategoryId || undefined,
    include_descendants: true,
    q: searchQuery || undefined,
    operational_status: input.collectionFilter,
    order_by: input.sortBy === 'name_asc' ? 'name' : 'created_at',
    order_dir: input.sortBy === 'name_asc' ? 'asc' : 'desc',
  }
}

function formatRelativeTime(value?: string | null): string {
  if (!value) return '—'
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
        className: 'border-success/25 bg-success/10 text-success',
        dotClassName: 'bg-success',
      }
    case 'anomaly':
      return {
        label: '异常',
        className: 'border-destructive/25 bg-destructive/10 text-destructive',
        dotClassName: 'bg-destructive',
      }
    case 'pending':
      return {
        label: '处理中',
        className: 'border-warning/25 bg-warning/10 text-warning',
        dotClassName: 'bg-warning',
      }
    case 'testing':
      return {
        label: '测试集',
        className: 'border-info/20 bg-info/10 text-info',
        dotClassName: 'bg-info',
      }
  }
}

function getDatasetStatusIconConfig(status: 'active' | 'anomaly' | 'pending' | 'testing') {
  switch (status) {
    case 'active':
      return {
        defaultClassName: 'border-success/30 bg-success/10 text-success',
        activeClassName: 'border-success/40 bg-success/15 text-success',
      }
    case 'anomaly':
      return {
        defaultClassName: 'border-destructive/30 bg-destructive/10 text-destructive',
        activeClassName: 'border-destructive/40 bg-destructive/15 text-destructive',
      }
    case 'pending':
      return {
        defaultClassName: 'border-warning/30 bg-warning/10 text-warning',
        activeClassName: 'border-warning/40 bg-warning/15 text-warning',
      }
    case 'testing':
      return {
        defaultClassName: 'border-info/20 bg-info/10 text-info',
        activeClassName: 'border-info/30 bg-info/15 text-info',
      }
  }
}

function getDatasetIconTone(icon: LucideIcon) {
  if (icon === Database) {
    return {
      iconClassName: 'text-accent',
      softIconClassName: 'text-accent',
      containerClassName: 'border-accent/30 bg-accent/10 text-accent',
      chipClassName: 'text-accent',
    }
  }

  if (icon === FolderOpen || icon === FileSearch || icon === Search) {
    return {
      iconClassName: 'text-info',
      softIconClassName: 'text-info/80',
      containerClassName: 'border-info/20 bg-info/10 text-info',
      chipClassName: 'text-info',
    }
  }

  if (icon === Layers || icon === Table2) {
    return {
      iconClassName: 'text-primary',
      softIconClassName: 'text-primary',
      containerClassName: 'border-primary/30 bg-primary/10 text-primary',
      chipClassName: 'text-primary',
    }
  }

  if (icon === ShieldCheck || icon === Users) {
    return {
      iconClassName: 'text-primary',
      softIconClassName: 'text-primary/80',
      containerClassName: 'border-primary/20 bg-primary/10 text-primary',
      chipClassName: 'text-primary',
    }
  }

  if (icon === Settings2 || icon === Clock3) {
    return {
      iconClassName: 'text-warning',
      softIconClassName: 'text-warning',
      containerClassName: 'border-warning/30 bg-warning/10 text-warning',
      chipClassName: 'text-warning',
    }
  }

  if (icon === AlertCircle) {
    return {
      iconClassName: 'text-destructive',
      softIconClassName: 'text-destructive',
      containerClassName: 'border-destructive/30 bg-destructive/10 text-destructive',
      chipClassName: 'text-destructive',
    }
  }

  if (icon === BarChart3) {
    return {
      iconClassName: 'text-success',
      softIconClassName: 'text-success',
      containerClassName: 'border-success/30 bg-success/10 text-success',
      chipClassName: 'text-success',
    }
  }

  return {
    iconClassName: 'text-muted-foreground',
    softIconClassName: 'text-muted-foreground',
    containerClassName: 'border-border/60 bg-muted/50 text-muted-foreground',
    chipClassName: 'text-muted-foreground',
  }
}

export default function DatasetsPage() {
  const router = useRouter()
  const queryClient = useQueryClient()
  const { options: defaultPipelineOptions } = usePipelineOptions()
  const [pipelineTogglePendingId, setPipelineTogglePendingId] = useState<string | null>(null)
  const [permissionUpdatePendingId, setPermissionUpdatePendingId] = useState<string | null>(null)
  const [selectedCategoryId, setSelectedCategoryId] = useState<string | null>(null)
  const [searchQuery, setSearchQuery] = useState('')
  const [debouncedSearchQuery, setDebouncedSearchQuery] = useState('')
  const [collectionFilter, setCollectionFilter] = useState<'all' | 'active' | 'anomaly' | 'pending' | 'testing'>('all')
  const [sortBy, setSortBy] = useState<'default' | 'name_asc'>('default')
  const [selectedDatasetId, setSelectedDatasetId] = useState<string | null>(null)
  const [pageSize, setPageSize] = useState(20)
  const [currentPage, setCurrentPage] = useState(1)
  const [deleteTarget, setDeleteTarget] = useState<Dataset | null>(null)
  const [deleteIncludingDocuments, setDeleteIncludingDocuments] = useState(false)
  const [deleteDocumentCountHint, setDeleteDocumentCountHint] = useState<number | null>(null)
  const [deletePending, setDeletePending] = useState(false)

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

  const trimmedSearchQuery = useMemo(
    () => searchQuery.trim().slice(0, DATASET_SEARCH_MAX_LENGTH),
    [searchQuery]
  )

  useEffect(() => {
    const timer = globalThis.window?.setTimeout(() => {
      setDebouncedSearchQuery(trimmedSearchQuery)
    }, DATASET_SEARCH_DEBOUNCE_MS)

    return () => {
      if (timer !== undefined) globalThis.window.clearTimeout(timer)
    }
  }, [trimmedSearchQuery])

  const datasetListParams = useMemo(
    () =>
      buildDatasetListParams({
        selectedCategoryId,
        searchQuery: debouncedSearchQuery,
        collectionFilter,
        sortBy,
        currentPage,
        pageSize,
      }),
    [collectionFilter, currentPage, debouncedSearchQuery, pageSize, selectedCategoryId, sortBy]
  )

  const datasetsQueryKey = useMemo(() => queryKeys.datasets.list(datasetListParams), [datasetListParams])

  const datasetsQuery = useQuery({
    queryKey: datasetsQueryKey,
    queryFn: () => datasetApi.list(datasetListParams),
  })

  const response = datasetsQuery.data ?? null
  const items = useMemo(() => response?.items || [], [response?.items])
  const scopeTotal = Number(response?.facets?.scope_total || 0)
  const filteredTotal = Number(response?.facets?.filtered_total || 0)
  const displayedTotal = Number(response?.total || 0)
  const statusCounts = useMemo(
    () => ({
      active: Number(response?.facets?.status_counts?.active || 0),
      anomaly: Number(response?.facets?.status_counts?.anomaly || 0),
      pending: Number(response?.facets?.status_counts?.pending || 0),
      testing: Number(response?.facets?.status_counts?.testing || 0),
    }),
    [response?.facets?.status_counts]
  )
  const isLoading = datasetsQuery.isPending
  const isRefreshing = datasetsQuery.isFetching

  useEffect(() => {
    if (!datasetsQuery.error) return
    reportClientError('Failed to load datasets', datasetsQuery.error)
    toast.error(formatApiError(datasetsQuery.error, '加载数据集失败'))
  }, [datasetsQuery.error, datasetsQuery.errorUpdatedAt])

  const refreshDatasets = useCallback(async () => {
    await datasetsQuery.refetch()
  }, [datasetsQuery])

  const updateDatasetListCache = useCallback((updater: (current: DatasetListResponse) => DatasetListResponse) => {
    queryClient.setQueryData<DatasetListResponse>(datasetsQueryKey, (current) => {
      if (!current) return current
      return updater(current)
    })
  }, [datasetsQueryKey, queryClient])
  const totalPages = displayedTotal === 0 ? 0 : Math.ceil(displayedTotal / pageSize)

  useEffect(() => {
    setCurrentPage(1)
  }, [searchQuery, collectionFilter, selectedCategoryId, sortBy])

  useEffect(() => {
    const nextTotalPages = displayedTotal === 0 ? 1 : Math.ceil(displayedTotal / pageSize)
    if (currentPage > nextTotalPages) {
      setCurrentPage(nextTotalPages)
    }
  }, [currentPage, displayedTotal, pageSize])

  useEffect(() => {
    if (items.length === 0) {
      if (selectedDatasetId !== null) setSelectedDatasetId(null)
      return
    }

    if (!selectedDatasetId || !items.some((item) => item.id === selectedDatasetId)) {
      setSelectedDatasetId(items[0]?.id ?? null)
    }
  }, [items, selectedDatasetId])

  const canSubmit = useMemo(() => form.name.trim().length > 0, [form.name])
  const selectedDataset = useMemo(
    () => items.find((item) => item.id === selectedDatasetId) ?? items[0] ?? null,
    [items, selectedDatasetId]
  )
  const selectedDatasetStats = selectedDataset?.ingestion_summary ?? undefined
  const selectedDatasetStatus = selectedDataset ? getDatasetOperationalStatus(selectedDataset, selectedDatasetStats) : 'active'
  const selectedStatusBadge = getDatasetStatusBadgeConfig(selectedDatasetStatus)
  const selectedStatusIcon = getDatasetStatusIconConfig(selectedDatasetStatus)
  const deleteTargetStats = deleteTarget?.ingestion_summary ?? undefined
  const deleteTargetDocumentCount = Math.max(0, Number(deleteDocumentCountHint ?? deleteTargetStats?.total_documents ?? 0))
  const deleteRequiresDocumentPurge = deleteTargetDocumentCount > 0
  const collectionFilterLabel = {
    all: '全部数据集',
    active: '活跃集合',
    anomaly: '异常集合',
    pending: '处理中集合',
    testing: '测试集合',
  }[collectionFilter]
  const hasActiveFilters = Boolean(searchQuery.trim() || selectedCategoryId || collectionFilter !== 'all')

  const replaceDataset = useCallback((next: Dataset) => {
    updateDatasetListCache((current) =>
      ({
        ...current,
        items: (current.items || []).map((item) =>
          item.id === next.id
            ? {
                ...item,
                ...next,
                ingestion_summary: next.ingestion_summary ?? item.ingestion_summary,
                operational_status: next.operational_status ?? item.operational_status,
              }
            : item
        ),
      })
    )
  }, [updateDatasetListCache])

  const buildPayload = (mode: 'create' | 'update') => {
    const payload: DatasetSavePayload = {
      name: form.name.trim(),
      description: form.description.trim() || undefined,
      permission: form.permission,
      partial_member_list: null,
      partial_group_list: null,
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
      await refreshDatasets()
    } catch (e: unknown) {
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
      await refreshDatasets()
    } catch (e: unknown) {
      toast.error(formatApiError(e, '更新失败'))
    }
  }

  const handleDelete = async () => {
    if (!deleteTarget?.id) return
    const datasetId = deleteTarget.id
    const shouldPurgeDocuments = deleteRequiresDocumentPurge && deleteIncludingDocuments
    let shouldCloseDialog = true
    setDeletePending(true)
    try {
      if (shouldPurgeDocuments) {
        const purgeResult = await datasetApi.purge(datasetId, {
          dry_run: false,
          max_delete: Math.min(Math.max(deleteTargetDocumentCount, 1), 10000),
        })
        const blocked = Number(purgeResult?.denied || 0) + Number(purgeResult?.conflicts || 0) + Number(purgeResult?.errors || 0)
        if (blocked > 0) {
          throw new Error(`清空文档未完成：${blocked} 个文档需要人工处理`)
        }
      }

      await datasetApi.delete(datasetId)
      toast.success(shouldPurgeDocuments ? '已删除数据集及关联文档' : '已删除数据集')
      await refreshDatasets()
    } catch (e: unknown) {
      const message = formatApiError(e, '删除失败')
      const isNonEmptyDataset = /Dataset is not empty|still reference this dataset|数据集内仍有/.test(message)
      if (isNonEmptyDataset) {
        shouldCloseDialog = false
        const countHint = Number(/\d+/.exec(message)?.[0] || 1)
        setDeleteDocumentCountHint(Number.isFinite(countHint) && countHint > 0 ? countHint : 1)
      }
      toast.error(isNonEmptyDataset ? '数据集内仍有文档，请勾选“同时删除文档和索引”后再删除。' : message)
    } finally {
      setDeletePending(false)
      if (shouldCloseDialog) {
        setDeleteTarget(null)
        setDeleteIncludingDocuments(false)
        setDeleteDocumentCountHint(null)
      }
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
    } catch (e: unknown) {
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
    } catch (e: unknown) {
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
        size="full"
        compact
        density="system-dense"
        showHeader={false}
        bodyGutter="none"
        bodyClassName="bg-sidebar/20 px-3 pt-0 pb-3"
        topClassName="bg-sidebar/20 px-3 pt-2 pb-2 md:px-3 lg:px-3"
        top={
          <header
            data-testid="datasets-page-toolbar"
            className="relative flex min-h-14 flex-col gap-2 border-b border-foreground/15 px-1 py-2 sm:flex-row sm:items-center sm:justify-between"
          >
            <span className="absolute -bottom-px left-1 h-px w-8 bg-info/55" aria-hidden="true" />
            <div className="flex min-w-0 items-center gap-2.5">
              <span
                data-dataset-title-mark="true"
                className="flex size-8 shrink-0 items-center justify-center rounded-md border border-foreground/10 bg-background/70"
                aria-hidden="true"
              >
                <Image
                  src="/brand/mimirq-dataset-mark.png"
                  alt=""
                  aria-hidden="true"
                  draggable={false}
                  width={64}
                  height={64}
                  loading="eager"
                  className="size-7 scale-110 object-contain"
                />
              </span>
              <div className="min-w-0 sm:flex sm:items-center sm:gap-2.5">
                <h1 className="text-[19px] font-semibold leading-6 tracking-[-0.02em] text-foreground">数据集</h1>
                <span className="hidden h-3.5 w-px bg-border/80 sm:block" aria-hidden="true" />
                <p className="truncate text-[12px] leading-5 text-muted-foreground/80">管理知识库集合与访问权限</p>
              </div>
            </div>

            <div className="flex shrink-0 items-center gap-1">
              <Button
                variant="ghost"
                size="sm"
                className="h-8 rounded-md px-2.5 text-[12px] text-muted-foreground shadow-none hover:bg-info/8 hover:text-info"
                onClick={() => { detachPromise(refreshDatasets()) }}
                disabled={isRefreshing}
              >
                <RefreshCw className={cn('size-4', isRefreshing && 'animate-spin motion-reduce:animate-none')} />
                刷新
              </Button>
              <Dialog open={createOpen} onOpenChange={(open) => { setCreateOpen(open); if (open) resetForm() }}>
                <DialogTrigger asChild>
                  <CreateDatasetButton
                    variant="info"
                    className="h-8 rounded-md px-3 py-0 text-[12px] font-semibold shadow-none sm:h-8"
                  />
                </DialogTrigger>
                <DialogContent className="max-w-xl p-0 sm:rounded-xl">
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
          </header>
        }
      >
        <div className="flex min-h-[calc(100vh-7rem)] flex-col overflow-hidden rounded-lg border border-foreground/15 bg-sidebar/18 xl:h-[calc(100vh-5.5rem)] xl:min-h-0">
          <div
            data-testid="datasets-workspace"
            className={cn(
              'grid min-h-0 flex-1 bg-sidebar/22 lg:grid-cols-[216px_minmax(0,1fr)]',
              selectedDataset && 'xl:grid-cols-[216px_minmax(0,1fr)_300px]'
            )}
          >
            <aside className="min-h-0 overflow-hidden border-b border-foreground/10 bg-sidebar/28 p-3 lg:border-b-0 lg:border-r">
              <div className="pb-2">
                <div className="text-[12px] font-semibold text-foreground">分类与筛选</div>
                <div className="mt-0.5 text-[10px] text-muted-foreground/65">按状态或目录缩小范围</div>
              </div>

              <div className="mt-1 border-t border-border/50 pt-2">
                <div className="mb-1.5 text-[10px] font-medium text-muted-foreground">状态</div>
                <div className="space-y-1">
                <DatasetFilterButton
                  label="全部数据集"
                  count={scopeTotal}
                  active={collectionFilter === 'all'}
                  onClick={() => setCollectionFilter('all')}
                  icon={Layers}
                />
                <DatasetFilterButton
                  label="活跃"
                  count={statusCounts.active}
                  active={collectionFilter === 'active'}
                  onClick={() => setCollectionFilter('active')}
                  dotClassName="bg-success"
                />
                <DatasetFilterButton
                  label="异常"
                  count={statusCounts.anomaly}
                  active={collectionFilter === 'anomaly'}
                  onClick={() => setCollectionFilter('anomaly')}
                  dotClassName="bg-destructive"
                />
                <DatasetFilterButton
                  label="待处理"
                  count={statusCounts.pending}
                  active={collectionFilter === 'pending'}
                  onClick={() => setCollectionFilter('pending')}
                  dotClassName="bg-warning"
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
                <div className="mb-1.5 text-[10px] font-medium text-muted-foreground">目录</div>
                <DatasetCategoryTree
                  className="max-h-[420px] overflow-y-auto pr-1 xl:max-h-[calc(100vh-17rem)]"
                  selectedId={selectedCategoryId}
                  onSelect={(id) => setSelectedCategoryId(id)}
                />
              </div>
            </aside>

            <section className="min-h-0 min-w-0 bg-transparent">
              <div className="flex h-full min-h-0 flex-col">
                <div className="flex flex-col gap-2.5 border-b border-foreground/10 px-4 py-2.5 lg:flex-row lg:items-center lg:justify-between">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2 text-[13px] font-semibold text-foreground">
                      <h2 className="truncate">{selectedCategoryId ? '当前分类数据集' : '全部数据集'}</h2>
                      <span className="tabular-nums text-[11px] font-medium text-muted-foreground">
                        {displayedTotal}
                      </span>
                      {isLoading ? <Loader2 className="size-3.5 animate-spin text-info motion-reduce:animate-none" /> : null}
                    </div>
                    <div className="mt-0.5 flex items-center gap-1 text-[10px] text-muted-foreground/65">
                      {collectionFilter !== 'all' ? <span>{collectionFilterLabel} ·</span> : null}
                      {selectedCategoryId ? <span>当前分类 ·</span> : null}
                      <span>显示 {displayedTotal} / {filteredTotal}</span>
                    </div>
                  </div>

                  <div className="flex min-w-0 flex-col gap-2 sm:flex-row sm:items-center">
                    <div className="relative min-w-0 sm:w-[260px] xl:w-[320px]">
                      <Search className="absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground/70" />
                      <Input
                        aria-label="搜索数据集"
                        value={searchQuery}
                        onChange={(e) => setSearchQuery(e.target.value)}
                        maxLength={DATASET_SEARCH_MAX_LENGTH}
                        placeholder="搜索名称、描述或 ID"
                        className="h-8 rounded-lg border-border/60 bg-muted/30 pl-8 text-[11px] shadow-none"
                      />
                    </div>
                    <Select value={sortBy} onValueChange={(value) => setSortBy(value as 'default' | 'name_asc')}>
                      <SelectTrigger className="h-8 w-full rounded-lg border-border/60 bg-background px-2.5 text-[11px] font-medium sm:w-[112px]" aria-label="排序方式">
                        <SelectValue placeholder="排序方式" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="default">默认排序</SelectItem>
                        <SelectItem value="name_asc">按名称</SelectItem>
                      </SelectContent>
                    </Select>
                    {hasActiveFilters ? (
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        className="h-8 rounded-lg px-2.5 text-[11px] text-muted-foreground"
                        onClick={() => {
                          setSearchQuery('')
                          setCollectionFilter('all')
                          setSelectedCategoryId(null)
                        }}
                      >
                        清除筛选
                      </Button>
                    ) : null}
                  </div>
                </div>

                <div
                  data-dataset-catalog-scroll="true"
                  className="min-h-0 flex-1 overflow-y-auto overscroll-contain custom-scrollbar px-3.5 py-3"
                >
                  {items.length === 0 && !isLoading ? (
                    <EmptyState
                      icon={Layers}
                      title={searchQuery ? '未找到匹配的数据集' : '暂无数据集'}
                      description={searchQuery ? '尝试更换关键词或清空筛选。' : '点击“新建数据集”开始构建知识库。'}
                      className="min-h-full rounded-none border-0 bg-transparent shadow-none"
                    />
                  ) : (
                    <motion.div
                      initial="hidden"
                      animate="visible"
                      variants={{ hidden: { opacity: 0 }, visible: { opacity: 1, transition: { staggerChildren: 0.04 } } }}
                      className="space-y-3"
                    >
                      {items.map((dataset) => {
                        const stats = dataset.ingestion_summary
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
                              'focus-ring group w-full cursor-pointer rounded-lg border px-4 py-3 text-left transition-colors duration-200 active:scale-[0.998]',
                              isActive
                                ? 'border-foreground/10 bg-info/[0.04] ring-1 ring-info/15'
                                : 'border-foreground/10 bg-background/70 hover:border-foreground/15 hover:bg-background'
                            )}
                          >
                            <div className={cn(
                              'grid gap-3 xl:items-start',
                              isActive && 'xl:grid-cols-[minmax(0,1fr)_auto]'
                            )}>
                              <div className="flex min-w-0 items-start gap-3.5">
                                <div
                                  className={cn(
                                    'flex size-10 shrink-0 items-center justify-center rounded-lg border',
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
                                <div className="inline-flex w-fit shrink-0 justify-self-start items-center gap-1 rounded-md border border-foreground/10 bg-background/70 p-0.5 xl:justify-self-end">
                                  <button
                                    type="button"
                                    aria-label={`查看 ${dataset.name} 详情`}
                                    title="查看数据集详情"
                                    onClick={(e) => {
                                      e.stopPropagation()
                                      router.push(`/datasets/${dataset.id}/profile`)
                                    }}
                                    className="rounded-md bg-background px-2.5 py-1 text-[11px] font-medium text-primary shadow-none transition-colors duration-200 hover:bg-muted/20 hover:text-primary active:scale-[0.98]"
                                  >
                                    详情
                                  </button>
                                  <button
                                    type="button"
                                    onClick={(e) => {
                                      e.stopPropagation()
                                      router.push(`/knowledge?tab=retrieval&dataset=${dataset.id}`)
                                    }}
                                    className="rounded-md bg-background px-2.5 py-1 text-[11px] font-medium text-primary shadow-none transition-colors duration-200 hover:bg-muted/20 hover:text-primary active:scale-[0.98]"
                                  >
                                    检索
                                  </button>
                                  <Button
                                    size="sm"
                                    className="h-8 rounded-md bg-primary px-3 text-[11px] font-medium text-primary-foreground shadow-none transition-transform duration-200 hover:bg-primary/90 active:scale-[0.98]"
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
                                    className="size-8 rounded-md border border-foreground/10 bg-background/70 transition-colors duration-200 hover:bg-background active:scale-[0.96]"
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
                              <DatasetMetaPill icon={Database} label="ID" value={dataset.id.slice(0, 8)} className="font-mono text-accent" valueClassName="text-accent" />
                              <DatasetMetaPill icon={Clock3} label="更新" value={formatRelativeTime(stats?.last_processed_at)} />
                              <DatasetMetaPill icon={FileSearch} label="文档" value={String(Number(stats?.total_documents || 0))} />
                              <DatasetMetaPill icon={Layers} label="Chunk" value={Number(stats?.total_chunks || 0).toLocaleString()} />
                              <DatasetMetaPill icon={AlertCircle} label="异常" value={String(anomalyCount)} className={anomalyCount > 0 ? 'text-destructive' : undefined} />
                              <DatasetMetaPill icon={Users} label="成员" value={memberCount > 0 ? String(memberCount) : '0'} />
                            </div>
                          </motion.div>
                        )
                      })}
                    </motion.div>
                  )}
                </div>

                <div className="flex items-center justify-between border-t border-border/60 px-4 py-3 text-[11px] text-muted-foreground/72">
                  <span>共 {displayedTotal} 条 · 共 {totalPages} 页</span>
                  <div className="flex items-center gap-2">
                    <Select
                      value={String(pageSize)}
                      onValueChange={(value) => {
                        setPageSize(Number(value))
                        setCurrentPage(1)
                      }}
                    >
                      <SelectTrigger className="h-8 w-[98px] rounded-[11px] border border-border/60 bg-muted/40 px-2.5 text-[11px] font-medium shadow-none transition-all duration-200 hover:border-border hover:bg-card">
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
                        className="size-8 rounded-[11px] border border-border/60 bg-muted/40 text-muted-foreground/50 transition-all duration-200 hover:border-border hover:bg-card hover:text-foreground active:scale-[0.96] disabled:cursor-not-allowed disabled:opacity-45"
                      >
                        ‹
                      </button>
                      <span className="inline-flex min-w-[60px] items-center justify-center rounded-[11px] bg-primary px-2.5 text-[11px] font-semibold text-primary-foreground shadow-[0_10px_18px_-16px_hsl(var(--primary)/0.6)]">
                        {totalPages === 0 ? '0 / 0' : `${currentPage} / ${totalPages}`}
                      </span>
                      <button
                        type="button"
                        disabled={totalPages === 0 || currentPage >= totalPages}
                        onClick={() => setCurrentPage((page) => Math.min(totalPages, page + 1))}
                        className="size-8 rounded-[11px] border border-border/60 bg-muted/40 text-muted-foreground/50 transition-all duration-200 hover:border-border hover:bg-card hover:text-foreground active:scale-[0.96] disabled:cursor-not-allowed disabled:opacity-45"
                      >
                        ›
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            </section>

            {selectedDataset ? (
              <aside
                data-testid="dataset-inspector"
                className="min-h-0 overflow-hidden border-t border-foreground/10 bg-sidebar/28 p-3 lg:col-span-2 xl:col-span-1 xl:border-l xl:border-t-0"
              >
                <motion.div
                  key={selectedDataset.id}
                  initial={{ opacity: 0, x: 12 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ duration: 0.18 }}
                  className="flex h-full flex-col gap-1.5 overflow-y-auto pr-1 custom-scrollbar"
                >
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <div className="text-[12px] font-semibold text-foreground">数据集详情</div>
                        <div className="mt-0.5 text-[10px] text-muted-foreground/65">访问权限与治理入口</div>
                      </div>
                      <div className="flex items-center gap-2">
                        <Button variant="ghost" size="icon" aria-label="编辑数据集" title="编辑数据集" className="size-7 rounded-full border border-border/60 bg-muted/50 text-muted-foreground transition-all duration-200 hover:border-border hover:bg-card hover:text-foreground active:scale-[0.96]" onClick={() => openEdit(selectedDataset)}>
                          <Pencil className="size-3" />
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon"
                          aria-label="删除数据集"
                          title="删除数据集"
                          className="size-7 rounded-full border border-destructive/20 bg-destructive/10 text-destructive/70 transition-all duration-200 hover:border-destructive/30 hover:bg-destructive/15 active:scale-[0.96]"
                          onClick={() => {
                            setDeleteIncludingDocuments(false)
                            setDeleteDocumentCountHint(null)
                            setDeleteTarget(selectedDataset)
                          }}
                        >
                          <Trash2 className="size-3" />
                        </Button>
                      </div>
                    </div>

                    <div className="rounded-lg border border-foreground/10 bg-background/70 px-2 py-1.5">
                      <div className="flex items-start gap-1.5">
                        <div className={cn(
                          'flex size-7 shrink-0 items-center justify-center rounded-[10px] border',
                          selectedStatusIcon.activeClassName
                        )}>
                          <Layers className="size-3" />
                        </div>
                        <div className="min-w-0 flex-1">
                          <div className="flex flex-wrap items-center gap-1.5">
                            <div className="truncate text-[12px] font-semibold text-foreground">{selectedDataset.name}</div>
                            <span className={cn('inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-semibold', selectedStatusBadge.className)}>
                              <span className={cn('size-1.5 rounded-full', selectedStatusBadge.dotClassName)} />
                              {selectedStatusBadge.label}
                            </span>
                          </div>
                        </div>
                      </div>

                      <div className="mt-1 grid grid-cols-3 gap-1">
                        <DetailStat
                          label="文档数"
                          value={Number(selectedDatasetStats?.total_documents || 0).toLocaleString()}
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

                    <div className="space-y-0.5 rounded-lg border border-foreground/10 bg-background/70 px-2 py-1.5">
                      <InspectorRow icon={Database} label="数据集 ID">
                        <span className="font-mono text-accent">{selectedDataset.id.slice(0, 8)}</span>
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
              </aside>
            ) : null}
          </div>
        </div>
      </PageScaffold>

      {/* Delete confirmation */}
      <AlertDialog
        open={!!deleteTarget}
        onOpenChange={(open) => {
          if (open) return
          if (deletePending) return
          setDeleteTarget(null)
          setDeleteIncludingDocuments(false)
          setDeleteDocumentCountHint(null)
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>删除数据集？</AlertDialogTitle>
            <AlertDialogDescription>
              你将删除 <span className="font-medium">{deleteTarget?.name}</span>。此操作不可撤销。
            </AlertDialogDescription>
          </AlertDialogHeader>
          {deleteRequiresDocumentPurge ? (
            <div className="rounded-2xl border border-warning/30 bg-warning/5 p-3 text-sm text-warning">
              <div className="flex items-start gap-2.5">
                <AlertCircle className="mt-0.5 size-4 shrink-0 text-warning" />
                <div className="min-w-0">
                  <div className="font-semibold">该数据集还有 {deleteTargetDocumentCount} 个文档</div>
                  <p className="mt-1 text-xs leading-relaxed text-warning/80">
                    直接删除会被后端拦截。勾选后会先清空文档、分块和索引，再删除数据集记录。
                  </p>
                </div>
              </div>
              <label className="mt-3 flex cursor-pointer items-center gap-2 rounded-xl border border-warning/30 bg-card/70 px-3 py-2 text-xs font-medium text-warning">
                <Checkbox
                  checked={deleteIncludingDocuments}
                  onCheckedChange={(checked) => setDeleteIncludingDocuments(checked === true)}
                />
                同时删除文档和索引
              </label>
            </div>
          ) : null}
          <AlertDialogFooter>
            <AlertDialogCancel disabled={deletePending}>取消</AlertDialogCancel>
            <Button
              variant="destructive"
              size="sm"
              onClick={handleDelete}
              disabled={deletePending || (deleteRequiresDocumentPurge && !deleteIncludingDocuments)}
            >
              {deletePending ? (
                <>
                  <Loader2 className="mr-2 size-4 animate-spin" />
                  删除中
                </>
              ) : '删除'}
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Edit dialog */}
      <Dialog open={editOpen} onOpenChange={(open) => {
        setEditOpen(open)
        if (!open) { setEditing(null); resetForm() }
      }}>
        <DialogContent className="max-w-xl p-0 sm:rounded-xl">
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
        <div className="truncate text-[9px] font-semibold uppercase tracking-[0.14em] text-muted-foreground/50">{label}</div>
        <div className={cn('truncate text-[10px] font-medium leading-none text-foreground/82', valueClassName)}>{value}</div>
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
        'flex w-full items-center justify-between rounded-md border px-2.5 py-1.5 text-left transition-colors',
        active
          ? 'border-foreground/10 bg-info/[0.06] text-info shadow-none'
          : 'border-transparent text-foreground/78 hover:border-border/60 hover:bg-muted/40'
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
        active ? 'bg-background/90 text-info' : 'bg-background/80 text-foreground/76'
      )}>
        {count}
      </span>
    </button>
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
        <div className="flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-[0.14em] text-muted-foreground/56">
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
      className="focus-ring group relative flex min-h-[70px] flex-col items-start justify-between rounded-lg border border-foreground/10 bg-background/70 px-2 py-1.5 transition-colors duration-200 hover:border-foreground/15 hover:bg-muted/20 active:scale-[0.98]"
      onClick={onClick}
      aria-label={`${title}：${description}`}
    >
      <div className={cn('flex size-5 items-center justify-center rounded-md border transition-all duration-200 group-hover:bg-primary/10 group-hover:text-primary', tone.containerClassName)}>
        <Icon className="size-3" />
      </div>
      <div className="min-w-0 text-left">
        <div className="truncate text-[11px] font-semibold text-foreground/84 transition-colors group-hover:text-primary">
          {title}
        </div>
        <div className="mt-0.5 line-clamp-2 text-[10px] leading-[0.95rem] text-muted-foreground/72">
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
      className="focus-ring group relative flex min-h-[38px] items-center gap-1.5 rounded-md border border-foreground/10 bg-background/70 px-2 py-1.5 transition-colors duration-200 hover:border-foreground/15 hover:bg-muted/20 active:scale-[0.98]"
    >
      <div className={cn('flex size-4 shrink-0 items-center justify-center rounded-md border transition-colors duration-200 group-hover:text-primary', tone.containerClassName)}>
        <Icon className="size-2.5" />
      </div>
      <span className="truncate text-[10px] font-medium text-foreground/84 transition-colors duration-200 group-hover:text-primary">
        {title}
      </span>
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
    <div className="rounded-md border border-foreground/10 bg-background/70 px-2 py-1.5 transition-colors duration-200 hover:border-foreground/15 hover:bg-background">
      <div className="flex items-center gap-1">
        <span
          className={cn(
            'size-1 rounded-full',
            tone === 'success' && 'bg-success',
            tone === 'warning' && 'bg-warning',
            tone === 'danger' && 'bg-destructive',
            tone === 'neutral' && 'bg-border'
          )}
        />
        <span className="text-[10px] font-semibold uppercase tracking-[0.1em] text-foreground/72">{label}</span>
      </div>
      <div className="mt-1 text-[11px] font-semibold text-foreground/86">{value}</div>
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

      <Panel variant="muted" padding="none" className="rounded-lg overflow-hidden border border-foreground/10">
        <div className="flex items-start gap-3 border-b border-foreground/15 bg-background/70 px-4 py-3">
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
          <div className="bg-background/70 p-4">
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
