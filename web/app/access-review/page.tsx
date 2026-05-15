'use client'

import { useMutation, useQuery } from '@tanstack/react-query'
import { useMemo, useState, type ReactNode } from 'react'
import { useTranslations } from 'next-intl'
import { toast } from 'sonner'
import {
  Download,
  RefreshCw,
  ShieldCheck,
  Users,
  Database,
  Files,
  Code,
  Activity,
  UserCheck,
  CheckCircle2,
  LayoutGrid,
  ChevronRight,
  type LucideIcon,
} from 'lucide-react'

import { TenantPermissionGate } from '@/components/auth/tenant-permission-gate'
import { AppFrame } from '@/components/app-frame'
import { PageScaffold } from '@/components/ui/page-scaffold'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'

import { auditApi } from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'
import { TENANT_PERMISSIONS } from '@/lib/tenant-permissions'
import { coerceOneOf } from '@/lib/one-of'
import { cn } from '@/lib/utils'
import { queryKeys } from '@/lib/query-keys'

type AccessGraphSummary = {
  schema?: string
  tenant_id?: string
  generated_at?: string
  group_count?: number
  group_member_count?: number
  dataset_count?: number
  dataset_permission_counts?: Record<string, number>
  dataset_member_allowlist_count?: number
  dataset_group_allowlist_count?: number
  document_count?: number
  document_access_mode_counts?: Record<string, number>
  document_member_allowlist_count?: number
  document_group_allowlist_count?: number
}

function safeInt(v: unknown) {
  const n = Number(v ?? 0)
  return Number.isFinite(n) ? Math.max(0, Math.floor(n)) : 0
}

