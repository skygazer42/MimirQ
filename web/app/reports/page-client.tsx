'use client'

import { wrap, type Remote } from 'comlink'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { toast } from 'sonner'
import { AlertTriangle, BarChart3, Database, Download, FileSearch, FileText, FolderTree, Gauge, Layers, Loader2, RefreshCw, ShieldAlert, SlidersHorizontal, Tags } from 'lucide-react'
import { Bar, BarChart, CartesianGrid, Cell, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'

import { AppFrame } from '@/components/app-frame'
import { AnalysisPageShell } from '@/components/ui/analysis-page-shell'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { EmptyState } from '@/components/ui/empty-state'
import { Input } from '@/components/ui/input'
import { SearchInput } from '@/components/ui/search-input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { StatCard, StatsGrid } from '@/components/ui/stats-card'

import { datasetApi, datasetCategoryApi } from '@/lib/api/datasets'
import { reportApi } from '@/lib/api/reports'
import { formatApiError } from '@/lib/api-errors'
import { flattenFolderTree } from '@/lib/report-transforms'
import { sanitizeFilename } from '@/lib/sanitize'
import { formatDate, formatFileSize, detachPromise } from '@/lib/utils'

import type { FlatFolderRow } from '@/lib/report-transforms'
import type { Dataset, DatasetCategoryNode, DatasetReport } from '@/types'
import type { ReportTransformsWorkerApi } from '@/workers/report-transforms.worker'

const PIE_COLORS = ['#3b82f6', '#0ea5e9', '#14b8a6', '#22c55e', '#f59e0b', '#6366f1', '#64748b']
const CHART_TOOLTIP_STYLE = {
  borderRadius: 10,
  border: '1px solid #cbd5e1',
  background: 'rgba(255,255,255,0.96)',
  boxShadow: '0 8px 26px rgba(15,23,42,0.12)',
  padding: '8px 10px',
}
const CHART_TOOLTIP_LABEL_STYLE = { color: '#334155', fontWeight: 600 }
const CHART_TOOLTIP_CURSOR = { fill: 'rgba(148,163,184,0.08)' }

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  globalThis.window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}

