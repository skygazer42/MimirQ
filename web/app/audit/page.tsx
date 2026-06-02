'use client'

import { useCallback, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { toast } from 'sonner'
import {
  ShieldCheck,
  RefreshCw,
  Copy,
  FilterX,
  ScrollText,
  ChevronDown,
  ChevronUp,
  Filter,
  CheckCircle2,
  FileJson,
  LayoutGrid,
  Trash2,
  ChevronLeft,
  ChevronRight,
  type LucideIcon,
} from 'lucide-react'
import { useTranslations } from 'next-intl'

import { TenantPermissionGate } from '@/components/auth/tenant-permission-gate'
import { AppFrame } from '@/components/app-frame'
import { PageScaffold } from '@/components/ui/page-scaffold'
import { Button } from '@/components/ui/button'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { auditApi } from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'
import { toTrimmedPrimitiveString } from '@/lib/primitive-text'
import { queryKeys } from '@/lib/query-keys'
import {
  TENANT_PERMISSIONS,
  tenantAccessAllows,
} from '@/lib/tenant-permissions'
import type { AuditLogItem, AuditLogListResponse } from '@/types'
import { cn } from '@/lib/utils'
import { EmptyState } from '@/components/ui/empty-state'
import { AuditRetentionPanel } from '@/components/audit/audit-retention-panel'
import { useTenantAccess } from '@/hooks/use-tenant-access'

// --- Constants ---

const FIELD_LABEL =
  'text-[10px] font-semibold uppercase tracking-[0.14em] text-muted-foreground mb-1.5 block'
const AUDIT_SURFACE_CLASS =
  'border-border/60 bg-background/70 text-foreground'
const AUDIT_PANEL_CLASS = `rounded-2xl ${AUDIT_SURFACE_CLASS} bg-card/82 shadow-[0_12px_30px_hsl(var(--primary)/0.05)]`
const AUDIT_TABLE_HEAD_CLASS =
  'border-b border-border/50 bg-muted/38 text-left backdrop-blur'
const AUDIT_TABLE_HEADER_CLASS =
  'px-6 py-3.5 text-[11px] font-semibold tracking-[0.08em] text-muted-foreground'
const FILTER_ALL_VALUE = '__all__'
const FILTER_EMPTY_VALUE_PREFIX = '__empty__'
const AUDIT_FILTER_OPTION_PAGE_SIZE = 200
const AUDIT_FILTER_OPTION_MAX_PAGES = 5
const AUDIT_PAGE_SIZE_OPTIONS = [20, 50, 100] as const

type AuditFilters = {
  actor_id: string
  action: string
  resource_type: string
  resource_id: string
  request_id: string
  since: string
  until: string
}

type AuditFilterKey = keyof AuditFilters
type AuditLogQueryParams = NonNullable<Parameters<typeof auditApi.listLogs>[0]>

const EMPTY_AUDIT_FILTERS: AuditFilters = {
  actor_id: '',
  action: '',
  resource_type: '',
  resource_id: '',
  request_id: '',
  since: '',
  until: '',
}

function uniqueAuditValues(items: AuditLogItem[], key: keyof AuditLogItem) {
  return Array.from(
    new Set(
      items
        .map((item) => item[key])
        .filter(
          (value): value is string =>
            typeof value === 'string' && value.trim().length > 0
        )
        .map((value) => value.trim())
    )
  ).sort((a, b) => a.localeCompare(b))
}

function withCurrentOption(options: string[], current: string) {
  const value = current.trim()
  return value && !options.includes(value) ? [value, ...options] : options
}

function compactOption(value: string, max = 42) {
  return value.length > max ? `${value.slice(0, Math.max(8, max - 1))}…` : value
}

const AUDIT_ACTION_LABELS: Record<string, string> = {
  'audit.logs.purge': '审计日志清理',
  'audit.logs.retention': '审计保留策略',
  'compliance.access_graph.export': '访问回溯导出',
  'compliance.access_review.daily': '访问审查',
  'dataset.retention.sweep': '数据集保留清理',
  'document.version.retention_delete': '文档版本保留删除',
  'evaluations.regression_runs.retention': '评测运行保留清理',
  'evidence.drift_audit.daily': '证据策略',
  'knowledge.assets.retention': '知识资产保留清理',
  'observability.index_audit.daily': '索引审计',
}

const AUDIT_TERM_LABELS: Record<string, string> = {
  access: '访问',
  account: '账号',
  answer: '回答',
  api: '接口',
  asset: '资产',
  assets: '资产',
  audit: '审计',
  chat: '对话',
  chunk: '分块',
  chunks: '分块',
  compliance: '合规',
  completed: '已完成',
  create: '创建',
  created: '已创建',
  daily: '日常',
  dataset: '数据集',
  datasets: '数据集',
  delete: '删除',
  deleted: '已删除',
  document: '文档',
  documents: '文档',
  drift: '漂移',
  evidence: '证据',
  export: '导出',
  failed: '失败',
  graph: '图谱',
  index: '索引',
  ingest: '入库',
  ingestion: '入库',
  kg: '知识图谱',
  knowledge: '知识库',
  log: '日志',
  logs: '日志',
  parse: '解析',
  purge: '清理',
  query: '查询',
  retention: '保留',
  review: '审查',
  run: '运行',
  runs: '运行',
  started: '已开始',
  sweep: '扫描清理',
  version: '版本',
}

const AUDIT_RESOURCE_TYPE_LABELS: Record<string, string> = {
  audit_logs: '审计日志',
  dataset: '数据集',
  dataset_member_permission: '数据集成员权限',
  dataset_group_permission: '数据集组权限',
  document: '文档',
  document_member_permission: '文档成员权限',
  document_group_permission: '文档组权限',
  document_version: '文档版本',
  knowledge_asset: '知识资产',
  regression_run: '评测运行',
  stale_report: '过期报告',
}

function humanizeAuditTokens(value: string) {
  return value
    .split(/[._:-]+/)
    .map((part) => part.trim().toLowerCase())
    .filter(Boolean)
    .map((part) => AUDIT_TERM_LABELS[part] || part)
    .join(' / ')
}

function formatAuditAction(value: string | null | undefined) {
  const raw = String(value || '').trim()
  if (!raw) return '未记录动作'
  return AUDIT_ACTION_LABELS[raw] || humanizeAuditTokens(raw)
}

function formatAuditResourceType(value: string | null | undefined) {
  const raw = String(value || '').trim()
  if (!raw) return '未绑定资源'
  return AUDIT_RESOURCE_TYPE_LABELS[raw] || humanizeAuditTokens(raw)
}

function formatAuditDateTime(value: string) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return { date: '时间未知', time: '--:--:--' }
  }

  return {
    date: date.toLocaleDateString('zh-CN'),
    time: date.toLocaleTimeString('zh-CN', { hour12: false }),
  }
}

