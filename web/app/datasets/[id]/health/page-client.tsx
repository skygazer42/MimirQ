'use client'

import { useEffect, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useParams } from 'next/navigation'
import { toast } from 'sonner'
import { Activity, ArrowLeft, BarChart3, Cloud, Database, Download, FileSearch, RefreshCw, Settings2, ShieldAlert, Sparkles, Table2 } from '@/components/icons'
import { Bar, BarChart, CartesianGrid, Pie, PieChart, Tooltip, XAxis, YAxis } from 'recharts'

import { AppFrame } from '@/components/app-frame'
import { OperationalWorkspace, WorkspaceMetrics, WorkspaceNotice, workspaceStyles as ws } from '@/components/ui/operational-workspace'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { MoreHorizontal } from '@/components/icons'
import { Panel } from '@/components/ui/panel'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { EmptyState } from '@/components/ui/empty-state'
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

const PIE_COLORS = ['hsl(var(--chart-5))', 'hsl(var(--chart-2))', 'hsl(var(--chart-4))', 'hsl(var(--chart-6))', 'hsl(var(--chart-3))', 'hsl(var(--chart-1))', 'hsl(var(--chart-8))']

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
    }
  }, [dataset, datasetId, health])

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
  const generatedAtLabel = health?.generated_at ? formatDate(health.generated_at) : '--'
  const healthStatusLabel = loadError
    ? '加载失败'
    : health
      ? '后端快照已返回'
      : '待加载'

  const exportHealth = (format: 'json' | 'markdown') => {
    if (!exportPayload) return
    const filename = sanitizeFilename(dataset?.name || datasetId || 'dataset')
    const text = format === 'json' ? JSON.stringify(exportPayload, null, 2) : datasetHealthToMarkdown({ datasetId, datasetName: dataset?.name || null, exportedAt: exportPayload.exported_at, generatedAt: exportPayload.health.generated_at, profile: exportPayload.health.profile ?? null, ingestion: exportPayload.health.ingestion ?? null, suggestions: [] })
    downloadTextFile(`${filename}.health.${format === 'json' ? 'json' : 'md'}`, text, format === 'json' ? 'application/json' : 'text/markdown;charset=utf-8')
    toast.success('已导出健康报告')
  }
  return <AppFrame><OperationalWorkspace title="健康概览" icon="diagnostics" context={dataset?.name ?? (datasetQuery.isPending ? '正在读取数据集…' : '数据集未取得')} back={() => router.push('/datasets')} actions={<>
    <Button variant="outline" onClick={() => router.push(`/datasets/${datasetId}/profile`)}><BarChart3 />数据画像</Button><DropdownMenu><DropdownMenuTrigger asChild><Button variant="outline" aria-label="导出健康报告" disabled={!health}><Download />导出</Button></DropdownMenuTrigger><DropdownMenuContent align="end"><DropdownMenuItem onSelect={() => exportHealth('json')}>JSON 报告</DropdownMenuItem><DropdownMenuItem onSelect={() => exportHealth('markdown')}>Markdown 报告</DropdownMenuItem></DropdownMenuContent></DropdownMenu><DropdownMenu><DropdownMenuTrigger asChild><Button variant="ghost" size="icon" aria-label="数据集操作"><MoreHorizontal /></Button></DropdownMenuTrigger><DropdownMenuContent align="end"><DropdownMenuItem onSelect={() => router.push(`/datasets/${datasetId}/precheck`)}>文档预检</DropdownMenuItem><DropdownMenuItem onSelect={() => router.push(`/datasets/${datasetId}/ingestion`)}>入库策略</DropdownMenuItem><DropdownMenuItem onSelect={() => router.push(`/datasets/${datasetId}/tables`)}>表格资产</DropdownMenuItem><DropdownMenuItem onSelect={() => { void datasetQuery.refetch(); void healthQuery.refetch() }}>重新读取健康概览</DropdownMenuItem></DropdownMenuContent></DropdownMenu>
  </>}>
    {loadError ? <WorkspaceNotice retry={() => { void datasetQuery.refetch(); void healthQuery.refetch() }} retryLabel="重新读取健康概览" pending={isLoading}>{health ? '更新失败，保留上次快照。' : null}{formatApiError(loadError, '健康概览读取失败')}</WorkspaceNotice> : null}
    {health ? <><WorkspaceMetrics items={[{ label: '文档总数', value: <span data-health-document-count>{profile?.total_documents ?? '—'}</span> },{ label: '总大小', value: totalSizeLabel },{ label: '处理失败', value: ingestion?.failed ?? '—', tone: (ingestion?.failed ?? 0) > 0 ? 'danger' : undefined },{ label: '隔离文档', value: ingestion?.quarantined ?? '—', tone: (ingestion?.quarantined ?? 0) > 0 ? 'warning' : undefined },{ label: '扫描版 PDF', value: scannedPdfLabel },{ label: '个人信息命中', value: profile ? piiTotal : '—' },{ label: '密钥命中', value: profile ? secretsTotal : '—' }]} />
      <section className={ws.section}><div className={ws.sectionHeading}><h2 className={ws.sectionTitle}>异常清单</h2><span className={ws.muted}>更新于 {generatedAtLabel}</span></div>{topFindings.length ? <div className={ws.tableScroll}><table aria-label="健康异常清单" className={ws.table}><thead><tr><th>问题与说明</th><th>级别</th><th className="text-right">命中文件</th></tr></thead><tbody>{topFindings.map(finding => <tr key={finding.key}><td><strong className="font-medium">{finding.label}</strong>{finding.description ? <p>{finding.description}</p> : null}</td><td><span className={finding.severity === 'error' ? 'text-destructive' : finding.severity === 'warning' ? ws.warning : ws.muted}>{finding.severity === 'error' ? '错误' : finding.severity === 'warning' ? '注意' : '提示'}</span></td><td className="text-right tabular-nums">{finding.count}</td></tr>)}</tbody></table></div> : <p className={ws.muted}>{profile ? '当前报告没有问题条目。' : '尚无可读取的画像报告。'}</p>}</section>
      <details className={ws.section}><summary className="cursor-pointer text-[15px] font-semibold">状态与格式分布</summary>          <div className={ws.charts}>
            <Panel variant="seamless" className={ws.section}>
              <div className="flex items-center justify-between mb-4">
                <div className="font-semibold">入库状态分布</div>
                <div className="text-xs text-muted-foreground font-mono">
                  {health?.generated_at ? `更新于 ${formatDate(health.generated_at)}` : ''}
                </div>
              </div>
              {statusChartData.length ? (
                <>
                  <SafeResponsiveChart className="h-[160px]" minHeight={160}>
                    <BarChart data={statusChartData} margin={{ top: 10, right: 10, left: 0, bottom: 0 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                      <XAxis dataKey="name" tick={{ fontSize: 12 }} />
                      <YAxis tick={{ fontSize: 12 }} allowDecimals={false} />
                      <Tooltip contentStyle={{ backgroundColor: 'hsl(var(--popover))', color: 'hsl(var(--popover-foreground))', borderColor: 'hsl(var(--border))' }} itemStyle={{ color: 'hsl(var(--popover-foreground))' }} />
                      <Bar isAnimationActive={false} dataKey="value" fill="hsl(var(--chart-1))" radius={[8, 8, 0, 0]} />
                    </BarChart>
                  </SafeResponsiveChart>
                  <div className="mt-3 flex flex-wrap gap-2">
                    {statusChartData.map((item) => (
                      <span key={item.name} className="inline-flex items-center gap-2 text-xs">
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

            <Panel variant="seamless" className={ws.section}>
              <div className="flex items-center justify-between mb-4">
                <div className="font-semibold">格式分布</div>
                <div className="text-xs text-muted-foreground font-mono">
                  {profile?.generated_at ? `更新于 ${formatDate(profile.generated_at)}` : ''}
                </div>
              </div>
              {fileTypeChartData.length ? (
                <>
                  <SafeResponsiveChart className="h-[160px]" minHeight={160}>
                    <PieChart>
                      <Pie isAnimationActive={false} data={fileTypeChartData} dataKey="value" nameKey="name" outerRadius={70} label />
                      <Tooltip contentStyle={{ backgroundColor: 'hsl(var(--popover))', color: 'hsl(var(--popover-foreground))', borderColor: 'hsl(var(--border))' }} itemStyle={{ color: 'hsl(var(--popover-foreground))' }} />
                    </PieChart>
                  </SafeResponsiveChart>
                  <div className="mt-3 flex flex-wrap gap-2">
                    {fileTypeChartData.map((item) => (
                      <span key={item.name} className="inline-flex items-center gap-2 text-xs">
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

</details>
    </> : <div className={ws.empty} role="status">{healthQuery.isPending ? '正在读取健康概览…' : '当前健康概览暂不可用。'}</div>}
  </OperationalWorkspace></AppFrame>
}
