'use client'

import { wrap, type Remote } from 'comlink'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { toast } from 'sonner'
import {
  AlertTriangle,
  Archive,
  BarChart3,
  CheckCircle2,
  Clock3,
  Database,
  Download,
  FileSearch,
  FileText,
  Layers,
  Loader2,
  PlayCircle,
  RefreshCw,
  ShieldAlert,
  ShieldCheck,
  type LucideIcon,
} from 'lucide-react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Pie,
  PieChart,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import { AppFrame } from '@/components/app-frame'
import { AnalysisPageShell } from '@/components/ui/analysis-page-shell'
import { PageHeader } from '@/components/ui/page-header'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { EmptyState } from '@/components/ui/empty-state'
import { Label } from '@/components/ui/label'
import { SafeResponsiveChart } from '@/components/ui/safe-responsive-chart'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'

import { datasetApi, datasetCategoryApi } from '@/lib/api/datasets'
import { reportApi } from '@/lib/api/reports'
import { formatApiError } from '@/lib/api-errors'
import { queryKeys } from '@/lib/query-keys'
import { flattenFolderTree } from '@/lib/report-transforms'
import { sanitizeFilename } from '@/lib/sanitize'
import { cn, formatDate, formatFileSize, detachPromise } from '@/lib/utils'

import type { FlatFolderRow } from '@/lib/report-transforms'
import type { DatasetCategoryNode, DatasetReport } from '@/types'
import type { ReportTransformsWorkerApi } from '@/workers/report-transforms.worker'

const PIE_COLORS = [
  '#3b82f6',
  '#0ea5e9',
  '#14b8a6',
  '#22c55e',
  '#f59e0b',
  '#6366f1',
  '#64748b',
]
const CHART_TOOLTIP_STYLE = {
  borderRadius: 10,
  border: '1px solid #cbd5e1',
  background: 'rgba(255,255,255,0.96)',
  boxShadow: '0 8px 26px rgba(15,23,42,0.12)',
  padding: '8px 10px',
}
const CHART_TOOLTIP_LABEL_STYLE = { color: '#334155', fontWeight: 600 }
const CHART_TOOLTIP_CURSOR = { fill: 'rgba(148,163,184,0.08)' }
const DEFAULT_PIPELINE_VERSION_VALUE = '__mimirq_default_pipeline_version__'

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  globalThis.window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}

function shortPipelineHash(hash: string) {
  const value = String(hash || '').trim()
  if (value.length <= 18) return value
  return `${value.slice(0, 10)}…${value.slice(-6)}`
}

function safeNumber(value: unknown): number {
  const n = Number(value || 0)
  return Number.isFinite(n) ? n : 0
}

function formatPct(numerator: number, denominator: number) {
  if (!denominator || !Number.isFinite(denominator)) return '0%'
  return `${((numerator / denominator) * 100).toFixed(1).replace('.0', '')}%`
}

function sumRecordValues(value: Record<string, number> | null | undefined) {
  return Object.values(value || {}).reduce(
    (acc, item) => acc + safeNumber(item),
    0
  )
}

function DataPill({
  icon: Icon,
  label,
  value,
  sub,
  tone = 'blue',
}: Readonly<{
  icon: LucideIcon
  label: string
  value: string
  sub?: string
  tone?: 'blue' | 'green' | 'amber' | 'rose' | 'violet' | 'slate'
}>) {
  const toneClass = {
    blue: 'bg-blue-50 text-blue-600 ring-blue-100',
    green: 'bg-emerald-50 text-emerald-600 ring-emerald-100',
    amber: 'bg-amber-50 text-amber-600 ring-amber-100',
    rose: 'bg-rose-50 text-rose-600 ring-rose-100',
    violet: 'bg-violet-50 text-violet-600 ring-violet-100',
    slate: 'bg-slate-50 text-slate-600 ring-slate-100',
  }[tone]

  return (
    <div className="flex min-w-[170px] items-center gap-3 border-l border-slate-200/80 px-4 py-2 first:border-l-0">
      <div
        className={cn(
          'flex size-8 items-center justify-center rounded-xl ring-1',
          toneClass
        )}
      >
        <Icon className="size-4" />
      </div>
      <div className="min-w-0">
        <div className="text-[11px] text-slate-500">{label}</div>
        <div className="truncate text-[13px] font-semibold text-slate-900">
          {value}
        </div>
        {sub ? (
          <div className="mt-0.5 truncate text-[11px] text-slate-500">
            {sub}
          </div>
        ) : null}
      </div>
    </div>
  )
}

function AuditMetricCard({
  icon: Icon,
  label,
  value,
  sub,
  tone = 'blue',
}: Readonly<{
  icon: LucideIcon
  label: string
  value: string
  sub: string
  tone?: 'blue' | 'green' | 'amber' | 'rose' | 'violet' | 'slate'
}>) {
  const toneClass = {
    blue: 'bg-blue-50 text-blue-600 ring-blue-100',
    green: 'bg-emerald-50 text-emerald-600 ring-emerald-100',
    amber: 'bg-amber-50 text-amber-600 ring-amber-100',
    rose: 'bg-rose-50 text-rose-600 ring-rose-100',
    violet: 'bg-violet-50 text-violet-600 ring-violet-100',
    slate: 'bg-slate-50 text-slate-600 ring-slate-100',
  }[tone]

  return (
    <div className="rounded-2xl border border-slate-200/80 bg-card p-4 shadow-[0_10px_28px_rgba(15,23,42,0.04)]">
      <div className="flex items-start justify-between gap-3">
        <div
          className={cn(
            'flex size-10 items-center justify-center rounded-2xl ring-1',
            toneClass
          )}
        >
          <Icon className="size-5" />
        </div>
      </div>
      <div className="mt-3 text-[12px] font-medium text-slate-500">{label}</div>
      <div className="mt-1 font-mono text-[22px] font-semibold tracking-[-0.03em] text-slate-950">
        {value}
      </div>
      <div className="mt-3 text-[11px] text-slate-500">{sub}</div>
    </div>
  )
}

