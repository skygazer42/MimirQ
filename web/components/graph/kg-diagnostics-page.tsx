'use client'

import { useMemo, useState } from 'react'
import { Activity, Download, GitCompare, PlayCircle, RefreshCcw } from 'lucide-react'
import { useTranslations } from 'next-intl'
import { toast } from 'sonner'

import { AppFrame } from '@/components/app-frame'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { PageScaffold } from '@/components/ui/page-scaffold'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { formatApiError } from '@/lib/api-errors'
import { evaluationApi, type KGHardcaseMode, type KGSearchDiagnosticsResponse, type KGSearchDiagnosticsRunDetail } from '@/lib/api'
import { coerceOneOf } from '@/lib/one-of'
import { sanitizeFilename } from '@/lib/sanitize'

const KG_EXTRACT_MODE_VALUES = ['auto', 'on', 'off'] as const

function prettyJson(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
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

function toNumber(value: any): number | null {
  if (value === null || value === undefined) return null
  const n = Number(value)
  return Number.isFinite(n) ? n : null
}

function formatMetricValue(value: unknown): string {
  if (value === null || value === undefined) return '-'
  if (typeof value === 'number' || typeof value === 'string' || typeof value === 'boolean') {
    return String(value)
  }
  return prettyJson(value)
}

function extractBaselineMetrics(item: any): { hit_at_k: boolean; mrr: number; recall: number } | null {
  const baseline = item?.baseline
  const metrics = baseline?.metrics
  const hit = Boolean(metrics?.hit_at_k)
  const mrr = toNumber(metrics?.mrr)
  const recall = toNumber(metrics?.recall)
  if (mrr === null || recall === null) return null
  return { hit_at_k: hit, mrr, recall }
}

function caseKey(item: any): string | null {
  const id = item?.case_id
  const s = String(id || '').trim()
  return s || null
}

export function KGDiagnosticsPage() {
  const t = useTranslations('KGDiagnosticsPage')
  const [datasetId, setDatasetId] = useState('')

  const [qualityDocLimit, setQualityDocLimit] = useState(200)
  const [qualityPipelineHash, setQualityPipelineHash] = useState('')
  const [qualityLoading, setQualityLoading] = useState(false)
  const [qualityReport, setQualityReport] = useState<any | null>(null)
  const qualityJson = useMemo(
    () => prettyJson(qualityReport ?? { hint: t("qualityReport.hint") }),
    [qualityReport, t]
  )

  const [maxCases, setMaxCases] = useState(50)
  const [k, setK] = useState(10)
  const [autoExtractKg, setAutoExtractKg] = useState(true)
  const [extractSkills, setExtractSkills] = useState<'auto' | 'on' | 'off'>('auto')
  const [extractRelations, setExtractRelations] = useState<'auto' | 'on' | 'off'>('auto')
  const [hardcaseMode, setHardcaseMode] = useState<KGHardcaseMode>('deterministic')
  const [hardcasesPerFailed, setHardcasesPerFailed] = useState(4)
  const [maxFailedForHardcase, setMaxFailedForHardcase] = useState(20)
  const [llmTemperature, setLlmTemperature] = useState(0.2)
  const [persistRun, setPersistRun] = useState(true)

  const [running, setRunning] = useState(false)
  const [runResp, setRunResp] = useState<KGSearchDiagnosticsResponse | null>(null)
  const runRespJson = useMemo(() => prettyJson(runResp ?? { hint: t("summary.runHint") }), [runResp, t])

  const [runsLoading, setRunsLoading] = useState(false)
  const [runs, setRuns] = useState<any[]>([])
  const [selectedRunA, setSelectedRunA] = useState<string>('')
  const [selectedRunB, setSelectedRunB] = useState<string>('')
  const [detailA, setDetailA] = useState<KGSearchDiagnosticsRunDetail | null>(null)
  const [detailB, setDetailB] = useState<KGSearchDiagnosticsRunDetail | null>(null)

  const diff = useMemo(() => {
    if (!detailA?.run || !detailB?.run) return null
    const a = detailA
    const b = detailB

    const aSummary = (a.run?.summary && typeof a.run.summary === 'object' ? a.run.summary : {})
    const bSummary = (b.run?.summary && typeof b.run.summary === 'object' ? b.run.summary : {})

    const keys = ['baseline_hit_rate', 'baseline_mrr', 'baseline_recall', 'hardcase_hit_rate', 'hardcase_mrr', 'hardcase_recall']
    const summaryDelta: Record<string, any> = {}
    for (const key of keys) {
      const av = toNumber(aSummary[key])
      const bv = toNumber(bSummary[key])
      if (av === null && bv === null) continue
      summaryDelta[key] = { a: av, b: bv, delta: av !== null && bv !== null ? Number((bv - av).toFixed(4)) : null }
    }

    const byCaseA = new Map<string, { question: string; metrics: ReturnType<typeof extractBaselineMetrics> }>()
    for (const item of a.items || []) {
      const key = caseKey(item)
      if (!key) continue
      byCaseA.set(key, { question: String(item?.question || ''), metrics: extractBaselineMetrics(item) })
    }

    const byCaseB = new Map<string, { question: string; metrics: ReturnType<typeof extractBaselineMetrics> }>()
    for (const item of b.items || []) {
      const key = caseKey(item)
      if (!key) continue
      byCaseB.set(key, { question: String(item?.question || ''), metrics: extractBaselineMetrics(item) })
    }

    const allKeys = new Set<string>([...Array.from(byCaseA.keys()), ...Array.from(byCaseB.keys())])
    const rows: Array<{
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
    }> = []

    for (const key of allKeys) {
      const ra = byCaseA.get(key)
      const rb = byCaseB.get(key)
      const qa = ra?.question || ''
      const qb = rb?.question || ''
      const question = qa || qb
      const ma = ra?.metrics
      const mb = rb?.metrics
      const a_hit = ma ? Boolean(ma.hit_at_k) : null
      const b_hit = mb ? Boolean(mb.hit_at_k) : null
      const a_mrr = ma ? ma.mrr : null
      const b_mrr = mb ? mb.mrr : null
      const a_recall = ma ? ma.recall : null
      const b_recall = mb ? mb.recall : null
      rows.push({
        case_id: key,
        question,
        a_hit,
        b_hit,
        a_mrr,
        b_mrr,
        a_recall,
        b_recall,
        delta_recall: a_recall !== null && b_recall !== null ? Number((b_recall - a_recall).toFixed(4)) : null,
        delta_mrr: a_mrr !== null && b_mrr !== null ? Number((b_mrr - a_mrr).toFixed(4)) : null,
      })
    }

    const changed = rows
      .filter((r) => r.delta_recall !== null || r.delta_mrr !== null || (r.a_hit !== null && r.b_hit !== null && r.a_hit !== r.b_hit))
      .sort((x, y) => Math.abs(y.delta_recall ?? 0) - Math.abs(x.delta_recall ?? 0))
      .slice(0, 20)

    const flips = rows.filter((r) => r.a_hit !== null && r.b_hit !== null && r.a_hit !== r.b_hit)
    const improved = flips.filter((r) => r.a_hit === false && r.b_hit === true).length
    const regressed = flips.filter((r) => r.a_hit === true && r.b_hit === false).length

    return {
      run_a: a.run,
      run_b: b.run,
      summary_delta: summaryDelta,
      changed_cases: changed,
      hit_flips: { total: flips.length, improved, regressed },
    }
  }, [detailA, detailB])

  const diffJson = useMemo(() => prettyJson(diff ?? { hint: '选择两个 runs 并加载后生成 diff' }), [diff])

  async function refreshRuns(): Promise<void> {
    const ds = datasetId.trim()
    if (!ds) {
      toast.error(t("toasts.datasetRequired"))
      return
    }
    setRunsLoading(true)
    try {
      const res = await evaluationApi.listKgSearchDiagnosticsRuns({ dataset_id: ds, limit: 50 })
      const items = Array.isArray(res.items) ? res.items : []
      setRuns(items)
      if (!selectedRunA && items?.[0]?.id) setSelectedRunA(items[0].id)
    } catch (err) {
      toast.error(formatApiError(err, t("toasts.runsLoadFailed")))
    } finally {
      setRunsLoading(false)
    }
  }

  async function loadRun(which: 'a' | 'b', runId: string): Promise<void> {
    const id = String(runId || '').trim()
    if (!id) return
    try {
      const detail = await evaluationApi.getKgSearchDiagnosticsRun(id)
      if (which === 'a') setDetailA(detail)
      else setDetailB(detail)
    } catch (err) {
      toast.error(formatApiError(err, t("toasts.runLoadFailed", { id: id.slice(0, 8) })))
    }
  }

  async function loadQualityReport(): Promise<void> {
    const ds = datasetId.trim()
    if (!ds) {
      toast.error(t("toasts.datasetRequired"))
      return
    }
    setQualityLoading(true)
    try {
      const resp = await evaluationApi.getKgQualityReport({
        dataset_id: ds,
        document_limit: Math.max(1, Math.min(qualityDocLimit, 2000)),
        pipeline_hash: qualityPipelineHash.trim() || undefined,
      })
      setQualityReport(resp ?? null)
      toast.success(t("toasts.qualityReportLoaded"))
    } catch (err) {
      toast.error(formatApiError(err, t("toasts.qualityReportLoadFailed")))
    } finally {
      setQualityLoading(false)
    }
  }

  async function runDiagnostics(): Promise<void> {
    const ds = datasetId.trim()
    if (!ds) {
      toast.error(t("toasts.datasetRequired"))
      return
    }
    setRunning(true)
    setRunResp(null)
    try {
      const resp = await evaluationApi.runKgSearchDiagnostics({
        dataset_id: ds,
        max_cases: Math.max(1, Math.min(maxCases, 200)),
        k: Math.max(1, Math.min(k, 50)),
        auto_extract_kg: Boolean(autoExtractKg),
        extract_skills: extractSkills === 'auto' ? null : extractSkills === 'on',
        extract_relations: extractRelations === 'auto' ? null : extractRelations === 'on',
        hardcase_mode: hardcaseMode,
        hardcases_per_failed_case: Math.max(0, Math.min(hardcasesPerFailed, 20)),
        max_failed_cases_for_hardcase: Math.max(0, Math.min(maxFailedForHardcase, 200)),
        llm_temperature: Math.max(0, Math.min(llmTemperature, 2)),
        persist_run: Boolean(persistRun),
      })
      setRunResp(resp || null)
      toast.success(t("toasts.diagnosticsRan"))
      if (persistRun) {
        // Refresh runs so user can diff right away.
        await refreshRuns()
      }
    } catch (err) {
      toast.error(formatApiError(err, t("toasts.diagnosticsRunFailed")))
    } finally {
      setRunning(false)
    }
  }

  const summary = runResp?.summary && typeof runResp.summary === 'object' ? runResp.summary : null

  return (
    <AppFrame>
      <PageScaffold
        title={t("page.title")}
        description={t("page.description")}
        icon={Activity}
        iconColor="text-sky-600 dark:text-sky-400"
        size="7xl"
        actions={
          <div className="flex items-center gap-2">
            <Button variant="outline" size="sm" className="gap-2" onClick={refreshRuns} disabled={runsLoading}>
              <RefreshCcw className="h-4 w-4" aria-hidden="true" />
              {t("page.actions.refreshRuns")}
            </Button>
            <Button size="sm" className="gap-2" onClick={runDiagnostics} disabled={running}>
              <PlayCircle className="h-4 w-4" aria-hidden="true" />
              {t("page.actions.run")}
            </Button>
            <Button
              variant="outline"
              size="sm"
              className="gap-2"
              onClick={() => {
                const base = sanitizeFilename(`kg_diagnostics_${datasetId.trim() || 'dataset'}`)
                downloadJson(runResp ?? {}, `${base}.json`)
                toast.success(t("toasts.runExported"))
              }}
              disabled={!runResp}
            >
              <Download className="h-4 w-4" aria-hidden="true" />
              {t("page.actions.exportRun")}
            </Button>
          </div>
        }
      >
        <div className="grid gap-4 lg:grid-cols-2">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">{t("runConfig.title")}</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="grid gap-3 md:grid-cols-2">
                <div className="space-y-1">
                  <Label>{t("runConfig.datasetId")}</Label>
                  <Input
                    value={datasetId}
                    onChange={(e) => setDatasetId(e.target.value)}
                    placeholder={t("runConfig.datasetPlaceholder")}
                  />
                </div>
                <div className="space-y-1">
                  <Label>{t("runConfig.hardcaseMode")}</Label>
                  <Select value={hardcaseMode} onValueChange={(v) => setHardcaseMode(v as KGHardcaseMode)}>
                    <SelectTrigger>
                      <SelectValue placeholder={t("runConfig.hardcaseModePlaceholder")} />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="off">off</SelectItem>
                      <SelectItem value="deterministic">deterministic</SelectItem>
                      <SelectItem value="llm">llm</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-1">
                  <Label>{t("runConfig.maxCases")}</Label>
                  <Input
                    type="number"
                    value={String(maxCases)}
                    onChange={(e) => setMaxCases(Number(e.target.value || 0))}
                    min={1}
                    max={200}
                  />
                </div>
                <div className="space-y-1">
                  <Label>{t("runConfig.k")}</Label>
                  <Input
                    type="number"
                    value={String(k)}
                    onChange={(e) => setK(Number(e.target.value || 0))}
                    min={1}
                    max={50}
                  />
                </div>
                <div className="space-y-1">
                  <Label>{t("runConfig.hardcasesPerFailedCase")}</Label>
                  <Input
                    type="number"
                    value={String(hardcasesPerFailed)}
                    onChange={(e) => setHardcasesPerFailed(Number(e.target.value || 0))}
                    min={0}
                    max={20}
                  />
                </div>
                <div className="space-y-1">
                  <Label>{t("runConfig.maxFailedCasesForHardcase")}</Label>
                  <Input
                    type="number"
                    value={String(maxFailedForHardcase)}
                    onChange={(e) => setMaxFailedForHardcase(Number(e.target.value || 0))}
                    min={0}
                    max={200}
                  />
                </div>
                <div className="space-y-1">
                  <Label>{t("runConfig.llmTemperature")}</Label>
                  <Input
                    type="number"
                    value={String(llmTemperature)}
                    onChange={(e) => setLlmTemperature(Number(e.target.value || 0))}
                    min={0}
                    max={2}
                    step={0.1}
                  />
                </div>
                <div className="space-y-1">
                  <Label>{t("runConfig.extractSkills")}</Label>
                  <Select
                    value={extractSkills}
                    onValueChange={(value) => setExtractSkills(coerceOneOf(KG_EXTRACT_MODE_VALUES, value, 'auto'))}
                  >
                    <SelectTrigger>
                      <SelectValue placeholder={t("runConfig.extractModePlaceholder")} />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="auto">auto</SelectItem>
                      <SelectItem value="on">on</SelectItem>
                      <SelectItem value="off">off</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-1">
                  <Label>{t("runConfig.extractRelations")}</Label>
                  <Select
                    value={extractRelations}
                    onValueChange={(value) => setExtractRelations(coerceOneOf(KG_EXTRACT_MODE_VALUES, value, 'auto'))}
                  >
                    <SelectTrigger>
                      <SelectValue placeholder={t("runConfig.extractModePlaceholder")} />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="auto">auto</SelectItem>
                      <SelectItem value="on">on</SelectItem>
                      <SelectItem value="off">off</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
              </div>

              <div className="flex flex-wrap items-center gap-4">
                <Label className="flex items-center gap-2">
                  <Checkbox checked={autoExtractKg} onCheckedChange={(v) => setAutoExtractKg(Boolean(v))} />
                  {t("runConfig.autoExtractKg")}
                </Label>
                <Label className="flex items-center gap-2">
                  <Checkbox checked={persistRun} onCheckedChange={(v) => setPersistRun(Boolean(v))} />
                  {t("runConfig.persistRun")}
                </Label>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">{t("summary.title")}</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              {summary ? (
                <div className="grid gap-2 md:grid-cols-2">
                  <div className="rounded-md border bg-muted/20 p-3">
                    <div className="text-xs text-muted-foreground">{t("summary.baselineHitRate")}</div>
                    <div className="text-lg font-semibold tabular-nums">{formatMetricValue(summary.baseline_hit_rate)}</div>
                  </div>
                  <div className="rounded-md border bg-muted/20 p-3">
                    <div className="text-xs text-muted-foreground">{t("summary.baselineMrr")}</div>
                    <div className="text-lg font-semibold tabular-nums">{formatMetricValue(summary.baseline_mrr)}</div>
                  </div>
                  <div className="rounded-md border bg-muted/20 p-3">
                    <div className="text-xs text-muted-foreground">{t("summary.baselineRecall")}</div>
                    <div className="text-lg font-semibold tabular-nums">{formatMetricValue(summary.baseline_recall)}</div>
                  </div>
                  <div className="rounded-md border bg-muted/20 p-3">
                    <div className="text-xs text-muted-foreground">{t("summary.hardcasesGenerated")}</div>
                    <div className="text-lg font-semibold tabular-nums">{formatMetricValue(summary.hardcases_generated)}</div>
                  </div>
                </div>
              ) : (
                <div className="text-sm text-muted-foreground">{t("summary.empty")}</div>
              )}
              <Textarea value={runRespJson} readOnly rows={12} className="font-mono text-xs" />
            </CardContent>
          </Card>
        </div>

        <div className="mt-4 grid gap-4 lg:grid-cols-2">
          <Card className="lg:col-span-2">
            <CardHeader className="flex flex-row items-center justify-between gap-2">
              <CardTitle className="text-base">{t("qualityReport.title")}</CardTitle>
              <Button variant="outline" size="sm" className="gap-2" onClick={loadQualityReport} disabled={qualityLoading}>
                <RefreshCcw className="h-4 w-4" aria-hidden="true" />
                {t("qualityReport.pull")}
              </Button>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="grid gap-3 md:grid-cols-3">
                <div className="space-y-1">
                  <Label>{t("qualityReport.documentLimit")}</Label>
                  <Input
                    type="number"
                    value={String(qualityDocLimit)}
                    onChange={(e) => setQualityDocLimit(Number(e.target.value || 0))}
                    min={1}
                    max={2000}
                  />
                </div>
                <div className="space-y-1 md:col-span-2">
                  <Label>{t("qualityReport.pipelineHash")}</Label>
                  <Input
                    value={qualityPipelineHash}
                    onChange={(e) => setQualityPipelineHash(e.target.value)}
                    placeholder={t("qualityReport.pipelineHashPlaceholder")}
                  />
                </div>
              </div>
              <Textarea value={qualityJson} readOnly rows={10} className="font-mono text-xs" />
            </CardContent>
          </Card>
        </div>

        <div className="mt-4 grid gap-4 lg:grid-cols-2">
          <Card>
            <CardHeader className="flex flex-row items-center justify-between gap-2">
              <CardTitle className="text-base">Runs（持久化）</CardTitle>
              <Button variant="outline" size="sm" className="gap-2" onClick={refreshRuns} disabled={runsLoading}>
                <RefreshCcw className="h-4 w-4" aria-hidden="true" />
                刷新
              </Button>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="text-xs text-muted-foreground">
                需要先勾选 persist_run 才能在这里看到 runs；compare 以 run.items 的 case_id 为 key。
              </div>
              <div className="grid gap-3 md:grid-cols-2">
                <div className="space-y-1">
                  <Label>Run A</Label>
                  <Select value={selectedRunA} onValueChange={(v) => setSelectedRunA(v)}>
                    <SelectTrigger>
                      <SelectValue placeholder="选择 run A" />
                    </SelectTrigger>
                    <SelectContent>
                      {runs.map((r) => (
                        <SelectItem key={r.id} value={r.id}>
                          {String(r.created_at || '').slice(0, 19)} · {String(r.id).slice(0, 8)}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <Button
                    variant="outline"
                    size="sm"
                    className="mt-2 w-full"
                    onClick={() => loadRun('a', selectedRunA)}
                    disabled={!selectedRunA}
                  >
                    加载 A
                  </Button>
                </div>
                <div className="space-y-1">
                  <Label>Run B</Label>
                  <Select value={selectedRunB} onValueChange={(v) => setSelectedRunB(v)}>
                    <SelectTrigger>
                      <SelectValue placeholder="选择 run B" />
                    </SelectTrigger>
                    <SelectContent>
                      {runs.map((r) => (
                        <SelectItem key={r.id} value={r.id}>
                          {String(r.created_at || '').slice(0, 19)} · {String(r.id).slice(0, 8)}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <Button
                    variant="outline"
                    size="sm"
                    className="mt-2 w-full"
                    onClick={() => loadRun('b', selectedRunB)}
                    disabled={!selectedRunB}
                  >
                    加载 B
                  </Button>
                </div>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="flex flex-row items-center justify-between gap-2">
              <CardTitle className="text-base">Compare</CardTitle>
              <Button
                variant="outline"
                size="sm"
                className="gap-2"
                onClick={() => {
                  const a = String(detailA?.run?.id || '').slice(0, 8) || 'A'
                  const b = String(detailB?.run?.id || '').slice(0, 8) || 'B'
                  downloadJson(diff ?? {}, `${sanitizeFilename(`kg_diagnostics_diff_${a}_vs_${b}`)}.json`)
                  toast.success('已导出 diff.json')
                }}
                disabled={!diff}
              >
                <Download className="h-4 w-4" aria-hidden="true" />
                导出 diff
              </Button>
            </CardHeader>
            <CardContent className="space-y-3">
              {diff ? (
                <div className="grid gap-2 md:grid-cols-2">
                  <div className="rounded-md border bg-muted/20 p-3">
                    <div className="text-xs text-muted-foreground">hit flips</div>
                    <div className="text-sm tabular-nums">
                      total={diff.hit_flips.total} improved={diff.hit_flips.improved} regressed={diff.hit_flips.regressed}
                    </div>
                  </div>
                  <div className="rounded-md border bg-muted/20 p-3">
                    <div className="text-xs text-muted-foreground">summary keys</div>
                    <div className="text-sm tabular-nums">{Object.keys(diff.summary_delta || {}).length}</div>
                  </div>
                </div>
              ) : (
                <div className="text-sm text-muted-foreground">选择并加载 run A/B 后自动生成 diff</div>
              )}

              <div className="rounded-md border bg-muted/10 p-3">
                <div className="text-xs text-muted-foreground mb-2 flex items-center gap-2">
                  <GitCompare className="h-4 w-4" aria-hidden="true" />
                  diff（json）
                </div>
                <Textarea value={diffJson} readOnly rows={14} className="font-mono text-xs" />
              </div>

              {diff?.changed_cases?.length ? (
                <div className="rounded-md border p-3">
                  <div className="text-xs text-muted-foreground mb-2">changed cases (top)</div>
                  <div className="grid gap-2">
                    {diff.changed_cases.map((r: any) => (
                      <div key={r.case_id} className="rounded-md border bg-background p-2">
                        <div className="text-xs text-muted-foreground tabular-nums">{String(r.case_id).slice(0, 8)}</div>
                        <div className="text-sm">{r.question || '(no question)'}</div>
                        <div className="text-xs text-muted-foreground tabular-nums mt-1">
                          hit: {String(r.a_hit)} → {String(r.b_hit)} | recall: {String(r.a_recall)} → {String(r.b_recall)} (Δ {String(r.delta_recall)})
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              ) : null}
            </CardContent>
          </Card>
        </div>
      </PageScaffold>
    </AppFrame>
  )
}
