'use client'

import { useEffect, useLayoutEffect, useMemo, useRef, useState, useSyncExternalStore } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useSearchParams } from 'next/navigation'
import { useTranslations } from 'next-intl'
import { toast } from 'sonner'
import { ChevronDown, Download, Loader2 } from '@/components/icons'
import { AppFrame } from '@/components/app-frame'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import {
  DirectoryWorkspace,
  OperationalWorkspace,
  WorkspaceMetrics,
  WorkspaceNotice,
  WorkspaceNoticeStack,
  WorkspaceTableScroll,
  workspaceStyles as ws,
} from '@/components/ui/operational-workspace'
import { formatApiError } from '@/lib/api-errors'
import {
  datasetApi,
  evaluationApi,
  type KGSearchDiagnosticsResponse,
  type KGSearchDiagnosticsRunDetail,
  type KGSearchDiagnosticsRunOut,
  type KGSearchDiagnosticsRunList,
} from '@/lib/api'
import { queryKeys } from '@/lib/query-keys'
import { sanitizeFilename } from '@/lib/sanitize'
import { cn, detachPromise } from '@/lib/utils'
import { downloadBlob } from '@/lib/download'
import {
  kgDiagnosticsFormSchema,
  kgQualityRequestSchema,
  type KGSearchRunMetrics,
  type KGQualityReport,
  type KGQualityRequest,
} from '@/lib/kg-diagnostics-schema'
import { getAuthSessionKey, subscribeAuthSession } from '@/lib/auth-storage'
import type { JsonObject } from '@/types'

const DIAGNOSTICS_METRIC_LABELS: Record<string, string> = {
  baseline_hit_rate: '基线命中率',
  baseline_mrr: 'Baseline MRR',
  baseline_recall: 'Baseline Recall',
  baseline_ndcg: 'Baseline NDCG@K',
  baseline_map: 'Baseline MAP@K',
  baseline_valid_searches: '有效检索样本',
  baseline_search_errors: '检索失败样本',
  hardcase_hit_rate: '难例命中率',
  hardcase_mrr: 'Hardcase MRR',
  hardcase_recall: 'Hardcase Recall',
  hardcase_ndcg: 'Hardcase NDCG@K',
  hardcase_map: 'Hardcase MAP@K',
  hardcase_valid_searches: '有效难例检索',
  hardcase_search_errors: '难例检索失败',
  hardcases_generated: '生成难例数',
  documents: '文档数',
  events: '事件数',
  entities: '实体数',
  relations: '关系数',
  event_entity_links: '事件实体关联数',
  avg_relations_per_entity: '平均每实体关系数',
  isolated_entities: '孤立实体数',
  isolated_entity_ratio: '孤立实体占比',
  nodes: '节点数',
  edges: '边数',
  components: '连通分量数',
  largest_component_ratio: '最大连通分量占比',
  relations_total: '关系总数',
  low_confidence_threshold: '低置信阈值',
  low_confidence_relations: '低置信关系数',
  missing_references_relations: '缺少引用的关系数',
  missing_chunk_relations: '缺少切片的关系数',
  relation_edges_truncated: '关系边已截断',
  relation_edges_limit: '关系边上限',
  dataset_id: '数据集',
  documents_sampled: '抽样文档数',
  documents_allowed: '有权限文档数',
}

type DiagnosticsScope = { datasetId: string; active: boolean; controller: AbortController }
type DiagnosticsRunDiffRow = {
  case_id: string
  question: string
  a_hit: boolean | null
  b_hit: boolean | null
  a_mrr: number | null
  b_mrr: number | null
  a_recall: number | null
  b_recall: number | null
  delta_recall: number | null
  delta_mrr: number | null
  presence: 'both' | 'only_a' | 'only_b'
  a_error: string | null | undefined
  b_error: string | null | undefined
}

const DIAGNOSTICS_DIFF_METRIC_KEYS = [
  'baseline_hit_rate',
  'baseline_mrr',
  'baseline_recall',
  'baseline_ndcg',
  'baseline_map',
  'hardcase_hit_rate',
  'hardcase_mrr',
  'hardcase_recall',
  'hardcase_ndcg',
  'hardcase_map',
] as const

function downloadJson(value: unknown, filename: string): void {
  downloadBlob(filename, new Blob([JSON.stringify(value, null, 2)], { type: 'application/json;charset=utf-8' }))
}

const metricNumber = new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 4 })

function formatMetricValue(value: unknown): string {
  if (value === null || value === undefined) return '-'
  if (typeof value === 'number') return metricNumber.format(value)
  if (typeof value === 'boolean') return value ? '是' : '否'
  if (typeof value === 'string') return value
  return JSON.stringify(value, null, 2)
}

function formatDiagnosticsMetricLabel(key: string): string {
  return DIAGNOSTICS_METRIC_LABELS[key] ?? key.replaceAll('_', ' ')
}

type BaselineMetrics = Pick<KGSearchRunMetrics, 'hit_at_k' | 'mrr' | 'recall'>

function extractBaselineMetrics(item: {
  baseline: { error: string | null; metrics: BaselineMetrics }
}): BaselineMetrics | null {
  return item.baseline.error === null ? item.baseline.metrics : null
}

function diagnosticsMetricDelta(aValue: number | null | undefined, bValue: number | null | undefined) {
  if (aValue === null || aValue === undefined || bValue === null || bValue === undefined) return null
  return bValue - aValue
}

