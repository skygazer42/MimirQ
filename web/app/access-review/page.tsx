'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { useTranslations } from 'next-intl'
import { toast } from 'sonner'
import { Download, RefreshCw, ShieldCheck } from 'lucide-react'

import { AppFrame } from '@/components/app-frame'
import { PageScaffold } from '@/components/ui/page-scaffold'
import { Panel } from '@/components/ui/panel'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { Input } from '@/components/ui/input'
import { SystemDataStrip } from '@/components/ui/system-data-strip'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { StatCard, StatsGrid } from '@/components/ui/stats-card'

import { auditApi } from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'
import { coerceOneOf } from '@/lib/one-of'
import { cn, detachPromise } from '@/lib/utils'
import { systemDenseControls, systemPageTokens, systemWorkbenchTokens } from '@/components/ui/system-page-tokens'

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

const SUMMARY_SKELETON_KEYS = ['summary-1', 'summary-2', 'summary-3', 'summary-4', 'summary-5', 'summary-6', 'summary-7', 'summary-8', 'summary-9', 'summary-10']
const EXPORT_FORMAT_VALUES = ['ndjson', 'json'] as const
const DENSE_OUTLINE_BUTTON = systemDenseControls.outlineButton
const DENSE_PRIMARY_BUTTON = systemDenseControls.primaryButton
const DENSE_PANEL = systemWorkbenchTokens.panel
const DENSE_INPUT = systemDenseControls.input
const DENSE_SELECT_TRIGGER = systemDenseControls.selectTrigger

function permissionLabel(key: string): string {
  if (key === 'all_team_members') return '全员可访问'
  if (key === 'partial_members') return '部分成员'
  if (key === 'only_me') return '仅自己'
  if (key === 'inherit') return '继承'
  if (key === 'unknown') return '未知'
  return key
}

