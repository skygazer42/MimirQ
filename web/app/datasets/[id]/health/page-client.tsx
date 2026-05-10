'use client'

import { useEffect, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useParams } from 'next/navigation'
import { toast } from 'sonner'
import { Activity, ArrowLeft, BarChart3, Download, FileSearch, RefreshCw, Settings2, ShieldAlert } from 'lucide-react'
import { Bar, BarChart, CartesianGrid, Cell, Pie, PieChart, Tooltip, XAxis, YAxis } from 'recharts'

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
import { datasetHealthToMarkdown } from '@/lib/dataset-health-export'
import { queryKeys } from '@/lib/query-keys'
import { sanitizeFilename } from '@/lib/sanitize'
import { cn, formatDate, formatFileSize, detachPromise } from '@/lib/utils'
import { useRouter } from '@/i18n/navigation'

import type { Dataset, DatasetHealthResponse, DatasetProfileFindingSummary } from '@/types'

const PIE_COLORS = ['#38bdf8', '#22c55e', '#f59e0b', '#fb7185', '#a78bfa', '#14b8a6', '#94a3b8']

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

function sumRecordValues(m: Record<string, any> | undefined | null): number {
  return Object.values(m || {}).reduce((acc: number, v: any) => acc + Number(v || 0), 0)
}

function suggestionBadgeVariant(sev: 'info' | 'warning' | 'error'): 'outline' | 'soft' | 'destructive' {
  if (sev === 'error') return 'destructive'
  if (sev === 'warning') return 'soft'
  return 'outline'
}