// --- Helper Components ---

const HUD_TONE_CLASSES = {
  slate: 'bg-muted/55 text-muted-foreground border-border/60',
  green: 'bg-success/10 text-success border-success/20',
  blue: 'bg-primary/10 text-primary border-primary/20',
  purple: 'bg-accent/10 text-accent border-accent/20',
} as const

function HUDTile({
  icon: Icon,
  label,
  value,
  tone = 'slate',
}: Readonly<{
  icon: LucideIcon
  label: string
  value: string | number
  tone?: keyof typeof HUD_TONE_CLASSES
}>) {
  const toneClasses = HUD_TONE_CLASSES[tone] || HUD_TONE_CLASSES.slate

  return (
    <div className="bg-card rounded-2xl border border-border/60 p-5 flex items-center gap-4 shadow-[0_1px_2px_rgba(0,0,0,0.01)]">
      <div
        className={cn(
          'size-10 rounded-xl flex items-center justify-center border',
          toneClasses
        )}
      >
        <Icon className="size-5" />
      </div>
      <div className="min-w-0">
        <p className="text-[11px] font-medium text-muted-foreground leading-none mb-1.5 uppercase">
          {label}
        </p>
        <h4 className="text-[18px] font-black text-foreground leading-none">
          {value}
        </h4>
      </div>
    </div>
  )
}

function PresetButton({
  label,
  active,
  onClick,
}: Readonly<{
  label: string
  active?: boolean
  onClick: () => void
}>) {
  return (
    <Button
      variant="outline"
      size="sm"
      className={cn(
        'h-7 rounded-full px-3 text-[11px] font-bold shadow-none transition-all',
        active
          ? 'border-primary bg-primary text-primary-foreground hover:bg-primary/90 hover:text-primary-foreground'
          : 'border-primary/20 bg-primary/[0.06] text-muted-foreground hover:border-primary/30 hover:bg-primary/10 hover:text-primary'
      )}
      onClick={onClick}
    >
      {label}
    </Button>
  )
}