export default function ReportsCenterPage() {
  const [datasets, setDatasets] = useState<Dataset[]>([])
  const [datasetId, setDatasetId] = useState<string>('')
  const [pipelineHash, setPipelineHash] = useState<string>('')
  const [connectorRunsLimit, setConnectorRunsLimit] = useState<number>(20)
  const [redact, setRedact] = useState<boolean>(true)

  const [isLoadingDatasets, setIsLoadingDatasets] = useState(false)
  const [isLoadingReport, setIsLoadingReport] = useState(false)
  const [isExportingJson, setIsExportingJson] = useState(false)
  const [isExportingHtml, setIsExportingHtml] = useState(false)
  const [isExportingRagAuditHtml, setIsExportingRagAuditHtml] = useState(false)

  const [report, setReport] = useState<DatasetReport | null>(null)
  const [folderQuery, setFolderQuery] = useState<string>('')
  const [categoryQuery, setCategoryQuery] = useState<string>('')
  const [categoryTree, setCategoryTree] = useState<DatasetCategoryNode[]>([])
  const [isLoadingCategories, setIsLoadingCategories] = useState(false)

  const [flatFolders, setFlatFolders] = useState<FlatFolderRow[] | null>(null)
  const transformsWorkerRef = useRef<Worker | null>(null)
  const transformsApiRef = useRef<Remote<ReportTransformsWorkerApi> | null>(null)
  const transformsDisabledRef = useRef(false)
  const flatFoldersSeqRef = useRef(0)

  const selectedDataset = useMemo(() => datasets.find((d) => d.id === datasetId) || null, [datasets, datasetId])

  const loadDatasets = useCallback(async () => {
    setIsLoadingDatasets(true)
    try {
      const res = await datasetApi.list({ skip: 0, limit: 200 })
      const items = res?.items || []
      setDatasets(items)
      if (!datasetId && items.length > 0) setDatasetId(items[0].id)
    } catch (e: any) {
      console.error('Failed to load datasets', e)
      toast.error(formatApiError(e, '加载数据集失败'))
    } finally {
      setIsLoadingDatasets(false)
    }
  }, [datasetId])

  const loadReport = useCallback(async () => {
    if (!datasetId) return
    setIsLoadingReport(true)
    try {
      const r = await reportApi.getDatasetReport(datasetId, {
        pipeline_hash: pipelineHash.trim() || undefined,
        connector_runs_limit: connectorRunsLimit,
      })
      setReport(r)
    } catch (e: any) {
      console.error('Failed to load dataset report', e)
      toast.error(formatApiError(e, '加载报告预览失败'))
      setReport(null)
    } finally {
      setIsLoadingReport(false)
    }
  }, [connectorRunsLimit, datasetId, pipelineHash])

  const loadCategories = useCallback(async () => {
    setIsLoadingCategories(true)
    try {
      const res = await datasetCategoryApi.listTree()
      setCategoryTree(res.items || [])
    } catch (e: any) {
      console.error('Failed to load dataset categories', e)
      toast.error(formatApiError(e, '加载分类失败'))
      setCategoryTree([])
    } finally {
      setIsLoadingCategories(false)
    }
  }, [])

  useEffect(() => {
    detachPromise(loadDatasets())
  }, [loadDatasets])

  useEffect(() => {
    detachPromise(loadCategories())
  }, [loadCategories])

  useEffect(() => {
    detachPromise(loadReport())
  }, [loadReport])

  useEffect(() => {
    return () => {
      if (transformsWorkerRef.current) {
        transformsWorkerRef.current.terminate()
        transformsWorkerRef.current = null
        transformsApiRef.current = null
      }
    }
  }, [])

  const handleExportJson = useCallback(async () => {
    if (!datasetId) return
    setIsExportingJson(true)
    try {
      const blob = await reportApi.exportDatasetReportJson(datasetId, {
        pipeline_hash: pipelineHash.trim() || undefined,
        connector_runs_limit: connectorRunsLimit,
      })
      const safe = sanitizeFilename(selectedDataset?.name || 'dataset')
      const suffix = pipelineHash.trim() ? `.${pipelineHash.trim().slice(0, 8)}` : ''
      downloadBlob(blob, `${safe}.report${suffix}.json`)
    } catch (e: any) {
      console.error('Export report json failed', e)
      toast.error(formatApiError(e, '导出 JSON 报告失败'))
    } finally {
      setIsExportingJson(false)
    }
  }, [connectorRunsLimit, datasetId, pipelineHash, selectedDataset?.name])

  const handleExportHtml = useCallback(async () => {
    if (!datasetId) return
    setIsExportingHtml(true)
    try {
      const blob = await reportApi.exportDatasetReportHtml(datasetId, {
        pipeline_hash: pipelineHash.trim() || undefined,
        connector_runs_limit: connectorRunsLimit,
        redact,
      })
      const safe = sanitizeFilename(selectedDataset?.name || 'dataset')
      const suffix = pipelineHash.trim() ? `.${pipelineHash.trim().slice(0, 8)}` : ''
      downloadBlob(blob, `${safe}.report${suffix}.html`)
    } catch (e: any) {
      console.error('Export report html failed', e)
      toast.error(formatApiError(e, '导出 HTML 报告失败'))
    } finally {
      setIsExportingHtml(false)
    }
  }, [connectorRunsLimit, datasetId, pipelineHash, redact, selectedDataset?.name])

  const handleExportRagAuditHtml = useCallback(async () => {
    if (!datasetId) return
    setIsExportingRagAuditHtml(true)
    try {
      const blob = await reportApi.exportDatasetRagAuditHtml(datasetId, {
        pipeline_hash: pipelineHash.trim() || undefined,
        connector_runs_limit: connectorRunsLimit,
        redact,
      })
      const safe = sanitizeFilename(selectedDataset?.name || 'dataset')
      const suffix = pipelineHash.trim() ? `.${pipelineHash.trim().slice(0, 8)}` : ''
      downloadBlob(blob, `${safe}.rag_audit${suffix}.html`)
    } catch (e: any) {
      console.error('Export rag audit html failed', e)
      toast.error(formatApiError(e, '导出 RAG Audit 报告失败'))
    } finally {
      setIsExportingRagAuditHtml(false)
    }
  }, [connectorRunsLimit, datasetId, pipelineHash, redact, selectedDataset?.name])

  const totalDocs = report?.profile?.total_documents || 0
  const totalBytes = report?.profile?.total_size_bytes || 0
  const quarantined = report?.compliance?.quarantined_documents || 0
  const failed = report?.compliance?.failed_documents || 0
  const pipelineVersions = report?.pipeline_versions || []
  const connectorRuns = report?.connectors || []
  const folderTree = report?.folder_tree || null
  const governance = report?.governance_metrics || null
  const governanceAudit = report?.governance_audit || null

  useEffect(() => {
    const seq = ++flatFoldersSeqRef.current

    if (!folderTree) {
      setFlatFolders(null)
      return
    }

    // Null => computed pending for this folder tree.
    setFlatFolders(null)

    const computeSync = () => {
      try {
        const rows = flattenFolderTree(folderTree)
        if (flatFoldersSeqRef.current === seq) setFlatFolders(rows)
      } catch (e) {
        console.warn('Failed to flatten folder tree; falling back to empty list', e)
        if (flatFoldersSeqRef.current === seq) setFlatFolders([])
      }
    }

    if (transformsDisabledRef.current || typeof Worker === 'undefined') {
      computeSync()
      return
    }

    let cancelled = false
    detachPromise((async () => {
      try {
        if (!transformsWorkerRef.current || !transformsApiRef.current) {
          transformsWorkerRef.current = new Worker(new URL('../../workers/report-transforms.worker.ts', import.meta.url), { type: 'module' })
          transformsApiRef.current = wrap<ReportTransformsWorkerApi>(transformsWorkerRef.current)
        }

        const rows = await transformsApiRef.current.flattenFolderTree(folderTree)
        if (cancelled) return
        if (flatFoldersSeqRef.current !== seq) return
        setFlatFolders(rows)
      } catch (e) {
        // If the environment can't load a worker bundle (or Comlink fails), keep the page functional.
        console.warn('Report transforms worker failed; falling back to main thread', e)
        transformsDisabledRef.current = true
        computeSync()
      }
    })())

    return () => {
      cancelled = true
    }
  }, [folderTree])

  const folderBarData = useMemo(() => {
    const rows = flatFolders ?? []
    const q = folderQuery.trim().toLowerCase()
    const filtered = q ? rows.filter((f) => f.path.toLowerCase().includes(q)) : rows
    return filtered
      .slice()
      .sort((a, b) => b.documents - a.documents)
      .slice(0, 12)
      .map((f) => ({ name: f.path || '/', value: Number(f.documents || 0) }))
  }, [flatFolders, folderQuery])

  const flatCategories = useMemo(() => {
    const out: Array<{ id: string; name: string; depth: number; datasets: number }> = []
    const walk = (node: DatasetCategoryNode) => {
      out.push({
        id: String(node.id),
        name: String(node.name || ''),
        depth: Number(node.depth || 0),
        datasets: Number(node.datasets || 0),
      })
      for (const child of node.children || []) walk(child)
    }
    for (const n of categoryTree || []) walk(n)
    return out
  }, [categoryTree])

  const categoryBarData = useMemo(() => {
    const q = categoryQuery.trim().toLowerCase()
    const filtered = q ? flatCategories.filter((c) => c.name.toLowerCase().includes(q)) : flatCategories
    return filtered
      .slice()
      .sort((a, b) => b.datasets - a.datasets)
      .slice(0, 12)
      .map((c) => ({ name: c.name || c.id, value: Number(c.datasets || 0), depth: c.depth }))
  }, [categoryQuery, flatCategories])

  const dropReasonsData = useMemo(() => {
    const m = governance?.drop_reasons_total || {}
    return Object.entries(m)
      .map(([name, value]) => ({ name, value: Number(value || 0) }))
      .filter((x) => x.value > 0)
      .sort((a, b) => b.value - a.value)
      .slice(0, 12)
  }, [governance?.drop_reasons_total])

  const rulePacksData = useMemo(() => {
    const m = governance?.rule_packs_docs || {}
    return Object.entries(m)
      .map(([name, value]) => ({ name, value: Number(value || 0) }))
      .filter((x) => x.value > 0)
      .sort((a, b) => b.value - a.value)
      .slice(0, 12)
  }, [governance?.rule_packs_docs])

  const govAuditReductionPct = useMemo(() => {
    const ratio = Number(governanceAudit?.char_reduction_ratio || 0)
    if (!Number.isFinite(ratio) || ratio <= 0) return 0
    return Math.round(ratio * 1000) / 10
  }, [governanceAudit?.char_reduction_ratio])

  const govAuditCharData = useMemo(() => {
    if (!governanceAudit) return []
    return [
      { name: 'original_chars_total', value: Number(governanceAudit.original_chars_total || 0) },
      { name: 'cleaned_chars_total', value: Number(governanceAudit.cleaned_chars_total || 0) },
    ]
  }, [governanceAudit])

  const govAuditReductionHistData = useMemo(() => {
    if (!governanceAudit) return []
    const bins = governanceAudit.char_reduction_pct_histogram || []
    return bins.map((b) => ({ name: String(b.label || ''), value: Number(b.count || 0) }))
  }, [governanceAudit])

  const govAuditDensityHistData = useMemo(() => {
    if (!governanceAudit) return []
    const bins = governanceAudit.density_pct_histogram || []
    return bins.map((b) => ({ name: String(b.label || ''), value: Number(b.count || 0) }))
  }, [governanceAudit])

  const govAuditHeadingRatioHistData = useMemo(() => {
    if (!governanceAudit) return []
    const bins = governanceAudit.heading_ratio_pct_histogram || []
    return bins.map((b) => ({ name: String(b.label || ''), value: Number(b.count || 0) }))
  }, [governanceAudit])

  const govAuditEffectsData = useMemo(() => {
    if (!governanceAudit) return []
    const items = [
      { name: '段落去重（dropped）', value: Number(governanceAudit.paragraphs_dropped_total || 0) },
      { name: '裁剪 References（lines）', value: Number(governanceAudit.references_removed_lines_total || 0) },
      { name: 'URL 规范化（changed）', value: Number(governanceAudit.urls_changed_total || 0) },
      { name: '去样板（lines）', value: Number(governanceAudit.boilerplate_removed_lines_total || 0) },
      { name: '移除图片（count）', value: Number(governanceAudit.images_removed_total || 0) },
      { name: '表格规范化（tables）', value: Number(governanceAudit.tables_normalized_total || 0) },
      { name: '代码行号移除（lines）', value: Number(governanceAudit.code_lines_stripped_total || 0) },
    ]
    return items
      .filter((x) => x.value > 0)
      .sort((a, b) => b.value - a.value)
      .slice(0, 12)
  }, [governanceAudit])

  const handleExportChartsJson = useCallback(() => {
    if (!datasetId || !report) return
    const safe = sanitizeFilename(selectedDataset?.name || report.dataset_name || 'dataset')
    const suffix = pipelineHash.trim() ? `.${pipelineHash.trim().slice(0, 8)}` : ''
    const payload = {
      schema: 'mimirq.report_charts.v1',
      exported_at: new Date().toISOString(),
      dataset: { id: datasetId, name: selectedDataset?.name || report.dataset_name || null },
      pipeline_hash: report.pipeline_hash || null,
      governance: {
        metrics: report.governance_metrics || null,
        audit: report.governance_audit || null,
        drop_reasons_top: dropReasonsData,
        rule_packs_top: rulePacksData,
        audit_chars: govAuditCharData,
        audit_reduction_histogram: govAuditReductionHistData,
        audit_density_histogram: govAuditDensityHistData,
        audit_heading_ratio_histogram: govAuditHeadingRatioHistData,
        audit_effects_top: govAuditEffectsData,
      },
      folders: {
        query: folderQuery,
        top: folderBarData,
      },
      categories: {
        query: categoryQuery,
        top: categoryBarData,
      },
    }
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json;charset=utf-8' })
    downloadBlob(blob, `${safe}.charts${suffix}.json`)
  }, [
    categoryBarData,
    categoryQuery,
    datasetId,
    dropReasonsData,
    folderBarData,
    folderQuery,
    govAuditCharData,
    govAuditDensityHistData,
    govAuditReductionHistData,
    govAuditHeadingRatioHistData,
    govAuditEffectsData,
    pipelineHash,
    report,
    rulePacksData,
    selectedDataset?.name,
  ])

  return (
    <AppFrame>
      <AnalysisPageShell
        title="报告中心"
        description="一键导出数据集「质量报告 + 合规报告」，支持按 pipeline_hash 过滤并生成可分享的 HTML。"
        icon={FileText}
        iconColor="text-primary"
        badge="报告"
        size="full"
        showHeader={false}
        bodyGutter="none"
        bodyClassName="!pb-0"
        bodyContainerClassName="max-w-none"
      >
        <div className="overflow-hidden rounded-2xl border border-slate-200/80 bg-[linear-gradient(180deg,#f8fafc_0%,#ffffff_22%)] shadow-[0_1px_0_rgba(15,23,42,0.04)]">
          <div className="flex flex-col gap-2.5 border-b border-slate-200/80 bg-gradient-to-r from-sky-50/65 via-white to-slate-50 px-4 py-3 lg:flex-row lg:items-end lg:justify-between">
            <div className="min-w-0">
              <div className="text-[11px] font-medium uppercase tracking-[0.12em] text-muted-foreground">报告中心 · 数据质检台</div>
              <div className="mt-1 text-[15px] font-semibold tracking-[-0.01em] text-foreground">数据集报告导出与审计预览</div>
              <p className="mt-1 text-[12px] leading-5 text-muted-foreground">按数据集与 pipeline_hash 聚合质量与合规指标，并导出 JSON / HTML / RAG 审计。</p>
            </div>
            <div className="flex flex-wrap items-center gap-1.5 text-[11px]">
              <Badge variant="outline" className="rounded-md border-slate-200/80 bg-white text-[11px] text-slate-600"><Database className="mr-1 size-3" />数据集 {datasets.length}</Badge>
              <Badge variant="outline" className="rounded-md border-slate-200/80 bg-white text-[11px] text-slate-600"><FileSearch className="mr-1 size-3" />文档 {totalDocs}</Badge>
              <Badge variant="outline" className="rounded-md border-slate-200/80 bg-white text-[11px] text-slate-600"><Layers className="mr-1 size-3" />流水线 {pipelineVersions.length}</Badge>
              <Badge variant="outline" className="rounded-md border-slate-200/80 bg-white text-[11px] text-slate-600"><RefreshCw className="mr-1 size-3" />运行 {connectorRuns.length}</Badge>
            </div>
          </div>
          <div className="space-y-3 p-3">
          <section className="space-y-3 rounded-xl border border-slate-200/80 bg-white p-3 shadow-[inset_0_1px_0_rgba(255,255,255,0.9)]">
            <div className="flex items-start justify-between gap-4 flex-wrap">
              <div className="space-y-1">
                <div className="flex items-center gap-1.5 text-[13px] font-semibold text-slate-800"><SlidersHorizontal className="size-4 text-sky-600" />参数配置</div>
                <div className="text-xs text-muted-foreground">选择数据集与可选 pipeline_hash，点击“刷新预览”或直接导出。</div>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <Button variant="outline" className="h-8 rounded-lg border-slate-200/80 bg-white text-slate-700 hover:bg-slate-50" onClick={() => detachPromise(loadDatasets())} disabled={isLoadingDatasets} aria-label="刷新数据集列表">
                  {isLoadingDatasets ? <Loader2 className="size-4 animate-spin motion-reduce:animate-none" /> : <RefreshCw className="size-4" />}
                  <span className="ml-2">刷新数据集</span>
                </Button>
                <Button className="h-8 rounded-lg bg-sky-600 text-white shadow-[0_6px_16px_rgba(2,132,199,0.2)] hover:bg-sky-500" onClick={() => detachPromise(loadReport())} disabled={!datasetId || isLoadingReport} aria-label="刷新报告预览">
                  {isLoadingReport ? <Loader2 className="size-4 animate-spin motion-reduce:animate-none" /> : <RefreshCw className="size-4" />}
                  <span className="ml-2">刷新预览</span>
                </Button>
              </div>
            </div>
            <div className="grid gap-3 md:grid-cols-3">
              <div className="space-y-2">
                <Label htmlFor="dataset-select">数据集</Label>
                <Select value={datasetId} onValueChange={(v) => setDatasetId(v)}>
                  <SelectTrigger id="dataset-select" className="h-8 w-full border-slate-200/80 bg-white text-[12px]">
                    <SelectValue placeholder={isLoadingDatasets ? '加载中...' : '请选择数据集'} />
                  </SelectTrigger>
                  <SelectContent>
                    {datasets.map((ds) => (
                      <SelectItem key={ds.id} value={ds.id}>
                        {ds.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <div className="space-y-2">
                <Label htmlFor="pipeline-hash">pipeline_hash（可选）</Label>
                <Input
                  id="pipeline-hash"
                  value={pipelineHash}
                  onChange={(e) => setPipelineHash(e.target.value)}
                  placeholder="留空表示全部活动版本"
                  className="h-8 border-slate-200/80 bg-white text-[12px]"
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="connector-limit">连接器运行上限</Label>
                <Select
                  value={String(connectorRunsLimit)}
                  onValueChange={(v) => setConnectorRunsLimit(Number(v || 20))}
                >
                  <SelectTrigger id="connector-limit" className="h-8 w-full border-slate-200/80 bg-white text-[12px]">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="0">0</SelectItem>
                    <SelectItem value="10">10</SelectItem>
                    <SelectItem value="20">20</SelectItem>
                    <SelectItem value="50">50</SelectItem>
                    <SelectItem value="100">100</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>

            <div className="mt-3 flex items-center justify-between gap-2.5 flex-wrap border-t border-slate-200/80 pt-2.5">
              <div className="flex items-center gap-3">
                <div className="flex items-center gap-2">
                  <Switch id="redact-switch" checked={redact} onCheckedChange={setRedact} />
                  <Label htmlFor="redact-switch">导出 HTML 时脱敏（推荐分享用）</Label>
                </div>
              </div>

              <div className="flex items-center gap-2">
                <Button
                  className="h-8 rounded-lg bg-sky-600 text-white shadow-[0_6px_16px_rgba(2,132,199,0.2)] hover:bg-sky-500"
                  onClick={() => detachPromise(handleExportJson())}
                  disabled={!datasetId || isExportingJson}
                  aria-label="导出 JSON 报告"
                >
                  {isExportingJson ? <Loader2 className="size-4 animate-spin motion-reduce:animate-none" /> : <Download className="size-4" />}
                  <span className="ml-2">导出 JSON</span>
                </Button>
                <Button
                  variant="outline"
                  className="h-8 rounded-lg border-slate-200/80 bg-white text-slate-700 hover:bg-slate-50"
                  onClick={handleExportChartsJson}
                  disabled={!datasetId || !report}
                  aria-label="导出 Charts JSON"
                >
                  <Download className="size-4" />
                  <span className="ml-2">导出图表 JSON</span>
                </Button>
                <Button
                  variant="outline"
                  className="h-8 rounded-lg border-slate-200/80 bg-white text-slate-700 hover:bg-slate-50"
                  onClick={() => detachPromise(handleExportRagAuditHtml())}
                  disabled={!datasetId || isExportingRagAuditHtml}
                  aria-label="导出 RAG Audit 报告"
                >
                  {isExportingRagAuditHtml ? (
                    <Loader2 className="size-4 animate-spin motion-reduce:animate-none" />
                  ) : (
                    <Download className="size-4" />
                  )}
                  <span className="ml-2">导出 RAG 审计</span>
                </Button>
                <Button
                  variant="outline"
                  className="h-8 rounded-lg border-slate-200/80 bg-white text-slate-700 hover:bg-slate-50"
                  onClick={() => detachPromise(handleExportHtml())}
                  disabled={!datasetId || isExportingHtml}
                  aria-label="导出 HTML 报告"
                >
                  {isExportingHtml ? <Loader2 className="size-4 animate-spin motion-reduce:animate-none" /> : <Download className="size-4" />}
                  <span className="ml-2">导出 HTML</span>
                </Button>
              </div>
            </div>
          </section>

          {(() => {
    if (datasetId) {
        if (report) {
            return (<section className="space-y-3 rounded-xl border border-slate-200/80 bg-white p-3 shadow-[inset_0_1px_0_rgba(255,255,255,0.9)]">
              <div className="space-y-1">
                <div className="flex items-center gap-1.5 text-[13px] font-semibold text-slate-800"><Gauge className="size-4 text-sky-600" />预览</div>
                <div className="text-xs text-muted-foreground">
                  数据集：{selectedDataset?.name || report.dataset_name || datasetId} · 生成时间：{formatDate(report.generated_at)}
                </div>
              </div>
              <StatsGrid className="mb-3 md:grid-cols-3 xl:grid-cols-6">
                <StatCard icon={FileSearch} label="文档总数" value={String(totalDocs)} color="blue"/>
                <StatCard icon={BarChart3} label="总大小" value={formatFileSize(Number(totalBytes || 0))} color="gray"/>
                <StatCard icon={ShieldAlert} label="隔离文档" value={String(quarantined)} color="amber"/>
                <StatCard icon={AlertTriangle} label="失败文档" value={String(failed)} color="rose"/>
                <StatCard icon={Layers} label="流水线版本" value={String(pipelineVersions.length)} color="gray"/>
                <StatCard icon={RefreshCw} label="连接器运行" value={String(connectorRuns.length)} color="blue"/>
              </StatsGrid>

              {governance ? (<div className="rounded-xl border border-slate-200/80 bg-white p-3 space-y-3">
                  <div className="flex items-start justify-between gap-3 flex-wrap">
                    <div className="space-y-1">
                      <div className="flex items-center gap-1.5 text-[13px] font-semibold text-slate-800"><ShieldAlert className="size-4 text-sky-600" />治理指标</div>
                      <div className="text-xs text-muted-foreground">
                        采样 {governance.used_documents}/{governance.total_documents}
                        {governance.truncated ? '（已截断）' : ''}
                      </div>
                    </div>
                    <Badge variant={governance.truncated ? 'soft' : 'outline'} className="text-xs">
                      治理覆盖： {governance.docs_with_governance}/{governance.used_documents}
                    </Badge>
                  </div>

                  <StatsGrid className="md:grid-cols-2 xl:grid-cols-4">
                    <StatCard icon={BarChart3} label="规则命中（总）" value={String(governance.rules_applied_total || 0)} color="blue"/>
                    <StatCard icon={RefreshCw} label="变更文档（总）" value={String(governance.changed_documents_total || 0)} color="gray"/>
                    <StatCard icon={ShieldAlert} label="过滤/隔离（总）" value={String(governance.dropped_documents_total || 0)} color="amber"/>
                    <StatCard icon={Layers} label="规则包数（文档）" value={String(Object.keys(governance.rule_packs_docs || {}).length)} color="gray"/>
                  </StatsGrid>

                  <div className="grid gap-3 md:grid-cols-2">
                    <div className="rounded-xl border border-slate-200/80 bg-white p-2.5">
                      <div className="text-[13px] font-semibold text-slate-800 mb-1.5">过滤原因分布（Top）</div>
                      {dropReasonsData.length === 0 ? (<div className="text-sm text-muted-foreground">暂无数据</div>) : (<div className="h-[236px]">
                          <ResponsiveContainer width="100%" height="100%">
                            <PieChart>
                              <Pie data={dropReasonsData} dataKey="value" nameKey="name" innerRadius={48} outerRadius={90}>
                                {dropReasonsData.map((entry, idx) => (<Cell key={String(entry.name ?? 'drop')} fill={PIE_COLORS[idx % PIE_COLORS.length]}/>))}
                              </Pie>
                              <Tooltip cursor={CHART_TOOLTIP_CURSOR} contentStyle={CHART_TOOLTIP_STYLE} labelStyle={CHART_TOOLTIP_LABEL_STYLE} />
                            </PieChart>
                          </ResponsiveContainer>
                        </div>)}
                    </div>

                    <div className="rounded-xl border border-slate-200/80 bg-white p-2.5">
                      <div className="text-[13px] font-semibold text-slate-800 mb-1.5">规则包命中（Top）</div>
                      {rulePacksData.length === 0 ? (<div className="text-sm text-muted-foreground">暂无数据</div>) : (<div className="h-[236px]">
                          <ResponsiveContainer width="100%" height="100%">
                            <BarChart data={rulePacksData} layout="vertical" margin={{ left: 90, right: 16 }}>
                              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" opacity={0.55}/>
                              <XAxis type="number"/>
                              <YAxis type="category" dataKey="name" width={80}/>
                              <Tooltip cursor={CHART_TOOLTIP_CURSOR} contentStyle={CHART_TOOLTIP_STYLE} labelStyle={CHART_TOOLTIP_LABEL_STYLE} />
                              <Bar dataKey="value" radius={[0, 6, 6, 0]}>
                                {rulePacksData.map((entry, idx) => (<Cell key={String(entry.name ?? 'rule-pack')} fill={PIE_COLORS[idx % PIE_COLORS.length]}/>))}
                              </Bar>
                            </BarChart>
                          </ResponsiveContainer>
                        </div>)}
                    </div>
                  </div>
                </div>) : (<div className="rounded-xl border border-slate-200/80 bg-white p-2.5">
                  <div className="text-sm text-muted-foreground">暂无治理指标（后端未返回治理指标数据）</div>
                </div>)}

              {governanceAudit ? (<div className="rounded-xl border border-slate-200/80 bg-white p-3 space-y-3">
                  <div className="flex items-start justify-between gap-3 flex-wrap">
                    <div className="space-y-1">
                      <div className="flex items-center gap-1.5 text-[13px] font-semibold text-slate-800"><BarChart3 className="size-4 text-sky-600" />治理效果审计</div>
                      <div className="text-xs text-muted-foreground">
                        采样 {governanceAudit.used_documents}/{governanceAudit.total_documents}
                        {governanceAudit.truncated ? '（已截断）' : ''} · 字符统计覆盖：{governanceAudit.docs_with_char_stats}/{governanceAudit.used_documents} · 解析内容持久化：{' '}
                        {governanceAudit.docs_with_parsed_content_persisted}/{governanceAudit.used_documents}
                        {' · '}字符缩减 p50/p90/p99：{governanceAudit.char_reduction_pct_percentiles?.p50 || 0}%/{governanceAudit.char_reduction_pct_percentiles?.p90 || 0}%/
                        {governanceAudit.char_reduction_pct_percentiles?.p99 || 0}%
                      </div>
                    </div>
                    <Badge variant={governanceAudit.truncated ? 'soft' : 'outline'} className="text-xs">
                      字符缩减： {govAuditReductionPct}%
                    </Badge>
                  </div>

                  <StatsGrid className="md:grid-cols-2 xl:grid-cols-4">
                    <StatCard icon={FileText} label="原始字符（总）" value={String(governanceAudit.original_chars_total || 0)} color="blue"/>
                    <StatCard icon={FileText} label="清洗后字符（总）" value={String(governanceAudit.cleaned_chars_total || 0)} color="gray"/>
                    <StatCard icon={BarChart3} label="字符缩减" value={`${govAuditReductionPct}%`} color="blue"/>
                    <StatCard icon={Layers} label="字符统计覆盖（文档）" value={String(governanceAudit.docs_with_char_stats || 0)} color="gray"/>
                    <StatCard icon={FileSearch} label="解析内容持久化（文档）" value={String(governanceAudit.docs_with_parsed_content_persisted || 0)} color="gray"/>
                    <StatCard icon={RefreshCw} label="变更文档（文档）" value={String(governanceAudit.docs_changed || 0)} color="gray"/>
                    <StatCard icon={ShieldAlert} label="过滤/隔离（文档）" value={String(governanceAudit.docs_dropped || 0)} color="amber"/>
                  </StatsGrid>

                  <div className="grid gap-3 md:grid-cols-2">
                    <div className="rounded-xl border border-slate-200/80 bg-white p-2.5">
                      <div className="text-[13px] font-semibold text-slate-800 mb-1.5">字符缩减分布（%）</div>
                      {govAuditReductionHistData.length === 0 ? (<div className="text-sm text-muted-foreground">暂无数据</div>) : (<div className="h-[236px]">
                          <ResponsiveContainer width="100%" height="100%">
                            <BarChart data={govAuditReductionHistData} margin={{ left: 16, right: 16 }}>
                              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" opacity={0.55}/>
                              <XAxis dataKey="name"/>
                              <YAxis />
                              <Tooltip cursor={CHART_TOOLTIP_CURSOR} contentStyle={CHART_TOOLTIP_STYLE} labelStyle={CHART_TOOLTIP_LABEL_STYLE} />
                              <Bar dataKey="value" radius={[6, 6, 0, 0]}>
                                {govAuditReductionHistData.map((entry, idx) => (<Cell key={String(entry.name ?? 'reduction')} fill={PIE_COLORS[idx % PIE_COLORS.length]}/>))}
                              </Bar>
                            </BarChart>
                          </ResponsiveContainer>
                        </div>)}
                    </div>

                    <div className="rounded-xl border border-slate-200/80 bg-white p-2.5">
                      <div className="text-[13px] font-semibold text-slate-800 mb-1.5">规则效果（Top）</div>
                      {govAuditEffectsData.length === 0 ? (<div className="text-sm text-muted-foreground">暂无数据</div>) : (<div className="h-[236px]">
                          <ResponsiveContainer width="100%" height="100%">
                            <BarChart data={govAuditEffectsData} layout="vertical" margin={{ left: 130, right: 16 }}>
                              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" opacity={0.55}/>
                              <XAxis type="number"/>
                              <YAxis type="category" dataKey="name" width={120}/>
                              <Tooltip cursor={CHART_TOOLTIP_CURSOR} contentStyle={CHART_TOOLTIP_STYLE} labelStyle={CHART_TOOLTIP_LABEL_STYLE} />
                              <Bar dataKey="value" radius={[0, 6, 6, 0]}>
                                {govAuditEffectsData.map((entry, idx) => (<Cell key={String(entry.name ?? 'effect')} fill={PIE_COLORS[idx % PIE_COLORS.length]}/>))}
                              </Bar>
                            </BarChart>
                          </ResponsiveContainer>
                        </div>)}
                    </div>
                  </div>

                  <div className="grid gap-3 md:grid-cols-2">
                    <div className="rounded-xl border border-slate-200/80 bg-white p-2.5">
                      <div className="text-[13px] font-semibold text-slate-800 mb-1.5">文本密度分布（%）</div>
                      {govAuditDensityHistData.length === 0 ? (<div className="text-sm text-muted-foreground">暂无数据</div>) : (<div className="h-[236px]">
                          <ResponsiveContainer width="100%" height="100%">
                            <BarChart data={govAuditDensityHistData} margin={{ left: 16, right: 16 }}>
                              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" opacity={0.55}/>
                              <XAxis dataKey="name"/>
                              <YAxis />
                              <Tooltip cursor={CHART_TOOLTIP_CURSOR} contentStyle={CHART_TOOLTIP_STYLE} labelStyle={CHART_TOOLTIP_LABEL_STYLE} />
                              <Bar dataKey="value" radius={[6, 6, 0, 0]}>
                                {govAuditDensityHistData.map((entry, idx) => (<Cell key={String(entry.name ?? 'density')} fill={PIE_COLORS[idx % PIE_COLORS.length]}/>))}
                              </Bar>
                            </BarChart>
                          </ResponsiveContainer>
                        </div>)}
                    </div>

                    <div className="rounded-xl border border-slate-200/80 bg-white p-2.5">
                      <div className="text-[13px] font-semibold text-slate-800 mb-1.5">标题占比分布（%）</div>
                      {govAuditHeadingRatioHistData.length === 0 ? (<div className="text-sm text-muted-foreground">暂无数据</div>) : (<div className="h-[236px]">
                          <ResponsiveContainer width="100%" height="100%">
                            <BarChart data={govAuditHeadingRatioHistData} margin={{ left: 16, right: 16 }}>
                              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" opacity={0.55}/>
                              <XAxis dataKey="name"/>
                              <YAxis />
                              <Tooltip cursor={CHART_TOOLTIP_CURSOR} contentStyle={CHART_TOOLTIP_STYLE} labelStyle={CHART_TOOLTIP_LABEL_STYLE} />
                              <Bar dataKey="value" radius={[6, 6, 0, 0]}>
                                {govAuditHeadingRatioHistData.map((entry, idx) => (<Cell key={String(entry.name ?? 'heading')} fill={PIE_COLORS[idx % PIE_COLORS.length]}/>))}
                              </Bar>
                            </BarChart>
                          </ResponsiveContainer>
                        </div>)}
                    </div>
                  </div>
                </div>) : (<div className="rounded-xl border border-slate-200/80 bg-white p-2.5">
                  <div className="text-sm text-muted-foreground">暂无治理效果（后端未返回治理审计数据）</div>
                </div>)}

              <div className="grid gap-3 md:grid-cols-2">
                <div className="rounded-xl border border-slate-200/80 bg-white p-2.5">
	                  <div className="flex items-start justify-between gap-3 flex-wrap">
	                    <div>
	                      <div className="flex items-center gap-1.5 text-[13px] font-semibold text-slate-800"><FolderTree className="size-4 text-sky-600" />目录分布（Top）</div>
	                      {folderTree ? (<div className="text-xs text-muted-foreground">
	                          含 source_path： {folderTree.total_with_source_path}/{folderTree.total_documents}
	                        </div>) : null}
	                    </div>
	                    <SearchInput value={folderQuery} onValueChange={setFolderQuery} placeholder="搜索目录…" containerClassName="w-48" inputClassName="h-8 text-xs" disabled={!folderTree}/>
	                  </div>

                  {(() => {
                    if (folderTree) {
                        if (flatFolders === null) {
                            return (<div className="mt-3 flex items-center gap-2 text-sm text-muted-foreground">
                      <Loader2 className="size-4 animate-spin motion-reduce:animate-none"/>
                      <span>目录统计计算中...</span>
                    </div>);
                        }
                        else if (flatFolders.length === 0) {
                                return (<div className="mt-3 text-sm text-muted-foreground">暂无目录（未上传带路径的文件）</div>);
                            }
                            else if (folderBarData.length === 0) {
                                    return (<div className="mt-3 text-sm text-muted-foreground">无匹配结果</div>);
                                }
                                else {
                                    return (<div className="mt-3 space-y-3">
                      <div className="h-[236px]">
                        <ResponsiveContainer width="100%" height="100%">
                          <BarChart data={folderBarData} layout="vertical" margin={{ left: 80, right: 16 }}>
                            <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" opacity={0.55}/>
                            <XAxis type="number"/>
                            <YAxis type="category" dataKey="name" width={80}/>
                            <Tooltip cursor={CHART_TOOLTIP_CURSOR} contentStyle={CHART_TOOLTIP_STYLE} labelStyle={CHART_TOOLTIP_LABEL_STYLE} />
                            <Bar dataKey="value" radius={[0, 6, 6, 0]} fill={PIE_COLORS[0]}/>
                          </BarChart>
                        </ResponsiveContainer>
                      </div>

                      <div className="space-y-2">
                        {folderBarData.slice(0, 10).map((f) => (<div key={f.name} className="flex items-center justify-between gap-3 rounded-md px-2 py-1 hover:bg-sky-50/60">
                            <span className="font-mono text-xs text-foreground truncate" title={f.name}>
                              {f.name}
                            </span>
                            <span className="font-mono text-xs text-muted-foreground">{f.value}</span>
                          </div>))}
                      </div>
                    </div>);
                                }
                    }
                    else {
                        return (<div className="mt-3 text-sm text-muted-foreground">后端未提供目录统计</div>);
                    }
                })()}
                </div>

                <div className="rounded-xl border border-slate-200/80 bg-white p-2.5">
                  <div className="mb-2 flex items-center gap-1.5 text-[13px] font-semibold text-slate-800"><Layers className="size-4 text-sky-600" />流水线版本分布（Top）</div>
                  {pipelineVersions.length === 0 ? (<div className="text-sm text-muted-foreground">暂无数据</div>) : (<div className="space-y-2">
                      {pipelineVersions.slice(0, 10).map((v) => (<div key={v.pipeline_hash} className="flex items-center justify-between gap-3 rounded-md px-2 py-1 hover:bg-sky-50/60">
                          <span className="font-mono text-xs text-foreground truncate" title={v.pipeline_hash}>
                            {v.pipeline_hash}
                          </span>
                          <span className="font-mono text-xs text-muted-foreground">{v.documents}</span>
                        </div>))}
                    </div>)}
                </div>

                <div className="rounded-xl border border-slate-200/80 bg-white p-2.5">
                  <div className="flex items-start justify-between gap-3 flex-wrap">
	                    <div>
	                      <div className="flex items-center gap-1.5 text-[13px] font-semibold text-slate-800"><Tags className="size-4 text-sky-600" />分类分布（Top）</div>
	                      <div className="text-xs text-muted-foreground">按分类统计「数据集数量」</div>
	                    </div>
	                    <div className="flex items-center gap-2">
	                      <SearchInput value={categoryQuery} onValueChange={setCategoryQuery} placeholder="搜索分类…" containerClassName="w-40" inputClassName="h-8 text-xs" disabled={isLoadingCategories}/>
	                      <Button variant="ghost" size="sm" className="h-8 px-2 text-muted-foreground" onClick={() => detachPromise(loadCategories())} disabled={isLoadingCategories} aria-label="刷新分类">
                        {isLoadingCategories ? (<Loader2 className="size-4 animate-spin motion-reduce:animate-none"/>) : (<RefreshCw className="size-4"/>)}
                      </Button>
                    </div>
                  </div>

                  {(() => {
                    if (isLoadingCategories) {
                        return (<div className="mt-3 text-sm text-muted-foreground">加载中…</div>);
                    }
                    else if (categoryBarData.length === 0) {
                            return (<div className="mt-3 text-sm text-muted-foreground">暂无数据</div>);
                        }
                        else {
                            return (<div className="mt-3 space-y-3">
                      <div className="h-[236px]">
                        <ResponsiveContainer width="100%" height="100%">
                          <BarChart data={categoryBarData} layout="vertical" margin={{ left: 80, right: 16 }}>
                            <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" opacity={0.55}/>
                            <XAxis type="number"/>
                            <YAxis type="category" dataKey="name" width={80}/>
                            <Tooltip cursor={CHART_TOOLTIP_CURSOR} contentStyle={CHART_TOOLTIP_STYLE} labelStyle={CHART_TOOLTIP_LABEL_STYLE} />
                            <Bar dataKey="value" radius={[0, 6, 6, 0]} fill={PIE_COLORS[1]}/>
                          </BarChart>
                        </ResponsiveContainer>
                      </div>

                      <div className="space-y-2">
                        {categoryBarData.slice(0, 10).map((c) => (<div key={String(c.name)} className="flex items-center justify-between gap-3 rounded-md px-2 py-1 hover:bg-sky-50/60">
                            <span className="font-mono text-xs text-foreground truncate" title={String(c.name)}>
                              {String(c.name)}
                            </span>
                            <span className="font-mono text-xs text-muted-foreground">{String(c.value)}</span>
                          </div>))}
                      </div>
                    </div>);
                        }
                })()}
                </div>

                <div className="rounded-xl border border-slate-200/80 bg-white p-2.5">
                  <div className="mb-2 flex items-center gap-1.5 text-[13px] font-semibold text-slate-800"><RefreshCw className="size-4 text-sky-600" />最近连接器运行</div>
                  {connectorRuns.length === 0 ? (<div className="text-sm text-muted-foreground">暂无数据</div>) : (<div className="space-y-2">
                      {connectorRuns.slice(0, 8).map((r) => (<div key={r.id} className="flex items-start justify-between gap-3 rounded-md px-2 py-1.5 hover:bg-sky-50/60">
                          <div className="min-w-0">
                            <div className="font-mono text-xs text-foreground truncate" title={r.connector_id}>
                              {r.connector_id}
                            </div>
                            <div className="text-xs text-muted-foreground">{formatDate(r.created_at)}</div>
                          </div>
                          <div className="font-mono text-xs text-muted-foreground">{r.status}</div>
                        </div>))}
                    </div>)}
                </div>
              </div>
            </section>);
        }
        else {
            return (<EmptyState title={isLoadingReport ? '报告加载中...' : '暂无预览'} description={isLoadingReport ? '正在拉取报告数据...' : '点击“刷新预览”生成报告。'}/>);
        }
    }
    else {
        return (<EmptyState title="请选择数据集" description="选择一个数据集后即可生成报告预览并导出。"/>);
    }
})()}
          </div>
        </div>
      </AnalysisPageShell>
    </AppFrame>
  )
}