function MiniRiskCard({
  label,
  value,
  sub,
  tone = 'blue',
}: Readonly<{
  label: string
  value: string
  sub: string
  tone?: 'blue' | 'green' | 'amber' | 'rose' | 'violet'
}>) {
  const toneClass = {
    blue: 'text-blue-600',
    green: 'text-emerald-600',
    amber: 'text-amber-600',
    rose: 'text-rose-600',
    violet: 'text-violet-600',
  }[tone]
  return (
    <div className="rounded-xl border border-slate-200/80 bg-card/80 p-3">
      <div className="text-[12px] text-slate-500">{label}</div>
      <div
        className={cn('mt-2 font-mono text-[20px] font-semibold', toneClass)}
      >
        {value}
      </div>
      <div className="mt-2 text-[11px] text-slate-500">{sub}</div>
    </div>
  )
}

function ProgressRow({
  label,
  value,
  max,
}: Readonly<{ label: string; value: number; max: number }>) {
  const pct = max > 0 ? Math.max(0, Math.min(100, (value / max) * 100)) : 0
  return (
    <div className="grid grid-cols-[120px_1fr_48px] items-center gap-3 text-[12px]">
      <div className="truncate text-slate-600" title={label}>
        {label}
      </div>
      <div className="h-2 rounded-full bg-slate-100">
        <div
          className="h-full rounded-full bg-blue-500"
          style={{ width: `${pct}%` }}
        />
      </div>
      <div className="text-right font-mono text-slate-600">
        {formatPct(value, max)}
      </div>
    </div>
  )
}

