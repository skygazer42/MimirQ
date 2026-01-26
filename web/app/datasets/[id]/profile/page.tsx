'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useParams, useRouter } from 'next/navigation'
import { toast } from 'sonner'
import {
  ArrowLeft,
  BarChart3,
  Download,
  FileSearch,
  Loader2,
  RefreshCw,
  Settings2,
  Sparkles,
} from 'lucide-react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import { AppFrame } from '@/components/app-frame'
import { PageScaffold } from '@/components/ui/page-scaffold'
import { Panel } from '@/components/ui/panel'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { Input } from '@/components/ui/input'
import { StatCard, StatsGrid } from '@/components/ui/stats-card'

import { datasetApi } from '@/lib/api-client'
import { formatApiError } from '@/lib/api-errors'
import { cn, formatFileSize, formatDate } from '@/lib/utils'

import type {
  Dataset,
  DatasetProfileFindingListResponse,
  DatasetProfileFindingSummary,
  DatasetProfileScanRunCreateRequest,
  DatasetProfileScanRunOut,
  DatasetProfileSummary,
} from '@/types'

const PIE_COLORS = ['#38bdf8', '#22c55e', '#f59e0b', '#fb7185', '#a78bfa', '#14b8a6', '#94a3b8']

function asDatasetId(raw: unknown): string | null {
  if (typeof raw === 'string' && raw.trim()) return raw
  if (Array.isArray(raw) && typeof raw[0] === 'string') return raw[0]
  return null
}

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

function findingBadgeVariant(sev: string): 'secondary' | 'outline' | 'soft' | 'destructive' {
  const s = String(sev || '').toLowerCase()
  if (s === 'error') return 'destructive'
  if (s === 'warning') return 'soft'
  return 'outline'
}

