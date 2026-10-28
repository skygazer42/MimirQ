'use client'

import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useTranslations } from 'next-intl'
import { toast } from 'sonner'
import { Download, Loader2 } from '@/components/icons'
import { AppFrame } from '@/components/app-frame'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { DirectoryWorkspace, OperationalWorkspace, WorkspaceMetrics, WorkspaceNotice, WorkspaceTableScroll, workspaceStyles as ws } from '@/components/ui/operational-workspace'
import { formatApiError } from '@/lib/api-errors'
import { datasetApi, evaluationApi, type KGHardcaseMode, type KGSearchDiagnosticsResponse, type KGSearchDiagnosticsRunDetail, type KGSearchDiagnosticsRunOut } from '@/lib/api'
import { toTrimmedPrimitiveString } from '@/lib/primitive-text'
import { queryKeys } from '@/lib/query-keys'
import { sanitizeFilename } from '@/lib/sanitize'
import { cn } from '@/lib/utils'
import type { JsonObject } from '@/types'

const DIAGNOSTICS_METRIC_LABELS: Record<string, string> = {
  baseline_hit_rate: '基线命中率',
  baseline_mrr: 'Baseline MRR',
  baseline_recall: 'Baseline Recall',
  baseline_ndcg: 'Baseline NDCG@K',
  baseline_map: 'Baseline MAP@K',
  hardcase_hit_rate: '难例命中率',
  hardcase_mrr: 'Hardcase MRR',
  hardcase_recall: 'Hardcase Recall',
  hardcase_ndcg: 'Hardcase NDCG@K',
  hardcase_map: 'Hardcase MAP@K',
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

type DiagnosticsRunCaseMetrics = ReturnType<typeof extractBaselineMetrics>
type DiagnosticsRunCaseMapValue = {
  question: string
  metrics: DiagnosticsRunCaseMetrics
}
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
]