function BoundFilterSelect({
  id,
  label,
  value,
  options,
  allLabel,
  loading,
  formatOption,
  onChange,
}: Readonly<{
  id: string
  label: string
  value: string
  options: string[]
  allLabel: string
  loading?: boolean
  formatOption?: (value: string) => string
  onChange: (value: string) => void
}>) {
  const emptyValue = `${FILTER_EMPTY_VALUE_PREFIX}-${id}`
  const currentLabel = value
    ? compactOption(formatOption ? formatOption(value) : value, 28)
    : allLabel

  return (
    <div className="space-y-1">
      <Label htmlFor={id} className={FIELD_LABEL}>
        {label}
      </Label>
      <Select
        value={value || FILTER_ALL_VALUE}
        onValueChange={(next) => {
          if (next === FILTER_ALL_VALUE) onChange('')
          else if (!next.startsWith(FILTER_EMPTY_VALUE_PREFIX)) onChange(next)
        }}
      >
        <SelectTrigger
          id={id}
          aria-label={label}
          className="h-9 rounded-lg border-border/60 bg-background/70 text-left text-xs font-medium text-foreground shadow-none hover:border-primary/30 hover:bg-card focus-visible:ring-primary/20"
        >
          <span className="truncate">{currentLabel}</span>
        </SelectTrigger>
        <SelectContent className="max-h-72 rounded-xl border-border/60 bg-card text-foreground shadow-lg">
          <SelectItem value={FILTER_ALL_VALUE} className="text-xs font-medium">
            {allLabel}
          </SelectItem>
          {options.map((option) => (
            <SelectItem
              key={option}
              value={option}
              className="text-xs font-medium"
            >
              <span className="flex min-w-0 flex-col gap-0.5">
                <span className="truncate">
                  {compactOption(formatOption ? formatOption(option) : option)}
                </span>
                {formatOption && formatOption(option) !== option && (
                  <span className="truncate font-mono text-[10px] font-normal text-muted-foreground">
                    {compactOption(option, 56)}
                  </span>
                )}
              </span>
            </SelectItem>
          ))}
          {!options.length && (
            <SelectItem
              value={emptyValue}
              disabled
              className="text-xs text-muted-foreground"
            >
              {loading ? '正在加载后端选项' : '暂无后端选项'}
            </SelectItem>
          )}
        </SelectContent>
      </Select>
    </div>
  )
}

// --- Main Component ---

export default function AuditLogsPage() {
  return (
    <TenantPermissionGate
      permission={TENANT_PERMISSIONS.AUDIT_READ}
      pageName="审计日志"
    >
      <AuditLogsPageContent />
    </TenantPermissionGate>
  )
}

