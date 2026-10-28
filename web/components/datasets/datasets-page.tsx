'use client'

import { useCallback, useEffect, useMemo, useRef, useState, type Dispatch, type ReactNode, type SetStateAction } from 'react'
import { Dataset as DatasetIcon } from '@/components/icons'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import {
  AlertCircle, BarChart3, Check, CheckCircle, ChevronDown, ChevronLeft, ChevronRight,
  Clock3, Database, FileSearch, FlaskConical, FolderOpen, FolderTree, Globe,
  Ingestion, Layers, Loader2, Lock, MoreHorizontal, Pencil, RefreshCw, Search,
  Settings2, Table2, Trash2, Users, type PlatformIcon,
} from '@/components/icons'

import { AppFrame } from '@/components/app-frame'
import { Link, useRouter } from '@/i18n/navigation'
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
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Panel } from '@/components/ui/panel'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { Textarea } from '@/components/ui/textarea'
import { datasetApi, datasetCategoryApi } from '@/lib/api'
import type { DatasetListParams } from '@/lib/api/datasets'
import { formatApiError } from '@/lib/api-errors'
import { reportClientError } from '@/lib/client-logging'
import { queryKeys } from '@/lib/query-keys'
import { cn, detachPromise } from '@/lib/utils'
import type {
  Dataset,
  DatasetCategoryNode,
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
import styles from './datasets-page.module.css'

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

const PERMISSION_CONFIG: Record<PermissionEnum, { label: string; icon: PlatformIcon }> = {
  all_team_members: { label: '全员', icon: Globe },
  only_me: { label: '仅自己', icon: Lock },
  partial_members: { label: '部分成员', icon: Users },
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

function getDatasetStatusBadgeConfig(status: DatasetOperationalStatus) {
  switch (status) {
    case 'active': return { label: '正常', icon: CheckCircle }
    case 'anomaly': return { label: '异常', icon: AlertCircle }
    case 'pending': return { label: '待处理', icon: Clock3 }
    case 'testing': return { label: '测试集', icon: FlaskConical }
  }
}

function DatasetStatus({ dataset }: Readonly<{ dataset: Dataset }>) {
  const status = getDatasetOperationalStatus(dataset, dataset.ingestion_summary)
  const { label, icon: Icon } = getDatasetStatusBadgeConfig(status)
  const count = status === 'anomaly' ? getDatasetAnomalyCount(dataset.ingestion_summary) : 0
  return (
    <span className={styles.status} data-state={status}>
      <Icon className="size-3.5" />
      {label}
      {count > 0 ? <span className={styles.anomalyCount}>{count}</span> : null}
    </span>
  )
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
  const [inspectorOpen, setInspectorOpen] = useState(false)
  const rowButtons = useRef(new Map<string, HTMLButtonElement>())
  const returnDatasetId = useRef<string | null>(null)
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
    if (!response) return
    const nextTotalPages = displayedTotal === 0 ? 1 : Math.ceil(displayedTotal / pageSize)
    if (currentPage > nextTotalPages) {
      setCurrentPage(nextTotalPages)
    }
  }, [currentPage, displayedTotal, pageSize, response])

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
  const deleteTargetStats = deleteTarget?.ingestion_summary ?? undefined
  const deleteTargetDocumentCount = Math.max(0, Number(deleteDocumentCountHint ?? deleteTargetStats?.total_documents ?? 0))
  const deleteRequiresDocumentPurge = deleteTargetDocumentCount > 0
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
    returnDatasetId.current = ds.id
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
      setInspectorOpen(false)
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

  const openDetails = (dataset: Dataset) => {
    returnDatasetId.current = dataset.id
    setSelectedDatasetId(dataset.id)
    setInspectorOpen(true)
  }

  const restoreRowFocus = (event: Event) => {
    event.preventDefault()
    if (editOpen || deleteTarget) return
    const target = rowButtons.current.get(returnDatasetId.current || '') || rowButtons.current.get(selectedDataset?.id || '')
    target?.focus()
  }

  const clearFilters = () => {
    setSearchQuery('')
    setCollectionFilter('all')
    setSelectedCategoryId(null)
  }

  const requestDelete = (dataset: Dataset) => {
    returnDatasetId.current = dataset.id
    setInspectorOpen(false)
    setDeleteIncludingDocuments(false)
    setDeleteDocumentCountHint(null)
    setDeleteTarget(dataset)
  }

  return (
    <AppFrame>
      <section className={styles.shell} data-datasets-shell="true">
        <header data-testid="datasets-page-toolbar" className={styles.pageHeader}>
          <div className={styles.pageHeading}>
            <DatasetIcon appearance="color" className="size-6" data-dataset-title-mark="true" />
            <h1>数据集</h1>
          </div>
          <Dialog open={createOpen} onOpenChange={(open) => { setCreateOpen(open); if (open) resetForm() }}>
            <DialogTrigger asChild>
              <CreateDatasetButton className={styles.createButton} />
            </DialogTrigger>
            <DialogContent className="max-w-xl p-0 sm:rounded-xl">
              <div className="flex max-h-[min(88dvh,860px)] flex-col">
                <DialogHeader className="border-b border-border/60 px-6 pt-6 pb-4">
                  <DialogTitle>新建数据集</DialogTitle>
                  <DialogDescription>为文档分组并设置访问权限</DialogDescription>
                </DialogHeader>
                <div className="min-h-0 flex-1 overflow-y-auto custom-scrollbar px-6 py-5">
                  <DatasetForm form={form} setForm={setForm} />
                </div>
                <DialogFooter className="border-t border-border/60 px-6 py-4">
                  <Button variant="ghost" onClick={() => setCreateOpen(false)}>取消</Button>
                  <Button onClick={handleCreate} disabled={!canSubmit}>确认创建</Button>
                </DialogFooter>
              </div>
            </DialogContent>
          </Dialog>
        </header>

        <div className={styles.toolbar}>
          <DatasetCategoryFilter selectedId={selectedCategoryId} onSelect={setSelectedCategoryId} />
          <div className={styles.filters} role="group" aria-label="数据集状态">
            {([
              { value: 'all', label: '全部', count: scopeTotal },
              { value: 'active', label: '正常', count: statusCounts.active },
              { value: 'anomaly', label: '异常', count: statusCounts.anomaly },
              { value: 'pending', label: '待处理', count: statusCounts.pending },
              { value: 'testing', label: '测试集', count: statusCounts.testing },
            ] as const).map((filter) => (
              <Button
                key={filter.value}
                variant="ghost"
                size="sm"
                className={styles.filter}
                aria-pressed={collectionFilter === filter.value}
                aria-label={filter.label}
                onClick={() => setCollectionFilter(filter.value)}
              >
                {filter.label}
                <span className={styles.filterCount}>{isLoading ? '—' : filter.count.toLocaleString()}</span>
              </Button>
            ))}
          </div>
          <div className={styles.toolsEnd}>
            <div className={styles.search}>
              <Search className="size-4" aria-hidden="true" />
              <Input
                aria-label="搜索数据集"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                maxLength={DATASET_SEARCH_MAX_LENGTH}
                placeholder="搜索数据集"
                className={styles.searchInput}
              />
            </div>
            <Select value={sortBy} onValueChange={(value) => setSortBy(value as 'default' | 'name_asc')}>
              <SelectTrigger className={styles.sort} aria-label="排序方式">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="default">最近创建</SelectItem>
                <SelectItem value="name_asc">名称 A–Z</SelectItem>
              </SelectContent>
            </Select>
            <Button
              variant="ghost"
              size="icon"
              className={styles.refresh}
              aria-label="刷新数据集"
              title="刷新数据集"
              onClick={() => { detachPromise(refreshDatasets()) }}
              disabled={isRefreshing}
            >
              <RefreshCw className={cn('size-4', isRefreshing && 'animate-spin motion-reduce:animate-none')} />
            </Button>
          </div>
        </div>

        {hasActiveFilters ? (
          <div className={styles.filterSummary} role="status">
            <span>{isLoading ? '正在筛选…' : `找到 ${displayedTotal.toLocaleString()} 个数据集`}</span>
            <Button variant="ghost" size="sm" onClick={clearFilters}>清除筛选</Button>
          </div>
        ) : null}

        <div className={styles.workspace} data-testid="datasets-workspace">
          <div className={cn(styles.tableScroll, 'custom-scrollbar')} data-dataset-catalog-scroll="true" tabIndex={0} role="region" aria-label="数据集列表">
            <table className={styles.table} aria-label="数据集" aria-busy={isRefreshing}>
              <colgroup>
                <col className={styles.nameColumn} />
                <col className={styles.statusColumn} />
                <col className={styles.numericColumn} />
                <col className={styles.chunksColumn} />
                <col className={styles.accessColumn} />
                <col className={styles.updatedColumn} />
                <col className={styles.actionsColumn} />
              </colgroup>
              <thead>
                <tr>
                  <th scope="col">数据集名称</th>
                  <th scope="col">状态</th>
                  <th scope="col" className={cn(styles.numeric, styles.desktopColumn)}>文档量</th>
                  <th scope="col" className={cn(styles.numeric, styles.chunks, styles.desktopColumn)}>切块量</th>
                  <th scope="col" className={styles.desktopColumn}>访问权限</th>
                  <th scope="col" className={cn(styles.updated, styles.desktopColumn)}>最近处理</th>
                  <th scope="col" className={styles.actionHeading}><span className={styles.actionLabel}>操作</span><span className="sr-only md:hidden">操作</span></th>
                </tr>
              </thead>
              <tbody>
                {isLoading ? (
                  <tr className={styles.stateRow}><td colSpan={7}>
                    <div className={styles.loading} role="status">
                      <Loader2 className="size-5 animate-spin motion-reduce:animate-none" />
                      加载数据集…
                    </div>
                  </td></tr>
                ) : datasetsQuery.isError ? (
                  <tr className={styles.stateRow}><td colSpan={7}>
                    <EmptyState icon={AlertCircle} iconClassName="text-destructive" title="数据集加载失败" description="请稍后重试。" className={styles.empty}>
                      <Button variant="outline" onClick={() => { detachPromise(refreshDatasets()) }} disabled={isRefreshing}>重新加载</Button>
                    </EmptyState>
                  </td></tr>
                ) : items.length === 0 ? (
                  <tr className={styles.stateRow}><td colSpan={7}>
                    <EmptyState
                      icon={DatasetIcon}
                      title={hasActiveFilters ? '未找到匹配的数据集' : '暂无数据集'}
                      description={hasActiveFilters ? '试试其他关键词，或清除筛选。' : '新建数据集，开始整理文档。'}
                      className={styles.empty}
                    >
                      {hasActiveFilters
                        ? <Button variant="outline" onClick={clearFilters}>清除筛选</Button>
                        : <Button onClick={() => { resetForm(); setCreateOpen(true) }}>新建数据集</Button>}
                    </EmptyState>
                  </td></tr>
                ) : items.map((dataset) => {
                  const stats = dataset.ingestion_summary
                  const permission = PERMISSION_CONFIG[dataset.permission] || PERMISSION_CONFIG.all_team_members
                  const PermissionIcon = permission.icon
                  const isActive = selectedDataset?.id === dataset.id
                  return (
                    <tr
                      key={dataset.id}
                      data-dataset-row={dataset.id}
                      data-selected={isActive}
                      onClick={() => setSelectedDatasetId(dataset.id)}
                    >
                      <td>
                        <div className={styles.dataset}>
                          <DatasetIcon appearance="color" className={styles.datasetIcon} />
                          <div className={styles.datasetCopy}>
                            <button
                              ref={(node) => { if (node) rowButtons.current.set(dataset.id, node); else rowButtons.current.delete(dataset.id) }}
                              type="button"
                              className={cn('focus-ring', styles.datasetName)}
                              aria-label={`查看 ${dataset.name} 详情`}
                              aria-haspopup="dialog"
                              aria-expanded={inspectorOpen && isActive}
                              title={dataset.name}
                              onClick={() => openDetails(dataset)}
                            >
                              <span>{dataset.name}</span>
                              {isActive ? <Check className={styles.selectedCheck} /> : null}
                            </button>
                            {dataset.description ? <p className={styles.description} title={dataset.description}>{dataset.description}</p> : null}
                            <span className={styles.mobileMeta}>{Number(stats?.total_documents || 0).toLocaleString()} 篇文档</span>
                          </div>
                        </div>
                      </td>
                      <td><DatasetStatus dataset={dataset} /></td>
                      <td className={cn(styles.numeric, styles.desktopColumn)}>{Number(stats?.total_documents || 0).toLocaleString()}</td>
                      <td className={cn(styles.numeric, styles.chunks, styles.desktopColumn)}>{Number(stats?.total_chunks || 0).toLocaleString()}</td>
                      <td className={styles.desktopColumn}>
                        <span className={styles.permission}><PermissionIcon className="size-3.5" />{permission.label}</span>
                      </td>
                      <td className={cn(styles.updated, styles.desktopColumn)}>
                        <time dateTime={stats?.last_processed_at || undefined} title={stats?.last_processed_at ? new Date(stats.last_processed_at).toLocaleString() : '尚无处理记录'}>
                          {formatRelativeTime(stats?.last_processed_at)}
                        </time>
                      </td>
                      <td>
                        <div className={styles.rowActions}>
                          <Button asChild variant="ghost" size="sm" className={styles.rowAction}>
                            <Link href={`/datasets/${dataset.id}/ingestion`} aria-label={`向 ${dataset.name} 入库`}><Ingestion className="size-3.5" />入库</Link>
                          </Button>
                          <Button asChild variant="ghost" size="sm" className={styles.rowAction}>
                            <Link href={`/knowledge?tab=retrieval&dataset=${dataset.id}`} aria-label={`在 ${dataset.name} 中检索`}><FileSearch className="size-3.5" />检索</Link>
                          </Button>
                          <DropdownMenu>
                            <DropdownMenuTrigger asChild>
                              <Button variant="ghost" size="icon" className={styles.more} aria-label={`${dataset.name}的更多操作`} title="更多操作">
                                <MoreHorizontal className="size-4" />
                              </Button>
                            </DropdownMenuTrigger>
                            <DropdownMenuContent align="end" className={styles.menu}>
                              <DropdownMenuItem onSelect={() => openDetails(dataset)}><DatasetIcon className="size-4" />数据集详情</DropdownMenuItem>
                              <DropdownMenuItem onSelect={() => openEdit(dataset)}><Pencil className="size-4" />编辑设置</DropdownMenuItem>
                              <DropdownMenuSeparator />
                              <DropdownMenuItem className={styles.mobileMenuAction} onSelect={() => router.push(`/datasets/${dataset.id}/ingestion`)}><Ingestion className="size-4" />入库管理</DropdownMenuItem>
                              <DropdownMenuItem className={styles.mobileMenuAction} onSelect={() => router.push(`/knowledge?tab=retrieval&dataset=${dataset.id}`)}><FileSearch className="size-4" />检索测试</DropdownMenuItem>
                              <DropdownMenuItem onSelect={() => router.push(`/datasets/${dataset.id}/precheck`)}><FileSearch className="size-4" />文档预检</DropdownMenuItem>
                              <DropdownMenuItem onSelect={() => router.push(`/datasets/${dataset.id}/profile`)}><BarChart3 className="size-4" />数据画像</DropdownMenuItem>
                              <DropdownMenuItem onSelect={() => router.push(`/datasets/${dataset.id}/workflow`)}><Layers className="size-4" />流程编排</DropdownMenuItem>
                              <DropdownMenuItem onSelect={() => router.push(`/datasets/${dataset.id}/tables`)}><Table2 className="size-4" />表格资产</DropdownMenuItem>
                              <DropdownMenuItem onSelect={() => router.push(`/datasets/${dataset.id}/db-catalog`)}><Database className="size-4" />数据库目录</DropdownMenuItem>
                              <DropdownMenuSeparator />
                              <DropdownMenuItem className="text-destructive focus:bg-destructive/10 focus:text-destructive" onSelect={() => requestDelete(dataset)}><Trash2 className="size-4" />删除数据集</DropdownMenuItem>
                            </DropdownMenuContent>
                          </DropdownMenu>
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>

        <footer className={styles.tableFooter} data-task-center-dock="true">
          <span className={styles.total} role="status" aria-live="polite">{isLoading ? '加载中…' : datasetsQuery.isError ? '加载失败' : <>共 <strong>{displayedTotal.toLocaleString()}</strong> 个数据集</>}</span>
          <div className={styles.pagination}>
            <Select value={String(pageSize)} onValueChange={(value) => { setPageSize(Number(value)); setCurrentPage(1) }}>
              <SelectTrigger className={styles.pageSize} aria-label="每页数据集数量"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="10">10 条 / 页</SelectItem>
                <SelectItem value="20">20 条 / 页</SelectItem>
                <SelectItem value="50">50 条 / 页</SelectItem>
              </SelectContent>
            </Select>
            <div className={styles.pageControls}>
              <Button variant="ghost" size="icon" aria-label="上一页" className={styles.pageArrow} disabled={isLoading || currentPage <= 1} onClick={() => setCurrentPage((page) => Math.max(1, page - 1))}><ChevronLeft className="size-4" /></Button>
              <span className={styles.pageNumber} aria-label={`第 ${totalPages === 0 ? 0 : currentPage} 页，共 ${totalPages} 页`}>{totalPages === 0 ? '0' : currentPage}</span>
              <span className={styles.pageOf}>/ {totalPages}</span>
              <Button variant="ghost" size="icon" aria-label="下一页" className={styles.pageArrow} disabled={isLoading || totalPages === 0 || currentPage >= totalPages} onClick={() => setCurrentPage((page) => Math.min(totalPages, page + 1))}><ChevronRight className="size-4" /></Button>
            </div>
          </div>
        </footer>
      </section>

      <Sheet open={inspectorOpen && Boolean(selectedDataset)} onOpenChange={setInspectorOpen}>
        <SheetContent className={styles.detailSheet} onCloseAutoFocus={restoreRowFocus}>
          {selectedDataset ? (
            <>
              <SheetHeader className={styles.detailHeader}>
                <SheetTitle>数据集详情</SheetTitle>
                <SheetDescription className="sr-only">查看数据集信息，调整访问权限和默认管线</SheetDescription>
              </SheetHeader>
              <div data-testid="dataset-inspector" className={cn(styles.detailBody, 'custom-scrollbar')}>
                <div className={styles.detailIdentity}>
                  <DatasetIcon appearance="color" className="size-7" />
                  <h2>{selectedDataset.name}</h2>
                  <DatasetStatus dataset={selectedDataset} />
                </div>
                {selectedDataset.description ? <p className={styles.detailDescription}>{selectedDataset.description}</p> : null}
                <dl className={styles.detailFields}>
                  <DatasetDetailRow label="数据集 ID"><span className={styles.datasetId}>{selectedDataset.id}</span></DatasetDetailRow>
                  <DatasetDetailRow label="文档量">{Number(selectedDatasetStats?.total_documents || 0).toLocaleString()}</DatasetDetailRow>
                  <DatasetDetailRow label="切块量">{Number(selectedDatasetStats?.total_chunks || 0).toLocaleString()}</DatasetDetailRow>
                  <DatasetDetailRow label="最近处理">{formatRelativeTime(selectedDatasetStats?.last_processed_at)}</DatasetDetailRow>
                  <DatasetDetailRow label="访问权限">
                    <Select
                      value={selectedDataset.permission}
                      disabled={permissionUpdatePending}
                      onValueChange={(value) => detachPromise(handleInspectorPermissionChange(selectedDataset, value as PermissionEnum))}
                    >
                      <SelectTrigger aria-label="访问权限" className={styles.detailSelect}><SelectValue /></SelectTrigger>
                      <SelectContent>
                        <SelectItem value="only_me">仅自己</SelectItem>
                        <SelectItem value="all_team_members">全员可见</SelectItem>
                        <SelectItem value="partial_members">部分成员</SelectItem>
                      </SelectContent>
                    </Select>
                  </DatasetDetailRow>
                  <DatasetDetailRow label="默认管线">
                    <div className={styles.pipelineControl}>
                      <span>{selectedDataset.pipeline ? '已启用' : '未启用'}</span>
                      <Switch
                        checked={Boolean(selectedDataset.pipeline)}
                        disabled={pipelineTogglePending}
                        onCheckedChange={(nextChecked) => detachPromise(handleToggleDefaultPipeline(selectedDataset, nextChecked))}
                        aria-label={selectedDataset.pipeline ? '关闭默认管线' : '启用默认管线'}
                      />
                    </div>
                  </DatasetDetailRow>
                </dl>
                <nav className={styles.detailLinks} aria-label="数据集操作">
                  {([
                    { label: '入库管理', icon: Ingestion, href: `/datasets/${selectedDataset.id}/ingestion` },
                    { label: '检索测试', icon: FileSearch, href: `/knowledge?tab=retrieval&dataset=${selectedDataset.id}` },
                    { label: '文档预检', icon: FileSearch, href: `/datasets/${selectedDataset.id}/precheck` },
                    { label: '数据画像', icon: BarChart3, href: `/datasets/${selectedDataset.id}/profile` },
                  ]).map(({ label, icon: Icon, href }) => (
                    <Button key={href} variant="ghost" onClick={() => router.push(href)}><Icon className="size-4" />{label}<ChevronRight className="ml-auto size-4" /></Button>
                  ))}
                </nav>
              </div>
              <div className={styles.detailFooter}>
                <Button variant="outline" onClick={() => requestDelete(selectedDataset)}><Trash2 className="size-4" />删除</Button>
                <Button onClick={() => { setInspectorOpen(false); openEdit(selectedDataset) }}><Pencil className="size-4" />编辑设置</Button>
              </div>
            </>
          ) : null}
        </SheetContent>
      </Sheet>

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
        <AlertDialogContent onCloseAutoFocus={restoreRowFocus}>
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
        <DialogContent className="max-w-xl p-0 sm:rounded-xl" onCloseAutoFocus={restoreRowFocus}>
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

function DatasetDetailRow({ label, children }: Readonly<{ label: string; children: ReactNode }>) {
  return <div className={styles.detailRow}><dt>{label}</dt><dd>{children}</dd></div>
}

function flattenCategories(items: DatasetCategoryNode[], depth = 0): Array<{ id: string; name: string; depth: number }> {
  return items.flatMap((item) => [{ id: item.id, name: item.name, depth }, ...flattenCategories(item.children || [], depth + 1)])
}

function DatasetCategoryFilter({ selectedId, onSelect }: Readonly<{ selectedId: string | null; onSelect: (id: string | null) => void }>) {
  const [open, setOpen] = useState(false)
  const [managerOpen, setManagerOpen] = useState(false)
  const trigger = useRef<HTMLButtonElement>(null)
  const categories = useQuery({
    queryKey: queryKeys.datasetCategories.tree,
    queryFn: () => datasetCategoryApi.listTree(),
  })
  const items = useMemo(() => flattenCategories(categories.data?.items || []), [categories.data])
  const label = selectedId ? items.find((item) => item.id === selectedId)?.name || '当前分类' : '全部分类'
  const select = (id: string | null) => { onSelect(id); setOpen(false) }
  return (
    <>
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <Button ref={trigger} variant="outline" className={styles.categoryTrigger} aria-label="选择数据集分类" title={label}>
            <FolderOpen className="size-4" /><span>{label}</span><ChevronDown className="size-3.5" />
          </Button>
        </PopoverTrigger>
        <PopoverContent align="start" className={styles.categoryMenu}>
          <div className={styles.categoryOptions} role="group" aria-label="数据集分类">
            <Button variant="ghost" aria-pressed={!selectedId} onClick={() => select(null)}><FolderTree className="size-4" /><span>全部分类</span>{!selectedId ? <Check className="ml-auto size-3.5" /> : null}</Button>
            {categories.isPending ? <p className={styles.categoryMessage} role="status">加载分类…</p> : null}
            {categories.isError ? (
              <div className={styles.categoryMessage} role="status">分类加载失败<Button variant="ghost" size="sm" onClick={() => detachPromise(categories.refetch())}>重试</Button></div>
            ) : items.map((item) => (
              <Button key={item.id} variant="ghost" aria-pressed={selectedId === item.id} onClick={() => select(item.id)} style={{ paddingLeft: 12 + item.depth * 16 }} title={item.name}>
                <FolderOpen className="size-4" /><span>{item.name}</span>{selectedId === item.id ? <Check className="ml-auto size-3.5" /> : null}
              </Button>
            ))}
          </div>
          <div className={styles.categoryManage}>
            <Button variant="ghost" onClick={() => { setOpen(false); setManagerOpen(true) }}><Settings2 className="size-4" />管理分类</Button>
          </div>
        </PopoverContent>
      </Popover>
      <Sheet open={managerOpen} onOpenChange={setManagerOpen}>
        <SheetContent className={styles.categorySheet} onCloseAutoFocus={(event) => { event.preventDefault(); trigger.current?.focus() }}>
          <SheetHeader className={styles.detailHeader}><SheetTitle>管理分类</SheetTitle><SheetDescription>新建或删除数据集分类</SheetDescription></SheetHeader>
          <div className={cn(styles.detailBody, 'custom-scrollbar')}>
            <DatasetCategoryTree selectedId={selectedId} onSelect={onSelect} />
          </div>
        </SheetContent>
      </Sheet>
    </>
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