function buildDiagnosticsSummaryDelta(
  aSummary: KGSearchDiagnosticsRunOut['summary'],
  bSummary: KGSearchDiagnosticsRunOut['summary'],
) {
  const summaryDelta: JsonObject = {}
  for (const key of DIAGNOSTICS_DIFF_METRIC_KEYS) {
    const aValue = aSummary[key]
    const bValue = bSummary[key]
    summaryDelta[key] = {
      a: aValue,
      b: bValue,
      delta: diagnosticsMetricDelta(aValue, bValue),
    }
  }
  return summaryDelta
}

function buildDiagnosticsDiffRow(
  key: string,
  byCaseA: ReadonlyMap<string, KGSearchDiagnosticsRunDetail['items'][number]>,
  byCaseB: ReadonlyMap<string, KGSearchDiagnosticsRunDetail['items'][number]>,
): DiagnosticsRunDiffRow {
  const runCaseA = byCaseA.get(key)
  const runCaseB = byCaseB.get(key)
  const metricsA = runCaseA === undefined ? null : extractBaselineMetrics(runCaseA)
  const metricsB = runCaseB === undefined ? null : extractBaselineMetrics(runCaseB)
  const aRecall = metricsA?.recall ?? null
  const bRecall = metricsB?.recall ?? null
  const aMrr = metricsA?.mrr ?? null
  const bMrr = metricsB?.mrr ?? null

  return {
    case_id: key,
    question: runCaseB === undefined ? runCaseA!.question : runCaseB.question,
    presence: runCaseA === undefined ? 'only_b' : runCaseB === undefined ? 'only_a' : 'both',
    a_error: runCaseA?.baseline.error,
    b_error: runCaseB?.baseline.error,
    a_hit: metricsA === null ? null : metricsA.hit_at_k,
    b_hit: metricsB === null ? null : metricsB.hit_at_k,
    a_mrr: aMrr,
    b_mrr: bMrr,
    a_recall: aRecall,
    b_recall: bRecall,
    delta_recall: diagnosticsMetricDelta(aRecall, bRecall),
    delta_mrr: diagnosticsMetricDelta(aMrr, bMrr),
  }
}

function isChangedDiagnosticsDiffRow(row: DiagnosticsRunDiffRow): boolean {
  return (
    row.presence !== 'both' ||
    row.a_error != null ||
    row.b_error != null ||
    (row.delta_recall !== null && row.delta_recall !== 0) ||
    (row.delta_mrr !== null && row.delta_mrr !== 0) ||
    (row.a_hit !== null && row.b_hit !== null && row.a_hit !== row.b_hit)
  )
}

function compareDiagnosticsDiffRows(left: DiagnosticsRunDiffRow, right: DiagnosticsRunDiffRow) {
  if (left.delta_recall === null) return right.delta_recall === null ? 0 : 1
  if (right.delta_recall === null) return -1
  return Math.abs(right.delta_recall) - Math.abs(left.delta_recall)
}

function countDiagnosticsHitFlips(rows: DiagnosticsRunDiffRow[]) {
  const flips = rows.filter((row) => row.a_hit !== null && row.b_hit !== null && row.a_hit !== row.b_hit)
  const improved = flips.filter((row) => row.a_hit === false && row.b_hit === true).length
  const regressed = flips.filter((row) => row.a_hit === true && row.b_hit === false).length
  return { flips, improved, regressed }
}

function buildKgDiagnosticsDiff(
  detailA: KGSearchDiagnosticsRunDetail | null,
  detailB: KGSearchDiagnosticsRunDetail | null,
) {
  if (detailA === null || detailB === null || detailA.run.id === detailB.run.id) return null

  const summaryDelta = buildDiagnosticsSummaryDelta(detailA.run.summary, detailB.run.summary)
  const byCaseA = new Map(detailA.items.map((item) => [item.case_id, item]))
  const byCaseB = new Map(detailB.items.map((item) => [item.case_id, item]))
  const allKeys = new Set<string>([...byCaseA.keys(), ...byCaseB.keys()])
  const rows = Array.from(allKeys, (key) => buildDiagnosticsDiffRow(key, byCaseA, byCaseB))
  const changed = rows.filter(isChangedDiagnosticsDiffRow).sort(compareDiagnosticsDiffRows)
  const { flips, improved, regressed } = countDiagnosticsHitFlips(rows)

  return {
    run_a: detailA.run,
    run_b: detailB.run,
    summary_delta: summaryDelta,
    changed_cases: changed,
    hit_flips: { total: flips.length, improved, regressed },
  }
}

const selectClass =
  'h-11 w-full min-w-0 rounded-md border border-input bg-background px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring sm:h-9'
const primaryActionClass = 'bg-accent px-3 text-accent-foreground hover:bg-accent/90'

function NumberSetting({
  label,
  value,
  onChange,
  min,
  max,
  step = 1,
}: {
  label: string
  value: string
  onChange: (value: string) => void
  min: number
  max: number
  step?: number
}) {
  return (
    <label className="block space-y-2 text-[13px]">
      {label}
      <Input
        type="number"
        className="h-11 sm:h-9"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(event) => onChange(event.target.value)}
      />
    </label>
  )
}

function RawResult({ label, value }: { label: string; value: unknown }) {
  return (
    <details className="mt-5 py-4">
      <summary className="cursor-pointer text-[13px] font-medium">{label}</summary>
      <pre tabIndex={0} className="mt-3 max-h-96 overflow-auto bg-muted/30 p-4 text-xs leading-6">
        {JSON.stringify(value, null, 2)}
      </pre>
    </details>
  )
}

export function KGDiagnosticsPage() {
  const sessionKey = useSyncExternalStore(subscribeAuthSession, getAuthSessionKey, getAuthSessionKey)
  return <KGDiagnosticsWorkspace key={sessionKey} sessionKey={sessionKey} />
}

