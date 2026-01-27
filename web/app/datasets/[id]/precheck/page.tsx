'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useParams, useRouter } from 'next/navigation'
import { toast } from 'sonner'
import { ArrowLeft, Download, FileSearch, Loader2, RefreshCw, Settings2, Sparkles } from 'lucide-react'
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
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { StatCard, StatsGrid } from '@/components/ui/stats-card'

import { datasetApi } from '@/lib/api-client'
import { formatApiError } from '@/lib/api-errors'
import { cn, formatFileSize, formatDate } from '@/lib/utils'

import type {
  Dataset,
  DatasetPrecheckFindingListResponse,
  DatasetPrecheckFindingSummary,
  DatasetPrecheckScanRunCreateRequest,
  DatasetPrecheckScanRunOut,
  DatasetPrecheckSummary,
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

export default function DatasetPrecheckPage() {
  const router = useRouter()
  const params = useParams()
  const datasetId = asDatasetId((params as any)?.id)

  const [dataset, setDataset] = useState<Dataset | null>(null)
  const [runs, setRuns] = useState<DatasetPrecheckScanRunOut[]>([])
  const [selectedRun, setSelectedRun] = useState<DatasetPrecheckScanRunOut | null>(null)
  const [summary, setSummary] = useState<DatasetPrecheckSummary | null>(null)

  const [loading, setLoading] = useState(false)
  const [scanRunning, setScanRunning] = useState(false)
  const pollTimerRef = useRef<number | null>(null)

  const [isExporting, setIsExporting] = useState(false)

  const [scanConfig, setScanConfig] = useState<DatasetPrecheckScanRunCreateRequest>({
    root_path: '',
    max_files: null,
    enable_pdf_quality: true,
    enable_text_extract: true,
    enable_pii: false,
    enable_secrets: false,
    compute_file_hash: false,
    pdf_sample_pages: null,
    text_extract_max_bytes: null,
    redact_paths: false,
    pdf_min_text_chars_per_page: null,
    pdf_text_chars_per_page: null,
    pdf_scan_ratio_threshold: null,
    enable_pii_samples: false,
    pii_context_chars: null,
    pii_max_samples_per_file: null,
    enable_secrets_samples: false,
    secrets_context_chars: null,
    secrets_max_samples_per_file: null,
    enable_near_dup: false,
    near_dup_hamming_threshold: null,
    near_dup_max_pairs: null,
    enable_sampling: true,
    sample_size: null,
    reuse_unchanged_files: false,
    reuse_from_scan_run_id: null,
  })

  const [findingOpen, setFindingOpen] = useState(false)
  const [selectedFinding, setSelectedFinding] = useState<DatasetPrecheckFindingSummary | null>(null)
  const [findingLoading, setFindingLoading] = useState(false)
  const [findingRes, setFindingRes] = useState<DatasetPrecheckFindingListResponse | null>(null)

  const stopPolling = useCallback(() => {
    const t = pollTimerRef.current
    if (t) window.clearTimeout(t)
    pollTimerRef.current = null
  }, [])

  const loadRuns = useCallback(async () => {
    if (!datasetId) return
    try {
      const res = await datasetApi.listPrecheckScanRuns(datasetId, { skip: 0, limit: 20 })
      setRuns(res.items || [])
      if (!selectedRun && (res.items || []).length) {
        setSelectedRun(res.items[0])
      }
    } catch (e: any) {
      console.error('Failed to load precheck runs', e)
    }
  }, [datasetId, selectedRun])

  const load = useCallback(async () => {
    if (!datasetId) return
    setLoading(true)
    try {
      const [ds, runList] = await Promise.all([
        datasetApi.get(datasetId),
        datasetApi.listPrecheckScanRuns(datasetId, { skip: 0, limit: 20 }),
      ])
      setDataset(ds)
      setRuns(runList.items || [])
      const first = (runList.items || [])[0] || null
      setSelectedRun((prev) => prev || first)
    } catch (e: any) {
      console.error('Failed to load dataset precheck', e)
      toast.error(formatApiError(e, '加载预检页面失败'))
    } finally {
      setLoading(false)
    }
  }, [datasetId])

  useEffect(() => {
    void load()
    return () => stopPolling()
  }, [load, stopPolling])

  const pollRun = useCallback(
    async (datasetIdValue: string, runId: string) => {
      try {
        const next = await datasetApi.getPrecheckScanRun(datasetIdValue, runId)
        setSelectedRun(next)
        const st = String(next.status || '').toLowerCase()
        if (st === 'pending' || st === 'running') {
          pollTimerRef.current = window.setTimeout(() => void pollRun(datasetIdValue, runId), 2000)
          return
        }
        setScanRunning(false)
        stopPolling()
        await loadRuns()
        if (st === 'completed') {
          const s = await datasetApi.getPrecheckSummary(datasetIdValue, runId)
          setSummary(s)
        } else if (next.error_message) {
          toast.error(`预检扫描失败：${next.error_message}`)
        }
      } catch (e: any) {
        console.error('Failed to poll precheck run', e)
        setScanRunning(false)
        stopPolling()
      }
    },
    [loadRuns, stopPolling]
  )

  // When selectedRun changes, load summary (if available) and resume polling (if running).
  useEffect(() => {
    if (!datasetId || !selectedRun?.id) return
    const st = String(selectedRun.status || '').toLowerCase()
    if (st === 'pending' || st === 'running') {
      if (!pollTimerRef.current) {
        setScanRunning(true)
        pollTimerRef.current = window.setTimeout(() => void pollRun(datasetId, selectedRun.id), 800)
      }
      return
    }
    setScanRunning(false)
    stopPolling()
    if (st === 'completed') {
      void datasetApi
        .getPrecheckSummary(datasetId, selectedRun.id)
        .then(setSummary)
        .catch(() => setSummary(null))
      return
    }
    setSummary(null)
  }, [datasetId, pollRun, selectedRun, stopPolling])

  const startScan = useCallback(async () => {
    if (!datasetId) return
    if (!scanConfig.root_path?.trim()) {
      toast.error('请输入要扫描的文件夹路径（root_path）')
      return
    }
    setScanRunning(true)
    try {
      const run = await datasetApi.startPrecheckScan(datasetId, scanConfig)
      setSelectedRun(run)
      await loadRuns()
      const st = String(run.status || '').toLowerCase()
      if (st === 'pending' || st === 'running') {
        pollTimerRef.current = window.setTimeout(() => void pollRun(datasetId, run.id), 800)
      } else {
        setScanRunning(false)
      }
      toast.success('已启动预检扫描')
    } catch (e: any) {
      console.error('Failed to start precheck scan', e)
      toast.error(formatApiError(e, '启动预检扫描失败'))
      setScanRunning(false)
    }
  }, [datasetId, loadRuns, pollRun, scanConfig])

  const exportJson = useCallback(async () => {
    if (!datasetId || !selectedRun?.id) return
    setIsExporting(true)
    try {
      const blob = await datasetApi.exportPrecheckSummary(datasetId, selectedRun.id)
      const safe = String(dataset?.name || 'dataset').replace(/[^a-zA-Z0-9_.-]+/g, '_').slice(0, 64)
      downloadBlob(blob, `${safe}.precheck.json`)
      toast.success('已导出 JSON 报告')
    } catch (e: any) {
      console.error('Failed to export precheck json', e)
      toast.error(formatApiError(e, '导出失败'))
    } finally {
      setIsExporting(false)
    }
  }, [datasetId, dataset?.name, selectedRun?.id])

  const exportHtml = useCallback(async () => {
    if (!datasetId || !selectedRun?.id) return
    setIsExporting(true)
    try {
      const blob = await datasetApi.exportPrecheckHtml(datasetId, selectedRun.id, { redact: true })
      const safe = String(dataset?.name || 'dataset').replace(/[^a-zA-Z0-9_.-]+/g, '_').slice(0, 64)
      downloadBlob(blob, `${safe}.precheck.html`)
      toast.success('已导出 HTML 报告')
    } catch (e: any) {
      console.error('Failed to export precheck html', e)
      toast.error(formatApiError(e, '导出失败'))
    } finally {
      setIsExporting(false)
    }
  }, [datasetId, dataset?.name, selectedRun?.id])

  const fileTypeChartData = useMemo(() => {
    const m = summary?.by_file_type || {}
    const entries = Object.entries(m)
      .map(([name, value]) => ({ name, value: Number(value || 0) }))
      .filter((x) => x.value > 0)
      .sort((a, b) => b.value - a.value)
    const top = entries.slice(0, 10)
    const rest = entries.slice(10)
    const other = rest.reduce((acc, x) => acc + x.value, 0)
    if (other > 0) top.push({ name: '其他', value: other })
    return top
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

  const piiChartData = useMemo(() => {
    const m = summary?.pii_hits_total || {}
    return Object.entries(m)
      .map(([name, value]) => ({ name, value: Number(value || 0) }))
      .filter((x) => x.value > 0)
      .sort((a, b) => b.value - a.value)
      .slice(0, 10)
  }, [summary])

  const secretsChartData = useMemo(() => {
    const m = summary?.secrets_hits_total || {}
    return Object.entries(m)
      .map(([name, value]) => ({ name, value: Number(value || 0) }))
      .filter((x) => x.value > 0)
      .sort((a, b) => b.value - a.value)
      .slice(0, 10)
  }, [summary])

  const openFinding = useCallback(
    async (finding: DatasetPrecheckFindingSummary) => {
      if (!datasetId || !selectedRun?.id) return
      setSelectedFinding(finding)
      setFindingOpen(true)
      setFindingLoading(true)
      try {
        const res = await datasetApi.listPrecheckFinding(datasetId, selectedRun.id, finding.key, { skip: 0, limit: 50 })
        setFindingRes(res)
      } catch (e: any) {
        console.error('Failed to load precheck finding', e)
        toast.error(formatApiError(e, '加载清单失败'))
        setFindingRes(null)
      } finally {
        setFindingLoading(false)
      }
    },
    [datasetId, selectedRun?.id]
  )

  const loadMoreFinding = useCallback(async () => {
    if (!datasetId || !selectedRun?.id || !selectedFinding || !findingRes) return
    if (findingRes.items.length >= findingRes.total) return
    const nextSkip = findingRes.items.length
    setFindingLoading(true)
    try {
      const res = await datasetApi.listPrecheckFinding(datasetId, selectedRun.id, selectedFinding.key, { skip: nextSkip, limit: 50 })
      setFindingRes({ total: res.total, items: [...findingRes.items, ...(res.items || [])] })
    } catch (e: any) {
      console.error('Failed to load more precheck finding', e)
      toast.error(formatApiError(e, '加载更多失败'))
    } finally {
      setFindingLoading(false)
    }
  }, [datasetId, findingRes, selectedFinding, selectedRun?.id])

  const latestRunStatus = selectedRun?.status
  const latestRunProgress = selectedRun?.progress ?? 0

  return (
    <AppFrame>
      <PageScaffold
        title="预检扫描（未入库）"
        badge="Precheck"
        icon={FileSearch}
        iconColor="text-primary"
        description={
          <span className="text-sm text-muted-foreground">
            数据集：<span className="text-foreground font-medium">{dataset?.name || datasetId}</span> · 扫描本地文件夹，生成结构/质量画像（格式、扫描件、长度、PII/Secrets 等）
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
            <Button variant="outline" className="gap-2" onClick={() => void load()} disabled={loading}>
              <RefreshCw className={cn('w-4 h-4', loading && 'animate-spin motion-reduce:animate-none')} />
              刷新
            </Button>
            <Button variant="outline" className="gap-2" onClick={() => void exportJson()} disabled={isExporting || !selectedRun?.id || !summary}>
              {isExporting ? <Loader2 className="w-4 h-4 animate-spin motion-reduce:animate-none" /> : <Download className="w-4 h-4" />}
              导出 JSON
            </Button>
            <Button variant="outline" className="gap-2" onClick={() => void exportHtml()} disabled={isExporting || !selectedRun?.id || !summary}>
              {isExporting ? <Loader2 className="w-4 h-4 animate-spin motion-reduce:animate-none" /> : <Download className="w-4 h-4" />}
              导出 HTML
            </Button>
          </div>
        }
      >
        <div className="space-y-6">
          <Panel className="p-5">
            <div className="flex items-start justify-between gap-4">
              <div className="min-w-0">
                <div className="font-semibold flex items-center gap-2">
                  启动预检扫描
                  {latestRunStatus ? (
                    <Badge variant="outline" className="font-mono text-xs">
                      {String(latestRunStatus)}
                    </Badge>
                  ) : null}
                </div>
                <div className="text-sm text-muted-foreground mt-1">
                  说明：后端需要启用 <span className="font-mono">LOCAL_SCAN_ENABLED</span> 且扫描路径需在允许的根目录内（或 uploads 下）。
                </div>
              </div>

              <Button className="gap-2" onClick={() => void startScan()} disabled={scanRunning}>
                {scanRunning ? <Loader2 className="w-4 h-4 animate-spin motion-reduce:animate-none" /> : <Sparkles className="w-4 h-4" />}
                启动
              </Button>
            </div>

            <div className="mt-4 grid grid-cols-1 md:grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label>root_path（文件夹路径）</Label>
                <Input
                  placeholder="例如：/data/docs 或 C:\\\\docs（需容器/进程可访问）"
                  value={scanConfig.root_path || ''}
                  onChange={(e) => setScanConfig((prev) => ({ ...prev, root_path: e.target.value }))}
                />
              </div>

              <div className="space-y-2">
                <Label>最大文件数（可选）</Label>
                <Input
                  placeholder="不限"
                  value={scanConfig.max_files ?? ''}
                  onChange={(e) => {
                    const raw = e.target.value.trim()
                    if (!raw) {
                      setScanConfig((prev) => ({ ...prev, max_files: null }))
                      return
                    }
                    const n = Number(raw)
                    setScanConfig((prev) => ({ ...prev, max_files: Number.isFinite(n) ? Math.max(0, Math.floor(n)) : null }))
                  }}
                  className="font-mono"
                />
              </div>
            </div>

            <div className="mt-4 grid grid-cols-1 md:grid-cols-4 gap-4">
              <div className="flex items-center justify-between gap-3 p-3 rounded-lg border border-border/60 bg-muted/20">
                <Label className="text-sm">PDF 质量</Label>
                <Switch checked={!!scanConfig.enable_pdf_quality} onCheckedChange={(v) => setScanConfig((p) => ({ ...p, enable_pdf_quality: !!v }))} />
              </div>
              <div className="flex items-center justify-between gap-3 p-3 rounded-lg border border-border/60 bg-muted/20">
                <Label className="text-sm">文本抽样</Label>
                <Switch checked={!!scanConfig.enable_text_extract} onCheckedChange={(v) => setScanConfig((p) => ({ ...p, enable_text_extract: !!v }))} />
              </div>
              <div className="flex items-center justify-between gap-3 p-3 rounded-lg border border-border/60 bg-muted/20">
                <Label className="text-sm">PII 检测</Label>
                <Switch checked={!!scanConfig.enable_pii} onCheckedChange={(v) => setScanConfig((p) => ({ ...p, enable_pii: !!v }))} />
              </div>
              <div className="flex items-center justify-between gap-3 p-3 rounded-lg border border-border/60 bg-muted/20">
                <Label className="text-sm">Secrets 检测</Label>
                <Switch checked={!!scanConfig.enable_secrets} onCheckedChange={(v) => setScanConfig((p) => ({ ...p, enable_secrets: !!v }))} />
              </div>
            </div>

            <div className="mt-4 grid grid-cols-1 md:grid-cols-2 gap-4">
              <div className="flex items-center justify-between gap-3 p-3 rounded-lg border border-border/60 bg-muted/20">
                <Label className="text-sm">计算 file_sha256（重复）</Label>
                <Switch checked={!!scanConfig.compute_file_hash} onCheckedChange={(v) => setScanConfig((p) => ({ ...p, compute_file_hash: !!v }))} />
              </div>
              <div className="flex items-center justify-between gap-3 p-3 rounded-lg border border-border/60 bg-muted/20">
                <Label className="text-sm">脱敏路径（分享用）</Label>
                <Switch checked={!!scanConfig.redact_paths} onCheckedChange={(v) => setScanConfig((p) => ({ ...p, redact_paths: !!v }))} />
              </div>
            </div>

            <div className="mt-4 flex items-center justify-between gap-4">
              <div className="text-sm text-muted-foreground">
                进度：{scanRunning ? `${latestRunProgress || 0}%` : latestRunProgress ? `${latestRunProgress}%` : '-'}
                {selectedRun?.error_message ? <span className="ml-3 text-destructive">错误：{selectedRun.error_message}</span> : null}
              </div>
            </div>
          </Panel>

          <Panel className="p-5">
            <StatsGrid>
              <StatCard icon={FileSearch} label="文件总数" value={summary?.total_files ?? (loading ? '…' : 0)} color="cyan" />
              <StatCard icon={FileSearch} label="总大小" value={summary ? formatFileSize(summary.total_size_bytes || 0) : loading ? '…' : '-'} color="teal" />
              <StatCard icon={Sparkles} label="P50 长度" value={summary?.length_percentiles?.p50 ?? (loading ? '…' : 0)} subValue="chars" color="blue" />
              <StatCard icon={Sparkles} label="P90 长度" value={summary?.length_percentiles?.p90 ?? (loading ? '…' : 0)} subValue="chars" color="blue" />
              <StatCard icon={Sparkles} label="扫描 PDF" value={summary ? `${summary.pdf_scan.scanned}/${summary.pdf_scan.scanned + summary.pdf_scan.not_scanned + summary.pdf_scan.unknown}` : loading ? '…' : '-'} color="orange" />
            </StatsGrid>
          </Panel>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <Panel className="p-5">
              <div className="flex items-center justify-between mb-4">
                <div className="font-semibold">格式分布</div>
                <div className="text-xs text-muted-foreground font-mono">{summary?.generated_at ? `updated ${formatDate(summary.generated_at)}` : ''}</div>
              </div>
              <div className="h-[280px]">
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart>
                    <Tooltip />
                    <Pie data={fileTypeChartData} dataKey="value" nameKey="name" innerRadius={55} outerRadius={95} paddingAngle={2}>
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

            <Panel className="p-5">
              <div className="flex items-center justify-between mb-4">
                <div className="font-semibold">PII 命中（次数）</div>
              </div>
              {piiChartData.length ? (
                <div className="h-[280px]">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={piiChartData}>
                      <CartesianGrid strokeDasharray="3 3" />
                      <XAxis dataKey="name" fontSize={12} />
                      <YAxis allowDecimals={false} fontSize={12} />
                      <Tooltip />
                      <Bar dataKey="value" fill="#f59e0b" radius={[6, 6, 0, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              ) : (
                <div className="h-[280px] flex items-center justify-center text-muted-foreground">暂无数据</div>
              )}
            </Panel>

            <Panel className="p-5">
              <div className="flex items-center justify-between mb-4">
                <div className="font-semibold">Secrets/Token 命中（次数）</div>
              </div>
              {secretsChartData.length ? (
                <div className="h-[280px]">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={secretsChartData}>
                      <CartesianGrid strokeDasharray="3 3" />
                      <XAxis dataKey="name" fontSize={12} />
                      <YAxis allowDecimals={false} fontSize={12} />
                      <Tooltip />
                      <Bar dataKey="value" fill="#fb7185" radius={[6, 6, 0, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              ) : (
                <div className="h-[280px] flex items-center justify-center text-muted-foreground">暂无数据</div>
              )}
            </Panel>
          </div>

          <Panel className="p-5">
            <div className="flex items-center justify-between gap-4 mb-4">
              <div className="font-semibold">问题清单（可操作）</div>
              <div className="text-xs text-muted-foreground">点击卡片查看文件列表（分页）</div>
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
                  {f.description ? <div className="mt-1 text-xs text-muted-foreground line-clamp-2">{f.description}</div> : null}
                </button>
              ))}
            </div>
          </Panel>
        </div>

        <Dialog
          open={findingOpen}
          onOpenChange={(open) => {
            setFindingOpen(open)
            if (!open) {
              setSelectedFinding(null)
              setFindingRes(null)
            }
          }}
        >
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
                {selectedFinding?.description || '预检扫描的文件列表（不入库，不产生切片）'}
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
                          <th className="px-3 py-2 font-medium">文件</th>
                          <th className="px-3 py-2 font-medium">类型</th>
                          <th className="px-3 py-2 font-medium">大小</th>
                          <th className="px-3 py-2 font-medium">长度</th>
                          <th className="px-3 py-2 font-medium">估算</th>
                        </tr>
                      </thead>
                      <tbody>
                        {findingRes.items.map((d) => (
                          <tr key={`${d.name}-${d.file_type}-${d.file_size}`} className="border-t border-border/60 hover:bg-muted/20 transition-colors">
                            <td className="px-3 py-2 font-mono text-xs">{d.name}</td>
                            <td className="px-3 py-2 font-mono text-xs">{d.file_type}</td>
                            <td className="px-3 py-2 font-mono text-xs">{formatFileSize(d.file_size || 0)}</td>
                            <td className="px-3 py-2 font-mono text-xs">{d.text_characters}</td>
                            <td className="px-3 py-2 font-mono text-xs">{d.estimated_text ? 'yes' : ''}</td>
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
                <div className="py-10 text-center text-muted-foreground">暂无数据</div>
              )}
            </div>
          </DialogContent>
        </Dialog>
      </PageScaffold>
    </AppFrame>
  )
}