function AuditLogsPageContent() {
  const t = useTranslations('AuditPage')
  const [skip, setSkip] = useState(0)
  const [limit, setLimit] =
    useState<(typeof AUDIT_PAGE_SIZE_OPTIONS)[number]>(20)

  const [filters, setFilters] = useState<AuditFilters>(EMPTY_AUDIT_FILTERS)

  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [showAdvanced, setShowAdvanced] = useState(true)
  const [selectedIds, setSelectedIds] = useState<string[]>([])
  const [deletingScope, setDeletingScope] = useState<string | null>(null)
  const tenantAccess = useTenantAccess()
  const canManageAudit = tenantAccessAllows(
    tenantAccess.data,
    TENANT_PERMISSIONS.AUDIT_MANAGE
  )

  const presets = useMemo(
    () => [
      {
        label: t('presets.accessReviewDaily'),
        action: 'compliance.access_review.daily',
      },
      {
        label: t('presets.indexAuditDaily'),
        action: 'observability.index_audit.daily',
      },
      {
        label: t('presets.evidenceDriftDaily'),
        action: 'evidence.drift_audit.daily',
      },
      {
        label: t('presets.accessGraphExport'),
        action: 'compliance.access_graph.export',
      },
    ],
    [t]
  )

  const auditQueryParams = useMemo(() => {
    const params: AuditLogQueryParams = { skip, limit }
    for (const [key, value] of Object.entries(filters)) {
      const trimmed = toTrimmedPrimitiveString(value)
      if (trimmed) {
        params[key as AuditFilterKey] = trimmed
      }
    }
    return params
  }, [filters, skip, limit])

  const logsQuery = useQuery<AuditLogListResponse>({
    queryKey: queryKeys.audit.logs(auditQueryParams),
    queryFn: () => auditApi.listLogs(auditQueryParams),
    placeholderData: (previousData) => previousData,
  })

  const filterOptionsQuery = useQuery<AuditLogItem[]>({
    queryKey: queryKeys.audit.filterOptions,
    queryFn: async () => {
      try {
        const firstPage = await auditApi.listLogs({ skip: 0, limit: AUDIT_FILTER_OPTION_PAGE_SIZE })
        const pageCount = Math.min(
          Math.ceil((firstPage.total || 0) / AUDIT_FILTER_OPTION_PAGE_SIZE),
          AUDIT_FILTER_OPTION_MAX_PAGES
        )
        const remainingPages = await Promise.all(
          Array.from({ length: Math.max(0, pageCount - 1) }, (_, index) => {
            const pageIndex = index + 1
            return auditApi.listLogs({
              skip: pageIndex * AUDIT_FILTER_OPTION_PAGE_SIZE,
              limit: AUDIT_FILTER_OPTION_PAGE_SIZE,
            })
          })
        )
        return [
          ...(firstPage.items || []),
          ...remainingPages.flatMap((page) => page.items || []),
        ]
      } catch {
        return []
      }
    },
    staleTime: 5 * 60 * 1000,
  })

  const resp = logsQuery.data ?? null
  const filterSeedItems = useMemo(
    () => filterOptionsQuery.data ?? [],
    [filterOptionsQuery.data]
  )
  const loading = logsQuery.isFetching
  const filterOptionsLoading = filterOptionsQuery.isFetching
  const loadErrorMessage = logsQuery.error
    ? formatApiError(logsQuery.error, t('errors.loadLogs'))
    : ''

  const total = resp?.total || 0
  const page = Math.floor(skip / limit) + 1
  const totalPages = Math.max(1, Math.ceil(total / limit))
  const displayPage = Math.min(page, totalPages)
  const visibleLogIds = useMemo(
    () => (resp?.items || []).map((item) => item.id),
    [resp?.items]
  )
  const selectedSet = useMemo(() => new Set(selectedIds), [selectedIds])
  const selectedVisibleCount = visibleLogIds.filter((id) =>
    selectedSet.has(id)
  ).length
  const allVisibleSelected =
    visibleLogIds.length > 0 && selectedVisibleCount === visibleLogIds.length
  const activeFilterCount = Object.values(filters).filter((v) =>
    toTrimmedPrimitiveString(v)
  ).length
  const optionSourceItems = useMemo(
    () => [...filterSeedItems, ...(resp?.items || [])],
    [filterSeedItems, resp?.items]
  )
  const actionOptions = useMemo(
    () =>
      withCurrentOption(
        uniqueAuditValues(optionSourceItems, 'action'),
        filters.action
      ),
    [optionSourceItems, filters.action]
  )
  const actorOptions = useMemo(
    () =>
      withCurrentOption(
        uniqueAuditValues(optionSourceItems, 'actor_id'),
        filters.actor_id
      ),
    [optionSourceItems, filters.actor_id]
  )
  const requestOptions = useMemo(
    () =>
      withCurrentOption(
        uniqueAuditValues(optionSourceItems, 'request_id'),
        filters.request_id
      ),
    [optionSourceItems, filters.request_id]
  )
  const resourceTypeOptions = useMemo(
    () =>
      withCurrentOption(
        uniqueAuditValues(optionSourceItems, 'resource_type'),
        filters.resource_type
      ),
    [optionSourceItems, filters.resource_type]
  )
  const resourceIdOptions = useMemo(
    () =>
      withCurrentOption(
        uniqueAuditValues(optionSourceItems, 'resource_id'),
        filters.resource_id
      ),
    [optionSourceItems, filters.resource_id]
  )
  const auditOperationFilters = useMemo(() => {
    const out: Record<string, string> = {}
    for (const [key, value] of Object.entries(filters)) {
      const trimmed = toTrimmedPrimitiveString(value)
      if (trimmed) out[key] = trimmed
    }
    return out
  }, [filters])

  const setFilterValue = useCallback((key: AuditFilterKey, value: string) => {
    setSkip(0)
    setFilters((current) => ({ ...current, [key]: value }))
  }, [])

  const handleCopy = async (text: string) => {
    try {
      await navigator.clipboard.writeText(text)
      toast.success(t('toasts.copySuccess'))
    } catch {
      toast.error(t('toasts.copyFailure'))
    }
  }

  const handlePageSizeChange = (value: string) => {
    const next = Number(value)
    const safeLimit = AUDIT_PAGE_SIZE_OPTIONS.includes(
      next as (typeof AUDIT_PAGE_SIZE_OPTIONS)[number]
    )
      ? (next as (typeof AUDIT_PAGE_SIZE_OPTIONS)[number])
      : 20
    setLimit(safeLimit)
    setSkip(0)
  }

  const refetchAuditLogs = async () => {
    await Promise.all([logsQuery.refetch(), filterOptionsQuery.refetch()])
  }

  const toggleSelectAllVisible = (checked: boolean) => {
    setSelectedIds((current) => {
      const next = new Set(current)
      for (const id of visibleLogIds) {
        if (checked) next.add(id)
        else next.delete(id)
      }
      return Array.from(next)
    })
  }

  const toggleSelectLog = (id: string, checked: boolean) => {
    setSelectedIds((current) => {
      const next = new Set(current)
      if (checked) next.add(id)
      else next.delete(id)
      return Array.from(next)
    })
  }

  const handleDeleteLog = async (id: string) => {
    setDeletingScope(id)
    try {
      const result = await auditApi.deleteLog(id)
      setSelectedIds((current) => current.filter((value) => value !== id))
      toast.success(`已删除 ${result.deleted} 条审计日志`)
      await refetchAuditLogs()
    } catch (error) {
      toast.error(formatApiError(error, '删除审计日志失败'))
    } finally {
      setDeletingScope(null)
    }
  }

  const handleBulkDeleteLogs = async () => {
    if (selectedIds.length === 0) return
    setDeletingScope('bulk')
    try {
      const ids = [...selectedIds]
      const result = await auditApi.bulkDeleteLogs(ids)
      setSelectedIds([])
      toast.success(`已删除 ${result.deleted} 条审计日志`)
      await refetchAuditLogs()
    } catch (error) {
      toast.error(formatApiError(error, '批量删除审计日志失败'))
    } finally {
      setDeletingScope(null)
    }
  }

  return (
    <AppFrame>
      <PageScaffold
        title={t('title')}
        description={t('description')}
        iconImage="audit-log"
        icon={ShieldCheck}
        iconColor="text-primary"
        size="full"
        bodyClassName="bg-transparent"
        actions={
          <div className="flex items-center gap-3">
            <Button
              variant="outline"
              size="sm"
              className="h-8 gap-2 rounded-lg text-[12px] font-bold border-border/60 bg-card/80"
              onClick={() => {
                logsQuery.refetch()
                filterOptionsQuery.refetch()
              }}
            >
              <RefreshCw
                className={cn('size-3.5', loading && 'animate-spin')}
              />
              {t('actions.refresh')}
            </Button>
            <Button
              variant="outline"
              size="icon"
              className="h-8 w-8 rounded-lg border-border/60 bg-card/80"
              aria-label="清空审计筛选"
              onClick={() => {
                setFilters({ ...EMPTY_AUDIT_FILTERS })
                setSkip(0)
              }}
            >
              <FilterX className="size-4" />
            </Button>
          </div>
        }
      >
        <div className="flex flex-col gap-6 pb-20">
          {/* Top HUD Cards */}
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
            <HUDTile
              icon={FileJson}
              label={t('strip.total')}
              value={total}
              tone="blue"
            />
            <HUDTile
              icon={LayoutGrid}
              label={t('strip.currentPage')}
              value={`${page}/${totalPages}`}
              tone="green"
            />
            <HUDTile
              icon={Filter}
              label={t('strip.filters')}
              value={activeFilterCount}
              tone="purple"
            />
            <HUDTile
              icon={CheckCircle2}
              label={t('strip.status')}
              value={
                loading
                  ? t('strip.loading')
                  : total > 0
                    ? t('strip.ready')
                    : t('strip.empty')
              }
              tone={loading ? 'slate' : 'green'}
            />
          </div>

          {/* Filter Console */}
          <div className={cn(AUDIT_PANEL_CLASS, 'p-6')}>
            <div className="flex items-center justify-between mb-6">
              <div className="flex items-center gap-4">
                <span className="text-[11px] font-black uppercase text-muted-foreground">
                  {t('presets.quick')}
                </span>
                <div className="flex flex-wrap gap-2">
                  {presets.map((p) => (
                    <PresetButton
                      key={p.action}
                      label={p.label}
                      active={filters.action === p.action}
                      onClick={() => setFilterValue('action', p.action)}
                    />
                  ))}
                </div>
              </div>
              <Button
                variant="ghost"
                size="sm"
                className="h-7 gap-1.5 text-[11px] font-bold text-muted-foreground hover:text-primary"
                onClick={() => setShowAdvanced(!showAdvanced)}
              >
                {showAdvanced ? t('filters.more') : '更多筛选'}
                {showAdvanced ? (
                  <ChevronUp className="size-3" />
                ) : (
                  <ChevronDown className="size-3" />
                )}
              </Button>
            </div>

            {showAdvanced && (
              <div className="grid gap-6 md:grid-cols-3">
                <BoundFilterSelect
                  id="audit-action-filter"
                  label={t('filters.action')}
                  value={filters.action}
                  options={actionOptions}
                  allLabel="全部动作"
                  loading={filterOptionsLoading}
                  formatOption={formatAuditAction}
                  onChange={(value) => setFilterValue('action', value)}
                />
                <BoundFilterSelect
                  id="audit-actor-filter"
                  label="操作者"
                  value={filters.actor_id}
                  options={actorOptions}
                  allLabel="全部操作者"
                  loading={filterOptionsLoading}
                  onChange={(value) => setFilterValue('actor_id', value)}
                />
                <BoundFilterSelect
                  id="audit-request-filter"
                  label="请求 ID"
                  value={filters.request_id}
                  options={requestOptions}
                  allLabel="全部请求"
                  loading={filterOptionsLoading}
                  onChange={(value) => setFilterValue('request_id', value)}
                />
                <BoundFilterSelect
                  id="audit-resource-type-filter"
                  label="资源类型"
                  value={filters.resource_type}
                  options={resourceTypeOptions}
                  allLabel="全部资源类型"
                  loading={filterOptionsLoading}
                  formatOption={formatAuditResourceType}
                  onChange={(value) => setFilterValue('resource_type', value)}
                />
                <BoundFilterSelect
                  id="audit-resource-id-filter"
                  label="资源 ID"
                  value={filters.resource_id}
                  options={resourceIdOptions}
                  allLabel="全部资源"
                  loading={filterOptionsLoading}
                  onChange={(value) => setFilterValue('resource_id', value)}
                />
                <div className="grid grid-cols-2 gap-3">
                  <div className="space-y-1">
                    <Label className={FIELD_LABEL}>{t('filters.since')}</Label>
                    <Input
                      type="datetime-local"
                      value={filters.since}
                      onChange={(e) => setFilterValue('since', e.target.value)}
                      className="h-9 rounded-lg bg-background/70 border-border/60 text-[10px]"
                    />
                  </div>
                  <div className="space-y-1">
                    <Label className={FIELD_LABEL}>{t('filters.until')}</Label>
                    <Input
                      type="datetime-local"
                      value={filters.until}
                      onChange={(e) => setFilterValue('until', e.target.value)}
                      className="h-9 rounded-lg bg-background/70 border-border/60 text-[10px]"
                    />
                  </div>
                </div>
              </div>
            )}

            <AuditRetentionPanel
              filters={auditOperationFilters}
              activeFilterCount={activeFilterCount}
              total={total}
              onAfterPurge={() => {
                logsQuery.refetch()
                filterOptionsQuery.refetch()
              }}
            />
          </div>

          {/* Table Canvas */}
          <div className={cn(AUDIT_PANEL_CLASS, 'overflow-hidden')}>
            <div className="flex items-center justify-between border-b border-border/50 bg-card/80 px-6 py-4">
              <div>
                <h2 className="text-[15px] font-semibold text-foreground">
                  审计事件
                </h2>
                <p className="mt-1 text-[12px] text-muted-foreground">
                  按后端审计日志展示时间、操作者、事件名称、资源/租户与操作明细。
                </p>
              </div>
              <div className="flex flex-wrap items-center justify-end gap-2">
                {selectedIds.length > 0 && (
                  <ConfirmDialog
                    title="确认批量删除审计日志"
                    description={`将真实删除已选 ${selectedIds.length} 条审计日志。删除后会新增一条批量删除审计记录。`}
                    confirmLabel="删除已选"
                    confirmVariant="destructive"
                    confirmDisabled={deletingScope === 'bulk' || !canManageAudit}
                    onConfirm={handleBulkDeleteLogs}
                  >
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={!canManageAudit || Boolean(deletingScope)}
                      className="h-8 gap-1.5 rounded-lg border-destructive/20 bg-destructive/10 px-3 text-[11px] font-bold text-destructive shadow-none hover:bg-destructive/15 hover:text-destructive"
                    >
                      <Trash2 className="size-3.5" />
                      删除已选 {selectedIds.length}
                    </Button>
                  </ConfirmDialog>
                )}
                <div className="rounded-full border border-border/60 bg-muted/40 px-3 py-1 text-[11px] font-semibold text-muted-foreground">
                  共 {total} 条
                </div>
              </div>
            </div>
            <div className="max-h-[640px] overflow-auto">
              <table className="w-full border-collapse">
                <thead className="sticky top-0 z-10">
                  <tr className={AUDIT_TABLE_HEAD_CLASS}>
                    <th className="w-10 px-6 py-3.5">
                      <input
                        type="checkbox"
                        aria-label="选择当前页审计日志"
                        disabled={!canManageAudit || visibleLogIds.length === 0}
                        checked={allVisibleSelected}
                        onChange={(event) =>
                          toggleSelectAllVisible(event.currentTarget.checked)
                        }
                        className="size-3.5 rounded border-border text-primary accent-[hsl(var(--primary))]"
                      />
                    </th>
                    <th className={AUDIT_TABLE_HEADER_CLASS}>
                      时间
                    </th>
                    <th className={AUDIT_TABLE_HEADER_CLASS}>
                      操作者
                    </th>
                    <th className={AUDIT_TABLE_HEADER_CLASS}>
                      事件名称
                    </th>
                    <th className={AUDIT_TABLE_HEADER_CLASS}>
                      资源 / 租户
                    </th>
                    <th className={cn(AUDIT_TABLE_HEADER_CLASS, 'text-right')}>
                      操作
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border/40">
                  {resp ? (
                    resp.items.length > 0 ? (
                      resp.items.map((log) => (
                        <AuditRow
                          key={log.id}
                          log={log}
                          expanded={expandedId === log.id}
                          selected={selectedSet.has(log.id)}
                          canDelete={canManageAudit}
                          deleting={deletingScope === log.id}
                          onSelectChange={(checked) =>
                            toggleSelectLog(log.id, checked)
                          }
                          onToggle={() =>
                            setExpandedId(expandedId === log.id ? null : log.id)
                          }
                          onCopy={handleCopy}
                          onDelete={() => handleDeleteLog(log.id)}
                        />
                      ))
                    ) : (
                      <tr>
                        <td colSpan={6} className="py-20">
                          <EmptyState
                            icon={ScrollText}
                            title={t('emptyState.title')}
                            description={t('emptyState.description')}
                          />
                        </td>
                      </tr>
                    )
                  ) : (
                    <tr>
                      <td
                        colSpan={6}
                        className="p-12 text-center text-xs text-muted-foreground font-medium"
                      >
                        {loading ? (
                          <RefreshCw className="size-5 animate-spin mx-auto mb-2" />
                        ) : (
                          loadErrorMessage || t('alerts.unableToLoad')
                        )}
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
            <div className="flex flex-col gap-3 border-t border-border/50 bg-muted/30 px-6 py-3 sm:flex-row sm:items-center sm:justify-between">
              <div className="flex items-center gap-2 text-[12px] font-medium text-muted-foreground">
                <span>共 {total} 条</span>
                <span className="text-muted-foreground/45">/</span>
                <span>每页</span>
                <Select
                  value={String(limit)}
                  onValueChange={handlePageSizeChange}
                >
                  <SelectTrigger className="h-8 w-[88px] rounded-lg border-border/60 bg-card text-[12px] font-semibold text-foreground shadow-none">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent className="rounded-xl border-border/60 bg-card">
                    {AUDIT_PAGE_SIZE_OPTIONS.map((size) => (
                      <SelectItem
                        key={size}
                        value={String(size)}
                        className="text-xs font-medium"
                      >
                        {size} 条
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="flex items-center justify-end gap-3">
                <Button
                  variant="outline"
                  size="sm"
                  className="h-8 gap-1 rounded-lg border-border/60 bg-card px-3 text-[11px] font-semibold shadow-none"
                  onClick={() => setSkip(Math.max(0, skip - limit))}
                  disabled={skip <= 0}
                >
                  <ChevronLeft className="size-3.5" /> 上一页
                </Button>
                <span className="min-w-[88px] rounded-lg border border-border/60 bg-card px-3 py-1.5 text-center text-[12px] font-semibold text-foreground">
                  第 {displayPage} / {totalPages} 页
                </span>
                <Button
                  variant="outline"
                  size="sm"
                  className="h-8 gap-1 rounded-lg border-border/60 bg-card px-3 text-[11px] font-semibold shadow-none"
                  onClick={() =>
                    setSkip(
                      Math.min(
                        Math.max(0, (totalPages - 1) * limit),
                        skip + limit
                      )
                    )
                  }
                  disabled={skip + limit >= total}
                >
                  下一页 <ChevronRight className="size-3.5" />
                </Button>
              </div>
            </div>
          </div>

          {/* Detailed Response Collapsible */}
          <details className="group border-t border-border/50 pt-6">
            <summary className="flex cursor-pointer list-none items-center justify-between text-muted-foreground hover:text-foreground transition-colors">
              <div className="flex items-center gap-3">
                <FileJson className="size-4" />
                <span className="text-[11px] font-black uppercase tracking-[0.2em]">
                  排障材料 (原始响应)
                </span>
              </div>
              <ChevronDown className="size-4 transition-transform group-open:rotate-180" />
            </summary>
            <div className="mt-6 grid grid-cols-1 md:grid-cols-2 gap-4">
              <pre className="p-5 rounded-2xl bg-foreground font-mono text-[11px] text-background/85 max-h-[300px] overflow-auto custom-scrollbar shadow-strong border border-border/60">
                {JSON.stringify(resp, null, 2)}
              </pre>
            </div>
          </details>
        </div>
      </PageScaffold>
    </AppFrame>
  )
}

function AuditRow({
  log,
  expanded,
  selected,
  canDelete,
  deleting,
  onSelectChange,
  onToggle,
  onCopy,
  onDelete,
}: Readonly<{
  log: AuditLogItem
  expanded: boolean
  selected: boolean
  canDelete: boolean
  deleting: boolean
  onSelectChange: (checked: boolean) => void
  onToggle: () => void
  onCopy: (s: string) => void
  onDelete: () => void | Promise<void>
}>) {
  const resource = [log.resource_type, log.resource_id]
    .filter(Boolean)
    .join(': ')
  const timestamp = formatAuditDateTime(log.created_at)
  const actionLabel = formatAuditAction(log.action)
  const resourceTypeLabel = formatAuditResourceType(log.resource_type)

  return (
    <>
      <tr
        className={cn(
          'hover:bg-primary/[0.035] transition-colors group cursor-pointer',
          expanded && 'bg-primary/[0.045]',
          selected && 'bg-primary/[0.065]'
        )}
      >
        <td className="px-6 py-4 align-top">
          <input
            type="checkbox"
            aria-label={`选择审计日志 ${log.id}`}
            disabled={!canDelete}
            checked={selected}
            onChange={(event) => onSelectChange(event.currentTarget.checked)}
            className="mt-1 size-3.5 rounded border-border text-primary accent-[hsl(var(--primary))]"
          />
        </td>
        <td className="px-6 py-4" onClick={onToggle}>
          <div className="flex flex-col">
            <span className="text-[12px] font-semibold text-foreground leading-none mb-1">
              {timestamp.date}
            </span>
            <span className="text-[10px] font-mono text-muted-foreground font-medium">
              {timestamp.time}
            </span>
          </div>
        </td>
        <td className="px-6 py-4" onClick={onToggle}>
          <div className="flex items-center gap-2">
            <div className="size-6 rounded-full bg-muted flex items-center justify-center text-[10px] font-black text-muted-foreground uppercase">
              {log.actor_id?.slice(0, 2) || '??'}
            </div>
            <div className="min-w-0">
              <div className="max-w-[220px] truncate font-mono text-[12px] font-medium text-foreground">
                {log.actor_id || 'system'}
              </div>
              {log.ip && (
                <div className="mt-0.5 font-mono text-[10px] text-muted-foreground">
                  {log.ip}
                </div>
              )}
            </div>
          </div>
        </td>
        <td className="px-6 py-4" onClick={onToggle}>
          <div className="max-w-[320px]">
            <div className="truncate text-[13px] font-semibold text-foreground">
              {actionLabel}
            </div>
            <div className="mt-1 truncate font-mono text-[10px] text-muted-foreground">
              {log.action}
            </div>
            {log.request_id && (
              <div className="mt-1 truncate font-mono text-[10px] text-muted-foreground">
                请求 {log.request_id}
              </div>
            )}
          </div>
        </td>
        <td className="px-6 py-4" onClick={onToggle}>
          <div className="max-w-[320px]">
            <div className="truncate text-[12px] font-semibold text-foreground">
              {log.resource_type ? resourceTypeLabel : '未绑定资源'}
            </div>
            {resource && (
              <div className="mt-1 truncate font-mono text-[10px] font-medium text-muted-foreground">
                {resource}
              </div>
            )}
            <div className="mt-1 truncate text-[10px] font-medium text-muted-foreground">
              租户 <span className="font-mono">{log.tenant_id || '-'}</span>
            </div>
          </div>
        </td>
        <td className="px-6 py-4 text-right">
          <div className="flex items-center justify-end gap-2">
            <Button
              variant="ghost"
              size="sm"
              className="h-7 rounded-lg px-2.5 text-[10px] font-semibold text-muted-foreground hover:bg-primary/10 hover:text-primary"
              onClick={onToggle}
            >
              {expanded ? '收起' : '详情'}
            </Button>
            <Button
              variant="outline"
              size="sm"
              className="h-7 gap-1.5 rounded-lg border-border/60 bg-card px-2.5 text-[10px] font-black shadow-none transition-all hover:border-primary/30 hover:text-primary"
              onClick={() => onCopy(JSON.stringify(log.details, null, 2))}
            >
              <FileJson className="size-3" /> JSON
            </Button>
            <ConfirmDialog
              title="确认删除审计日志"
              description="将真实删除这条审计日志。删除后会新增一条删除操作审计记录。"
              confirmLabel="删除"
              confirmVariant="destructive"
              confirmDisabled={!canDelete || deleting}
              onConfirm={onDelete}
            >
              <Button
                variant="outline"
                size="sm"
                disabled={!canDelete || deleting}
                className="h-7 gap-1.5 rounded-lg border-destructive/20 bg-destructive/10 px-2.5 text-[10px] font-black text-destructive shadow-none transition-all hover:bg-destructive/15 hover:text-destructive"
              >
                {deleting ? (
                  <RefreshCw className="size-3 animate-spin" />
                ) : (
                  <Trash2 className="size-3" />
                )}
                删除
              </Button>
            </ConfirmDialog>
          </div>
        </td>
      </tr>
      {expanded && (
        <tr className="bg-primary/[0.025]">
          <td colSpan={6} className="px-6 pb-6">
            <div className="rounded-xl border border-primary/15 bg-card p-4 shadow-inner relative group">
              <Button
                variant="ghost"
                size="icon"
                className="absolute right-2 top-2 size-6 opacity-0 transition-opacity group-hover:opacity-100"
                aria-label="复制审计日志 JSON"
                onClick={() => onCopy(JSON.stringify(log.details, null, 2))}
              >
                <Copy className="size-3" />
              </Button>
              <pre className="font-mono text-[11px] leading-relaxed text-foreground overflow-auto max-h-[300px] custom-scrollbar">
                {JSON.stringify(log.details, null, 2)}
              </pre>
            </div>
          </td>
        </tr>
      )}
    </>
  )
}