function safeTs() {
  const d = new Date()
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}-${pad(d.getHours())}${pad(d.getMinutes())}${pad(d.getSeconds())}`
}

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  globalThis.window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}

const EXPORT_FORMAT_VALUES = ['ndjson', 'json'] as const

function permissionLabel(key: string): string {
  if (key === 'all_team_members') return '全员可访问'
  if (key === 'partial_members') return '部分成员'
  if (key === 'only_me') return '仅自己'
  if (key === 'inherit') return '继承'
  if (key === 'unknown') return '未知'
  return key
}

// --- Specialized Components ---

const HUD_TONE_CLASSES = {
  slate: 'bg-slate-50 text-slate-400 border-slate-100',
  blue: 'bg-blue-50 text-blue-600 border-blue-100',
  green: 'bg-emerald-50 text-emerald-600 border-emerald-100',
} as const

function HUDTile({
  icon: Icon,
  label,
  value,
  tone = 'slate',
}: {
  icon: LucideIcon
  label: string
  value: string | number
  tone?: keyof typeof HUD_TONE_CLASSES
}) {
  const toneClasses = HUD_TONE_CLASSES[tone] || HUD_TONE_CLASSES.slate

  return (
    <div className="bg-card rounded-2xl border border-slate-200/60 p-5 flex items-center gap-4 shadow-[0_1px_2px_rgba(0,0,0,0.01)]">
      <div
        className={cn(
          'size-10 rounded-xl flex items-center justify-center border',
          toneClasses
        )}
      >
        <Icon className="size-5" />
      </div>
      <div className="min-w-0">
        <p className="text-[11px] font-medium text-slate-400 leading-none mb-1.5 uppercase">
          {label}
        </p>
        <h4 className="text-[18px] font-black text-slate-900 leading-none">
          {value}
        </h4>
      </div>
    </div>
  )
}

function MetricItem({
  icon: Icon,
  label,
  value,
}: {
  icon: LucideIcon
  label: string
  value: number
}) {
  return (
    <div className="flex flex-col items-center justify-center p-4 rounded-xl border border-transparent hover:border-slate-100 hover:bg-slate-50/50 transition-all group">
      <div className="size-10 rounded-full bg-slate-50 flex items-center justify-center text-slate-400 group-hover:bg-blue-50 group-hover:text-blue-500 transition-colors mb-2 border border-slate-100">
        <Icon className="size-5" />
      </div>
      <p className="text-[10px] font-bold text-slate-400 uppercase text-center leading-tight mb-1">
        {label}
      </p>
      <p className="text-[16px] font-black text-slate-900 leading-none">
        {value}
      </p>
    </div>
  )
}

function DistributionBar({
  label,
  value,
  max,
}: {
  label: string
  value: number
  max: number
}) {
  const percentage = max > 0 ? (value / max) * 100 : 0
  return (
    <div className="flex flex-col gap-2 group">
      <div className="flex items-center justify-between text-[11px] font-bold">
        <span className="text-slate-600 group-hover:text-slate-900 transition-colors">
          {label}
        </span>
        <span className="text-slate-400 font-mono">{value}</span>
      </div>
      <div className="h-1.5 w-full bg-slate-100 rounded-full overflow-hidden">
        <div
          className="h-full bg-blue-500 rounded-full transition-all duration-500 ease-out shadow-[0_0_8px_rgba(59,130,246,0.3)]"
          style={{ width: `${percentage}%` }}
        />
      </div>
    </div>
  )
}

// --- Main Page ---

export default function AccessReviewPage() {
  return (
    <TenantPermissionGate
      permission={TENANT_PERMISSIONS.AUDIT_READ}
      pageName="访问审查"
    >
      <AccessReviewPageContent />
    </TenantPermissionGate>
  )
}

function AccessReviewPageContent() {
  const t = useTranslations('AccessReviewPage')

  const [exportFormat, setExportFormat] = useState<'ndjson' | 'json'>('ndjson')
  const [includeSensitive, setIncludeSensitive] = useState(false)
  const [gzip, setGzip] = useState(true)
  const [limit, setLimit] = useState(10000)

  const [exportPages, setExportPages] = useState(0)

  const summaryQuery = useQuery<AccessGraphSummary | null>({
    queryKey: queryKeys.accessReview.summary,
    retry: false,
    queryFn: async () => {
      try {
        const data = await auditApi.getAccessGraphSummary()
        return (data || null) as AccessGraphSummary | null
      } catch (err: unknown) {
        toast.error(formatApiError(err, t('errors.loadSummary')))
        throw err
      }
    },
  })

  const downloadMutation = useMutation({
    mutationFn: async () => {
      setExportPages(0)
      if (exportFormat === 'json') {
        const { blob } = await auditApi.exportAccessGraphPage({
          limit,
          export_format: 'json',
          include_sensitive: includeSensitive,
          gzip,
        })
        downloadBlob(blob, `access-graph.${safeTs()}.json`)
        return { format: 'json' as const, pages: 1 }
      }

      const blobs: Blob[] = []
      let cursor: {
        after_kind: string
        after_created_at: string
        after_id: string
      } | null = null
      let pages = 0
      while (true) {
        pages += 1
        setExportPages(pages)
        const res = await auditApi.exportAccessGraphPage({
          limit,
          export_format: 'ndjson',
          include_sensitive: includeSensitive,
          gzip,
          ...(cursor || {}),
        })
        blobs.push(res.blob)
        if (!res.nextCursor || pages >= 50) break
        cursor = res.nextCursor
      }
      downloadBlob(
        new Blob(blobs, { type: 'application/x-ndjson' }),
        `access-graph.${safeTs()}.ndjson`
      )
      return { format: 'ndjson' as const, pages }
    },
    onSuccess: ({ format, pages }) => {
      if (format === 'json') {
        toast.success(t('toasts.downloadJson'))
        return
      }
      toast.success(t('toasts.downloadPages', { pages }))
    },
    onError: (err: unknown) => {
      toast.error(formatApiError(err, t('errors.export')))
    },
  })

  const summary = summaryQuery.data
  const loadingSummary = summaryQuery.isFetching
  const exporting = downloadMutation.isPending
  const permissionCounts = summary?.dataset_permission_counts || {}
  const accessModeCounts = summary?.document_access_mode_counts || {}

  return (
    <AppFrame>
      <PageScaffold
        title={t('title')}
        description={t('description')}
        iconImage="access-review"
        icon={ShieldCheck}
        iconColor="text-blue-600"
        size="full"
        bodyClassName="bg-slate-50/50"
        actions={
          <div className="flex items-center gap-3">
            <Button
              variant="outline"
              size="sm"
              className="h-8 gap-1.5 rounded-lg text-[12px] font-bold border-slate-200 bg-card"
              onClick={() => {
                void summaryQuery.refetch()
              }}
            >
              <RefreshCw
                className={cn('size-3.5', loadingSummary && 'animate-spin')}
              />
              {t('actions.refresh')}
            </Button>
            <Button
              size="sm"
              className="h-8 gap-1.5 rounded-lg text-[12px] font-bold bg-blue-600 shadow-lg shadow-blue-900/20"
              onClick={() => downloadMutation.mutate()}
              disabled={exporting}
            >
              <Download className="size-3.5" />
              {t('actions.export')}
            </Button>
          </div>
        }
      >
        <div className="flex flex-col gap-6">
          {/* Top HUD Strip */}
          <div className="grid grid-cols-1 md:grid-cols-3 lg:grid-cols-5 gap-4">
            <HUDTile
              icon={Users}
              label={t('strip.groups')}
              value={safeInt(summary?.group_count)}
              tone="blue"
            />
            <HUDTile
              icon={Database}
              label={t('strip.datasets')}
              value={safeInt(summary?.dataset_count)}
              tone="blue"
            />
            <HUDTile
              icon={Files}
              label={t('strip.docs')}
              value={safeInt(summary?.document_count)}
              tone="blue"
            />
            <HUDTile
              icon={Code}
              label={t('strip.format')}
              value={exportFormat.toUpperCase()}
              tone="slate"
            />
            <HUDTile
              icon={Activity}
              label={t('strip.status')}
              value={
                exporting
                  ? t('strip.processing', { pages: exportPages })
                  : t('strip.idle')
              }
              tone={exporting ? 'green' : 'slate'}
            />
          </div>

          {/* Summary Panel */}
          <div className="bg-card rounded-2xl border border-slate-200/60 shadow-sm p-6">
            <div className="flex items-center justify-between mb-2">
              <h3 className="text-[14px] font-black text-slate-900 uppercase">
                {t('summary.heading')}
              </h3>
              <span className="text-[10px] font-mono font-bold text-slate-300">
                {summary?.generated_at
                  ? t('summary.generatedAt', {
                      timestamp: summary.generated_at,
                    })
                  : ''}
              </span>
            </div>
            <p className="text-[11px] text-slate-400 font-medium mb-8 max-w-3xl">
              {t('summary.description')}
            </p>

            {loadingSummary ? (
              <div className="grid grid-cols-2 md:grid-cols-7 gap-4">
                {[1, 2, 3, 4, 5, 6, 7].map((i) => (
                  <Skeleton key={i} className="h-24 rounded-xl bg-slate-50" />
                ))}
              </div>
            ) : (
              <div className="grid grid-cols-2 md:grid-cols-7 gap-4">
                <MetricItem
                  icon={Users}
                  label={t('summary.stats.groups')}
                  value={safeInt(summary?.group_count)}
                />
                <MetricItem
                  icon={UserCheck}
                  label={t('summary.stats.members')}
                  value={safeInt(summary?.group_member_count)}
                />
                <MetricItem
                  icon={Database}
                  label={t('summary.stats.datasets')}
                  value={safeInt(summary?.dataset_count)}
                />
                <MetricItem
                  icon={Files}
                  label={t('summary.stats.docs')}
                  value={safeInt(summary?.document_count)}
                />
                <MetricItem
                  icon={CheckCircle2}
                  label={t('summary.stats.datasetMemberWhitelist')}
                  value={safeInt(summary?.dataset_member_allowlist_count)}
                />
                <MetricItem
                  icon={CheckCircle2}
                  label={t('summary.stats.datasetOwnerWhitelist')}
                  value={safeInt(summary?.dataset_group_allowlist_count)}
                />
                <MetricItem
                  icon={CheckCircle2}
                  label={t('summary.stats.docOwnerWhitelist')}
                  value={safeInt(summary?.document_member_allowlist_count)}
                />
              </div>
            )}

            {/* Distribution Charts */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-10 mt-10 pt-10 border-t border-slate-50">
              <div className="space-y-6">
                <div className="flex items-center justify-between">
                  <h4 className="text-[12px] font-black text-slate-800 uppercase">
                    {t('stats.datasetDistribution')}
                  </h4>
                  <div className="flex items-center gap-4 text-[10px] font-bold text-slate-300 uppercase">
                    <span>{t('stats.dimension')}</span>
                    <span>{t('stats.count')}</span>
                  </div>
                </div>
                <div className="space-y-5">
                  <DistributionBar
                    label={permissionLabel('all_team_members')}
                    value={safeInt(permissionCounts.all_team_members)}
                    max={safeInt(summary?.dataset_count)}
                  />
                  <DistributionBar
                    label={permissionLabel('partial_members')}
                    value={safeInt(permissionCounts.partial_members)}
                    max={safeInt(summary?.dataset_count)}
                  />
                  <DistributionBar
                    label={permissionLabel('only_me')}
                    value={safeInt(permissionCounts.only_me)}
                    max={safeInt(summary?.dataset_count)}
                  />
                </div>
              </div>

              <div className="space-y-6">
                <div className="flex items-center justify-between">
                  <h4 className="text-[12px] font-black text-slate-800 uppercase">
                    {t('stats.documentDistribution')}
                  </h4>
                  <div className="flex items-center gap-4 text-[10px] font-bold text-slate-300 uppercase">
                    <span>{t('stats.dimension')}</span>
                    <span>{t('stats.count')}</span>
                  </div>
                </div>
                <div className="space-y-5">
                  {Object.entries(accessModeCounts).map(([k, v]) => (
                    <DistributionBar
                      key={k}
                      label={permissionLabel(k)}
                      value={safeInt(v)}
                      max={safeInt(summary?.document_count)}
                    />
                  ))}
                </div>
              </div>
            </div>
          </div>

          {/* Export Config Panel */}
          <div className="bg-card rounded-2xl border border-slate-200/60 shadow-sm p-8">
            <h3 className="text-[14px] font-black text-slate-900 uppercase mb-2">
              {t('export.heading')}
            </h3>
            <p className="text-[11px] text-slate-400 font-medium mb-8 max-w-3xl leading-relaxed">
              {t('export.description')}
            </p>

            <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 items-end">
              <div className="lg:col-span-4 space-y-2">
                <Label className="text-[10px] font-black uppercase tracking-[0.2em] text-slate-400">
                  {t('export.formatLabel')}
                </Label>
                <Select
                  value={exportFormat}
                  onValueChange={(v) =>
                    setExportFormat(coerceOneOf(EXPORT_FORMAT_VALUES, v, 'ndjson'))
                  }
                >
                  <SelectTrigger className="h-10 rounded-xl border-slate-200 bg-slate-50/50 font-bold text-[13px] shadow-none">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="ndjson">
                      {t('export.formatOptions.ndjson')}
                    </SelectItem>
                    <SelectItem value="json">
                      {t('export.formatOptions.json')}
                    </SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="lg:col-span-4 space-y-2">
                <Label className="text-[10px] font-black uppercase tracking-[0.2em] text-slate-400">
                  {t('export.limitLabel')}
                </Label>
                <Input
                  type="number"
                  value={limit}
                  onChange={(e) => setLimit(safeInt(e.target.value))}
                  className="h-10 rounded-xl border-slate-200 bg-slate-50/50 font-mono font-bold shadow-none"
                />
              </div>
              <div className="lg:col-span-4 flex items-center justify-between p-4 rounded-xl border border-slate-100 bg-slate-50/30">
                <div className="flex flex-col">
                  <span className="text-[12px] font-bold text-slate-700">
                    {t('export.gzipLabel')}
                  </span>
                  <span className="text-[9px] font-medium text-slate-400">
                    {t('export.gzipDescription')}
                  </span>
                </div>
                <Switch checked={gzip} onCheckedChange={setGzip} />
              </div>
            </div>

            <div className="mt-6 flex items-center justify-between p-5 rounded-2xl border border-slate-100 bg-slate-50/10">
              <div className="flex flex-col">
                <span className="text-[12px] font-bold text-slate-700">
                  {t('export.includeSensitiveLabel')}
                </span>
                <span className="text-[10px] font-medium text-slate-400 max-w-2xl">
                  {t('export.includeSensitiveDescription')}
                </span>
              </div>
              <Switch
                checked={includeSensitive}
                onCheckedChange={setIncludeSensitive}
              />
            </div>
          </div>
        </div>
      </PageScaffold>
    </AppFrame>
  )
}
