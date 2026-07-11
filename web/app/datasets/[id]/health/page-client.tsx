'use client'

import { useEffect, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useParams } from 'next/navigation'
import { toast } from 'sonner'
import { Activity, ArrowLeft, BarChart3, Cloud, Database, Download, FileSearch, RefreshCw, Settings2, ShieldAlert, Sparkles, Table2 } from 'lucide-react'
import { Bar, BarChart, CartesianGrid, Pie, PieChart, Tooltip, XAxis, YAxis } from 'recharts'

import { AppFrame } from '@/components/app-frame'
import { PageScaffold } from '@/components/ui/page-scaffold'
import { Panel } from '@/components/ui/panel'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { EmptyState } from '@/components/ui/empty-state'
import { StatCard, StatsGrid } from '@/components/ui/stats-card'
import { SafeResponsiveChart } from '@/components/ui/safe-responsive-chart'

import { datasetApi } from '@/lib/api/datasets'
import { formatApiError } from '@/lib/api-errors'
import { reportClientError } from '@/lib/client-logging'
import { datasetHealthToMarkdown } from '@/lib/dataset-health-export'
import { queryKeys } from '@/lib/query-keys'
import { sanitizeFilename } from '@/lib/sanitize'
import { cn, formatDate, formatFileSize, detachPromise } from '@/lib/utils'
import { useRouter } from '@/i18n/navigation'

import type { Dataset, DatasetHealthResponse, DatasetProfileFindingSummary } from '@/types'

const PIE_COLORS = ['#38bdf8', '#22c55e', '#f59e0b', '#fb7185', '#a78bfa', '#14b8a6', '#94a3b8']
const healthHeroCard = 'relative overflow-hidden rounded-2xl border border-border/60 bg-[radial-gradient(circle_at_0%_0%,hsl(var(--info)/0.18),transparent_34%),linear-gradient(135deg,hsl(var(--card)/0.96),hsl(var(--background)/0.92))] p-4 shadow-[0_18px_55px_rgba(15,23,42,0.08)] ring-1 ring-border/50 dark:border-border/60 dark:bg-card dark:ring-white/5'
const healthPanelClass = 'overflow-hidden border-border/60 bg-[linear-gradient(180deg,hsl(var(--card)/0.98),hsl(var(--background)/0.92))] p-4 shadow-[0_16px_45px_rgba(15,23,42,0.07)] ring-1 ring-border/50 dark:border-border/60 dark:bg-card/95 dark:ring-white/5'
const healthToolbarGroupClass = 'inline-flex flex-wrap items-center gap-1 rounded-2xl border border-border/60 bg-card/70 p-1 shadow-[0_10px_30px_rgba(15,23,42,0.055)] ring-1 ring-border/50 backdrop-blur dark:border-border/60 dark:bg-card/70 dark:ring-white/5'
const healthToolbarButtonClass = 'h-8 gap-1.5 rounded-xl px-2.5 text-[12px] font-medium text-muted-foreground shadow-none hover:bg-card/95 hover:text-foreground hover:shadow-sm dark:text-muted-foreground dark:hover:bg-muted/60 dark:hover:text-foreground [&_svg]:size-3.5'
const healthToolbarExportButtonClass = 'h-8 gap-1.5 rounded-xl border-border/60 bg-card/75 px-2.5 text-[12px] font-medium text-foreground/85 shadow-[0_8px_20px_rgba(15,23,42,0.045)] hover:bg-card/95 hover:text-foreground dark:border-border/60 dark:bg-card/70 dark:text-muted-foreground dark:hover:bg-muted/60 dark:hover:text-foreground [&_svg]:size-3.5'
const healthToolbarPrimaryButtonClass = 'h-8 gap-1.5 rounded-xl bg-[linear-gradient(90deg,hsl(var(--primary)),hsl(var(--info)))] px-3 text-[12px] font-semibold text-primary-foreground shadow-[0_10px_24px_rgba(14,165,233,0.24)] hover:bg-[linear-gradient(90deg,hsl(var(--primary)/0.92),hsl(var(--info)/0.92))] [&_svg]:size-3.5'