export default function ReportsCenterPage() {
  const [datasetId, setDatasetId] = useState<string>('')
  const [pipelineHash, setPipelineHash] = useState<string>('')
  const [connectorRunsLimit, setConnectorRunsLimit] = useState<number>(20)
  const [redact, setRedact] = useState<boolean>(true)
  const [showOnlyIssues, setShowOnlyIssues] = useState<boolean>(false)

  const [isExportingJson, setIsExportingJson] = useState(false)
  const [isExportingHtml, setIsExportingHtml] = useState(false)
  const [isExportingRagAuditHtml, setIsExportingRagAuditHtml] = useState(false)
  const [isExportingBundle, setIsExportingBundle] = useState(false)

  const [folderQuery, setFolderQuery] = useState<string>('')
  const [categoryQuery, setCategoryQuery] = useState<string>('')

  const [flatFolders, setFlatFolders] = useState<FlatFolderRow[] | null>(null)
  const transformsWorkerRef = useRef<Worker | null>(null)
  const transformsApiRef = useRef<Remote<ReportTransformsWorkerApi> | null>(
    null
  )
  const transformsDisabledRef = useRef(false)
  const flatFoldersSeqRef = useRef(0)

  const reportParams = useMemo(
    () => ({
      pipeline_hash: pipelineHash.trim() || undefined,
      connector_runs_limit: connectorRunsLimit,
    }),
    [connectorRunsLimit, pipelineHash]
  )

  const datasetsQuery = useQuery<Awaited<ReturnType<typeof datasetApi.list>>>({
    queryKey: queryKeys.datasets.list({ skip: 0, limit: 200, purpose: 'reports' }),
    queryFn: () => datasetApi.list({ skip: 0, limit: 200 }),
  })
  const categoriesQuery = useQuery<
    Awaited<ReturnType<typeof datasetCategoryApi.listTree>>
  >({
    queryKey: queryKeys.reports.categories,
    queryFn: () => datasetCategoryApi.listTree(),
  })
  const reportQuery = useQuery<DatasetReport>({
    queryKey: queryKeys.reports.dataset(datasetId, reportParams),
    queryFn: () => reportApi.getDatasetReport(datasetId, reportParams),
    enabled: Boolean(datasetId),
    placeholderData: (previousData) => previousData,
  })

  const datasets = useMemo(
    () => datasetsQuery.data?.items || [],
    [datasetsQuery.data?.items]
  )
  const categoryTree = useMemo(
    () => categoriesQuery.data?.items || [],
    [categoriesQuery.data?.items]
  )
  const report = reportQuery.data ?? null
  const isLoadingDatasets = datasetsQuery.isFetching
  const isLoadingReport = reportQuery.isFetching
  const selectedDataset = useMemo(
    () => datasets.find((d) => d.id === datasetId) || null,
    [datasets, datasetId]
  )

  useEffect(() => {
    if (!datasets.length) return
    if (datasetId && datasets.some((dataset) => dataset.id === datasetId)) {
      return
    }
    setDatasetId(datasets[0].id)
    setPipelineHash('')
  }, [datasetId, datasets])

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
      const suffix = pipelineHash.trim()
        ? `.${pipelineHash.trim().slice(0, 8)}`
        : ''
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
      const suffix = pipelineHash.trim()
        ? `.${pipelineHash.trim().slice(0, 8)}`
        : ''
      downloadBlob(blob, `${safe}.report${suffix}.html`)
    } catch (e: any) {
      console.error('Export report html failed', e)
      toast.error(formatApiError(e, '导出 HTML 报告失败'))
    } finally {
      setIsExportingHtml(false)
    }
  }, [
    connectorRunsLimit,
    datasetId,
    pipelineHash,
    redact,
    selectedDataset?.name,
  ])

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
      const suffix = pipelineHash.trim()
        ? `.${pipelineHash.trim().slice(0, 8)}`
        : ''
      downloadBlob(blob, `${safe}.rag_audit${suffix}.html`)
    } catch (e: any) {
      console.error('Export rag audit html failed', e)
      toast.error(formatApiError(e, '导出 RAG Audit 报告失败'))
    } finally {
      setIsExportingRagAuditHtml(false)
    }
  }, [
    connectorRunsLimit,
    datasetId,
    pipelineHash,
    redact,
    selectedDataset?.name,
  ])

  const handleExportBundleZip = useCallback(async () => {
    if (!datasetId) return
    setIsExportingBundle(true)
    try {
      const blob = await reportApi.exportDatasetReportBundleZip(datasetId, {
        pipeline_hash: pipelineHash.trim() || undefined,
        connector_runs_limit: connectorRunsLimit,
        redact,
      })
      const safe = sanitizeFilename(selectedDataset?.name || 'dataset')
      const suffix = pipelineHash.trim()
        ? `.${pipelineHash.trim().slice(0, 8)}`
        : ''
      downloadBlob(blob, `${safe}.report-bundle${suffix}.zip`)
    } catch (e: any) {
      console.error('Export report bundle zip failed', e)
      toast.error(formatApiError(e, '导出完整归档包失败'))
    } finally {
      setIsExportingBundle(false)
    }
  }, [
    connectorRunsLimit,
    datasetId,
    pipelineHash,
    redact,
    selectedDataset?.name,
  ])

  const totalDocs = report?.profile?.total_documents || 0
  const totalBytes = report?.profile?.total_size_bytes || 0
  const quarantined = report?.compliance?.quarantined_documents || 0
  const failed = report?.compliance?.failed_documents || 0
  const pipelineVersions = useMemo(
    () => report?.pipeline_versions ?? [],
    [report?.pipeline_versions]
  )
  const connectorRuns = report?.connectors || []
  const folderTree = report?.folder_tree || null
  const governance = report?.governance_metrics || null
  const governanceAudit = report?.governance_audit || null
  const pipelineVersionOptions = useMemo(() => {
    const seen = new Set<string>()
    return pipelineVersions
      .map((v) => ({
        pipeline_hash: String(v.pipeline_hash || '').trim(),
        documents: Number(v.documents || 0),
      }))
      .filter((v) => {
        if (
          !v.pipeline_hash ||
          v.pipeline_hash === 'unknown' ||
          seen.has(v.pipeline_hash)
        )
          return false
        seen.add(v.pipeline_hash)
        return true
      })
  }, [pipelineVersions])
  const pipelineVersionSelectValue =
    pipelineHash.trim() || DEFAULT_PIPELINE_VERSION_VALUE

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
        console.warn(
          'Failed to flatten folder tree; falling back to empty list',
          e
        )
        if (flatFoldersSeqRef.current === seq) setFlatFolders([])
      }
    }

    if (transformsDisabledRef.current || typeof Worker === 'undefined') {
      computeSync()
      return
    }

    let cancelled = false
    detachPromise(
      (async () => {
        try {
          if (!transformsWorkerRef.current || !transformsApiRef.current) {
            transformsWorkerRef.current = new Worker(
              new URL(
                '../../workers/report-transforms.worker.ts',
                import.meta.url
              ),
              { type: 'module' }
            )
            transformsApiRef.current = wrap<ReportTransformsWorkerApi>(
              transformsWorkerRef.current
            )
          }

          const rows =
            await transformsApiRef.current.flattenFolderTree(folderTree)
          if (cancelled) return
          if (flatFoldersSeqRef.current !== seq) return
          setFlatFolders(rows)
        } catch (e) {
          // If the environment can't load a worker bundle (or Comlink fails), keep the page functional.
          console.warn(
            'Report transforms worker failed; falling back to main thread',
            e
          )
          transformsDisabledRef.current = true
          computeSync()
        }
      })()
    )

    return () => {
      cancelled = true
    }
  }, [folderTree])

  const folderBarData = useMemo(() => {
    const rows = flatFolders ?? []
    const q = folderQuery.trim().toLowerCase()
    const filtered = q
      ? rows.filter((f) => f.path.toLowerCase().includes(q))
      : rows
    return filtered
      .slice()
      .sort((a, b) => b.documents - a.documents)
      .slice(0, 12)
      .map((f) => ({ name: f.path || '/', value: Number(f.documents || 0) }))
  }, [flatFolders, folderQuery])

  const flatCategories = useMemo(() => {
    const out: Array<{
      id: string
      name: string
      depth: number
      datasets: number
    }> = []
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
    const filtered = q
      ? flatCategories.filter((c) => c.name.toLowerCase().includes(q))
      : flatCategories
    return filtered
      .slice()
      .sort((a, b) => b.datasets - a.datasets)
      .slice(0, 12)
      .map((c) => ({
        name: c.name || c.id,
        value: Number(c.datasets || 0),
        depth: c.depth,
      }))
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
      {
        name: 'original_chars_total',
        value: Number(governanceAudit.original_chars_total || 0),
      },
      {
        name: 'cleaned_chars_total',
        value: Number(governanceAudit.cleaned_chars_total || 0),
      },
    ]
  }, [governanceAudit])

  const govAuditReductionHistData = useMemo(() => {
    if (!governanceAudit) return []
    const bins = governanceAudit.char_reduction_pct_histogram || []
    return bins.map((b) => ({
      name: String(b.label || ''),
      value: Number(b.count || 0),
    }))
  }, [governanceAudit])

  const govAuditDensityHistData = useMemo(() => {
    if (!governanceAudit) return []
    const bins = governanceAudit.density_pct_histogram || []
    return bins.map((b) => ({
      name: String(b.label || ''),
      value: Number(b.count || 0),
    }))
  }, [governanceAudit])

  const govAuditHeadingRatioHistData = useMemo(() => {
    if (!governanceAudit) return []
    const bins = governanceAudit.heading_ratio_pct_histogram || []
    return bins.map((b) => ({
      name: String(b.label || ''),
      value: Number(b.count || 0),
    }))
  }, [governanceAudit])

  const govAuditEffectsData = useMemo(() => {
    if (!governanceAudit) return []
    const items = [
      {
        name: '段落去重（dropped）',
        value: Number(governanceAudit.paragraphs_dropped_total || 0),
      },
      {
        name: '裁剪 References（lines）',
        value: Number(governanceAudit.references_removed_lines_total || 0),
      },
      {
        name: 'URL 规范化（changed）',
        value: Number(governanceAudit.urls_changed_total || 0),
      },
      {
        name: '去样板（lines）',
        value: Number(governanceAudit.boilerplate_removed_lines_total || 0),
      },
      {
        name: '移除图片（count）',
        value: Number(governanceAudit.images_removed_total || 0),
      },
      {
        name: '表格规范化（tables）',
        value: Number(governanceAudit.tables_normalized_total || 0),
      },
      {
        name: '代码行号移除（lines）',
        value: Number(governanceAudit.code_lines_stripped_total || 0),
      },
    ]
    return items
      .filter((x) => x.value > 0)
      .sort((a, b) => b.value - a.value)
      .slice(0, 12)
  }, [governanceAudit])

  const statusCounts = report?.profile?.by_status || {}
  const completedDocs = safeNumber(
    statusCounts.completed ?? statusCounts.ready ?? statusCounts.done
  )
  const successDocs =
    completedDocs || Math.max(0, totalDocs - failed - quarantined)
  const successRate = formatPct(successDocs, totalDocs)
  const failedRate = formatPct(failed, totalDocs)
  const selectedDatasetName =
    selectedDataset?.name || report?.dataset_name || '未选择数据集'
  const latestAuditTime = report?.generated_at
    ? formatDate(report.generated_at)
    : '-'
  const piiHits = sumRecordValues(report?.compliance?.pii_hits_total)
  const secretHits = sumRecordValues(report?.compliance?.secrets_hits_total)
  const sensitiveHits = piiHits + secretHits
  const findingRows = (report?.profile?.findings || []).filter((item) =>
    showOnlyIssues
      ? item.severity === 'warning' ||
        item.severity === 'error' ||
        safeNumber(item.count) > 0
      : true
  )
  const duplicateFindingCount = findingRows
    .filter((item) => /duplicate|重复/i.test(`${item.key} ${item.label}`))
    .reduce((acc, item) => acc + safeNumber(item.count), 0)
  const missingFindingCount = findingRows
    .filter((item) => /missing|缺失/i.test(`${item.key} ${item.label}`))
    .reduce((acc, item) => acc + safeNumber(item.count), 0)
  const lowQualityFindingCount = findingRows
    .filter((item) => /quality|低质量|low/i.test(`${item.key} ${item.label}`))
    .reduce((acc, item) => acc + safeNumber(item.count), 0)
  const topDocumentRows = (
    folderBarData.length > 0
      ? folderBarData
      : Object.entries(report?.profile?.by_file_type || {}).map(
          ([name, value]) => ({ name, value: safeNumber(value) })
        )
  )
    .slice()
    .sort((a, b) => safeNumber(b.value) - safeNumber(a.value))
    .slice(0, 3)
  const topDocumentMax = Math.max(
    1,
    ...topDocumentRows.map((item) => safeNumber(item.value))
  )
  const categoryMax = Math.max(
    1,
    ...categoryBarData.map((item) => safeNumber(item.value))
  )
  const versionTotal = pipelineVersions.reduce(
    (acc, item) => acc + safeNumber(item.documents),
    0
  )
  const issueRows = [
    ...findingRows.map((item) => ({
      id: `finding-${item.key}`,
      time: latestAuditTime,
      level:
        item.severity === 'error'
          ? '错误'
          : item.severity === 'warning'
            ? '警告'
            : '信息',
      type: item.label || item.key,
      description:
        item.description || `${item.label || item.key}：${item.count}`,
      target: `${item.count}`,
    })),
    ...connectorRuns
      .filter((item) => /fail|error|failed/i.test(String(item.status || '')))
      .map((item) => ({
        id: `connector-${item.id}`,
        time: formatDate(item.created_at),
        level: '错误',
        type: '连接器运行',
        description: item.error_message || item.status,
        target: item.connector_id || '-',
      })),
  ].slice(0, 5)
  const fieldCoverageRows = useMemo(
    () => [
      {
        label: '字符统计覆盖',
        value: safeNumber(governanceAudit?.docs_with_char_stats),
        max: safeNumber(governanceAudit?.used_documents || totalDocs),
      },
      {
        label: '解析内容持久化',
        value: safeNumber(governanceAudit?.docs_with_parsed_content_persisted),
        max: safeNumber(governanceAudit?.used_documents || totalDocs),
      },
      {
        label: '治理记录覆盖',
        value: safeNumber(governance?.docs_with_governance),
        max: safeNumber(governance?.used_documents || totalDocs),
      },
      {
        label: '变更文档占比',
        value: safeNumber(governanceAudit?.docs_changed),
        max: safeNumber(governanceAudit?.used_documents || totalDocs),
      },
      {
        label: '过滤/隔离占比',
        value: safeNumber(governanceAudit?.docs_dropped || quarantined),
        max: safeNumber(governanceAudit?.used_documents || totalDocs),
      },
    ],
    [
      governance?.docs_with_governance,
      governance?.used_documents,
      governanceAudit,
      quarantined,
      totalDocs,
    ]
  )

  const handleExportChartsJson = useCallback(() => {
    if (!datasetId || !report) return
    const safe = sanitizeFilename(
      selectedDataset?.name || report.dataset_name || 'dataset'
    )
    const suffix = pipelineHash.trim()
      ? `.${pipelineHash.trim().slice(0, 8)}`
      : ''
    const payload = {
      schema: 'mimirq.report_charts.v1',
      exported_at: new Date().toISOString(),
      dataset: {
        id: datasetId,
        name: selectedDataset?.name || report.dataset_name || null,
      },
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
    const blob = new Blob([JSON.stringify(payload, null, 2)], {
      type: 'application/json;charset=utf-8',
    })
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

  const handleExportCompleteJson = useCallback(() => {
    if (!datasetId || !report) return
    const safe = sanitizeFilename(
      selectedDataset?.name || report.dataset_name || 'dataset'
    )
    const suffix = pipelineHash.trim()
      ? `.${pipelineHash.trim().slice(0, 8)}`
      : ''
    const payload = {
      schema: 'mimirq.dataset_report_complete.v1',
      exported_at: new Date().toISOString(),
      report,
      derived: {
        success_documents: successDocs,
        success_rate: successRate,
        failed_rate: failedRate,
        sensitive_hits: sensitiveHits,
        risk_findings: findingRows,
        field_coverage: fieldCoverageRows,
        top_documents: topDocumentRows,
        category_top: categoryBarData,
        pipeline_version_total: versionTotal,
      },
    }
    const blob = new Blob([JSON.stringify(payload, null, 2)], {
      type: 'application/json;charset=utf-8',
    })
    downloadBlob(blob, `${safe}.complete-report${suffix}.json`)
  }, [
    categoryBarData,
    datasetId,
    failedRate,
    fieldCoverageRows,
    findingRows,
    pipelineHash,
    report,
    selectedDataset?.name,
    sensitiveHits,
    successDocs,
    successRate,
    topDocumentRows,
    versionTotal,
  ])

  return (
    <AppFrame>
      <AnalysisPageShell
        title="数据报告导出与审计概览"
        description="一键导出数据报告与审计结果，支持多种格式与指标视图，便于数据治理与合规审查。"
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
          <div className="border-b border-slate-200/80 bg-[linear-gradient(180deg,#f8fbff_0%,#ffffff_100%)] px-5 py-4">
            <PageHeader
              title="数据报告导出与审计概览"
              description="一键导出数据报告与审计结果，所有指标均来自后端报告接口与数据集接口。"
              iconImage="report-export"
              icon={FileText}
              iconColor="text-info"
              badge="报告"
              compact
              className="p-0"
            >
            <div className="flex flex-wrap overflow-hidden rounded-2xl border border-slate-200/80 bg-card/90 shadow-[0_10px_30px_rgba(15,23,42,0.05)]">
              <DataPill
                icon={Database}
                label="数据集"
                value={selectedDatasetName}
                sub={datasetId ? shortPipelineHash(datasetId) : '未选择'}
                tone="blue"
              />
              <DataPill
                icon={FileSearch}
                label="文档总数"
                value={`${totalDocs} 篇文档`}
                sub="后端 profile"
                tone="blue"
              />
              <DataPill
                icon={ShieldCheck}
                label="审计状态"
                value={
                  isLoadingReport ? '执行中' : report ? '已完成' : '待执行'
                }
                sub={report ? '报告已生成' : '等待执行审计'}
                tone={report ? 'green' : 'slate'}
              />
              <DataPill
                icon={Clock3}
                label="最近审计"
                value={latestAuditTime}
                sub={report ? '后端生成时间' : '暂无'}
                tone="slate"
              />
            </div>
            </PageHeader>
          </div>
          <div className="space-y-3 p-3">
            <section className="space-y-4 rounded-2xl border border-slate-200/80 bg-card p-4 shadow-[inset_0_1px_0_rgba(255,255,255,0.95)]">
              <div className="grid gap-3 xl:grid-cols-[1.25fr_1.1fr_0.9fr_auto] xl:items-end">
                <div className="space-y-2">
                  <Label htmlFor="dataset-select">数据集</Label>
                  <Select
                    value={datasetId}
                    onValueChange={(v) => {
                      setDatasetId(v)
                      setPipelineHash('')
                    }}
                  >
                    <SelectTrigger
                      id="dataset-select"
                      className="h-8 w-full border-slate-200/80 bg-card text-[12px]"
                    >
                      <SelectValue
                        placeholder={
                          isLoadingDatasets ? '加载中...' : '请选择数据集'
                        }
                      />
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
                  <Label htmlFor="pipeline-hash">处理版本</Label>
                  <Select
                    value={pipelineVersionSelectValue}
                    onValueChange={(value) => {
                      setPipelineHash(
                        value === DEFAULT_PIPELINE_VERSION_VALUE ? '' : value
                      )
                    }}
                  >
                    <SelectTrigger
                      id="pipeline-hash"
                      className="h-8 w-full border-slate-200/80 bg-card text-[12px]"
                    >
                      <SelectValue placeholder="选择或使用当前活动版本" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value={DEFAULT_PIPELINE_VERSION_VALUE}>
                        当前活动版本（默认）
                      </SelectItem>
                      {pipelineVersionOptions.map((v) => (
                        <SelectItem
                          key={v.pipeline_hash}
                          value={v.pipeline_hash}
                        >
                          {shortPipelineHash(v.pipeline_hash)} · {v.documents}{' '}
                          个文档
                        </SelectItem>
                      ))}
                      {pipelineVersionOptions.length === 0 ? (
                        <SelectItem
                          value="__mimirq_no_pipeline_versions__"
                          disabled
                        >
                          暂无可选历史版本
                        </SelectItem>
                      ) : null}
                    </SelectContent>
                  </Select>
                </div>

                <div className="space-y-2">
                  <Label htmlFor="connector-limit">返回记录数量限制</Label>
                  <Select
                    value={String(connectorRunsLimit)}
                    onValueChange={(v) =>
                      setConnectorRunsLimit(Number(v || 20))
                    }
                  >
                    <SelectTrigger
                      id="connector-limit"
                      className="h-8 w-full border-slate-200/80 bg-card text-[12px]"
                    >
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="0">不包含</SelectItem>
                      <SelectItem value="10">限制 10 条</SelectItem>
                      <SelectItem value="20">限制 20 条（默认）</SelectItem>
                      <SelectItem value="50">限制 50 条</SelectItem>
                      <SelectItem value="100">限制 100 条</SelectItem>
                    </SelectContent>
                  </Select>
                </div>

                <div className="flex items-center gap-2 pb-1">
                  <Switch
                    id="only-issues-switch"
                    checked={showOnlyIssues}
                    onCheckedChange={setShowOnlyIssues}
                  />
                  <Label
                    htmlFor="only-issues-switch"
                    className="whitespace-nowrap text-[12px]"
                  >
                    仅显示异常/失败
                  </Label>
                </div>
              </div>

              <div className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-200/80 pt-3">
                <div className="flex items-center gap-2">
                  <Switch
                    id="redact-switch"
                    checked={redact}
                    onCheckedChange={setRedact}
                  />
                  <Label htmlFor="redact-switch" className="text-[12px]">
                    分享导出时隐藏敏感字段
                  </Label>
                </div>

                <div className="flex flex-wrap items-center gap-2">
                  <Button
                    variant="outline"
                    className="h-8 rounded-lg border-slate-200/80 bg-card text-slate-700 hover:bg-slate-50 hover:text-slate-700"
                    onClick={() => detachPromise(handleExportJson())}
                    disabled={!datasetId || isExportingJson}
                    aria-label="导出 JSON"
                  >
                    {isExportingJson ? (
                      <Loader2 className="size-4 animate-spin motion-reduce:animate-none" />
                    ) : (
                      <Download className="size-4" />
                    )}
                    <span className="ml-2">导出 JSON</span>
                  </Button>
                  <Button
                    variant="outline"
                    className="h-8 rounded-lg border-slate-200/80 bg-card text-slate-700 hover:bg-slate-50 hover:text-slate-700"
                    onClick={handleExportCompleteJson}
                    disabled={!datasetId || !report}
                    aria-label="导出完整 JSON"
                  >
                    <Archive className="size-4" />
                    <span className="ml-2">导出完整 JSON</span>
                  </Button>
                  <Button
                    variant="outline"
                    className="h-8 rounded-lg border-slate-200/80 bg-card text-slate-700 hover:bg-slate-50 hover:text-slate-700"
                    onClick={handleExportChartsJson}
                    disabled={!datasetId || !report}
                    aria-label="导出 RAC 统计"
                  >
                    <BarChart3 className="size-4" />
                    <span className="ml-2">导出 RAC 统计</span>
                  </Button>
                  <Button
                    variant="outline"
                    className="h-8 rounded-lg border-slate-200/80 bg-card text-slate-700 hover:bg-slate-50 hover:text-slate-700"
                    onClick={() => detachPromise(handleExportRagAuditHtml())}
                    disabled={!datasetId || isExportingRagAuditHtml}
                    aria-label="导出 RAG 审计报告"
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
                    className="h-8 rounded-lg border-slate-200/80 bg-card text-slate-700 hover:bg-slate-50 hover:text-slate-700"
                    onClick={() => detachPromise(handleExportBundleZip())}
                    disabled={!datasetId || isExportingBundle}
                    aria-label="导出数据包 ZIP"
                  >
                    {isExportingBundle ? (
                      <Loader2 className="size-4 animate-spin motion-reduce:animate-none" />
                    ) : (
                      <Download className="size-4" />
                    )}
                    <span className="ml-2">导出数据包 ZIP</span>
                  </Button>
                  <Button
                    variant="outline"
                    className="h-8 rounded-lg border-slate-200/80 bg-card text-slate-700 hover:bg-slate-50 hover:text-slate-700"
                    onClick={() => detachPromise(handleExportHtml())}
                    disabled={!datasetId || isExportingHtml}
                    aria-label="导出 HTML"
                  >
                    {isExportingHtml ? (
                      <Loader2 className="size-4 animate-spin motion-reduce:animate-none" />
                    ) : (
                      <Download className="size-4" />
                    )}
                    <span className="ml-2">导出 HTML</span>
                  </Button>
                  <Button
                    className="h-8 rounded-lg bg-blue-600 text-info-foreground shadow-[0_8px_20px_rgba(37,99,235,0.22)] hover:bg-blue-700"
                    onClick={() => void reportQuery.refetch()}
                    disabled={!datasetId || isLoadingReport}
                    aria-label="执行审计"
                  >
                    {isLoadingReport ? (
                      <Loader2 className="size-4 animate-spin motion-reduce:animate-none" />
                    ) : (
                      <PlayCircle className="size-4" />
                    )}
                    <span className="ml-2">执行审计</span>
                  </Button>
                  <Button
                    variant="outline"
                    className="h-8 rounded-lg border-slate-200/80 bg-card text-slate-700 hover:bg-slate-50 hover:text-slate-700"
                    onClick={() => {
                      void datasetsQuery.refetch()
                      void categoriesQuery.refetch()
                      if (datasetId) void reportQuery.refetch()
                    }}
                    disabled={isLoadingDatasets}
                    aria-label="刷新"
                  >
                    {isLoadingDatasets ? (
                      <Loader2 className="size-4 animate-spin motion-reduce:animate-none" />
                    ) : (
                      <RefreshCw className="size-4" />
                    )}
                    <span className="ml-2">刷新</span>
                  </Button>
                </div>
              </div>
            </section>

            {report ? (
              <section className="space-y-4">
                <div className="grid gap-3 md:grid-cols-3 xl:grid-cols-6">
                  <AuditMetricCard
                    icon={FileText}
                    label="文档总数"
                    value={String(totalDocs)}
                    sub="来自后端报告 profile.total_documents"
                    tone="blue"
                  />
                  <AuditMetricCard
                    icon={BarChart3}
                    label="总大小"
                    value={formatFileSize(Number(totalBytes || 0))}
                    sub="来自后端报告 profile.total_size_bytes"
                    tone="violet"
                  />
                  <AuditMetricCard
                    icon={CheckCircle2}
                    label="成功文档数"
                    value={String(successDocs)}
                    sub={`成功率 ${successRate}`}
                    tone="green"
                  />
                  <AuditMetricCard
                    icon={AlertTriangle}
                    label="失败文档数"
                    value={String(failed)}
                    sub={`失败率 ${failedRate}`}
                    tone="amber"
                  />
                  <AuditMetricCard
                    icon={Layers}
                    label="版本数"
                    value={String(pipelineVersions.length)}
                    sub={`过滤：${pipelineHash ? shortPipelineHash(pipelineHash) : '当前活动版本'}`}
                    tone="blue"
                  />
                  <AuditMetricCard
                    icon={Clock3}
                    label="最近审计"
                    value={latestAuditTime}
                    sub="本次报告生成时间"
                    tone="slate"
                  />
                </div>

                <div className="grid gap-4 xl:grid-cols-[1.05fr_1.2fr_1.05fr_0.95fr]">
                  <div className="rounded-2xl border border-slate-200/80 bg-card p-4 shadow-[0_10px_28px_rgba(15,23,42,0.04)]">
                    <div className="mb-4 text-[15px] font-semibold text-slate-900">
                      边缘指标 / 风险指标
                    </div>
                    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-1 2xl:grid-cols-2">
                      <MiniRiskCard
                        label="缺失字段率"
                        value={formatPct(missingFindingCount, totalDocs)}
                        sub={`${missingFindingCount} 条后端 finding`}
                        tone={missingFindingCount ? 'amber' : 'blue'}
                      />
                      <MiniRiskCard
                        label="重复文档率"
                        value={formatPct(duplicateFindingCount, totalDocs)}
                        sub={`${duplicateFindingCount} 条后端 finding`}
                        tone={duplicateFindingCount ? 'violet' : 'blue'}
                      />
                      <MiniRiskCard
                        label="低置信度率"
                        value={formatPct(lowQualityFindingCount, totalDocs)}
                        sub={`${lowQualityFindingCount} 条质量 finding`}
                        tone={lowQualityFindingCount ? 'amber' : 'green'}
                      />
                      <MiniRiskCard
                        label="解析失败率"
                        value={failedRate}
                        sub={`${failed} 个失败文档`}
                        tone={failed ? 'rose' : 'green'}
                      />
                    </div>
                  </div>

                  <div className="rounded-2xl border border-slate-200/80 bg-card p-4 shadow-[0_10px_28px_rgba(15,23,42,0.04)]">
                    <div className="mb-4 flex items-center justify-between gap-3">
                      <div className="text-[15px] font-semibold text-slate-900">
                        字段覆盖分布
                      </div>
                      <Badge
                        variant="outline"
                        className="rounded-full text-[11px]"
                      >
                        后端治理审计
                      </Badge>
                    </div>
                    <div className="space-y-3">
                      {fieldCoverageRows.map((row) => (
                        <ProgressRow
                          key={row.label}
                          label={row.label}
                          value={row.value}
                          max={row.max}
                        />
                      ))}
                    </div>
                  </div>

                  <div className="rounded-2xl border border-slate-200/80 bg-card p-4 shadow-[0_10px_28px_rgba(15,23,42,0.04)]">
                    <div className="mb-4 flex items-center justify-between gap-3">
                      <div className="text-[15px] font-semibold text-slate-900">
                        文档分布 Top
                      </div>
                      <Button
                        variant="link"
                        className="h-auto p-0 text-xs"
                        onClick={() => setFolderQuery('')}
                      >
                        查看全部
                      </Button>
                    </div>
                    {topDocumentRows.length === 0 ? (
                      <EmptyState
                        title="暂无分布数据"
                        description="后端报告未返回目录或文件类型分布。"
                      />
                    ) : (
                      <div className="space-y-3">
                        {topDocumentRows.map((row) => (
                          <div
                            key={row.name}
                            className="grid grid-cols-[1fr_52px_100px] items-center gap-3 text-[12px]"
                          >
                            <div
                              className="truncate font-medium text-slate-700"
                              title={row.name}
                            >
                              {row.name}
                            </div>
                            <div className="font-mono text-slate-700">
                              {row.value}
                            </div>
                            <div className="h-2 rounded-full bg-slate-100">
                              <div
                                className="h-full rounded-full bg-blue-500"
                                style={{
                                  width: `${Math.max(3, (safeNumber(row.value) / topDocumentMax) * 100)}%`,
                                }}
                              />
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>

                  <div className="rounded-2xl border border-slate-200/80 bg-card p-4 shadow-[0_10px_28px_rgba(15,23,42,0.04)]">
                    <div className="mb-4 text-[15px] font-semibold text-slate-900">
                      污染观察 / 内容健康
                    </div>
                    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-1 2xl:grid-cols-2">
                      <MiniRiskCard
                        label="可疑链接数"
                        value={String(governanceAudit?.urls_changed_total || 0)}
                        sub="URL 规范化变更"
                        tone="blue"
                      />
                      <MiniRiskCard
                        label="外部附件数"
                        value={String(
                          governanceAudit?.images_removed_total || 0
                        )}
                        sub="治理审计图片移除"
                        tone="green"
                      />
                      <MiniRiskCard
                        label="敏感词命中"
                        value={String(sensitiveHits)}
                        sub={`PII ${piiHits} / Secret ${secretHits}`}
                        tone={sensitiveHits ? 'amber' : 'green'}
                      />
                      <MiniRiskCard
                        label="低质量片段数"
                        value={String(lowQualityFindingCount)}
                        sub="后端质量 finding"
                        tone={lowQualityFindingCount ? 'rose' : 'violet'}
                      />
                    </div>
                  </div>
                </div>

                <div className="grid gap-4 xl:grid-cols-[1.2fr_0.9fr_1.4fr]">
                  <div className="rounded-2xl border border-slate-200/80 bg-card p-4 shadow-[0_10px_28px_rgba(15,23,42,0.04)]">
                    <div className="mb-4 text-[15px] font-semibold text-slate-900">
                      类别统计 / 分布图
                    </div>
                    {categoryBarData.length === 0 ? (
                      <EmptyState
                        title="暂无分类数据"
                        description="后端分类树没有可展示的计数。"
                      />
                    ) : (
                      <SafeResponsiveChart
                        className="h-[260px]"
                        minHeight={260}
                      >
                        <BarChart
                          data={categoryBarData.slice(0, 8)}
                          margin={{ left: 8, right: 12, top: 8, bottom: 8 }}
                        >
                          <CartesianGrid
                            strokeDasharray="3 3"
                            stroke="#e2e8f0"
                            opacity={0.55}
                          />
                          <XAxis dataKey="name" />
                          <YAxis allowDecimals={false} />
                          <Tooltip
                            cursor={CHART_TOOLTIP_CURSOR}
                            contentStyle={CHART_TOOLTIP_STYLE}
                            labelStyle={CHART_TOOLTIP_LABEL_STYLE}
                          />
                          <Bar
                            dataKey="value"
                            radius={[7, 7, 0, 0]}
                            fill="#2563eb"
                          />
                        </BarChart>
                      </SafeResponsiveChart>
                    )}
                  </div>

                  <div className="rounded-2xl border border-slate-200/80 bg-card p-4 shadow-[0_10px_28px_rgba(15,23,42,0.04)]">
                    <div className="mb-4 text-[15px] font-semibold text-slate-900">
                      源状态版本分布 Top
                    </div>
                    {pipelineVersions.length === 0 ? (
                      <EmptyState
                        title="暂无版本数据"
                        description="后端报告未返回 pipeline_versions。"
                      />
                    ) : (
                      <div className="grid gap-3 lg:grid-cols-[1fr_1fr] xl:grid-cols-1 2xl:grid-cols-[1fr_1fr]">
                        <SafeResponsiveChart
                          className="h-[210px]"
                          minHeight={210}
                        >
                          <PieChart>
                            <Pie
                              data={pipelineVersions}
                              dataKey="documents"
                              nameKey="pipeline_hash"
                              innerRadius={54}
                              outerRadius={84}
                            >
                              {pipelineVersions.map((entry, idx) => (
                                <Cell
                                  key={entry.pipeline_hash}
                                  fill={PIE_COLORS[idx % PIE_COLORS.length]}
                                />
                              ))}
                            </Pie>
                            <Tooltip
                              cursor={CHART_TOOLTIP_CURSOR}
                              contentStyle={CHART_TOOLTIP_STYLE}
                              labelStyle={CHART_TOOLTIP_LABEL_STYLE}
                            />
                          </PieChart>
                        </SafeResponsiveChart>
                        <div className="space-y-2 self-center">
                          {pipelineVersions.slice(0, 5).map((version, idx) => (
                            <div
                              key={version.pipeline_hash}
                              className="flex items-center justify-between gap-2 text-[12px]"
                            >
                              <span className="flex min-w-0 items-center gap-2">
                                <span
                                  className="size-2 rounded-full"
                                  style={{
                                    background:
                                      PIE_COLORS[idx % PIE_COLORS.length],
                                  }}
                                />
                                <span
                                  className="truncate font-mono"
                                  title={version.pipeline_hash}
                                >
                                  {shortPipelineHash(version.pipeline_hash)}
                                </span>
                              </span>
                              <span className="font-mono text-slate-500">
                                {version.documents} (
                                {formatPct(version.documents, versionTotal)})
                              </span>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>

                  <div className="rounded-2xl border border-slate-200/80 bg-card p-4 shadow-[0_10px_28px_rgba(15,23,42,0.04)]">
                    <div className="mb-4 flex items-center justify-between gap-3">
                      <div className="text-[15px] font-semibold text-slate-900">
                        最近错误解析
                      </div>
                      <Button
                        variant="link"
                        className="h-auto p-0 text-xs"
                        onClick={() => setShowOnlyIssues(false)}
                      >
                        查看全部解读
                      </Button>
                    </div>
                    {issueRows.length === 0 ? (
                      <EmptyState
                        title="暂无异常记录"
                        description="当前后端报告没有返回失败连接器或风险 finding。"
                      />
                    ) : (
                      <div className="overflow-hidden rounded-xl border border-slate-100">
                        <div className="grid grid-cols-[120px_72px_120px_1fr_64px] bg-slate-50 px-3 py-2 text-[11px] font-medium text-slate-500">
                          <span>时间</span>
                          <span>级别</span>
                          <span>类型</span>
                          <span>描述</span>
                          <span className="text-right">数量</span>
                        </div>
                        {issueRows.map((row) => (
                          <div
                            key={row.id}
                            className="grid grid-cols-[120px_72px_120px_1fr_64px] items-center border-t border-slate-100 px-3 py-3 text-[12px] text-slate-700"
                          >
                            <span className="truncate">{row.time}</span>
                            <span
                              className={cn(
                                'font-medium',
                                row.level === '错误'
                                  ? 'text-rose-600'
                                  : row.level === '警告'
                                    ? 'text-amber-600'
                                    : 'text-emerald-600'
                              )}
                            >
                              {row.level}
                            </span>
                            <span className="truncate">{row.type}</span>
                            <span className="truncate" title={row.description}>
                              {row.description}
                            </span>
                            <span className="text-right font-mono">
                              {row.target}
                            </span>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              </section>
            ) : (
              <EmptyState
                title={
                  datasetId
                    ? isLoadingReport
                      ? '报告加载中...'
                      : '暂无预览'
                    : '请选择数据集'
                }
                description={
                  datasetId
                    ? isLoadingReport
                      ? '正在拉取后端报告数据...'
                      : '点击“执行审计”生成报告。'
                    : '选择一个数据集后即可生成报告预览并导出。'
                }
              />
            )}
          </div>
        </div>
      </AnalysisPageShell>
    </AppFrame>
  )
}