function KGDiagnosticsWorkspace({ sessionKey }: Readonly<{ sessionKey: string }>) {
  const t = useTranslations('KGDiagnosticsPage')
  const datasetIdFromUrl = useSearchParams().get('dataset_id')?.trim() ?? ''
  const datasetsQuery = useQuery({
    queryKey: queryKeys.datasets.exhaustive(),
    queryFn: ({ signal }) => datasetApi.listAll(undefined, { signal }),
    staleTime: 30_000,
  })
  const datasets = useMemo(() => datasetsQuery.data ?? [], [datasetsQuery.data])
  const [datasetId, setDatasetId] = useState(datasetIdFromUrl)
  const [pane, setPane] = useState<'directory' | 'detail'>('detail')
  const [activeView, setActiveView] = useState('run')
  const [maxCases, setMaxCases] = useState('50')
  const [k, setK] = useState('10')
  const [autoExtractKg, setAutoExtractKg] = useState(true)
  const [extractSkills, setExtractSkills] = useState('auto')
  const [extractRelations, setExtractRelations] = useState('auto')
  const [hardcaseMode, setHardcaseMode] = useState('deterministic')
  const [hardcasesPerFailed, setHardcasesPerFailed] = useState('4')
  const [maxFailedForHardcase, setMaxFailedForHardcase] = useState('20')
  const [llmTemperature, setLlmTemperature] = useState('0.2')
  const [persistRun, setPersistRun] = useState(true)
  const [qualityDocLimit, setQualityDocLimit] = useState('200')
  const [qualityPipelineHash, setQualityPipelineHash] = useState('')
  const [qualityLoading, setQualityLoading] = useState(false)
  const [qualityResult, setQualityResult] = useState<{ report: KGQualityReport; request: KGQualityRequest } | null>(
    null,
  )
  const qualityReport = qualityResult === null ? null : qualityResult.report
  const [qualityError, setQualityError] = useState<string | null>(null)
  const runRequests = useRef(new Map<string, Promise<KGSearchDiagnosticsResponse>>())
  const [pendingDatasets, setPendingDatasets] = useState<ReadonlySet<string>>(new Set())
  const running = pendingDatasets.has(datasetId)
  const [runResult, setRunResult] = useState<{ report: KGSearchDiagnosticsResponse; persistRequested: boolean } | null>(
    null,
  )
  const runResp = runResult === null ? null : runResult.report
  const [runError, setRunError] = useState<string | null>(null)
  const [runsLoading, setRunsLoading] = useState(false)
  const [runsResult, setRunsResult] = useState<{ response: KGSearchDiagnosticsRunList; skip: number } | null>(null)
  const runs = runsResult === null ? [] : runsResult.response.items
  const [runsSkip, setRunsSkip] = useState(0)
  const [runsError, setRunsError] = useState<string | null>(null)
  const [selectedRunA, setSelectedRunA] = useState('')
  const [selectedRunB, setSelectedRunB] = useState('')
  const [detailA, setDetailA] = useState<KGSearchDiagnosticsRunDetail | null>(null)
  const [detailB, setDetailB] = useState<KGSearchDiagnosticsRunDetail | null>(null)
  const [detailErrors, setDetailErrors] = useState<{ a: string | null; b: string | null }>({ a: null, b: null })
  const [detailLoading, setDetailLoading] = useState<ReadonlySet<'a' | 'b'>>(new Set())
  const [analysisTab, setAnalysisTab] = useState('failures')
  const scope = useRef<DiagnosticsScope | null>(null)
  const requests = useRef({ runs: 0, a: 0, b: 0, quality: 0 })
  const selectionInitialized = useRef(false)
  useEffect(() => setDatasetId(datasetIdFromUrl), [datasetIdFromUrl])
  useEffect(() => {
    if (!datasetId && datasets[0]) setDatasetId(datasets[0].id)
  }, [datasets, datasetId])
  useLayoutEffect(() => {
    const context = { datasetId, active: true, controller: new AbortController() }
    scope.current = context
    selectionInitialized.current = false
    setRunResult(null)
    setQualityResult(null)
    setRunsResult(null)
    setRunsSkip(0)
    setDetailA(null)
    setDetailB(null)
    setSelectedRunA('')
    setSelectedRunB('')
    setQualityPipelineHash('')
    setRunError(null)
    setQualityError(null)
    setRunsError(null)
    setDetailErrors({ a: null, b: null })
    setQualityLoading(false)
    setRunsLoading(false)
    setDetailLoading(new Set())
    setActiveView('run')
    return () => {
      context.active = false
      context.controller.abort()
    }
  }, [datasetId])

  function isCurrentScope(context: DiagnosticsScope): boolean {
    return context.active && getAuthSessionKey() === sessionKey
  }

  async function refreshRuns(targetSkip = runsSkip): Promise<void> {
    if (datasetId === '') return
    const context = scope.current!
    const request = ++requests.current.runs
    setRunsSkip(targetSkip)
    setRunsLoading(true)
    setRunsError(null)
    try {
      const response = await evaluationApi.listKgSearchDiagnosticsRuns(
        { dataset_id: context.datasetId, limit: 50, skip: targetSkip },
        { signal: context.controller.signal },
      )
      if (!isCurrentScope(context) || request !== requests.current.runs) return
      setRunsResult({ response, skip: targetSkip })
      if (!selectionInitialized.current) {
        if (response.items.length > 0) setSelectedRunA(response.items[0].id)
        if (response.items.length > 1) setSelectedRunB(response.items[1].id)
        selectionInitialized.current = true
      }
    } catch (error) {
      if (isCurrentScope(context) && request === requests.current.runs)
        setRunsError(formatApiError(error, t('toasts.runsLoadFailed')))
    } finally {
      if (isCurrentScope(context) && request === requests.current.runs) setRunsLoading(false)
    }
  }

  async function loadRun(which: 'a' | 'b', id: string): Promise<void> {
    const context = scope.current!
    const request = ++requests.current[which]
    setDetailLoading((current) => new Set(current).add(which))
    setDetailErrors((current) => ({ ...current, [which]: null }))
    try {
      const result = await evaluationApi.getKgSearchDiagnosticsRun(id, { signal: context.controller.signal })
      if (result.run.dataset_id.toLowerCase() !== context.datasetId.toLowerCase())
        throw new Error('运行记录不属于当前数据集')
      if (!isCurrentScope(context) || requests.current[which] !== request) return
      if (which === 'a') setDetailA(result)
      else setDetailB(result)
    } catch (error) {
      if (isCurrentScope(context) && requests.current[which] === request)
        setDetailErrors((current) => ({ ...current, [which]: formatApiError(error, '运行记录读取失败') }))
    } finally {
      if (isCurrentScope(context) && requests.current[which] === request) {
        setDetailLoading((current) => {
          const next = new Set(current)
          next.delete(which)
          return next
        })
      }
    }
  }

  async function loadQualityReport(): Promise<void> {
    const context = scope.current!
    const requestId = ++requests.current.quality
    setQualityLoading(true)
    setQualityError(null)
    try {
      const request = kgQualityRequestSchema.parse({
        dataset_id: context.datasetId,
        document_limit: Number(qualityDocLimit),
        ...(qualityPipelineHash.trim() === '' ? {} : { pipeline_hash: qualityPipelineHash.trim() }),
      })
      const result = await evaluationApi.getKgQualityReport(request, { signal: context.controller.signal })
      if (isCurrentScope(context) && requestId === requests.current.quality)
        setQualityResult({ report: result, request })
    } catch (error) {
      if (isCurrentScope(context) && requestId === requests.current.quality)
        setQualityError(formatApiError(error, t('toasts.qualityReportLoadFailed')))
    } finally {
      if (isCurrentScope(context) && requestId === requests.current.quality) setQualityLoading(false)
    }
  }

  async function runDiagnostics(): Promise<void> {
    if (runRequests.current.has(datasetId)) return
    const context = scope.current!
    const isCurrentDataset = () => scope.current?.datasetId === datasetId && getAuthSessionKey() === sessionKey
    const runsRequestAtSubmit = requests.current.runs
    setRunError(null)
    setActiveView('run')
    setPane('detail')
    try {
      const config = kgDiagnosticsFormSchema.parse({
        datasetId,
        maxCases,
        k,
        autoExtractKg,
        extractSkills,
        extractRelations,
        hardcaseMode,
        hardcasesPerFailed,
        maxFailedForHardcase,
        llmTemperature,
        persistRun,
      })
      const promise = evaluationApi.runKgSearchDiagnostics({
        dataset_id: config.datasetId,
        max_cases: config.maxCases,
        k: config.k,
        auto_extract_kg: config.autoExtractKg,
        extract_skills: config.extractSkills === 'auto' ? null : config.extractSkills === 'on',
        extract_relations: config.extractRelations === 'auto' ? null : config.extractRelations === 'on',
        hardcase_mode: config.hardcaseMode,
        hardcases_per_failed_case: config.hardcasesPerFailed,
        max_failed_cases_for_hardcase: config.maxFailedForHardcase,
        llm_temperature: config.llmTemperature,
        persist_run: config.persistRun,
      })
      runRequests.current.set(context.datasetId, promise)
      setPendingDatasets(new Set(runRequests.current.keys()))
      const result = await promise
      if (!isCurrentDataset()) return
      setRunResult({ report: result, persistRequested: config.persistRun })
      if (result.summary.baseline_search_errors > 0) toast.warning('诊断包含检索失败样本')
      else toast.success(t('toasts.diagnosticsRan'))
      if (result.run_id !== null && requests.current.runs === runsRequestAtSubmit) {
        detachPromise(refreshRuns(scope.current === context ? runsSkip : 0))
      }
    } catch (error) {
      if (isCurrentDataset())
        setRunError(
          formatApiError(error, t('toasts.diagnosticsRunFailed')) + ' 请先读取运行记录确认，再决定是否重新评测。',
        )
    } finally {
      runRequests.current.delete(context.datasetId)
      if (scope.current?.active && getAuthSessionKey() === sessionKey)
        setPendingDatasets(new Set(runRequests.current.keys()))
    }
  }

  const diff = useMemo(() => buildKgDiagnosticsDiff(detailA, detailB), [detailA, detailB])
  const items = runResp?.items ?? []
  const failedItems = items.filter((item) => {
    const metrics = extractBaselineMetrics(item)
    return item.baseline.error !== null || (metrics !== null && !metrics.hit_at_k)
  })
  const summary = runResp?.summary
  const unconfirmedPersistence = runResult !== null && runResult.persistRequested && runResult.report.run_id === null
  const baselineValues = items.map(extractBaselineMetrics).filter((value) => value !== null)
  function exportDiagnostics(): void {
    if (runResp === null) return
    try {
      downloadJson(runResp, `${sanitizeFilename(`kg_diagnostics_${runResp.summary.dataset_id}`)}.json`)
      toast.success('已开始下载本次诊断结果')
    } catch (error) {
      toast.error(formatApiError(error, '导出诊断结果失败'))
    }
  }
  const configuration = (
    <div className="space-y-5 p-4">
      <h2 className={ws.sectionTitle}>评测配置</h2>
      <label className="block space-y-2 text-[13px]">
        数据集
        <select
          aria-label="数据集"
          className={selectClass}
          value={datasetId}
          disabled={datasetsQuery.isLoading}
          onChange={(event) => setDatasetId(event.target.value)}
        >
          <option value="" disabled>
            选择数据集
          </option>
          {datasetId !== '' && !datasets.some((dataset) => dataset.id === datasetId) ? (
            <option value={datasetId}>已选数据集：{datasetId}</option>
          ) : null}
          {datasets.map((dataset) => (
            <option key={dataset.id} value={dataset.id}>
              {dataset.name}
            </option>
          ))}
        </select>
      </label>
      <fieldset disabled={running} className="min-w-0 space-y-5">
        <legend className="sr-only">本轮评测参数</legend>
        <NumberSetting label="评测样本数" value={maxCases} onChange={setMaxCases} min={1} max={200} />
        <NumberSetting label="TOP-K" value={k} onChange={setK} min={1} max={50} />
        <div className={ws.formRow}>
          <label htmlFor="kg-auto-extract">自动抽取 KG</label>
          <Switch id="kg-auto-extract" checked={autoExtractKg} onCheckedChange={setAutoExtractKg} />
        </div>
        <div className={ws.formRow}>
          <label htmlFor="kg-persist-run">保存运行记录</label>
          <Switch id="kg-persist-run" checked={persistRun} onCheckedChange={setPersistRun} />
        </div>
        <details className="group pt-4">
          <summary className="flex cursor-pointer list-none items-center gap-2 text-sm font-medium [&::-webkit-details-marker]:hidden">
            <ChevronDown
              className="size-3.5 shrink-0 text-muted-foreground transition-transform group-open:rotate-180"
              aria-hidden="true"
            />
            抽取与难例参数
          </summary>
          <div className="mt-4 space-y-5">
            <label className="block space-y-2 text-[13px]">
              技能抽取
              <select
                className={selectClass}
                value={extractSkills}
                onChange={(event) => setExtractSkills(event.target.value)}
              >
                <option value="auto">自动</option>
                <option value="on">开启</option>
                <option value="off">关闭</option>
              </select>
            </label>
            <label className="block space-y-2 text-[13px]">
              关系抽取
              <select
                className={selectClass}
                value={extractRelations}
                onChange={(event) => setExtractRelations(event.target.value)}
              >
                <option value="auto">自动</option>
                <option value="on">开启</option>
                <option value="off">关闭</option>
              </select>
            </label>
            <label className="block space-y-2 text-[13px]">
              难例生成方式
              <select
                className={selectClass}
                value={hardcaseMode}
                onChange={(event) => setHardcaseMode(event.target.value)}
              >
                <option value="off">关闭</option>
                <option value="deterministic">规则生成</option>
                <option value="llm">模型生成</option>
              </select>
            </label>
            <NumberSetting
              label="每条失败样本的难例数"
              value={hardcasesPerFailed}
              onChange={setHardcasesPerFailed}
              min={0}
              max={20}
            />
            <NumberSetting
              label="生成难例的失败样本上限"
              value={maxFailedForHardcase}
              onChange={setMaxFailedForHardcase}
              min={0}
              max={200}
            />
            <NumberSetting
              label="模型温度"
              value={llmTemperature}
              onChange={setLlmTemperature}
              min={0}
              max={2}
              step={0.1}
            />
          </div>
        </details>
      </fieldset>
    </div>
  )

  return (
    <AppFrame showBackground={false}>
      <OperationalWorkspace
        title={t('page.title')}
        icon="kg-retrieval-evaluation"
        mode="canvas"
        context={
          datasets.find((dataset) => dataset.id === datasetId)?.name ?? (datasetId === '' ? '选择数据集' : datasetId)
        }
        actions={
          <>
            <Button
              variant="ghost"
              className="w-11 px-0 sm:w-auto sm:px-3"
              disabled={!runResp}
              aria-label="导出本次评测"
              onClick={exportDiagnostics}
            >
              <Download className="size-4" />
              <span className="hidden sm:inline">导出</span>
            </Button>
            <Button
              className={cn(primaryActionClass, 'min-w-20')}
              aria-label={running ? '正在评测…' : '开始评测'}
              aria-busy={running}
              disabled={!datasetId || running}
              onClick={() => {
                void runDiagnostics()
              }}
            >
              {running ? <Loader2 className="hidden size-4 animate-spin motion-reduce:animate-none sm:inline" /> : null}
              {running ? '评测中…' : '开始评测'}
            </Button>
          </>
        }
      >
        {datasetsQuery.isError ||
        runError ||
        (runResp && unconfirmedPersistence) ||
        qualityError ||
        runsError ||
        detailErrors.a !== null ||
        detailErrors.b !== null ? (
          <WorkspaceNoticeStack ariaLabel="图谱诊断状态提示">
            {datasetsQuery.isError ? (
              <WorkspaceNotice
                tone="warning"
                title="数据集读取失败"
                error={datasetsQuery.error}
                fallbackMessage="数据集读取失败"
                retry={() => {
                  void datasetsQuery.refetch()
                }}
              />
            ) : null}
            {runError ? (
              <WorkspaceNotice
                retry={() => {
                  void runDiagnostics()
                }}
                retryLabel="重新评测"
                pending={running}
              >
                {runError}
              </WorkspaceNotice>
            ) : null}
            {runResp && unconfirmedPersistence ? (
              <WorkspaceNotice tone="warning">
                本次诊断已返回，但没有取得保存身份；请先读取运行记录确认。
              </WorkspaceNotice>
            ) : null}
            {qualityError ? (
              <WorkspaceNotice
                tone="warning"
                retry={() => {
                  void loadQualityReport()
                }}
              >
                {qualityError}
              </WorkspaceNotice>
            ) : null}
            {runsError ? (
              <WorkspaceNotice
                tone="warning"
                retry={() => {
                  void refreshRuns()
                }}
              >
                {runsError}
              </WorkspaceNotice>
            ) : null}
            {(['a', 'b'] as const).map((which) =>
              detailErrors[which] === null ? null : (
                <WorkspaceNotice key={which} tone="warning">
                  运行 {which.toUpperCase()}：{detailErrors[which]}
                </WorkspaceNotice>
              ),
            )}
          </WorkspaceNoticeStack>
        ) : null}
        <DirectoryWorkspace
          pane={pane}
          onPaneChange={setPane}
          directoryLabel="评测配置"
          detailLabel="报告结果"
          directory={configuration}
        >
          <Tabs
            value={activeView}
            onValueChange={(nextView) => {
              setActiveView(nextView)
              if (nextView === 'compare' && runsResult === null && !runsLoading) detachPromise(refreshRuns())
            }}
          >
            <TabsList className={ws.tabList}>
              <TabsTrigger value="run">本次评测</TabsTrigger>
              <TabsTrigger value="quality">抽取质量</TabsTrigger>
              <TabsTrigger value="compare">运行历史与比较</TabsTrigger>
            </TabsList>
            <TabsContent value="run" className={ws.tabContent}>
              {running ? (
                <p role="status" className="py-12 text-sm text-muted-foreground">
                  {runResp ? '正在评测，当前显示上次报告。' : '正在评测…'}
                </p>
              ) : null}
              {runResp ? (
                <>
                  <WorkspaceMetrics
                    items={[
                      'baseline_hit_rate',
                      'baseline_mrr',
                      'baseline_recall',
                      'baseline_ndcg',
                      'baseline_map',
                      'baseline_valid_searches',
                    ].map((key) => ({
                      label: formatDiagnosticsMetricLabel(key),
                      value: formatMetricValue(summary?.[key]),
                    }))}
                  />
                  <dl className="flex flex-wrap gap-x-6 gap-y-2 py-3 text-xs text-muted-foreground">
                    {['baseline_search_errors', 'hardcases_generated'].map((key) => (
                      <div key={key} className="inline-flex items-center gap-2">
                        <dt>{formatDiagnosticsMetricLabel(key)}</dt>
                        <dd className="font-medium text-foreground tabular-nums">
                          {formatMetricValue(summary?.[key])}
                        </dd>
                      </div>
                    ))}
                  </dl>
                  <section className="min-w-0 py-5">
                    <div className={ws.sectionHeading}>
                      <h2 className={ws.sectionTitle}>样本结果</h2>
                      <div role="group" aria-label="样本结果视图" className="flex gap-2">
                        {[
                          ['failures', '失败或未命中'],
                          ['all', '全部样本'],
                          ['distribution', '得分分布'],
                        ].map(([value, label]) => (
                          <Button
                            key={value}
                            variant={analysisTab === value ? 'secondary' : 'ghost'}
                            aria-pressed={analysisTab === value}
                            onClick={() => setAnalysisTab(value)}
                          >
                            {label}
                          </Button>
                        ))}
                      </div>
                    </div>
                    {analysisTab === 'distribution' ? (
                      baselineValues.length === 0 ? (
                        <p className="py-8 text-sm text-muted-foreground">没有可用于分布的成功检索样本。</p>
                      ) : (
                        <div className="space-y-4">
                          {Array.from({ length: 5 }, (_, index) => {
                            const count = baselineValues.filter(
                              (value) =>
                                value.recall >= index / 5 &&
                                (index === 4 ? value.recall <= 1 : value.recall < (index + 1) / 5),
                            ).length
                            return (
                              <div
                                key={index}
                                className="grid grid-cols-[72px_minmax(0,1fr)_40px] items-center gap-4 text-[13px]"
                              >
                                <span>
                                  {(index / 5).toFixed(1)}–{((index + 1) / 5).toFixed(1)}
                                </span>
                                <span className="h-2 bg-muted">
                                  <span
                                    className="block h-2 bg-foreground/60"
                                    style={{
                                      width: `${baselineValues.length === 0 ? 0 : (count / baselineValues.length) * 100}%`,
                                    }}
                                  />
                                </span>
                                <span className="text-right tabular-nums">{count}</span>
                              </div>
                            )
                          })}
                        </div>
                      )
                    ) : (
                      <WorkspaceTableScroll label="评测样本结果">
                        <table className={cn(ws.table, 'min-w-[560px]')}>
                          <thead>
                            <tr>
                              <th>问题</th>
                              <th>命中</th>
                              <th>Recall</th>
                              <th>MRR</th>
                            </tr>
                          </thead>
                          <tbody>
                            {(analysisTab === 'failures' ? failedItems : items).map((item) => {
                              const metrics = extractBaselineMetrics(item)
                              let status = '未返回'
                              if (item.baseline.error !== null) status = '检索失败'
                              else if (metrics) status = metrics.hit_at_k ? '命中' : '未命中'
                              return (
                                <tr key={item.case_id}>
                                  <td className="max-w-lg">{item.question}</td>
                                  <td>
                                    {status}
                                    {item.baseline.error === null ? null : (
                                      <p className="mt-1 max-w-lg break-words text-xs text-destructive">
                                        {item.baseline.error}
                                      </p>
                                    )}
                                  </td>
                                  <td>{metrics ? formatMetricValue(metrics.recall) : '—'}</td>
                                  <td>{metrics ? formatMetricValue(metrics.mrr) : '—'}</td>
                                </tr>
                              )
                            })}
                          </tbody>
                        </table>
                        {!(analysisTab === 'failures' ? failedItems : items).length ? (
                          <p className="py-8 text-sm text-muted-foreground">
                            {analysisTab === 'failures' ? '本次没有检索失败或未命中样本' : '本次评测未返回样本明细'}
                          </p>
                        ) : null}
                      </WorkspaceTableScroll>
                    )}
                  </section>
                  <RawResult label="完整评测结果" value={runResp} />
                </>
              ) : !runError && !running ? (
                <div className={ws.empty}>
                  <h2>尚未运行评测</h2>
                  <p>选择数据集并确认参数后，开始评测。</p>
                </div>
              ) : null}
            </TabsContent>
            <TabsContent value="quality" className={ws.tabContent}>
              <div className="flex flex-wrap items-end gap-4 py-5">
                <div className="w-40">
                  <NumberSetting
                    label="抽样文档上限"
                    value={qualityDocLimit}
                    onChange={setQualityDocLimit}
                    min={1}
                    max={2000}
                  />
                </div>
                <label className="block max-w-full space-y-2 text-[13px]">
                  流程版本（选填）
                  <Input
                    value={qualityPipelineHash}
                    onChange={(event) => setQualityPipelineHash(event.target.value)}
                    placeholder="Pipeline hash"
                  />
                </label>
                <Button
                  className={primaryActionClass}
                  disabled={!datasetId || qualityLoading}
                  onClick={() => {
                    void loadQualityReport()
                  }}
                >
                  {qualityLoading ? '正在读取…' : '读取质量报告'}
                </Button>
              </div>
              {qualityReport ? (
                <>
                  {qualityResult !== null ? (
                    <p className="mb-3 break-words text-xs text-muted-foreground">
                      当前展示：数据集 {qualityResult.request.dataset_id}，文档上限{' '}
                      {qualityResult.request.document_limit}；流程版本{' '}
                      {qualityResult.request.pipeline_hash === undefined
                        ? '请求时各文档的活跃版本'
                        : qualityResult.request.pipeline_hash}
                      。
                    </p>
                  ) : null}
                  {(['summary', 'components', 'noise', 'truncation', 'scope'] as const).map((group) => (
                    <section key={group} className={ws.section}>
                      <h2 className={ws.sectionTitle}>
                        {
                          {
                            summary: '总体统计',
                            components: '连通性',
                            noise: '关系噪声',
                            truncation: '统计范围限制',
                            scope: '抽样范围',
                          }[group]
                        }
                      </h2>
                      {group === 'scope' || group === 'truncation' ? (
                        <dl className={ws.formRows}>
                          {Object.entries(qualityReport[group]).map(([key, value]) => (
                            <div key={key} className={ws.formRow}>
                              <dt className="shrink-0 text-muted-foreground">{formatDiagnosticsMetricLabel(key)}</dt>
                              <dd className="min-w-0 text-right font-mono text-xs leading-5 break-all">
                                {formatMetricValue(value)}
                              </dd>
                            </div>
                          ))}
                        </dl>
                      ) : (
                        <WorkspaceMetrics
                          items={Object.entries(qualityReport[group]).map(([key, value]) => ({
                            label: formatDiagnosticsMetricLabel(key),
                            value:
                              typeof value === 'number' ? (
                                formatMetricValue(value)
                              ) : (
                                <span className="block break-all text-sm leading-6 font-normal">
                                  {formatMetricValue(value)}
                                </span>
                              ),
                          }))}
                        />
                      )}
                    </section>
                  ))}
                  <RawResult label="完整质量报告" value={qualityReport} />
                </>
              ) : !qualityLoading && !qualityError ? (
                <div className={ws.empty}>
                  <h2>尚未读取质量报告</h2>
                  <p>读取后查看实体、关系和来源引用的实际统计。</p>
                </div>
              ) : null}
            </TabsContent>
            <TabsContent value="compare" className={ws.tabContent}>
              <div className={cn(ws.sectionHeading, 'mt-5')}>
                <h2 className={ws.sectionTitle}>运行历史</h2>
                <Button
                  variant="outline"
                  disabled={!datasetId || runsLoading}
                  onClick={() => {
                    void refreshRuns()
                  }}
                >
                  {runsLoading ? '正在读取…' : '重新读取运行记录'}
                </Button>
              </div>
              {runsLoading ? (
                <p role="status" className="py-4 text-sm text-muted-foreground">
                  正在读取运行历史，保留已加载页…
                </p>
              ) : null}
              {runsResult === null && !runsLoading && !runsError ? (
                <p className="py-8 text-sm text-muted-foreground">选择数据集后读取运行历史。</p>
              ) : null}
              {runsResult !== null && !runsLoading && !runsError && !runs.length ? (
                <div className={ws.empty}>
                  <h2>当前数据集暂无运行记录</h2>
                  <p>运行评测时开启“保存运行记录”，即可在这里对比。</p>
                </div>
              ) : runsResult !== null ? (
                <WorkspaceTableScroll label="诊断运行历史">
                  <table className={cn(ws.table, 'min-w-[540px]')}>
                    <thead>
                      <tr>
                        <th>运行</th>
                        <th>时间</th>
                        <th>命中率</th>
                        <th>MRR</th>
                      </tr>
                    </thead>
                    <tbody>
                      {runs.map((run) => (
                        <tr key={run.id}>
                          <td className="break-all font-mono">{run.id}</td>
                          <td>{run.created_at.replace('T', ' ').slice(0, 19)}</td>
                          <td>{formatMetricValue(run.summary.baseline_hit_rate)}</td>
                          <td>{formatMetricValue(run.summary.baseline_mrr)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </WorkspaceTableScroll>
              ) : null}
              {runsResult !== null && runsResult.response.total > 0 ? (
                <div className="my-4 flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
                  <span>
                    已加载 {runsResult.skip + 1} 起的 {runs.length} 条，共 {runsResult.response.total} 条运行。
                  </span>
                  <div className="flex gap-2">
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      disabled={runsLoading || runsResult.skip === 0}
                      onClick={() => detachPromise(refreshRuns(runsResult.skip - 50))}
                    >
                      上一页
                    </Button>
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      disabled={runsLoading || runsResult.skip + 50 >= runsResult.response.total}
                      onClick={() => detachPromise(refreshRuns(runsResult.skip + 50))}
                    >
                      下一页
                    </Button>
                  </div>
                </div>
              ) : null}
              {runsResult !== null &&
              (runs.length > 0 ||
                selectedRunA !== '' ||
                selectedRunB !== '' ||
                detailA !== null ||
                detailB !== null) ? (
                <section className={ws.section}>
                  <div className="grid gap-4 sm:grid-cols-2">
                    {(['a', 'b'] as const).map((which) => {
                      const loaded = which === 'a' ? detailA : detailB
                      return (
                        <div key={which} className="space-y-2">
                          <label className="block text-sm" htmlFor={`kg-run-${which}`}>
                            运行 {which.toUpperCase()}
                          </label>
                          <div className="flex gap-2">
                            <select
                              id={`kg-run-${which}`}
                              className={selectClass}
                              value={which === 'a' ? selectedRunA : selectedRunB}
                              onChange={(event) => {
                                requests.current[which]++
                                selectionInitialized.current = true
                                setDetailLoading((current) => {
                                  const next = new Set(current)
                                  next.delete(which)
                                  return next
                                })
                                setDetailErrors((current) => ({ ...current, [which]: null }))
                                if (which === 'a') {
                                  setSelectedRunA(event.target.value)
                                } else {
                                  setSelectedRunB(event.target.value)
                                }
                              }}
                            >
                              <option value="">选择运行 {which.toUpperCase()}</option>
                              {(which === 'a' ? selectedRunA : selectedRunB) !== '' &&
                              !runs.some((run) => run.id === (which === 'a' ? selectedRunA : selectedRunB)) ? (
                                <option value={which === 'a' ? selectedRunA : selectedRunB}>
                                  已选运行：{which === 'a' ? selectedRunA : selectedRunB}
                                </option>
                              ) : null}
                              {runs.map((run) => (
                                <option key={run.id} value={run.id}>
                                  {run.created_at.slice(0, 19)} · {run.id.slice(0, 8)}
                                </option>
                              ))}
                            </select>
                            <Button
                              variant="outline"
                              disabled={
                                detailLoading.has(which) || (which === 'a' ? selectedRunA : selectedRunB) === ''
                              }
                              onClick={() => {
                                void loadRun(which, which === 'a' ? selectedRunA : selectedRunB)
                              }}
                            >
                              {detailLoading.has(which) ? '读取中…' : '读取'}
                            </Button>
                          </div>
                          {loaded !== null ? (
                            <p className="break-all text-xs text-muted-foreground">
                              当前已加载：{loaded.run.id}；新选择在读取成功后才替换。
                            </p>
                          ) : null}
                        </div>
                      )
                    })}
                  </div>
                  {diff ? (
                    <>
                      <p className="my-3 break-all text-xs text-muted-foreground">
                        当前比较：A {diff.run_a.id} · B {diff.run_b.id}
                      </p>
                      <WorkspaceMetrics
                        items={[
                          { label: '命中变化', value: diff.hit_flips.total },
                          { label: '改善', value: diff.hit_flips.improved },
                          {
                            label: '退化',
                            value: diff.hit_flips.regressed,
                            tone: diff.hit_flips.regressed ? 'danger' : undefined,
                          },
                        ]}
                      />
                      <h3 className="my-5 text-sm font-semibold">全部已返回样本中的变化与不可比记录</h3>
                      <WorkspaceTableScroll label="运行样本差异">
                        <table className={cn(ws.table, 'min-w-[600px]')}>
                          <thead>
                            <tr>
                              <th>问题</th>
                              <th>A Recall</th>
                              <th>B Recall</th>
                              <th>变化</th>
                              <th>可比状态</th>
                            </tr>
                          </thead>
                          <tbody>
                            {diff.changed_cases.map((item) => (
                              <tr key={item.case_id}>
                                <td>
                                  <span className="block break-all font-mono text-[11px] text-muted-foreground">
                                    {item.case_id}
                                  </span>
                                  {item.question}
                                </td>
                                <td>{formatMetricValue(item.a_recall)}</td>
                                <td>{formatMetricValue(item.b_recall)}</td>
                                <td>{formatMetricValue(item.delta_recall)}</td>
                                <td>
                                  {item.presence === 'only_a' ? (
                                    '仅A返回此样本'
                                  ) : item.presence === 'only_b' ? (
                                    '仅B返回此样本'
                                  ) : item.a_error !== null || item.b_error !== null ? (
                                    <>
                                      A：{item.a_error === null ? '成功' : item.a_error}；B：
                                      {item.b_error === null ? '成功' : item.b_error}
                                    </>
                                  ) : (
                                    '两侧检索成功'
                                  )}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </WorkspaceTableScroll>
                      <RawResult label="完整运行对比" value={diff} />
                    </>
                  ) : (
                    <p className="py-8 text-sm text-muted-foreground">请选择不同的 A、B 运行并分别读取，再查看差异。</p>
                  )}
                </section>
              ) : null}
            </TabsContent>
          </Tabs>
        </DirectoryWorkspace>
      </OperationalWorkspace>
    </AppFrame>
  )
}