function asDatasetId(raw: unknown): string {
  if (typeof raw === 'string' && raw.trim()) return raw
  if (Array.isArray(raw) && typeof raw[0] === 'string') return raw[0]
  return ''
}

function downloadTextFile(filename: string, content: string, mime = 'text/plain;charset=utf-8') {
  const blob = new Blob([content], { type: mime })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  globalThis.window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}

function sumRecordValues(m: Record<string, unknown> | undefined | null): number {
  return Object.values(m || {}).reduce<number>((acc, v) => acc + Number(v || 0), 0)
}

function suggestionBadgeVariant(sev: 'info' | 'warning' | 'error'): 'outline' | 'soft' | 'destructive' {
  if (sev === 'error') return 'destructive'
  if (sev === 'warning') return 'soft'
  return 'outline'
}

export default function DatasetHealthPage() {
  const router = useRouter()
  const params = useParams()
  const datasetId = asDatasetId((params as Record<string, unknown>)?.id)

  const datasetQuery = useQuery({
    queryKey: queryKeys.datasets.detail(datasetId),
    queryFn: () => datasetApi.get(datasetId),
    enabled: Boolean(datasetId),
  })

  const healthQuery = useQuery({
    queryKey: queryKeys.datasets.health(datasetId),
    queryFn: () => datasetApi.getHealth(datasetId),
    enabled: Boolean(datasetId),
  })

  const dataset = (datasetQuery.data ?? null) as Dataset | null
  const health = (healthQuery.data ?? null) as DatasetHealthResponse | null
  const isLoading = datasetQuery.isFetching || healthQuery.isFetching

  const loadError = datasetQuery.error ?? healthQuery.error

  useEffect(() => {
    if (!loadError) return
    reportClientError('Failed to load dataset health', loadError)
    toast.error(formatApiError(loadError, '加载健康概览失败'))
  }, [loadError])

  const profile = health?.profile
  const ingestion = health?.ingestion

  const statusChartData = useMemo(() => {
    const m = ingestion?.by_status || profile?.by_status || {}
    const entries = Object.entries(m)
      .map(([name, value]) => ({ name, value: Number(value || 0) }))
      .filter((x) => x.value > 0)
      .sort((a, b) => b.value - a.value)
    return entries.map((entry, idx) => ({ ...entry, fill: PIE_COLORS[idx % PIE_COLORS.length] }))
  }, [ingestion?.by_status, profile?.by_status])

  const fileTypeChartData = useMemo(() => {
    const m = profile?.by_file_type || {}
    const entries = Object.entries(m)
      .map(([name, value]) => ({ name, value: Number(value || 0) }))
      .filter((x) => x.value > 0)
      .sort((a, b) => b.value - a.value)

    const top = entries.slice(0, 10)
    const rest = entries.slice(10)
    const other = rest.reduce((acc, x) => acc + x.value, 0)
    if (other > 0) top.push({ name: '其他', value: other })
    return top.map((entry, idx) => ({ ...entry, fill: PIE_COLORS[idx % PIE_COLORS.length] }))
  }, [profile?.by_file_type])

  const piiTotal = useMemo(() => sumRecordValues(profile?.pii_hits_total), [profile?.pii_hits_total])
  const secretsTotal = useMemo(() => sumRecordValues(profile?.secrets_hits_total), [profile?.secrets_hits_total])

  const pdfScanTotal = useMemo(() => {
    const s = profile?.pdf_scan
    if (!s) return 0
    return Number(s.scanned || 0) + Number(s.not_scanned || 0) + Number(s.unknown || 0)
  }, [profile?.pdf_scan])

  const suggestions = useMemo(() => {
    const out: Array<{ severity: 'info' | 'warning' | 'error'; title: string; detail: string }> = []
    if (!health) return out

    const failed = Number(ingestion?.failed || 0)
    const quarantined = Number(ingestion?.quarantined || 0)
    const notScanned = Number(profile?.pdf_scan?.not_scanned || 0)
    const hasFindings = (profile?.findings || []).some((f) => Number(f.count || 0) > 0)

    if (failed > 0) {
      out.push({
        severity: 'error',
        title: '失败文档偏多',
        detail: `failed=${failed}；建议先查看失败文档的错误原因并重试/调整解析与切块策略。`,
      })
    }
    if (quarantined > 0) {
      out.push({
        severity: 'warning',
        title: '存在隔离文档',
        detail: `quarantined=${quarantined}；建议检查治理策略（PII/Secrets/清洗规则）与阈值设置。`,
      })
    }
    if (notScanned > 0) {
      out.push({
        severity: 'warning',
        title: '扫描 PDF 占比偏高',
        detail: `not_scanned=${notScanned}；建议启用 OCR（或切换更适合的 parser_backend），提高可检索文本质量。`,
      })
    }
    if (piiTotal > 0) {
      out.push({
        severity: 'warning',
        title: '检测到 PII 命中',
        detail: `pii_hits_total=${piiTotal}；建议在治理阶段开启脱敏/隔离策略并审计命中类型。`,
      })
    }
    if (secretsTotal > 0) {
      out.push({
        severity: 'warning',
        title: '检测到 Secrets 命中',
        detail: `secrets_hits_total=${secretsTotal}；建议隔离或清洗敏感信息并复查来源。`,
      })
    }
    if (!failed && !quarantined && !notScanned && !hasFindings) {
      out.push({
        severity: 'info',
        title: '健康状态良好',
        detail: '暂无明显风险信号；可继续通过画像/预检页做抽样复核。',
      })
    }

    return out
  }, [health, ingestion?.failed, ingestion?.quarantined, profile?.pdf_scan?.not_scanned, profile?.findings, piiTotal, secretsTotal])

  const exportPayload = useMemo(() => {
    if (!datasetId || !health) return null
    return {
      schema: 'mimirq.dataset_health.v1',
      exported_at: new Date().toISOString(),
      dataset: dataset
        ? {
            id: dataset.id ?? datasetId,
            name: dataset.name ?? null,
          }
        : { id: datasetId, name: null },
      health,
      suggestions,
    }
  }, [dataset, datasetId, health, suggestions])

  const topFindings: DatasetProfileFindingSummary[] = useMemo(() => {
    return (profile?.findings || [])
      .filter((f) => Number(f.count || 0) > 0)
      .sort((a, b) => Number(b.count || 0) - Number(a.count || 0))
      .slice(0, 8)
  }, [profile?.findings])
  const totalSizeLabel = profile ? formatFileSize(profile.total_size_bytes || 0) : (isLoading ? '…' : '-')
  const documentCountLabel = profile?.total_documents ?? (isLoading ? '…' : 0)
  const scannedPdfLabel = profile ? `${profile.pdf_scan?.scanned ?? 0}/${pdfScanTotal || 0}` : (isLoading ? '…' : '-')
  const piiLabel = profile ? piiTotal : (isLoading ? '…' : 0)
  const secretsLabel = profile ? secretsTotal : (isLoading ? '…' : 0)
  const failedCount = Number(ingestion?.failed || 0)
  const quarantinedCount = Number(ingestion?.quarantined || 0)
  const riskCount = suggestions.filter((s) => s.severity !== 'info').length
  const generatedAtLabel = health?.generated_at ? formatDate(health.generated_at) : '--'
  const healthStatusLabel = loadError
    ? '加载失败'
    : riskCount > 0
      ? `需处理 ${riskCount} 项`
      : health
        ? '健康良好'
        : '待加载'

  return (
    <AppFrame>
      <PageScaffold
        title="健康概览"
        showHeader={false}
        size="full"
        density="system-dense"
        bodyGutter="dense"
        bodyClassName="bg-[radial-gradient(circle_at_12%_0%,rgba(14,165,233,0.10),transparent_28%),linear-gradient(180deg,#f8fcff_0%,#f4f8fb_44%,#f8fafc_100%)] dark:bg-background"
        bodyContainerClassName="h-full min-h-full"
        top={
          <div className={healthHeroCard}>
            <div className="pointer-events-none absolute inset-0 bg-[linear-gradient(rgba(14,165,233,0.045)_1px,transparent_1px),linear-gradient(90deg,rgba(14,165,233,0.045)_1px,transparent_1px)] bg-[size:28px_28px]" />
            <div className="relative flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
              <div className="flex min-w-0 items-start gap-3.5">
                <div className="flex size-11 shrink-0 items-center justify-center rounded-2xl border border-info/20 bg-info/5 text-info shadow-inner">
                  <Activity className="size-5" />
                </div>
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <h1 className="truncate text-[20px] font-medium leading-none tracking-[-0.01em] text-foreground dark:text-foreground">
                      健康概览
                    </h1>
                    <Badge variant="soft" className="h-5 border-info/30 bg-info/10 px-2 text-[10px] font-medium leading-none text-info">
                      HEALTH
                    </Badge>
                  </div>
                  <p className="mt-1.5 max-w-4xl text-[13px] leading-tight text-muted-foreground">
                    数据集：<span className="font-semibold text-foreground dark:text-foreground">{dataset?.name || datasetId || '未选择'}</span>
                    <span className="mx-2 text-muted-foreground/60">·</span>
                    汇总数据画像、入库状态和下一步处理建议
                  </p>
                  <div className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-1.5 text-[11px] leading-none text-muted-foreground">
                    <span className="inline-flex items-center gap-1.5">
                      <Database className="size-3.5 text-info" />
                      文档 <strong className="font-mono text-foreground dark:text-foreground">{documentCountLabel}</strong>
                    </span>
                    <span className="inline-flex items-center gap-1.5">
                      <Cloud className="size-3.5 text-info" />
                      总大小 <strong className="font-mono text-foreground dark:text-foreground">{totalSizeLabel}</strong>
                    </span>
                    <span className="inline-flex items-center gap-1.5">
                      <ShieldAlert className="size-3.5 text-destructive" />
                      失败 <strong className="font-mono text-foreground dark:text-foreground">{ingestion ? failedCount : (isLoading ? '…' : 0)}</strong>
                    </span>
                    <span className="inline-flex items-center gap-1.5">
                      <FileSearch className="size-3.5 text-warning" />
                      隔离 <strong className="font-mono text-foreground dark:text-foreground">{ingestion ? quarantinedCount : (isLoading ? '…' : 0)}</strong>
                    </span>
                    <span className="inline-flex items-center gap-1.5">
                      <Sparkles className="size-3.5 text-success" />
                      更新时间 <strong className="font-mono text-foreground dark:text-foreground">{generatedAtLabel}</strong>
                    </span>
                  </div>
                </div>
              </div>
              <div
                className={cn(
                  'inline-flex h-9 shrink-0 items-center gap-2 rounded-lg border px-3 text-[13px] font-medium shadow-[inset_0_1px_0_rgba(255,255,255,0.75)]',
                  loadError
                    ? 'border-destructive/30 bg-destructive/5 text-destructive'
                    : riskCount > 0
                      ? 'border-warning/30 bg-warning/5 text-warning'
                      : 'border-success/30 bg-success/5 text-success',
                )}
              >
                <span
                  className={cn(
                    'size-2 rounded-full',
                    loadError ? 'bg-destructive' : riskCount > 0 ? 'bg-warning' : 'bg-success',
                  )}
                />
                {healthStatusLabel}
              </div>
            </div>
          </div>
        }
        toolbar={
          <div className="flex w-full flex-col gap-2 lg:flex-row lg:items-center lg:justify-between">
            <div className={healthToolbarGroupClass}>
              <Button size="sm" variant="ghost" className={healthToolbarButtonClass} onClick={() => router.push('/datasets')}>
                <ArrowLeft className="w-4 h-4" />
                返回
              </Button>
              {datasetId ? (
                <Button size="sm" variant="ghost" className={healthToolbarButtonClass} onClick={() => router.push(`/datasets/${datasetId}/profile`)}>
                  <BarChart3 className="w-4 h-4" />
                  数据画像
                </Button>
              ) : null}
              {datasetId ? (
                <Button size="sm" variant="ghost" className={healthToolbarButtonClass} onClick={() => router.push(`/datasets/${datasetId}/precheck`)}>
                  <ShieldAlert className="w-4 h-4" />
                  预检
                </Button>
              ) : null}
              {datasetId ? (
                <Button size="sm" variant="ghost" className={healthToolbarButtonClass} onClick={() => router.push(`/datasets/${datasetId}/ingestion`)}>
                  <Settings2 className="w-4 h-4" />
                  入库策略
                </Button>
              ) : null}
              {datasetId ? (
                <Button size="sm" variant="ghost" className={healthToolbarButtonClass} onClick={() => router.push(`/datasets/${datasetId}/tables`)}>
                  <Table2 className="w-4 h-4" />
                  表格 / TAG
                </Button>
              ) : null}
              <Button
                size="sm"
                variant="ghost"
                className={healthToolbarButtonClass}
                onClick={() =>
                  detachPromise(
                    Promise.all([datasetQuery.refetch(), healthQuery.refetch()]).then(() => undefined)
                  )
                }
                disabled={isLoading || !datasetId}
              >
                <RefreshCw className={cn('w-4 h-4', isLoading && 'animate-spin motion-reduce:animate-none')} />
                刷新
              </Button>
            </div>
            <div className="flex flex-wrap items-center gap-1.5">
              <Button
                size="sm"
                variant="outline"
                className={healthToolbarExportButtonClass}
                disabled={!exportPayload}
                onClick={() => {
                  if (!exportPayload) return
                  const filenameBase = sanitizeFilename(dataset?.name || datasetId || 'dataset')
                  downloadTextFile(`${filenameBase}.health.json`, JSON.stringify(exportPayload, null, 2), 'application/json;charset=utf-8')
                  toast.success('已导出 health.json')
                }}
              >
                <Download className="w-4 h-4" />
                导出 JSON
              </Button>
              <Button
                size="sm"
                className={healthToolbarPrimaryButtonClass}
                disabled={!exportPayload}
                onClick={() => {
                  if (!exportPayload) return
                  const exportedHealth = exportPayload.health
                  const filenameBase = sanitizeFilename(dataset?.name || datasetId || 'dataset')
                  const md = datasetHealthToMarkdown({
                    datasetId: datasetId || '',
                    datasetName: dataset?.name || null,
                    exportedAt: exportPayload.exported_at,
                    generatedAt: exportedHealth.generated_at ?? null,
                    profile: exportedHealth.profile ?? null,
                    ingestion: exportedHealth.ingestion ?? null,
                    suggestions,
                  })
                  downloadTextFile(`${filenameBase}.health.md`, md, 'text/markdown;charset=utf-8')
                  toast.success('已导出 health.md')
                }}
              >
                <Download className="w-4 h-4" />
                导出 MD
              </Button>
            </div>
          </div>
        }
      >
        <div className="space-y-3">
          <Panel className={cn(healthPanelClass, 'p-2.5')}>
            <StatsGrid dense className="grid-cols-2 gap-1.5 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-7 xl:grid-cols-7">
              <StatCard
                dense
                variant="minimal"
                className="w-full justify-start"
                icon={FileSearch}
                label="文档总数"
                value={profile?.total_documents ?? (isLoading ? '…' : 0)}
                color="cyan"
              />
              <StatCard
                dense
                variant="minimal"
                className="w-full justify-start"
                icon={BarChart3}
                label="总大小"
                value={totalSizeLabel}
                color="teal"
              />
              <StatCard
                dense
                variant="minimal"
                className="w-full justify-start"
                icon={ShieldAlert}
                label="失败"
                value={ingestion?.failed ?? (isLoading ? '…' : 0)}
                color="rose"
              />
              <StatCard
                dense
                variant="minimal"
                className="w-full justify-start"
                icon={ShieldAlert}
                label="隔离"
                value={ingestion?.quarantined ?? (isLoading ? '…' : 0)}
                color="amber"
              />
              <StatCard
                dense
                variant="minimal"
                className="w-full justify-start"
                icon={Activity}
                label="扫描 PDF"
                value={scannedPdfLabel}
                color="orange"
              />
              <StatCard
                dense
                variant="minimal"
                className="w-full justify-start"
                icon={ShieldAlert}
                label="PII"
                value={piiLabel}
                color="sky"
              />
              <StatCard
                dense
                variant="minimal"
                className="w-full justify-start"
                icon={ShieldAlert}
                label="Secrets"
                value={secretsLabel}
                color="sky"
              />
            </StatsGrid>
          </Panel>

          <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
            <Panel className={healthPanelClass}>
              <div className="flex items-center justify-between mb-4">
                <div className="font-semibold">入库状态分布</div>
                <div className="text-xs text-muted-foreground font-mono">
                  {health?.generated_at ? `updated ${formatDate(health.generated_at)}` : ''}
                </div>
              </div>
              {statusChartData.length ? (
                <>
                  <SafeResponsiveChart className="h-[160px]" minHeight={160}>
                    <BarChart data={statusChartData} margin={{ top: 10, right: 10, left: 0, bottom: 0 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                      <XAxis dataKey="name" tick={{ fontSize: 12 }} />
                      <YAxis tick={{ fontSize: 12 }} allowDecimals={false} />
                      <Tooltip />
                      <Bar dataKey="value" fill="hsl(var(--chart-1))" radius={[8, 8, 0, 0]} />
                    </BarChart>
                  </SafeResponsiveChart>
                  <div className="mt-3 flex flex-wrap gap-2">
                    {statusChartData.map((item) => (
                      <span key={item.name} className="inline-flex items-center gap-2 rounded-full border border-border/60 bg-card/60 px-3 py-1 text-xs shadow-sm dark:bg-muted/20">
                        <span className="size-2 rounded-full bg-info" />
                        <span className="font-medium">{item.name}</span>
                        <span className="font-mono text-muted-foreground">{item.value}</span>
                      </span>
                    ))}
                  </div>
                </>
              ) : (
                <EmptyState icon={Activity} title="暂无状态数据" description="后端未返回可用的状态分布。" className="min-h-[160px]" />
              )}
            </Panel>

            <Panel className={healthPanelClass}>
              <div className="flex items-center justify-between mb-4">
                <div className="font-semibold">格式分布</div>
                <div className="text-xs text-muted-foreground font-mono">
                  {profile?.generated_at ? `updated ${formatDate(profile.generated_at)}` : ''}
                </div>
              </div>
              {fileTypeChartData.length ? (
                <>
                  <SafeResponsiveChart className="h-[160px]" minHeight={160}>
                    <PieChart>
                      <Pie data={fileTypeChartData} dataKey="value" nameKey="name" outerRadius={70} label />
                      <Tooltip />
                    </PieChart>
                  </SafeResponsiveChart>
                  <div className="mt-3 flex flex-wrap gap-2">
                    {fileTypeChartData.map((item) => (
                      <span key={item.name} className="inline-flex items-center gap-2 rounded-full border border-border/60 bg-card/60 px-3 py-1 text-xs shadow-sm dark:bg-muted/20">
                        <span className="size-2 rounded-full bg-info" />
                        <span className="font-medium">{item.name}</span>
                        <span className="font-mono text-muted-foreground">{item.value}</span>
                      </span>
                    ))}
                  </div>
                </>
              ) : (
                <EmptyState icon={BarChart3} title="暂无格式数据" description="后端未返回可用的格式统计。" className="min-h-[160px]" />
              )}
            </Panel>
          </div>

          <Panel className={cn(healthPanelClass, 'p-3')}>
            <div className="mb-3 flex items-start justify-between gap-4">
              <div>
                <div className="text-sm font-semibold">质量洞察</div>
                <div className="mt-0.5 text-[11px] leading-4 text-muted-foreground/60">
                  汇总规则建议和画像发现，用于快速判断是否需要补扫或人工复核。
                </div>
              </div>
              <Badge variant="outline" className="h-5 px-1.5 text-[10px] font-mono text-muted-foreground">
                rules v1
              </Badge>
            </div>

            <div className="grid grid-cols-1 gap-3 lg:grid-cols-[minmax(0,1fr)_360px]">
              <div className="rounded-xl border border-border/50 bg-card/45 p-3 dark:bg-card/40">
                <div className="mb-2 flex items-center justify-between gap-2">
                  <div className="text-[13px] font-semibold text-foreground/85">建议</div>
                  <Badge variant={suggestions.length ? 'soft' : 'outline'} className="h-5 px-1.5 text-[10px] font-mono">
                    {suggestions.length}
                  </Badge>
                </div>
                {suggestions.length ? (
                  <div className="divide-y divide-border/45 overflow-hidden rounded-lg border border-border/45">
                    {suggestions.map((s) => (
                      <div key={`${s.severity}-${s.title}-${s.detail}`} className="grid gap-2 px-2.5 py-2 md:grid-cols-[auto_minmax(0,1fr)]">
                        <Badge variant={suggestionBadgeVariant(s.severity)} className="h-5 px-1.5 text-[10px] font-mono uppercase">
                          {s.severity}
                        </Badge>
                        <div className="min-w-0">
                          <div className="truncate text-[12px] font-semibold text-foreground/85">{s.title}</div>
                          <div className="mt-0.5 line-clamp-2 text-[11px] leading-4 text-muted-foreground/65">{s.detail}</div>
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="rounded-lg border border-success/20 bg-success/5 px-2.5 py-2 text-[11px] leading-4 text-success">
                    当前没有 rule-based 建议。若仍不放心，可查看画像与预检详情确认是否需要补扫。
                  </div>
                )}
              </div>

              <div className="rounded-xl border border-border/50 bg-card/45 p-3 dark:bg-card/40">
                <div className="mb-2.5 flex items-center justify-between gap-2">
                  <div>
                    <div className="text-[13px] font-semibold text-foreground/85">画像发现</div>
                    <div className="mt-0.5 text-[10px] leading-none text-muted-foreground/55">按影响度排序的可处理问题</div>
                  </div>
                  <Badge variant={topFindings.length ? 'soft' : 'outline'} className="h-5 px-1.5 text-[10px] font-mono">
                    {topFindings.length}
                  </Badge>
                </div>
                {topFindings.length ? (
                  <div className="space-y-1.5">
                    {topFindings.map((f) => (
                      <div
                        key={f.key}
                        className={cn(
                          'group relative overflow-hidden rounded-xl border bg-card/70 px-2.5 py-2 shadow-[inset_0_1px_0_rgba(255,255,255,0.72)] transition-colors hover:bg-card/90 dark:bg-muted/20',
                          f.severity === 'error'
                            ? 'border-destructive/30'
                            : f.severity === 'warning'
                              ? 'border-warning/30'
                              : 'border-border/60 dark:border-border/60',
                        )}
                        title={f.description || ''}
                      >
                        <div
                          className={cn(
                            'absolute inset-y-2 left-0 w-1 rounded-r-full',
                            f.severity === 'error'
                              ? 'bg-destructive'
                              : f.severity === 'warning'
                                ? 'bg-warning'
                                : 'bg-info/30',
                          )}
                        />
                        <div className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-2 pl-2">
                          <div className="min-w-0">
                            <div className="flex items-center gap-1.5">
                              <div className="truncate text-[12px] font-semibold text-foreground/85">{f.label}</div>
                              <span className="shrink-0 rounded-full bg-muted px-1.5 py-0.5 font-mono text-[10px] leading-none text-muted-foreground dark:bg-muted/50">
                                ×{Number(f.count || 0)}
                              </span>
                            </div>
                            {f.description ? (
                              <div className="mt-1 line-clamp-2 text-[11px] leading-4 text-muted-foreground/62">{f.description}</div>
                            ) : null}
                          </div>
                          <Badge variant={suggestionBadgeVariant(f.severity)} className="h-5 shrink-0 px-1.5 text-[10px] font-mono uppercase">
                            {String(f.severity || '')}
                          </Badge>
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="rounded-lg border border-dashed border-border/55 bg-muted/40 px-2.5 py-2 text-[11px] leading-4 text-muted-foreground/65 dark:bg-muted/20">
                    当前没有 profile findings。
                  </div>
                )}
              </div>
            </div>
          </Panel>

          {datasetId ? null : (
            <Panel className={healthPanelClass}>
              <EmptyState icon={Activity} title="缺少 datasetId" description="无法识别当前路由参数 id。" />
            </Panel>
          )}
        </div>
      </PageScaffold>
    </AppFrame>
  )
}
