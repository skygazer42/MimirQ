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
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { StatCard, StatsGrid } from '@/components/ui/stats-card'

import { auditApi } from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'
import { coerceOneOf } from '@/lib/one-of'
import { cn, detachPromise } from '@/lib/utils'

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

  return (
    <AppFrame>
      <div className="flex-1 flex flex-col overflow-hidden relative">
        <PageScaffold
          title={t('title')}
          description={t('description')}
          icon={ShieldCheck}
          iconColor="text-emerald-600 dark:text-emerald-400"
          size="7xl"
          actions={
            <div className="flex items-center gap-2">
              <Button
                size="sm"
                variant="outline"
                className="gap-2 rounded-xl"
                onClick={() => detachPromise(loadSummary())}
                disabled={loadingSummary}
              >
                <RefreshCw className={cn('w-4 h-4', loadingSummary && 'animate-spin motion-reduce:animate-none')} />
                {t('actions.refresh')}
              </Button>
              <Button
                size="sm"
                className="gap-2 rounded-xl"
                onClick={() => detachPromise(handleDownload())}
                disabled={exporting}
              >
                <Download className="w-4 h-4" />
                {t('actions.export')}
              </Button>
            </div>
          }
        >
          <Panel padding="lg" className="mt-4">
            <div className="flex items-start justify-between gap-4">
              <div>
                <div className="text-sm font-semibold text-foreground">{t('summary.heading')}</div>
                <div className="mt-1 text-xs text-muted-foreground text-pretty">{t('summary.description')}</div>
              </div>
              <div className="text-xs text-muted-foreground font-mono">
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
                  <StatsGrid className="mt-1">
                    <StatCard icon={ShieldCheck} label="Groups" value={summaryStats.group_count} color="cyan"/>
                    <StatCard icon={ShieldCheck} label="Group Members" value={summaryStats.group_member_count} color="gray"/>
                    <StatCard icon={ShieldCheck} label="Datasets" value={summaryStats.dataset_count} color="sky"/>
                    <StatCard icon={ShieldCheck} label="Documents" value={summaryStats.document_count} color="sky"/>
                    <StatCard icon={ShieldCheck} label="Dataset Member Allowlist" value={summaryStats.dataset_member_allowlist_count} color="gray"/>
                    <StatCard icon={ShieldCheck} label="Dataset Group Allowlist" value={summaryStats.dataset_group_allowlist_count} color="gray"/>
                    <StatCard icon={ShieldCheck} label="Document Member Allowlist" value={summaryStats.document_member_allowlist_count} color="gray"/>
                    <StatCard icon={ShieldCheck} label="Document Group Allowlist" value={summaryStats.document_group_allowlist_count} color="gray"/>
                  </StatsGrid>

                  <div className="mt-4 grid grid-cols-1 lg:grid-cols-2 gap-4">
                    <div className="rounded-xl border border-border/60 bg-muted/10 p-3">
                    <div className="text-sm font-semibold">{t('stats.datasetDistribution')}</div>
                      <div className="mt-2 text-xs text-muted-foreground font-mono tabular-nums space-y-1">
                        <div className="flex items-center justify-between gap-2">
                          <span>all_team_members</span>
                          <span>{permissionCounts.all_team_members}</span>
                        </div>
                        <div className="flex items-center justify-between gap-2">
                          <span>partial_members</span>
                          <span>{permissionCounts.partial_members}</span>
                        </div>
                        <div className="flex items-center justify-between gap-2">
                          <span>only_me</span>
                          <span>{permissionCounts.only_me}</span>
                        </div>
                      </div>
                    </div>

                    <div className="rounded-xl border border-border/60 bg-muted/10 p-3">
                      <div className="text-sm font-semibold">{t('stats.documentDistribution')}</div>
                      <div className="mt-2 text-xs text-muted-foreground font-mono tabular-nums space-y-1">
                        {Object.entries(accessModeCounts).map(([k, v]) => (<div key={k} className="flex items-center justify-between gap-2">
                            <span>{k}</span>
                            <span>{v}</span>
                          </div>))}
                      </div>
                    </div>
                  </div>
                </>);
        }
        else {
        return (<div className="text-sm text-muted-foreground">
              {t('errors.loadSummaryFallback')}
            </div>);
        }
})()}
            </div>
          </Panel>

          <Panel padding="lg" className="mt-4">
          <div className="text-sm font-semibold text-foreground">{t('export.heading')}</div>
            <div className="mt-1 text-xs text-muted-foreground text-pretty">{t('export.description')}</div>

            <div className="mt-4 grid grid-cols-1 md:grid-cols-3 gap-3">
              <div className="space-y-1">
                <Label>{t('export.formatLabel')}</Label>
                <Select
                  value={exportFormat}
                  onValueChange={(value) => setExportFormat(coerceOneOf(EXPORT_FORMAT_VALUES, value, 'ndjson'))}
                >
                  <SelectTrigger className="h-10 rounded-xl">
                    <SelectValue placeholder={t('export.formatPlaceholder')} />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="ndjson">{t('export.formatOptions.ndjson')}</SelectItem>
                    <SelectItem value="json">{t('export.formatOptions.json')}</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              <div className="space-y-1">
                <Label>{t('export.limitLabel')}</Label>
                <Input
                  type="number"
                  min={1}
                  max={10000}
                  value={String(limit)}
                  onChange={(e) => setLimit(safeInt(e.target.value))}
                />
              </div>

              <div className="flex items-end justify-between gap-3 rounded-xl border border-border/60 bg-muted/10 px-4 py-3">
                <div className="min-w-0">
                <Label className="text-sm">{t('export.gzipLabel')}</Label>
                <div className="text-xs text-muted-foreground truncate">{t('export.gzipDescription')}</div>
                </div>
                <Switch checked={gzip} onCheckedChange={(v) => setGzip(Boolean(v))} />
              </div>
            </div>

            <div className="mt-3 flex items-center justify-between gap-3 rounded-xl border border-border/60 bg-muted/10 px-4 py-3">
              <div className="min-w-0">
                <Label className="text-sm">{t('export.includeSensitiveLabel')}</Label>
                <div className="text-xs text-muted-foreground text-pretty">
                  {t('export.includeSensitiveDescription')}
                </div>
              </div>
              <Switch checked={includeSensitive} onCheckedChange={(v) => setIncludeSensitive(Boolean(v))} />
            </div>

            {exporting ? (
              <div className="mt-3 text-xs text-muted-foreground font-mono tabular-nums">
                exporting… pages={exportPages} bytes={exportBytes}
              </div>
            ) : null}
          </Panel>
        </PageScaffold>
      </div>
    </AppFrame>
  )
}