function isDiagnosticsRecord(value: unknown): value is JsonObject {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function diagnosticsField(source: unknown, key: string): unknown {
  return isDiagnosticsRecord(source) ? source[key] : undefined
}

function diagnosticsRecordField(source: unknown, key: string): JsonObject | null {
  const value = diagnosticsField(source, key)
  return isDiagnosticsRecord(value) ? value : null
}

function downloadJson(value: unknown, filename: string): void {
  const content = JSON.stringify(value ?? {}, null, 2)
  const blob = new Blob([content], { type: 'application/json;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  globalThis.window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}

function toNumber(value: unknown): number | null {
  if (value === null || value === undefined) return null
  const n = Number(value)
  return Number.isFinite(n) ? n : null
}

function formatMetricValue(value: unknown): string {
  if (value === null || value === undefined) return '-'
  if (
    typeof value === 'number' ||
    typeof value === 'string' ||
    typeof value === 'boolean'
  ) {
    return String(value)
  }
  return JSON.stringify(value, null, 2)
}

function formatDiagnosticsMetricLabel(key: string): string {
  return DIAGNOSTICS_METRIC_LABELS[key] ?? key.replaceAll('_', ' ')
}

function extractBaselineMetrics(item: unknown): {
  hit_at_k: boolean
  mrr: number
  recall: number
  ndcg: number | null
  map: number | null
} | null {
  const baseline = diagnosticsRecordField(item, 'baseline')
  const metrics = diagnosticsRecordField(baseline, 'metrics')
  const hit = Boolean(diagnosticsField(metrics, 'hit_at_k'))
  const mrr = toNumber(diagnosticsField(metrics, 'mrr'))
  const recall = toNumber(diagnosticsField(metrics, 'recall'))
  const ndcg = toNumber(diagnosticsField(metrics, 'ndcg'))
  const meanAveragePrecision = toNumber(diagnosticsField(metrics, 'map'))
  if (mrr === null || recall === null) return null
  return {
    hit_at_k: hit,
    mrr,
    recall,
    ndcg,
    map: meanAveragePrecision,
  }
}

function caseKey(item: unknown): string | null {
  const id = diagnosticsField(item, 'case_id')
  const s = toTrimmedPrimitiveString(id)
  return s || null
}

function diagnosticsRunSummary(run: KGSearchDiagnosticsRunDetail['run']) {
  return isDiagnosticsRecord(run?.summary) ? run.summary : {}
}

function diagnosticsMetricDelta(aValue: number | null, bValue: number | null) {
  if (aValue === null || bValue === null) return null
  return Number((bValue - aValue).toFixed(4))
}

function buildDiagnosticsSummaryDelta(
  aSummary: JsonObject,
  bSummary: JsonObject
) {
  const summaryDelta: JsonObject = {}
  for (const key of DIAGNOSTICS_DIFF_METRIC_KEYS) {
    const aValue = toNumber(aSummary[key])
    const bValue = toNumber(bSummary[key])
    if (aValue === null && bValue === null) continue
    summaryDelta[key] = {
      a: aValue,
      b: bValue,
      delta: diagnosticsMetricDelta(aValue, bValue),
    }
  }
  return summaryDelta
}

function buildDiagnosticsCaseMap(
  items: JsonObject[] | undefined
): Map<string, DiagnosticsRunCaseMapValue> {
  const byCase = new Map<string, DiagnosticsRunCaseMapValue>()
  for (const item of items || []) {
    const key = caseKey(item)
    if (!key) continue
    byCase.set(key, {
      question: toTrimmedPrimitiveString(diagnosticsField(item, 'question')),
      metrics: extractBaselineMetrics(item),
    })
  }
  return byCase
}

function buildDiagnosticsDiffRow(
  key: string,
  byCaseA: Map<string, DiagnosticsRunCaseMapValue>,
  byCaseB: Map<string, DiagnosticsRunCaseMapValue>
): DiagnosticsRunDiffRow {
  const runCaseA = byCaseA.get(key)
  const runCaseB = byCaseB.get(key)
  const metricsA = runCaseA?.metrics
  const metricsB = runCaseB?.metrics
  const aRecall = metricsA?.recall ?? null
  const bRecall = metricsB?.recall ?? null
  const aMrr = metricsA?.mrr ?? null
  const bMrr = metricsB?.mrr ?? null

  return {
    case_id: key,
    question: runCaseA?.question || runCaseB?.question || '',
    a_hit: metricsA ? Boolean(metricsA.hit_at_k) : null,
    b_hit: metricsB ? Boolean(metricsB.hit_at_k) : null,
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
    row.delta_recall !== null ||
    row.delta_mrr !== null ||
    (row.a_hit !== null && row.b_hit !== null && row.a_hit !== row.b_hit)
  )
}

function compareDiagnosticsDiffRows(
  left: DiagnosticsRunDiffRow,
  right: DiagnosticsRunDiffRow
) {
  return Math.abs(right.delta_recall ?? 0) - Math.abs(left.delta_recall ?? 0)
}

function countDiagnosticsHitFlips(rows: DiagnosticsRunDiffRow[]) {
  const flips = rows.filter(
    (row) =>
      row.a_hit !== null && row.b_hit !== null && row.a_hit !== row.b_hit
  )
  const improved = flips.filter(
    (row) => row.a_hit === false && row.b_hit === true
  ).length
  const regressed = flips.filter(
    (row) => row.a_hit === true && row.b_hit === false
  ).length
  return { flips, improved, regressed }
}

function buildKgDiagnosticsDiff(
  detailA: KGSearchDiagnosticsRunDetail | null,
  detailB: KGSearchDiagnosticsRunDetail | null
) {
  if (!detailA?.run || !detailB?.run) return null

  const summaryDelta = buildDiagnosticsSummaryDelta(
    diagnosticsRunSummary(detailA.run),
    diagnosticsRunSummary(detailB.run)
  )
  const byCaseA = buildDiagnosticsCaseMap(detailA.items)
  const byCaseB = buildDiagnosticsCaseMap(detailB.items)
  const allKeys = new Set<string>([...byCaseA.keys(), ...byCaseB.keys()])
  const rows = Array.from(allKeys, (key) =>
    buildDiagnosticsDiffRow(key, byCaseA, byCaseB)
  )
  const changed = rows
    .filter(isChangedDiagnosticsDiffRow)
    .sort(compareDiagnosticsDiffRows)
    .slice(0, 20)
  const { flips, improved, regressed } = countDiagnosticsHitFlips(rows)

  return {
    run_a: detailA.run,
    run_b: detailB.run,
    summary_delta: summaryDelta,
    changed_cases: changed,
    hit_flips: { total: flips.length, improved, regressed },
  }
}


const selectClass = 'h-10 w-full min-w-0 rounded-md border border-input bg-background px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring'

function NumberSetting({ label, value, onChange, min, max, step = 1 }: { label: string; value: number; onChange: (value: number) => void; min: number; max: number; step?: number }) {
  return <label className="block space-y-2 text-[13px]">{label}<Input type="number" min={min} max={max} step={step} value={value} onChange={event => onChange(Number(event.target.value))} /></label>
}

function RawResult({ label, value }: { label: string; value: unknown }) {
  return <details className="mt-5 border-t border-border py-4"><summary className="cursor-pointer text-[13px] font-medium">{label}</summary><pre tabIndex={0} className="mt-3 max-h-96 overflow-auto bg-muted/30 p-4 text-xs leading-6">{JSON.stringify(value, null, 2)}</pre></details>
}

export function KGDiagnosticsPage() {
  const t = useTranslations('KGDiagnosticsPage')
  const datasetsQuery = useQuery({ queryKey: queryKeys.datasets.exhaustive({ purpose: 'kg-diagnostics' }), queryFn: () => datasetApi.listAll(), staleTime: 30_000 })
  const datasets = useMemo(() => datasetsQuery.data ?? [], [datasetsQuery.data])
  const [datasetId, setDatasetId] = useState('')
  const [pane, setPane] = useState<'directory' | 'detail'>('detail')
  const [activeView, setActiveView] = useState('run')
  const [maxCases, setMaxCases] = useState(50)
  const [k, setK] = useState(10)
  const [autoExtractKg, setAutoExtractKg] = useState(true)
  const [extractSkills, setExtractSkills] = useState('auto')
  const [extractRelations, setExtractRelations] = useState('auto')
  const [hardcaseMode, setHardcaseMode] = useState<KGHardcaseMode>('deterministic')
  const [hardcasesPerFailed, setHardcasesPerFailed] = useState(4)
  const [maxFailedForHardcase, setMaxFailedForHardcase] = useState(20)
  const [llmTemperature, setLlmTemperature] = useState(0.2)
  const [persistRun, setPersistRun] = useState(true)
  const [qualityDocLimit, setQualityDocLimit] = useState(200)
  const [qualityPipelineHash, setQualityPipelineHash] = useState('')
  const [qualityLoading, setQualityLoading] = useState(false)
  const [qualityReport, setQualityReport] = useState<JsonObject | null>(null)
  const [qualityError, setQualityError] = useState<string | null>(null)
  const [running, setRunning] = useState(false)
  const [runResp, setRunResp] = useState<KGSearchDiagnosticsResponse | null>(null)
  const [runError, setRunError] = useState<string | null>(null)
  const [runsLoading, setRunsLoading] = useState(false)
  const [runs, setRuns] = useState<KGSearchDiagnosticsRunOut[]>([])
  const [runsError, setRunsError] = useState<string | null>(null)
  const [selectedRunA, setSelectedRunA] = useState('')
  const [selectedRunB, setSelectedRunB] = useState('')
  const [detailA, setDetailA] = useState<KGSearchDiagnosticsRunDetail | null>(null)
  const [detailB, setDetailB] = useState<KGSearchDiagnosticsRunDetail | null>(null)
  const [detailError, setDetailError] = useState<string | null>(null)
  const [detailLoading, setDetailLoading] = useState<'a' | 'b' | null>(null)
  const [analysisTab, setAnalysisTab] = useState('failures')
  const scope = useRef({ datasetId })
  const requests = useRef({ runs: 0, a: 0, b: 0 })
  useEffect(() => { if (!datasetId && datasets[0]) setDatasetId(datasets[0].id) }, [datasets, datasetId])
  useLayoutEffect(() => {
    scope.current = { datasetId }
    setRunResp(null); setQualityReport(null); setRuns([]); setDetailA(null); setDetailB(null)
    setSelectedRunA(''); setSelectedRunB(''); setQualityPipelineHash('')
    setRunError(null); setQualityError(null); setRunsError(null); setDetailError(null)
    setRunning(false); setQualityLoading(false); setRunsLoading(false); setDetailLoading(null); setActiveView('run')
  }, [datasetId])

  async function refreshRuns() {
    if (!datasetId) return
    const context = scope.current, request = ++requests.current.runs
    setRunsLoading(true); setRunsError(null)
    try {
      const response = await evaluationApi.listKgSearchDiagnosticsRuns({ dataset_id: datasetId, limit: 50 })
      if (scope.current !== context || request !== requests.current.runs) return
      setRuns(response.items)
      setSelectedRunA(current => current || response.items[0]?.id || '')
      setSelectedRunB(current => current || response.items[1]?.id || response.items[0]?.id || '')
    } catch (error) {
      if (scope.current === context && request === requests.current.runs) setRunsError(formatApiError(error, t('toasts.runsLoadFailed')))
    } finally { if (scope.current === context && request === requests.current.runs) setRunsLoading(false) }
  }

  async function loadRun(which: 'a' | 'b', id: string) {
    const context = scope.current, request = ++requests.current[which]
    setDetailLoading(which); setDetailError(null)
    if (which === 'a') setDetailA(null); else setDetailB(null)
    try {
      const result = await evaluationApi.getKgSearchDiagnosticsRun(id)
      if (scope.current !== context || requests.current[which] !== request) return
      if (which === 'a') setDetailA(result); else setDetailB(result)
    } catch (error) {
      if (scope.current === context && requests.current[which] === request) setDetailError(formatApiError(error, '运行记录读取失败'))
    } finally { if (scope.current === context && requests.current[which] === request) setDetailLoading(null) }
  }

  async function loadQualityReport() {
    const context = scope.current
    setQualityLoading(true); setQualityError(null); setQualityReport(null)
    try {
      const result = await evaluationApi.getKgQualityReport({ dataset_id: datasetId, document_limit: Math.max(1, Math.min(qualityDocLimit, 2000)), pipeline_hash: qualityPipelineHash.trim() || undefined })
      if (scope.current === context) setQualityReport(result)
    } catch (error) { if (scope.current === context) setQualityError(formatApiError(error, t('toasts.qualityReportLoadFailed'))) }
    finally { if (scope.current === context) setQualityLoading(false) }
  }

  async function runDiagnostics() {
    const context = scope.current
    setRunning(true); setRunResp(null); setRunError(null); setActiveView('run'); setPane('detail')
    try {
      const result = await evaluationApi.runKgSearchDiagnostics({ dataset_id: datasetId, max_cases: Math.max(1, Math.min(maxCases, 200)), k: Math.max(1, Math.min(k, 50)), auto_extract_kg: autoExtractKg, extract_skills: extractSkills === 'auto' ? null : extractSkills === 'on', extract_relations: extractRelations === 'auto' ? null : extractRelations === 'on', hardcase_mode: hardcaseMode, hardcases_per_failed_case: Math.max(0, Math.min(hardcasesPerFailed, 20)), max_failed_cases_for_hardcase: Math.max(0, Math.min(maxFailedForHardcase, 200)), llm_temperature: Math.max(0, Math.min(llmTemperature, 2)), persist_run: persistRun })
      if (scope.current !== context) return
      setRunResp(result)
      toast.success(t('toasts.diagnosticsRan'))
      if (persistRun) await refreshRuns()
    } catch (error) { if (scope.current === context) setRunError(formatApiError(error, t('toasts.diagnosticsRunFailed'))) }
    finally { if (scope.current === context) setRunning(false) }
  }

  const diff = useMemo(() => buildKgDiagnosticsDiff(detailA, detailB), [detailA, detailB])
  const items = runResp?.items ?? []
  const failedItems = items.filter(item => { const metrics = extractBaselineMetrics(item); return metrics !== null && !metrics.hit_at_k })
  const summary = runResp?.summary
  const configuration = <div className="space-y-5 p-4">
    <h2 className={ws.sectionTitle}>评测配置</h2>
    <label className="block space-y-2 text-[13px]">数据集<select aria-label="数据集" className={selectClass} value={datasetId} disabled={datasetsQuery.isLoading} onChange={event => setDatasetId(event.target.value)}><option value="" disabled>选择数据集</option>{datasets.map(dataset => <option key={dataset.id} value={dataset.id}>{dataset.name}</option>)}</select></label>
    <NumberSetting label="评测样本数" value={maxCases} onChange={setMaxCases} min={1} max={200} />
    <NumberSetting label="TOP-K" value={k} onChange={setK} min={1} max={50} />
    <div className={ws.formRow}><label htmlFor="kg-auto-extract">自动抽取 KG</label><Switch id="kg-auto-extract" checked={autoExtractKg} onCheckedChange={setAutoExtractKg} /></div>
    <div className={ws.formRow}><label htmlFor="kg-persist-run">保存运行记录</label><Switch id="kg-persist-run" checked={persistRun} onCheckedChange={setPersistRun} /></div>
    <details className="border-t border-border pt-4"><summary className="cursor-pointer text-sm font-medium">抽取与难例参数</summary><div className="mt-4 space-y-5">
      <label className="block space-y-2 text-[13px]">技能抽取<select className={selectClass} value={extractSkills} onChange={event => setExtractSkills(event.target.value)}><option value="auto">自动</option><option value="on">开启</option><option value="off">关闭</option></select></label>
      <label className="block space-y-2 text-[13px]">关系抽取<select className={selectClass} value={extractRelations} onChange={event => setExtractRelations(event.target.value)}><option value="auto">自动</option><option value="on">开启</option><option value="off">关闭</option></select></label>
      <label className="block space-y-2 text-[13px]">难例生成方式<select className={selectClass} value={hardcaseMode} onChange={event => setHardcaseMode(event.target.value as KGHardcaseMode)}><option value="off">关闭</option><option value="deterministic">规则生成</option><option value="llm">模型生成</option></select></label>
      <NumberSetting label="每条失败样本的难例数" value={hardcasesPerFailed} onChange={setHardcasesPerFailed} min={0} max={20} />
      <NumberSetting label="生成难例的失败样本上限" value={maxFailedForHardcase} onChange={setMaxFailedForHardcase} min={0} max={200} />
      <NumberSetting label="模型温度" value={llmTemperature} onChange={setLlmTemperature} min={0} max={2} step={0.1} />
    </div></details>
  </div>

  return <AppFrame showBackground={false}><OperationalWorkspace title={t('page.title')} icon="kg-retrieval-evaluation" mode="canvas" context={datasets.find(dataset => dataset.id === datasetId)?.name || '选择数据集'} actions={<><Button variant="ghost" disabled={!runResp} aria-label="导出本次评测" onClick={() => { downloadJson(runResp, `${sanitizeFilename(`kg_diagnostics_${datasetId}`)}.json`); toast.success(t('toasts.runExported')) }}><Download className="size-4" /><span className="hidden sm:inline">导出</span></Button><Button disabled={!datasetId || running} onClick={() => { void runDiagnostics() }}>{running ? <Loader2 className="size-4 animate-spin motion-reduce:animate-none" /> : null}{running ? '正在评测…' : '开始评测'}</Button></>}>
    {datasetsQuery.isError ? <div className="px-4"><WorkspaceNotice retry={() => { void datasetsQuery.refetch() }}>{formatApiError(datasetsQuery.error, '数据集读取失败')}</WorkspaceNotice></div> : null}
    <DirectoryWorkspace pane={pane} onPaneChange={setPane} directoryLabel="评测配置" detailLabel="报告结果" directory={configuration}>
      <Tabs value={activeView} onValueChange={setActiveView}>
        <TabsList className={ws.tabList}><TabsTrigger value="run">本次评测</TabsTrigger><TabsTrigger value="quality">抽取质量</TabsTrigger><TabsTrigger value="compare" onClick={() => { if (!runs.length && !runsLoading) void refreshRuns() }}>运行历史与比较</TabsTrigger></TabsList>
        <TabsContent value="run" className={ws.tabContent}>
          {runError ? <WorkspaceNotice retry={() => { void runDiagnostics() }} retryLabel="重新评测" pending={running}>{runError}</WorkspaceNotice> : null}
          {running ? <p role="status" className="py-12 text-sm text-muted-foreground">正在评测当前数据集…</p> : runResp ? <>
            <WorkspaceMetrics items={['baseline_hit_rate', 'baseline_mrr', 'baseline_recall', 'baseline_ndcg', 'baseline_map', 'hardcases_generated'].map(key => ({ label: formatDiagnosticsMetricLabel(key), value: formatMetricValue(diagnosticsField(summary, key)) }))} />
            <section className={ws.section}><div className={ws.sectionHeading}><h2 className={ws.sectionTitle}>样本结果</h2><div role="group" aria-label="样本结果视图" className="flex gap-2">{[['failures', '未命中样本'], ['all', '全部样本'], ['distribution', '得分分布']].map(([value, label]) => <Button key={value} variant={analysisTab === value ? 'secondary' : 'ghost'} aria-pressed={analysisTab === value} onClick={() => setAnalysisTab(value)}>{label}</Button>)}</div></div>
              {analysisTab === 'distribution' ? <div className="space-y-4">{Array.from({ length: 5 }, (_, index) => { const values = items.map(extractBaselineMetrics).filter(value => value !== null); const count = values.filter(value => value.recall >= index / 5 && (index === 4 ? value.recall <= 1 : value.recall < (index + 1) / 5)).length; return <div key={index} className="grid grid-cols-[72px_minmax(0,1fr)_40px] items-center gap-4 text-[13px]"><span>{(index / 5).toFixed(1)}–{((index + 1) / 5).toFixed(1)}</span><span className="h-2 bg-muted"><span className="block h-2 bg-foreground/60" style={{ width: `${values.length ? count / values.length * 100 : 0}%` }} /></span><span className="text-right tabular-nums">{count}</span></div> })}</div> : <WorkspaceTableScroll label="评测样本结果"><table className={cn(ws.table, 'min-w-[560px]')}><thead><tr><th>问题</th><th>命中</th><th>Recall</th><th>MRR</th></tr></thead><tbody>{(analysisTab === 'failures' ? failedItems : items).map(item => { const metrics = extractBaselineMetrics(item); return <tr key={item.case_id}><td className="max-w-lg">{item.question}</td><td>{metrics ? metrics.hit_at_k ? '命中' : '未命中' : '未返回'}</td><td>{metrics ? formatMetricValue(metrics.recall) : '—'}</td><td>{metrics ? formatMetricValue(metrics.mrr) : '—'}</td></tr> })}</tbody></table>{!(analysisTab === 'failures' ? failedItems : items).length ? <p className="py-8 text-sm text-muted-foreground">{analysisTab === 'failures' ? '本次结果没有可展示的未命中样本' : '本次评测未返回样本明细'}</p> : null}</WorkspaceTableScroll>}
            </section><RawResult label="完整评测结果" value={runResp} />
          </> : !runError ? <div className={ws.empty}><h2>尚未运行评测</h2><p>选择数据集并确认参数后，开始评测。</p></div> : null}
        </TabsContent>
        <TabsContent value="quality" className={ws.tabContent}>
          <div className="flex flex-wrap items-end gap-4 py-5"><div className="w-40"><NumberSetting label="抽样文档上限" value={qualityDocLimit} onChange={setQualityDocLimit} min={1} max={2000} /></div><label className="block max-w-full space-y-2 text-[13px]">流程版本（选填）<Input value={qualityPipelineHash} onChange={event => setQualityPipelineHash(event.target.value)} placeholder="Pipeline hash" /></label><Button disabled={!datasetId || qualityLoading} onClick={() => { void loadQualityReport() }}>{qualityLoading ? '正在读取…' : '读取质量报告'}</Button></div>
          {qualityError ? <WorkspaceNotice retry={() => { void loadQualityReport() }}>{qualityError}</WorkspaceNotice> : null}
          {qualityReport ? <><WorkspaceMetrics items={Object.entries(qualityReport).filter(([, value]) => typeof value === 'number').slice(0, 8).map(([key, value]) => ({ label: formatDiagnosticsMetricLabel(key), value: formatMetricValue(value) }))} /><RawResult label="完整质量报告" value={qualityReport} /></> : !qualityLoading && !qualityError ? <div className={ws.empty}><h2>尚未读取质量报告</h2><p>读取后查看实体、关系和来源引用的实际统计。</p></div> : null}
        </TabsContent>
        <TabsContent value="compare" className={ws.tabContent}>
          <div className={cn(ws.sectionHeading, 'mt-5')}><h2 className={ws.sectionTitle}>运行历史</h2><Button variant="outline" disabled={!datasetId || runsLoading} onClick={() => { void refreshRuns() }}>{runsLoading ? '正在读取…' : '重新读取运行记录'}</Button></div>
          {runsError ? <WorkspaceNotice retry={() => { void refreshRuns() }}>{runsError}</WorkspaceNotice> : null}
          {!runsLoading && !runsError && !runs.length ? <div className={ws.empty}><h2>当前数据集暂无运行记录</h2><p>运行评测时开启“保存运行记录”，即可在这里对比。</p></div> : <WorkspaceTableScroll label="诊断运行历史"><table className={cn(ws.table, 'min-w-[540px]')}><thead><tr><th>运行</th><th>时间</th><th>命中率</th><th>MRR</th></tr></thead><tbody>{runs.map(run => <tr key={run.id}><td className="font-mono">{run.id.slice(0, 8)}</td><td>{run.created_at.replace('T', ' ').slice(0, 19)}</td><td>{formatMetricValue(diagnosticsField(run.summary, 'baseline_hit_rate'))}</td><td>{formatMetricValue(diagnosticsField(run.summary, 'baseline_mrr'))}</td></tr>)}</tbody></table></WorkspaceTableScroll>}
          {runs.length ? <section className={ws.section}><div className="grid gap-4 sm:grid-cols-2">{(['a', 'b'] as const).map(which => <div key={which} className="space-y-2"><label className="block text-sm" htmlFor={`kg-run-${which}`}>运行 {which.toUpperCase()}</label><div className="flex gap-2"><select id={`kg-run-${which}`} className={selectClass} value={which === 'a' ? selectedRunA : selectedRunB} onChange={event => { requests.current[which]++; setDetailLoading(null); if (which === 'a') { setSelectedRunA(event.target.value); setDetailA(null) } else { setSelectedRunB(event.target.value); setDetailB(null) } }}>{runs.map(run => <option key={run.id} value={run.id}>{run.created_at.slice(0, 19)} · {run.id.slice(0, 8)}</option>)}</select><Button variant="outline" disabled={detailLoading !== null || !(which === 'a' ? selectedRunA : selectedRunB)} onClick={() => { void loadRun(which, which === 'a' ? selectedRunA : selectedRunB) }}>{detailLoading === which ? '读取中…' : '读取'}</Button></div></div>)}</div>
            {detailError ? <WorkspaceNotice>{detailError}</WorkspaceNotice> : null}
            {diff ? <><WorkspaceMetrics items={[{ label: '命中变化', value: diff.hit_flips.total }, { label: '改善', value: diff.hit_flips.improved }, { label: '退化', value: diff.hit_flips.regressed, tone: diff.hit_flips.regressed ? 'danger' : undefined }]} /><h3 className="my-5 text-sm font-semibold">样本差异（最多 20 条）</h3><WorkspaceTableScroll label="运行样本差异"><table className={cn(ws.table, 'min-w-[600px]')}><thead><tr><th>问题</th><th>A Recall</th><th>B Recall</th><th>变化</th></tr></thead><tbody>{diff.changed_cases.map(item => <tr key={item.case_id}><td>{item.question || item.case_id}</td><td>{formatMetricValue(item.a_recall)}</td><td>{formatMetricValue(item.b_recall)}</td><td>{formatMetricValue(item.delta_recall)}</td></tr>)}</tbody></table></WorkspaceTableScroll><RawResult label="完整运行对比" value={diff} /></> : <p className="py-8 text-sm text-muted-foreground">分别读取 A、B 运行记录，查看结果差异。</p>}
          </section> : null}
        </TabsContent>
      </Tabs>
    </DirectoryWorkspace>
  </OperationalWorkspace></AppFrame>
}