export default function DatasetHealthPage() {
  const router = useRouter()
  const params = useParams()
  const datasetId = asDatasetId((params as any)?.id)

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
    console.error('Failed to load dataset health', loadError)
    toast.error(formatApiError(loadError, '加载健康概览失败'))
  }, [loadError])

  const profile = health?.profile
  const ingestion = health?.ingestion

  const statusChartData = useMemo(() => {
    const m = ingestion?.by_status || profile?.by_status || {}
    return Object.entries(m)
      .map(([name, value]) => ({ name, value: Number(value || 0) }))
      .filter((x) => x.value > 0)
      .sort((a, b) => b.value - a.value)
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
    return top
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
            id: (dataset as any).id ?? datasetId,
            name: (dataset as any).name ?? null,
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

  return (
    <AppFrame>
      <PageScaffold
        title={`健康概览${dataset?.name ? ` · ${dataset.name}` : ''}`}
        badge="Dataset Health"
        icon={Activity}
        iconColor="text-rose"
        description={<span className="text-sm text-muted-foreground">汇总数据画像 + 入库状态，并给出下一步建议。</span>}
        actions={
          <div className="flex items-center gap-2">
            <Button variant="outline" className="gap-2" onClick={() => router.push('/datasets')}>
              <ArrowLeft className="w-4 h-4" />
              返回
            </Button>
            {datasetId ? (
              <Button variant="outline" className="gap-2" onClick={() => router.push(`/datasets/${datasetId}/profile`)}>
                <BarChart3 className="w-4 h-4" />
                画像
              </Button>
            ) : null}
            {datasetId ? (
              <Button variant="outline" className="gap-2" onClick={() => router.push(`/datasets/${datasetId}/precheck`)}>
                <ShieldAlert className="w-4 h-4" />
                预检
              </Button>
            ) : null}
            {datasetId ? (
              <Button variant="outline" className="gap-2" onClick={() => router.push(`/datasets/${datasetId}/ingestion`)}>
                <Settings2 className="w-4 h-4" />
                入库策略
              </Button>
            ) : null}
            <Button
              variant="outline"
              className="gap-2"
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
            <Button
              variant="outline"
              className="gap-2"
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
              variant="outline"
              className="gap-2"
              disabled={!exportPayload}
              onClick={() => {
                if (!exportPayload) return
                const filenameBase = sanitizeFilename(dataset?.name || datasetId || 'dataset')
                const md = datasetHealthToMarkdown({
                  datasetId: datasetId || '',
                  datasetName: dataset?.name || null,
                  exportedAt: exportPayload.exported_at,
                  generatedAt: (health as any)?.generated_at ?? null,
                  profile: (health as any)?.profile ?? null,
                  ingestion: (health as any)?.ingestion ?? null,
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
        }
      >
        <div className="space-y-6">
          <Panel className="p-5">
            <StatsGrid>
              <StatCard icon={FileSearch} label="文档总数" value={profile?.total_documents ?? (isLoading ? '…' : 0)} color="cyan" />
              <StatCard icon={BarChart3} label="总大小" value={(() => {
    if (profile) {
        return formatFileSize(profile.total_size_bytes || 0);
    }
    else if (isLoading) {
            return '…';
        }
        else {
            return '-';
        }
})()} color="teal" />
              <StatCard icon={ShieldAlert} label="失败" value={ingestion?.failed ?? (isLoading ? '…' : 0)} color="rose" />
              <StatCard icon={ShieldAlert} label="隔离" value={ingestion?.quarantined ?? (isLoading ? '…' : 0)} color="amber" />
              <StatCard
                icon={Activity}
                label="扫描 PDF"
                value={(() => {
    if (profile) {
        return `${profile.pdf_scan?.scanned ?? 0}/${pdfScanTotal || 0}`;
    }
    else if (isLoading) {
            return '…';
        }
        else {
            return '-';
        }
})()}
                color="orange"
              />
              <StatCard icon={ShieldAlert} label="PII" value={(() => {
    if (profile) {
        return piiTotal;
    }
    else if (isLoading) {
            return '…';
        }
        else {
            return 0;
        }
})()} color="sky" />
              <StatCard icon={ShieldAlert} label="Secrets" value={(() => {
    if (profile) {
        return secretsTotal;
    }
    else if (isLoading) {
            return '…';
        }
        else {
            return 0;
        }
})()} color="sky" />
            </StatsGrid>
          </Panel>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <Panel className="p-5">
              <div className="flex items-center justify-between mb-4">
                <div className="font-semibold">入库状态分布</div>
                <div className="text-xs text-muted-foreground font-mono">
                  {health?.generated_at ? `updated ${formatDate(health.generated_at)}` : ''}
                </div>
              </div>
              {statusChartData.length ? (
                <SafeResponsiveChart>
                    <BarChart data={statusChartData} margin={{ top: 10, right: 10, left: 0, bottom: 0 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                      <XAxis dataKey="name" tick={{ fontSize: 12 }} />
                      <YAxis tick={{ fontSize: 12 }} allowDecimals={false} />
                      <Tooltip />
                      <Bar dataKey="value" radius={[8, 8, 0, 0]}>
                        {statusChartData.map((entry, idx) => (
                          <Cell key={String(entry.name ?? 'status')} fill={PIE_COLORS[idx % PIE_COLORS.length]} />
                        ))}
                      </Bar>
                    </BarChart>
                  </SafeResponsiveChart>
              ) : (
                <EmptyState icon={Activity} title="暂无状态数据" description="后端未返回可用的状态分布。" className="min-h-[280px]" />
              )}
            </Panel>

            <Panel className="p-5">
              <div className="flex items-center justify-between mb-4">
                <div className="font-semibold">格式分布</div>
                <div className="text-xs text-muted-foreground font-mono">
                  {profile?.generated_at ? `updated ${formatDate(profile.generated_at)}` : ''}
                </div>
              </div>
              {fileTypeChartData.length ? (
                <SafeResponsiveChart>
                    <PieChart>
                      <Pie data={fileTypeChartData} dataKey="value" nameKey="name" outerRadius={110} label>
                        {fileTypeChartData.map((entry, idx) => (
                          <Cell key={String(entry.name ?? 'file-type')} fill={PIE_COLORS[idx % PIE_COLORS.length]} />
                        ))}
                      </Pie>
                      <Tooltip />
                    </PieChart>
                  </SafeResponsiveChart>
              ) : (
                <EmptyState icon={BarChart3} title="暂无格式数据" description="后端未返回可用的格式统计。" className="min-h-[280px]" />
              )}
            </Panel>
          </div>

          <Panel className="p-5">
            <div className="flex items-center justify-between mb-4">
              <div className="font-semibold">建议（rule-based）</div>
              <div className="text-xs text-muted-foreground">v1</div>
            </div>
            <div className="space-y-2">
              {suggestions.map((s) => (
                <div key={`${s.severity}-${s.title}-${s.detail}`} className="flex items-start gap-3 rounded-xl border border-border/60 bg-muted/20 p-3">
                  <Badge variant={suggestionBadgeVariant(s.severity)} className="shrink-0">
                    {s.severity.toUpperCase()}
                  </Badge>
                  <div className="min-w-0">
                    <div className="text-sm font-medium">{s.title}</div>
                    <div className="mt-1 text-xs text-muted-foreground">{s.detail}</div>
                  </div>
                </div>
              ))}
            </div>
          </Panel>

          <Panel className="p-5">
            <div className="flex items-center justify-between mb-4">
              <div className="font-semibold">Top Findings</div>
              <div className="text-xs text-muted-foreground">from profile summary</div>
            </div>
            {topFindings.length ? (
              <div className="flex flex-wrap gap-2">
                {topFindings.map((f) => (
                  <span
                    key={f.key}
                    className="inline-flex items-center gap-2 rounded-full border border-border/60 bg-muted/40 px-3 py-1 text-xs"
                    title={f.description || ''}
                  >
                    <span className="font-medium">{f.label}</span>
                    <span className="text-muted-foreground">× {Number(f.count || 0)}</span>
                    <Badge variant={suggestionBadgeVariant(f.severity)}>{String(f.severity || '').toUpperCase()}</Badge>
                  </span>
                ))}
              </div>
            ) : (
              <EmptyState icon={FileSearch} title="暂无 Findings" description="当前数据集中未统计到可行动的风险桶。" className="min-h-[180px]" />
            )}
          </Panel>

          {datasetId ? null : (
            <Panel className="p-5">
              <EmptyState icon={Activity} title="缺少 datasetId" description="无法识别当前路由参数 id。" />
            </Panel>
          )}
        </div>
      </PageScaffold>
    </AppFrame>
  )
}