export default function DatasetProfilePage() {
  const router = useRouter()
  const params = useParams()
  const datasetId = asDatasetId((params as any)?.id)

  const [dataset, setDataset] = useState<Dataset | null>(null)
  const [summary, setSummary] = useState<DatasetProfileSummary | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [isExporting, setIsExporting] = useState(false)

  const [scanConfig, setScanConfig] = useState<DatasetProfileScanRunCreateRequest>({
    backfill_pdf_quality: true,
    backfill_text_quality: true,
    compute_file_hash: false,
    max_documents: null,
  })
  const [scanRun, setScanRun] = useState<DatasetProfileScanRunOut | null>(null)
  const [scanRunning, setScanRunning] = useState(false)
  const pollTimerRef = useRef<number | null>(null)

  const [findingOpen, setFindingOpen] = useState(false)
  const [selectedFinding, setSelectedFinding] = useState<DatasetProfileFindingSummary | null>(null)
  const [findingLoading, setFindingLoading] = useState(false)
  const [findingRes, setFindingRes] = useState<DatasetProfileFindingListResponse | null>(null)

  const stopPolling = useCallback(() => {
    const t = pollTimerRef.current
    if (t) window.clearTimeout(t)
    pollTimerRef.current = null
  }, [])

  const load = useCallback(async () => {
    if (!datasetId) return
    setIsLoading(true)
    try {
      const [ds, prof] = await Promise.all([
        datasetApi.get(datasetId),
        datasetApi.getProfileSummary(datasetId),
      ])
      setDataset(ds)
      setSummary(prof)
    } catch (e: any) {
      console.error('Failed to load dataset profile', e)
      toast.error(formatApiError(e, '加载数据画像失败'))
    } finally {
      setIsLoading(false)
    }
  }, [datasetId])

  useEffect(() => {
    void load()
    return () => stopPolling()
  }, [load, stopPolling])

  const fileTypeChartData = useMemo(() => {
    const m = summary?.by_file_type || {}
    return Object.entries(m)
      .map(([name, value]) => ({ name, value: Number(value || 0) }))
      .sort((a, b) => b.value - a.value)
      .slice(0, 12)
  }, [summary])

  const statusChartData = useMemo(() => {
    const m = summary?.by_status || {}
    return Object.entries(m).map(([name, value]) => ({ name, value: Number(value || 0) }))
  }, [summary])

  const lengthHistogramData = useMemo(() => {
    return (summary?.length_histogram || []).map((b) => ({ name: b.label, value: Number(b.count || 0) }))
  }, [summary])

  const fileSizeHistogramData = useMemo(() => {
    return (summary?.file_size_histogram || []).map((b) => ({ name: b.label, value: Number(b.count || 0) }))
  }, [summary])

  const pdfScanData = useMemo(() => {
    const s = summary?.pdf_scan
    if (!s) return []
    return [
      { name: 'scanned', value: Number(s.scanned || 0) },
      { name: 'text', value: Number(s.not_scanned || 0) },
      { name: 'unknown', value: Number(s.unknown || 0) },
    ]
  }, [summary])

  const openFinding = useCallback(
    async (finding: DatasetProfileFindingSummary) => {
      if (!datasetId) return
      setSelectedFinding(finding)
      setFindingOpen(true)
      setFindingLoading(true)
      try {
        const res = await datasetApi.listProfileFinding(datasetId, finding.key, { skip: 0, limit: 50 })
        setFindingRes(res)
      } catch (e: any) {
        console.error('Failed to load finding documents', e)
        toast.error(formatApiError(e, '加载清单失败'))
        setFindingRes(null)
      } finally {
        setFindingLoading(false)
      }
    },
    [datasetId]
  )

  const loadMoreFinding = useCallback(async () => {
    if (!datasetId || !selectedFinding || !findingRes) return
    if (findingRes.items.length >= findingRes.total) return
      const nextSkip = findingRes.items.length
      setFindingLoading(true)
      try {
        const res = await datasetApi.listProfileFinding(datasetId, selectedFinding.key, { skip: nextSkip, limit: 50 })
        setFindingRes({ total: res.total, items: [...findingRes.items, ...(res.items || [])] })
      } catch (e: any) {
        console.error('Failed to load more finding documents', e)
        toast.error(formatApiError(e, '加载更多失败'))
      } finally {
      setFindingLoading(false)
    }
  }, [datasetId, selectedFinding, findingRes])

  const pollScanRun = useCallback(
    async (datasetIdValue: string, runId: string) => {
      try {
        const next = await datasetApi.getProfileScanRun(datasetIdValue, runId)
        setScanRun(next)
        const st = String(next.status || '').toLowerCase()
        if (st === 'pending' || st === 'running') {
          pollTimerRef.current = window.setTimeout(() => void pollScanRun(datasetIdValue, runId), 2000)
          return
        }
        setScanRunning(false)
        stopPolling()
        void load()
      } catch (e: any) {
        console.error('Failed to poll scan run', e)
        setScanRunning(false)
        stopPolling()
      }
    },
    [load, stopPolling]
  )

  const startDeepScan = useCallback(async () => {
    if (!datasetId) return
    setScanRunning(true)
    try {
      const run = await datasetApi.startProfileScan(datasetId, scanConfig)
      setScanRun(run)
      const st = String(run.status || '').toLowerCase()
      if (st === 'pending' || st === 'running') {
        pollTimerRef.current = window.setTimeout(() => void pollScanRun(datasetId, run.id), 1200)
      } else {
        setScanRunning(false)
        void load()
      }
      toast.success('已启动深度扫描')
    } catch (e: any) {
      console.error('Failed to start scan', e)
      toast.error(formatApiError(e, '启动扫描失败'))
      setScanRunning(false)
    }
  }, [datasetId, scanConfig, pollScanRun, load])

  const exportJson = useCallback(async () => {
    if (!datasetId) return
    setIsExporting(true)
    try {
      const blob = await datasetApi.exportProfileSummary(datasetId)
      const safe = String(dataset?.name || 'dataset').replace(/[^a-zA-Z0-9_.-]+/g, '_').slice(0, 64)
      downloadBlob(blob, `${safe}.profile.json`)
      toast.success('已导出 JSON 报告')
    } catch (e: any) {
      console.error('Failed to export profile', e)
      toast.error(formatApiError(e, '导出失败'))
    } finally {
      setIsExporting(false)
    }
  }, [datasetId, dataset?.name])

  const latestRunStatus = summary?.latest_scan_run?.status || scanRun?.status
  const latestRunProgress = summary?.latest_scan_run?.progress ?? scanRun?.progress ?? 0

  return (
    <AppFrame>
      <PageScaffold
        title={`数据画像${dataset?.name ? ` · ${dataset.name}` : ''}`}
        badge="Dataset Profile"
        icon={BarChart3}
        iconColor="text-primary"
        description={
          <span className="text-sm text-muted-foreground">
            基于文档库元数据的入库前/入库中质量画像（格式、长度、扫描件、PII、重复等）
          </span>
        }
        actions={
          <div className="flex items-center gap-2">
            <Button variant="outline" className="gap-2" onClick={() => router.push('/datasets')}>
              <ArrowLeft className="w-4 h-4" />
              返回
            </Button>
            {datasetId ? (
              <Button variant="outline" className="gap-2" onClick={() => router.push(`/datasets/${datasetId}/ingestion`)}>
                <Settings2 className="w-4 h-4" />
                入库策略
              </Button>
            ) : null}
            <Button
              variant="outline"
              className="gap-2"
              onClick={() => void load()}
              disabled={isLoading}
            >
              <RefreshCw className={cn('w-4 h-4', isLoading && 'animate-spin motion-reduce:animate-none')} />
              刷新
            </Button>
            <Button
              variant="outline"
              className="gap-2"
              onClick={() => void exportJson()}
              disabled={isExporting || !summary}
            >
              {isExporting ? <Loader2 className="w-4 h-4 animate-spin motion-reduce:animate-none" /> : <Download className="w-4 h-4" />}
              导出
            </Button>
          </div>
        }
      >
        <div className="space-y-6">
          <Panel className="p-5">
            <StatsGrid>
              <StatCard icon={FileSearch} label="文档总数" value={summary?.total_documents ?? (isLoading ? '…' : 0)} color="cyan" />
              <StatCard icon={BarChart3} label="总大小" value={summary ? formatFileSize(summary.total_size_bytes || 0) : isLoading ? '…' : '-'} color="teal" />
              <StatCard icon={Sparkles} label="P50 长度" value={summary?.length_percentiles?.p50 ?? (isLoading ? '…' : 0)} subValue="chars" color="blue" />
              <StatCard icon={Sparkles} label="P90 长度" value={summary?.length_percentiles?.p90 ?? (isLoading ? '…' : 0)} subValue="chars" color="blue" />
              <StatCard icon={Sparkles} label="扫描 PDF" value={summary ? `${summary.pdf_scan.scanned}/${summary.pdf_scan.scanned + summary.pdf_scan.not_scanned + summary.pdf_scan.unknown}` : isLoading ? '…' : '-'} color="orange" />
            </StatsGrid>
          </Panel>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <Panel className="p-5">
              <div className="flex items-center justify-between mb-4">
                <div className="font-semibold">格式分布</div>
                <div className="text-xs text-muted-foreground font-mono">
                  {summary?.generated_at ? `updated ${formatDate(summary.generated_at)}` : ''}
                </div>
              </div>
              <div className="h-[280px]">
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart>
                    <Tooltip />
                    <Pie
                      data={fileTypeChartData}
                      dataKey="value"
                      nameKey="name"
                      innerRadius={55}
                      outerRadius={95}
                      paddingAngle={2}
                    >
                      {fileTypeChartData.map((_entry, idx) => (
                        <Cell key={idx} fill={PIE_COLORS[idx % PIE_COLORS.length]} />
                      ))}
                    </Pie>
                  </PieChart>
                </ResponsiveContainer>
              </div>
            </Panel>

            <Panel className="p-5">
              <div className="flex items-center justify-between mb-4">
                <div className="font-semibold">状态分布</div>
              </div>
              <div className="h-[280px]">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={statusChartData}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="name" fontSize={12} />
                    <YAxis allowDecimals={false} fontSize={12} />
                    <Tooltip />
                    <Bar dataKey="value" fill="#38bdf8" radius={[6, 6, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </Panel>

            <Panel className="p-5">
              <div className="flex items-center justify-between mb-4">
                <div className="font-semibold">长度分布（chars）</div>
              </div>
              <div className="h-[280px]">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={lengthHistogramData}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="name" fontSize={12} />
                    <YAxis allowDecimals={false} fontSize={12} />
                    <Tooltip />
                    <Bar dataKey="value" fill="#22c55e" radius={[6, 6, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </Panel>

            <Panel className="p-5">
              <div className="flex items-center justify-between mb-4">
                <div className="font-semibold">PDF 扫描占比</div>
              </div>
              <div className="h-[280px]">
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart>
                    <Tooltip />
                    <Pie data={pdfScanData} dataKey="value" nameKey="name" innerRadius={55} outerRadius={95} paddingAngle={2}>
                      {pdfScanData.map((_entry, idx) => (
                        <Cell key={idx} fill={['#fb7185', '#38bdf8', '#94a3b8'][idx % 3]} />
                      ))}
                    </Pie>
                  </PieChart>
                </ResponsiveContainer>
              </div>
            </Panel>

            <Panel className="p-5">
              <div className="flex items-center justify-between mb-4">
                <div className="font-semibold">文件大小分布</div>
              </div>
              <div className="h-[280px]">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={fileSizeHistogramData}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="name" fontSize={12} />
                    <YAxis allowDecimals={false} fontSize={12} />
                    <Tooltip />
                    <Bar dataKey="value" fill="#a78bfa" radius={[6, 6, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </Panel>
          </div>

          <Panel className="p-5">
            <div className="flex items-center justify-between gap-4 mb-4">
              <div className="font-semibold">问题清单（可操作）</div>
              <div className="text-xs text-muted-foreground">
                点击卡片查看文件列表（分页）
              </div>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
              {(summary?.findings || []).map((f) => (
                <button
                  key={f.key}
                  type="button"
                  className={cn(
                    'text-left px-4 py-3 rounded-xl border border-border/60 bg-card/40 hover:bg-card/70 transition-colors',
                    'focus:outline-none focus:ring-2 focus:ring-primary/30'
                  )}
                  onClick={() => void openFinding(f)}
                >
                  <div className="flex items-center justify-between gap-2">
                    <div className="font-medium truncate">{f.label}</div>
                    <Badge variant={findingBadgeVariant(f.severity)} className="font-mono text-xs">
                      {f.count}
                    </Badge>
                  </div>
                  {f.description ? (
                    <div className="mt-1 text-xs text-muted-foreground line-clamp-2">{f.description}</div>
                  ) : null}
                </button>
              ))}
            </div>
          </Panel>

          <Panel className="p-5">
            <div className="flex items-start justify-between gap-4">
              <div>
                <div className="font-semibold flex items-center gap-2">
                  深度扫描（补齐指标）
                  {latestRunStatus ? (
                    <Badge variant="outline" className="font-mono text-xs">
                      {String(latestRunStatus)}
                    </Badge>
                  ) : null}
                </div>
                <div className="text-sm text-muted-foreground mt-1">
                  用于补齐缺失的 pdf_quality / parsed_text_quality；可选计算 file_sha256（用于完全重复）。
                </div>
              </div>

              <Button className="gap-2" onClick={() => void startDeepScan()} disabled={scanRunning}>
                {scanRunning ? <Loader2 className="w-4 h-4 animate-spin motion-reduce:animate-none" /> : <Sparkles className="w-4 h-4" />}
                启动
              </Button>
            </div>

            <div className="mt-4 grid grid-cols-1 md:grid-cols-4 gap-4">
              <div className="flex items-center justify-between gap-3 p-3 rounded-lg border border-border/60 bg-muted/20">
                <Label className="text-sm">补齐 PDF 指标</Label>
                <Switch
                  checked={!!scanConfig.backfill_pdf_quality}
                  onCheckedChange={(v) => setScanConfig((prev) => ({ ...prev, backfill_pdf_quality: !!v }))}
                />
              </div>
              <div className="flex items-center justify-between gap-3 p-3 rounded-lg border border-border/60 bg-muted/20">
                <Label className="text-sm">补齐文本质量</Label>
                <Switch
                  checked={!!scanConfig.backfill_text_quality}
                  onCheckedChange={(v) => setScanConfig((prev) => ({ ...prev, backfill_text_quality: !!v }))}
                />
              </div>
              <div className="flex items-center justify-between gap-3 p-3 rounded-lg border border-border/60 bg-muted/20">
                <Label className="text-sm">计算 file_sha256</Label>
                <Switch
                  checked={!!scanConfig.compute_file_hash}
                  onCheckedChange={(v) => setScanConfig((prev) => ({ ...prev, compute_file_hash: !!v }))}
                />
              </div>
              <div className="flex items-center justify-between gap-3 p-3 rounded-lg border border-border/60 bg-muted/20">
                <Label className="text-sm">最大文档数</Label>
                <Input
                  value={scanConfig.max_documents ?? ''}
                  placeholder="不限"
                  onChange={(e) => {
                    const raw = e.target.value.trim()
                    if (!raw) {
                      setScanConfig((prev) => ({ ...prev, max_documents: null }))
                      return
                    }
                    const n = Number(raw)
                    setScanConfig((prev) => ({ ...prev, max_documents: Number.isFinite(n) ? Math.max(0, Math.floor(n)) : null }))
                  }}
                  className="w-28 font-mono text-sm"
                />
              </div>
            </div>

            <div className="mt-4 flex items-center justify-between gap-4">
              <div className="text-sm text-muted-foreground">
                进度：{scanRunning ? `${latestRunProgress || 0}%` : latestRunProgress ? `${latestRunProgress}%` : '-'}
                {scanRun?.error_message ? <span className="ml-3 text-destructive">错误：{scanRun.error_message}</span> : null}
              </div>
            </div>
          </Panel>
        </div>

        <Dialog open={findingOpen} onOpenChange={(open) => {
          setFindingOpen(open)
          if (!open) {
            setSelectedFinding(null)
            setFindingRes(null)
          }
        }}>
          <DialogContent className="max-w-4xl border-border bg-background/95 backdrop-blur-xl shadow-strong sm:rounded-2xl">
            <DialogHeader>
              <DialogTitle className="text-xl font-bold text-foreground flex items-center gap-2">
                {selectedFinding?.label || '清单'}
                {selectedFinding ? (
                  <Badge variant={findingBadgeVariant(selectedFinding.severity)} className="font-mono text-xs">
                    {selectedFinding.count}
                  </Badge>
                ) : null}
              </DialogTitle>
              <DialogDescription className="text-muted-foreground">
                {selectedFinding?.description || '点击文件名可在知识库页查看详情（后续可做联动）'}
              </DialogDescription>
            </DialogHeader>

            <div className="mt-2">
              {findingLoading && !findingRes ? (
                <div className="py-10 flex items-center justify-center text-muted-foreground">
                  <Loader2 className="w-5 h-5 animate-spin motion-reduce:animate-none mr-2" />
                  加载中…
                </div>
              ) : findingRes ? (
                <div className="space-y-3">
                  <div className="text-xs text-muted-foreground font-mono">
                    showing {findingRes.items.length}/{findingRes.total}
                  </div>
                  <div className="rounded-xl border border-border/60 overflow-hidden">
                    <table className="w-full text-sm text-left">
                      <thead className="bg-muted/40 text-muted-foreground">
                        <tr>
                          <th className="px-3 py-2 font-medium">文件名</th>
                          <th className="px-3 py-2 font-medium">类型</th>
                          <th className="px-3 py-2 font-medium">大小</th>
                          <th className="px-3 py-2 font-medium">状态</th>
                          <th className="px-3 py-2 font-medium">长度</th>
                        </tr>
                      </thead>
                      <tbody>
                        {findingRes.items.map((d) => (
                          <tr key={d.id} className="border-t border-border/60 hover:bg-muted/20 transition-colors">
                            <td className="px-3 py-2">
                              <button
                                type="button"
                                className="text-primary hover:underline"
                                onClick={() => router.push(`/knowledge?dataset=${datasetId}`)}
                              >
                                {d.filename}
                              </button>
                            </td>
                            <td className="px-3 py-2 font-mono text-xs">{d.file_type}</td>
                            <td className="px-3 py-2 font-mono text-xs">{formatFileSize(d.file_size || 0)}</td>
                            <td className="px-3 py-2">
                              <Badge variant="outline" className="font-mono text-xs">
                                {d.status}
                              </Badge>
                            </td>
                            <td className="px-3 py-2 font-mono text-xs">{d.total_characters}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>

                  <div className="flex items-center justify-between">
                    <div className="text-xs text-muted-foreground">
                      {findingRes.items.length >= findingRes.total ? '已加载全部' : ''}
                    </div>
                    <Button
                      variant="outline"
                      className="gap-2"
                      onClick={() => void loadMoreFinding()}
                      disabled={findingLoading || findingRes.items.length >= findingRes.total}
                    >
                      {findingLoading ? <Loader2 className="w-4 h-4 animate-spin motion-reduce:animate-none" /> : null}
                      加载更多
                    </Button>
                  </div>
                </div>
              ) : (
                <div className="py-10 text-center text-muted-foreground">
                  暂无数据
                </div>
              )}
            </div>
          </DialogContent>
        </Dialog>
      </PageScaffold>
    </AppFrame>
  )
}