export default function AccessReviewPage() {
  const [summary, setSummary] = useState<AccessGraphSummary | null>(null)
  const [loadingSummary, setLoadingSummary] = useState(false)

  const [exportFormat, setExportFormat] = useState<'ndjson' | 'json'>('ndjson')
  const [includeSensitive, setIncludeSensitive] = useState(false)
  const [gzip, setGzip] = useState(true)
  const [limit, setLimit] = useState(10_000)

  const [exporting, setExporting] = useState(false)
  const [exportPages, setExportPages] = useState(0)
  const [exportBytes, setExportBytes] = useState(0)

  const t = useTranslations('AccessReviewPage')

  const permissionCounts = useMemo(() => {
    const m = summary?.dataset_permission_counts || {}
    return {
      all_team_members: safeInt(m.all_team_members),
      partial_members: safeInt(m.partial_members),
      only_me: safeInt(m.only_me),
    }
  }, [summary?.dataset_permission_counts])

  const accessModeCounts = useMemo(() => {
    const m = summary?.document_access_mode_counts || {}
    return {
      inherit: safeInt(m.inherit),
      partial_members: safeInt(m.partial_members),
      only_me: safeInt(m.only_me),
      all_team_members: safeInt(m.all_team_members),
      unknown: safeInt(m.unknown),
    }
  }, [summary?.document_access_mode_counts])

  const loadSummary = useCallback(async () => {
    setLoadingSummary(true)
    try {
      const data = await auditApi.getAccessGraphSummary()
      setSummary(data || null)
    } catch (err: any) {
      setSummary(null)
      toast.error(formatApiError(err, t('errors.loadSummary')))
    } finally {
      setLoadingSummary(false)
    }
  }, [t])

  useEffect(() => {
    detachPromise(loadSummary())
  }, [loadSummary])

  const handleDownload = useCallback(async () => {
    const cap = Math.max(1, Math.min(10_000, safeInt(limit)))
    const maxPages = 50
    const maxTotalBytes = 150 * 1024 * 1024

    setExporting(true)
    setExportPages(0)
    setExportBytes(0)

    try {
      if (exportFormat === 'json') {
        const { blob } = await auditApi.exportAccessGraphPage({
          limit: cap,
          export_format: 'json',
          include_sensitive: includeSensitive,
          gzip,
        })
        downloadBlob(blob, `access-graph.${safeTs()}.json`)
        toast.success(t('toasts.downloadJson'))
        return
      }

      const blobs: Blob[] = []
      let cursor: { after_kind: string; after_created_at: string; after_id: string } | null = null
      let pages = 0
      let bytes = 0

      while (true) {
        pages += 1
        const res = await auditApi.exportAccessGraphPage({
          limit: cap,
          export_format: 'ndjson',
          include_sensitive: includeSensitive,
          gzip,
          after_kind: cursor?.after_kind,
          after_created_at: cursor?.after_created_at,
          after_id: cursor?.after_id,
        })
        blobs.push(res.blob)
        bytes += safeInt((res.blob as any)?.size)

        setExportPages(pages)
        setExportBytes(bytes)

        if (!res.nextCursor) break
        cursor = res.nextCursor

        if (pages >= maxPages) {
        toast.warning(t('warnings.reachedPageLimit', { maxPages }))
          break
        }
        if (bytes >= maxTotalBytes) {
        toast.warning(t('warnings.reachedByteLimit'))
          break
        }
      }

      const out = new Blob(blobs, { type: 'application/x-ndjson' })
      downloadBlob(out, `access-graph.${safeTs()}.ndjson`)
      toast.success(t('toasts.downloadPages', { pages }))
    } catch (err: any) {
      toast.error(formatApiError(err, t('errors.export')))
    } finally {
      setExporting(false)
    }
  }, [exportFormat, gzip, includeSensitive, limit, t])

  const summaryStats = useMemo(() => {
    return {
      group_count: safeInt(summary?.group_count),
      group_member_count: safeInt(summary?.group_member_count),
      dataset_count: safeInt(summary?.dataset_count),
      dataset_member_allowlist_count: safeInt(summary?.dataset_member_allowlist_count),
      dataset_group_allowlist_count: safeInt(summary?.dataset_group_allowlist_count),
      document_count: safeInt(summary?.document_count),
      document_member_allowlist_count: safeInt(summary?.document_member_allowlist_count),
      document_group_allowlist_count: safeInt(summary?.document_group_allowlist_count),
    }
  }, [summary])

  const stripItems = useMemo(
    () => [
      { label: '组数量', value: summaryStats.group_count, mono: true },
      { label: '数据集', value: summaryStats.dataset_count, mono: true },
      { label: '文档', value: summaryStats.document_count, mono: true },
      { label: '导出格式', value: exportFormat.toUpperCase(), mono: true },
      {
        label: '导出状态',
        value: exporting ? `进行中 · ${exportPages} 页` : '空闲',
        tone: exporting ? 'warning' : 'default',
      },
    ],
    [summaryStats.group_count, summaryStats.dataset_count, summaryStats.document_count, exportFormat, exporting, exportPages]
  )

  return (
    <AppFrame>
      <div className="flex-1 flex flex-col overflow-hidden relative">
        <PageScaffold
          title={t('title')}
          description={t('description')}
          icon={ShieldCheck}
          iconColor="text-emerald-600 dark:text-emerald-400"
          size="full"
          density="system-dense"
          top={<SystemDataStrip items={stripItems} minColumnWidth={158} />}
          actions={
            <div className="flex items-center gap-2">
              <Button
                size="sm"
                variant="outline"
                className={DENSE_OUTLINE_BUTTON}
                onClick={() => detachPromise(loadSummary())}
                disabled={loadingSummary}
              >
                <RefreshCw className={cn('w-4 h-4', loadingSummary && 'animate-spin motion-reduce:animate-none')} />
                {t('actions.refresh')}
              </Button>
              <Button
                size="sm"
                className={DENSE_PRIMARY_BUTTON}
                onClick={() => detachPromise(handleDownload())}
                disabled={exporting}
              >
                <Download className="w-4 h-4" />
                {t('actions.export')}
              </Button>
            </div>
          }
        >
          <Panel padding="md" className={cn('mt-3', DENSE_PANEL)}>
            <div className="flex items-start justify-between gap-4">
              <div>
                <div className={cn(systemPageTokens.heading, 'text-sm')}>{t('summary.heading')}</div>
                <div className={cn('mt-1 text-pretty', systemPageTokens.subtle)}>{t('summary.description')}</div>
              </div>
              <div className={systemPageTokens.monoMeta}>
                {summary?.generated_at ? t('summary.generatedAt', { timestamp: summary.generated_at }) : null}
              </div>
            </div>

            <div className="mt-4">
              {(() => {
    if (loadingSummary) {
        return (<div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-4">
                  {SUMMARY_SKELETON_KEYS.map((key) => (<Skeleton key={key} className="h-[68px] rounded-xl"/>))}
                </div>);
    }
    else if (summary) {
            return (<>
                  <StatsGrid dense className="mt-1">
                    <StatCard icon={ShieldCheck} label="组数量" value={summaryStats.group_count} color="cyan" dense />
                    <StatCard icon={ShieldCheck} label="组成员数" value={summaryStats.group_member_count} color="gray" dense />
                    <StatCard icon={ShieldCheck} label="数据集数" value={summaryStats.dataset_count} color="sky" dense />
                    <StatCard icon={ShieldCheck} label="文档数" value={summaryStats.document_count} color="sky" dense />
                    <StatCard icon={ShieldCheck} label="数据集成员白名单" value={summaryStats.dataset_member_allowlist_count} color="gray" dense />
                    <StatCard icon={ShieldCheck} label="数据集组白名单" value={summaryStats.dataset_group_allowlist_count} color="gray" dense />
                    <StatCard icon={ShieldCheck} label="文档成员白名单" value={summaryStats.document_member_allowlist_count} color="gray" dense />
                    <StatCard icon={ShieldCheck} label="文档组白名单" value={summaryStats.document_group_allowlist_count} color="gray" dense />
                  </StatsGrid>

                  <div className="mt-4 grid grid-cols-1 lg:grid-cols-2 gap-4">
                    <div className="rounded-lg border border-border/60 bg-muted/10 p-3">
                    <div className={cn(systemPageTokens.heading, 'text-sm')}>{t('stats.datasetDistribution')}</div>
                      <div className="mt-2 space-y-1 font-mono text-[11px] text-muted-foreground tabular-nums">
                        <div className="flex items-center justify-between gap-2">
                          <span>{permissionLabel('all_team_members')}</span>
                          <span>{permissionCounts.all_team_members}</span>
                        </div>
                        <div className="flex items-center justify-between gap-2">
                          <span>{permissionLabel('partial_members')}</span>
                          <span>{permissionCounts.partial_members}</span>
                        </div>
                        <div className="flex items-center justify-between gap-2">
                          <span>{permissionLabel('only_me')}</span>
                          <span>{permissionCounts.only_me}</span>
                        </div>
                      </div>
                    </div>

                    <div className="rounded-lg border border-border/60 bg-muted/10 p-3">
                      <div className={cn(systemPageTokens.heading, 'text-sm')}>{t('stats.documentDistribution')}</div>
                      <div className="mt-2 space-y-1 font-mono text-[11px] text-muted-foreground tabular-nums">
                        {Object.entries(accessModeCounts).map(([k, v]) => (<div key={k} className="flex items-center justify-between gap-2">
                            <span>{permissionLabel(k)}</span>
                            <span>{v}</span>
                          </div>))}
                      </div>
                    </div>
                  </div>
                </>);
        }
        else {
        return (<div className={systemPageTokens.body}>
              {t('errors.loadSummaryFallback')}
            </div>);
        }
})()}
            </div>
          </Panel>

          <Panel padding="md" className={cn('mt-3', DENSE_PANEL)}>
          <div className={cn(systemPageTokens.heading, 'text-sm')}>{t('export.heading')}</div>
            <div className={cn('mt-1 text-pretty', systemPageTokens.subtle)}>{t('export.description')}</div>

            <div className="mt-4 grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-12">
              <div className="space-y-1 xl:col-span-3">
                <Label className={systemPageTokens.microLabel}>{t('export.formatLabel')}</Label>
                <Select
                  value={exportFormat}
                  onValueChange={(value) => setExportFormat(coerceOneOf(EXPORT_FORMAT_VALUES, value, 'ndjson'))}
                >
                  <SelectTrigger className={DENSE_SELECT_TRIGGER}>
                    <SelectValue placeholder={t('export.formatPlaceholder')} />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="ndjson">{t('export.formatOptions.ndjson')}</SelectItem>
                    <SelectItem value="json">{t('export.formatOptions.json')}</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              <div className="space-y-1 xl:col-span-3">
                <Label className={systemPageTokens.microLabel}>{t('export.limitLabel')}</Label>
                <Input
                  className={DENSE_INPUT}
                  type="number"
                  min={1}
                  max={10000}
                  value={String(limit)}
                  onChange={(e) => setLimit(safeInt(e.target.value))}
                />
              </div>

              <div className="flex items-end justify-between gap-3 rounded-lg border border-border/60 bg-muted/10 px-4 py-3 xl:col-span-6">
                <div className="min-w-0">
                <Label className="text-[12px] font-semibold">{t('export.gzipLabel')}</Label>
                <div className={cn('truncate', systemPageTokens.subtle)}>{t('export.gzipDescription')}</div>
                </div>
                <Switch checked={gzip} onCheckedChange={(v) => setGzip(Boolean(v))} />
              </div>
            </div>

            <div className="mt-3 flex flex-col gap-2 rounded-lg border border-border/60 bg-muted/10 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
              <div className="min-w-0">
                <Label className="text-[12px] font-semibold">{t('export.includeSensitiveLabel')}</Label>
                <div className={cn(systemPageTokens.subtle, 'text-pretty')}>
                  {t('export.includeSensitiveDescription')}
                </div>
              </div>
              <Switch checked={includeSensitive} onCheckedChange={(v) => setIncludeSensitive(Boolean(v))} />
            </div>

            {exporting ? (
              <div className="mt-3 font-mono text-[11px] text-muted-foreground tabular-nums">
                导出中… 页数={exportPages} 字节={exportBytes}
              </div>
            ) : null}
          </Panel>
        </PageScaffold>
      </div>
    </AppFrame>
  )
}
