'use client'

import { Activity, Download, GitCompare, PlayCircle, RefreshCcw } from 'lucide-react'
import { useMemo, useState, type ReactNode } from 'react'
import { useTranslations } from 'next-intl'
import { toast } from 'sonner'

import { AppFrame } from '@/components/app-frame'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Textarea } from '@/components/ui/textarea'
import { formatApiError } from '@/lib/api-errors'
import { evaluationApi, type KGHardcaseMode, type KGSearchDiagnosticsResponse, type KGSearchDiagnosticsRunDetail } from '@/lib/api'
import { coerceOneOf } from '@/lib/one-of'
import { sanitizeFilename } from '@/lib/sanitize'
import { cn } from '@/lib/utils'

const KG_EXTRACT_MODE_VALUES = ['auto', 'on', 'off'] as const

type DiagnosticsView = 'run' | 'quality' | 'compare'

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

function extractBaselineMetrics(item: any): { hit_at_k: boolean; mrr: number; recall: number; ndcg: number; map: number } | null {
  const baseline = item?.baseline
  const metrics = baseline?.metrics
  const hit = Boolean(metrics?.hit_at_k)
  const mrr = toNumber(metrics?.mrr)
  const recall = toNumber(metrics?.recall)
  const ndcg = toNumber(metrics?.ndcg)
  const meanAveragePrecision = toNumber(metrics?.map)
  if (mrr === null || recall === null) return null
  return { hit_at_k: hit, mrr, recall, ndcg: ndcg ?? 0, map: meanAveragePrecision ?? 0 }
}

function caseKey(item: any): string | null {
  const id = item?.case_id
  const s = String(id || '').trim()
  return s || null
}

function DiagnosticsInlineStat({
  label,
  value,
  tone = 'muted',
}: Readonly<{
  label: string
  value: ReactNode
  tone?: 'muted' | 'neutral' | 'positive' | 'negative'
}>) {
  return (
    <div className="flex items-center gap-2 rounded-full border border-border/70 bg-card/90 px-2.5 py-1">
      <span className="text-[11px] uppercase tracking-[0.12em] text-muted-foreground">{label}</span>
      <span
        className={cn(
          'font-mono text-[11px] tabular-nums',
          tone === 'positive'
            ? 'text-emerald-700'
            : tone === 'negative'
              ? 'text-rose-700'
              : tone === 'neutral'
                ? 'text-foreground'
                : 'text-muted-foreground'
        )}
      >
        {value}
      </span>
    </div>
  )
}

function DiagnosticsSection({
  label,
  description,
  children,
  className,
}: Readonly<{
  label: string
  description?: string
  children: ReactNode
  className?: string
}>) {
  return (
    <section className={cn('space-y-2.5 rounded-lg border border-border/70 bg-card px-3.5 py-3', className)}>
      <div className="space-y-1">
        <div className="text-[11px] font-medium uppercase tracking-[0.12em] text-muted-foreground">{label}</div>
        {description ? <p className="text-[11px] leading-5 text-muted-foreground">{description}</p> : null}
      </div>
      {children}
    </section>
  )
}

function DiagnosticsMetricTile({
  label,
  value,
  caption,
  tone = 'neutral',
  accent = 'neutral',
}: Readonly<{
  label: string
  value: ReactNode
  caption?: ReactNode
  tone?: 'neutral' | 'positive' | 'negative' | 'muted'
  accent?: 'neutral' | 'sky' | 'violet' | 'emerald' | 'amber'
}>) {
  const accentClasses =
    accent === 'sky'
      ? {
          surface: 'border-sky-200/80 bg-sky-50/80',
          label: 'text-sky-700',
          dot: 'bg-sky-400',
          value: 'text-sky-900',
          caption: 'text-sky-800/80',
        }
      : accent === 'violet'
        ? {
            surface: 'border-violet-200/80 bg-violet-50/80',
            label: 'text-violet-700',
            dot: 'bg-violet-400',
            value: 'text-violet-900',
            caption: 'text-violet-800/80',
          }
        : accent === 'emerald'
          ? {
              surface: 'border-emerald-200/80 bg-emerald-50/75',
              label: 'text-emerald-700',
              dot: 'bg-emerald-400',
              value: 'text-emerald-900',
              caption: 'text-emerald-800/80',
            }
          : accent === 'amber'
            ? {
                surface: 'border-amber-200/80 bg-amber-50/75',
                label: 'text-amber-700',
                dot: 'bg-amber-400',
                value: 'text-amber-900',
                caption: 'text-amber-800/80',
              }
            : {
                surface: 'border-border/70 bg-background',
                label: 'text-muted-foreground',
                dot: 'bg-muted-foreground/40',
                value: 'text-foreground',
                caption: 'text-muted-foreground',
              }

  const valueClass =
    tone === 'positive'
      ? 'text-emerald-700'
      : tone === 'negative'
        ? 'text-rose-700'
        : tone === 'muted'
          ? 'text-muted-foreground'
          : accentClasses.value

  return (
    <div className={cn('rounded-lg border px-4 py-3 shadow-[inset_0_1px_0_rgba(255,255,255,0.85)]', accentClasses.surface)}>
      <div className={cn('flex items-center gap-1.5 text-[11px] uppercase tracking-[0.08em]', accentClasses.label)}>
        <span className={cn('h-1.5 w-1.5 rounded-full', accentClasses.dot)} aria-hidden="true" />
        <span>{label}</span>
      </div>
      <div className={cn('mt-2 text-lg font-semibold tracking-[-0.02em] tabular-nums', valueClass)}>{value}</div>
      {caption ? <div className={cn('mt-1 text-[11px] leading-5', accentClasses.caption)}>{caption}</div> : null}
    </div>
  )
}

function DiagnosticsToggleCard({
  title,
  description,
  badge,
  checked,
  onCheckedChange,
  tone,
  stateLabel,
}: Readonly<{
  title: string
  description?: string
  badge: string
  checked: boolean
  onCheckedChange: (checked: boolean) => void
  tone: 'sky' | 'emerald'
  stateLabel: string
}>) {
  const toneClasses =
    tone === 'sky'
      ? {
          surface: 'border-border/70 bg-background',
          box: 'border-sky-200/80 bg-card text-sky-600',
          badge: 'text-sky-700',
          dot: 'bg-sky-400',
        }
      : {
          surface: 'border-border/70 bg-background',
          box: 'border-emerald-200/80 bg-card text-emerald-600',
          badge: 'text-emerald-700',
          dot: 'bg-emerald-400',
        }

  return (
    <label className={cn('block cursor-pointer select-none rounded-lg border px-3 py-2.5 transition-colors', toneClasses.surface)}>
      <div className="flex items-start gap-3">
        <div className={cn('mt-0.5 flex h-7 w-7 items-center justify-center rounded-lg border shadow-sm', toneClasses.box)}>
          <Checkbox checked={checked} onCheckedChange={(value) => onCheckedChange(Boolean(value))} />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-start justify-between gap-2">
            <div className="min-w-0">
              <div className={cn('flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-[0.12em]', toneClasses.badge)}>
                <span className={cn('h-1.5 w-1.5 rounded-full', toneClasses.dot)} />
                <span>{badge}</span>
              </div>
              <div className="mt-1 text-[13px] font-semibold leading-4 text-foreground">{title}</div>
            </div>
            <span className="inline-flex shrink-0 items-center rounded-full border border-border/70 bg-card/90 px-2 py-0.5 text-[11px] font-medium text-muted-foreground">
              {stateLabel}
            </span>
          </div>
          {description ? <p className="mt-1.5 text-[11px] leading-5 text-muted-foreground">{description}</p> : null}
        </div>
      </div>
    </label>
  )
}

function DiagnosticsEmptyState({
  title,
  description,
}: Readonly<{
  title: string
  description: string
}>) {
  return (
    <div className="rounded-lg border border-dashed border-border/70 bg-background px-5 py-12 text-center">
      <div className="text-sm font-medium text-foreground">{title}</div>
      <p className="mx-auto mt-2 max-w-xl text-[12px] leading-6 text-muted-foreground">{description}</p>
    </div>
  )
}

function DiagnosticsJsonPanel({
  label,
  value,
  rows = 14,
}: Readonly<{
  label: string
  value: string
  rows?: number
}>) {
  return (
    <div className="rounded-lg border border-border/70 bg-card">
      <div className="border-b border-border/70 px-4 py-3">
        <div className="text-[11px] font-medium uppercase tracking-[0.12em] text-muted-foreground">{label}</div>
      </div>
      <details className="px-4 py-3">
        <summary className="cursor-pointer select-none text-xs font-medium text-muted-foreground transition-colors hover:text-foreground">
          展开 JSON
        </summary>
        <Textarea value={value} readOnly rows={rows} className="mt-3 resize-none border-border/70 bg-background font-mono text-xs" />
      </details>
    </div>
  )
}

export function KGDiagnosticsPage() {
  const t = useTranslations('KGDiagnosticsPage')
  const [datasetId, setDatasetId] = useState('')
  const [activeView, setActiveView] = useState<DiagnosticsView>('run')

  const [qualityDocLimit, setQualityDocLimit] = useState(200)
  const [qualityPipelineHash, setQualityPipelineHash] = useState('')
  const [qualityLoading, setQualityLoading] = useState(false)
  const [qualityReport, setQualityReport] = useState<any | null>(null)
  const qualityJson = useMemo(
    () => prettyJson(qualityReport ?? { hint: t('qualityReport.hint') }),
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
  const runRespJson = useMemo(() => prettyJson(runResp ?? { hint: t('summary.runHint') }), [runResp, t])

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

    const aSummary = a.run?.summary && typeof a.run.summary === 'object' ? a.run.summary : {}
    const bSummary = b.run?.summary && typeof b.run.summary === 'object' ? b.run.summary : {}

    const keys = [
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

  const diffJson = useMemo(() => prettyJson(diff ?? { hint: t('compare.diffHint') }), [diff, t])

  async function refreshRuns(): Promise<void> {
    const ds = datasetId.trim()
    if (!ds) {
      toast.error(t('toasts.datasetRequired'))
      return
    }
    setRunsLoading(true)
    try {
      const res = await evaluationApi.listKgSearchDiagnosticsRuns({ dataset_id: ds, limit: 50 })
      const items = Array.isArray(res.items) ? res.items : []
      setRuns(items)
      if (!selectedRunA && items?.[0]?.id) setSelectedRunA(items[0].id)
      if (!selectedRunB && items?.[1]?.id) setSelectedRunB(items[1].id)
      if (!selectedRunB && !items?.[1]?.id && items?.[0]?.id) setSelectedRunB(items[0].id)
    } catch (err) {
      toast.error(formatApiError(err, t('toasts.runsLoadFailed')))
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
      toast.error(formatApiError(err, t('toasts.runLoadFailed', { id: id.slice(0, 8) })))
    }
  }

  async function loadQualityReport(): Promise<void> {
    const ds = datasetId.trim()
    if (!ds) {
      toast.error(t('toasts.datasetRequired'))
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
      setActiveView('quality')
      toast.success(t('toasts.qualityReportLoaded'))
    } catch (err) {
      toast.error(formatApiError(err, t('toasts.qualityReportLoadFailed')))
    } finally {
      setQualityLoading(false)
    }
  }

  async function runDiagnostics(): Promise<void> {
    const ds = datasetId.trim()
    if (!ds) {
      toast.error(t('toasts.datasetRequired'))
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
      setActiveView('run')
      toast.success(t('toasts.diagnosticsRan'))
      if (persistRun) {
        await refreshRuns()
      }
    } catch (err) {
      toast.error(formatApiError(err, t('toasts.diagnosticsRunFailed')))
    } finally {
      setRunning(false)
    }
  }

  const summary = runResp?.summary && typeof runResp.summary === 'object' ? runResp.summary : null
  const runItems = useMemo(() => (Array.isArray(runResp?.items) ? runResp.items : []), [runResp?.items])
  const runIdShort = String(runResp?.run_id || '').slice(0, 8)
  const datasetLabel = datasetId.trim() || '未选择'
  const qualityObject = qualityReport && typeof qualityReport === 'object' ? (qualityReport as Record<string, unknown>) : null
  const qualityHighlights = useMemo(() => {
    if (!qualityObject) return []
    return Object.entries(qualityObject)
      .filter(([, value]) => ['string', 'number', 'boolean'].includes(typeof value))
      .slice(0, 8)
  }, [qualityObject])
  const failedCases = useMemo(() => {
    return runItems
      .map((item) => {
        const metrics = extractBaselineMetrics(item)
        if (!metrics || metrics.hit_at_k) return null
        return {
          case_id: String(item?.case_id || '').slice(0, 8),
          question: String(item?.question || '').trim(),
          recall: metrics.recall,
          mrr: metrics.mrr,
        }
      })
      .filter(Boolean)
      .slice(0, 12) as Array<{ case_id: string; question: string; recall: number; mrr: number }>
  }, [runItems])
  const diffSummaryEntries = useMemo(() => Object.entries(diff?.summary_delta || {}), [diff])

  const viewDescription =
    activeView === 'run'
      ? t('workspace.runIntro')
      : activeView === 'quality'
        ? t('workspace.qualityIntro')
        : t('workspace.compareIntro')

  return (
    <AppFrame showBackground={false}>
      <div className="flex h-full min-h-0 flex-col bg-background">
        <header className="shrink-0 border-b border-border/70 bg-background backdrop-blur">
          <div className="flex min-h-[72px] items-center justify-between gap-4 px-4 py-3 md:px-6">
            <div className="min-w-0">
              <div className="flex items-center gap-3">
                <div className="flex h-10 w-10 items-center justify-center rounded-lg border border-border/70 bg-card text-sky-600 shadow-sm">
                  <Activity className="h-4 w-4" aria-hidden="true" />
                </div>
                <div className="min-w-0">
                  <div className="text-[11px] font-medium uppercase tracking-[0.14em] text-muted-foreground">Graph Evaluation</div>
                  <h1 className="truncate text-base font-semibold tracking-[-0.02em] text-foreground">{t('page.title')}</h1>
                  <p className="truncate text-[12px] text-muted-foreground">{t('page.description')}</p>
                </div>
              </div>
            </div>

            <div className="hidden shrink-0 flex-wrap items-center gap-2 xl:flex">
              <DiagnosticsInlineStat label={t('runConfig.datasetId')} value={datasetLabel} tone="neutral" />
              <DiagnosticsInlineStat label={t('runConfig.k')} value={k} />
              <DiagnosticsInlineStat label={t('runs.title')} value={runs.length} />
              {runIdShort ? <DiagnosticsInlineStat label="Run" value={runIdShort} tone="neutral" /> : null}
            </div>
          </div>
        </header>

        <div className="flex min-h-0 flex-1">
          <aside className="w-[304px] shrink-0 border-r border-border/70 bg-background">
            <div className="flex h-full min-h-0 flex-col">
              <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4">
                <div className="space-y-4">
                  <DiagnosticsSection
                    label={t('runConfig.title')}
                    description={t('workspace.sidebarIntro')}
                    className="bg-background"
                  >
                    <div className="space-y-1.5">
                      <Label htmlFor="dataset-id" className="text-[11px] uppercase tracking-[0.12em] text-muted-foreground">
                        {t('runConfig.datasetId')}
                      </Label>
                      <Input
                        id="dataset-id"
                        value={datasetId}
                        onChange={(e) => setDatasetId(e.target.value)}
                        placeholder={t('runConfig.datasetPlaceholder')}
                        className="h-9 rounded-lg border-border/70 bg-card/95 font-mono text-xs shadow-none"
                      />
                    </div>
                  </DiagnosticsSection>

                  <DiagnosticsSection
                    label={t('workspace.coreParams')}
                    description={t('workspace.coreParamsHint')}
                    className="bg-background"
                  >
                    <div className="grid gap-3 md:grid-cols-2">
                      <div className="space-y-1">
                        <Label className="min-h-[30px] text-[11px] uppercase tracking-[0.12em] text-muted-foreground">{t('runConfig.maxCases')}</Label>
                        <Input
                          type="number"
                          value={String(maxCases)}
                          onChange={(e) => setMaxCases(Number(e.target.value || 0))}
                          min={1}
                          max={200}
                          className="h-9 rounded-lg border-border/70 bg-card/95 text-sm shadow-none"
                        />
                      </div>
                      <div className="space-y-1">
                        <Label className="min-h-[30px] text-[11px] uppercase tracking-[0.12em] text-muted-foreground">{t('runConfig.k')}</Label>
                        <Input
                          type="number"
                          value={String(k)}
                          onChange={(e) => setK(Number(e.target.value || 0))}
                          min={1}
                          max={50}
                          className="h-9 rounded-lg border-border/70 bg-card/95 text-sm shadow-none"
                        />
                      </div>
                      <div className="space-y-1 md:col-span-2">
                        <Label className="min-h-[18px] text-[11px] uppercase tracking-[0.12em] text-muted-foreground">{t('runConfig.hardcaseMode')}</Label>
                        <Select value={hardcaseMode} onValueChange={(v) => setHardcaseMode(v as KGHardcaseMode)}>
                          <SelectTrigger className="h-9 rounded-lg border-border/70 bg-card/95 text-sm shadow-none">
                            <SelectValue placeholder={t('runConfig.hardcaseModePlaceholder')} />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="off">关闭</SelectItem>
                            <SelectItem value="deterministic">规则生成</SelectItem>
                            <SelectItem value="llm">LLM 生成</SelectItem>
                          </SelectContent>
                        </Select>
                      </div>
                      <div className="space-y-1">
                        <Label className="flex min-h-[42px] items-end text-[11px] uppercase tracking-[0.12em] text-muted-foreground">
                          {t('runConfig.hardcasesPerFailedCase')}
                        </Label>
                        <Input
                          type="number"
                          value={String(hardcasesPerFailed)}
                          onChange={(e) => setHardcasesPerFailed(Number(e.target.value || 0))}
                          min={0}
                          max={20}
                          className="h-9 rounded-lg border-border/70 bg-card/95 text-sm shadow-none"
                        />
                      </div>
                      <div className="space-y-1">
                        <Label className="flex min-h-[42px] items-end text-[11px] uppercase tracking-[0.12em] text-muted-foreground">
                          {t('runConfig.maxFailedCasesForHardcase')}
                        </Label>
                        <Input
                          type="number"
                          value={String(maxFailedForHardcase)}
                          onChange={(e) => setMaxFailedForHardcase(Number(e.target.value || 0))}
                          min={0}
                          max={200}
                          className="h-9 rounded-lg border-border/70 bg-card/95 text-sm shadow-none"
                        />
                      </div>
                      <div className="space-y-1 md:col-span-2">
                        <Label className="min-h-[18px] text-[11px] uppercase tracking-[0.12em] text-muted-foreground">{t('runConfig.llmTemperature')}</Label>
                        <Input
                          type="number"
                          value={String(llmTemperature)}
                          onChange={(e) => setLlmTemperature(Number(e.target.value || 0))}
                          min={0}
                          max={2}
                          step={0.1}
                          className="h-9 rounded-lg border-border/70 bg-card/95 text-sm shadow-none"
                        />
                      </div>
                    </div>
                  </DiagnosticsSection>

                  <DiagnosticsSection
                    label={t('workspace.extractionOptions')}
                    description={t('workspace.extractionHint')}
                    className="bg-background"
                  >
                    <div className="space-y-2.5">
                      <div className="space-y-1">
                        <Label className="min-h-[18px] text-[11px] uppercase tracking-[0.12em] text-muted-foreground">{t('runConfig.extractSkills')}</Label>
                        <Select
                          value={extractSkills}
                          onValueChange={(value) => setExtractSkills(coerceOneOf(KG_EXTRACT_MODE_VALUES, value, 'auto'))}
                        >
                          <SelectTrigger className="h-9 rounded-lg border-border/70 bg-card/95 text-sm shadow-none">
                            <SelectValue placeholder={t('runConfig.extractModePlaceholder')} />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="auto">自动</SelectItem>
                            <SelectItem value="on">开启</SelectItem>
                            <SelectItem value="off">关闭</SelectItem>
                          </SelectContent>
                        </Select>
                      </div>

                      <div className="space-y-1">
                        <Label className="min-h-[18px] text-[11px] uppercase tracking-[0.12em] text-muted-foreground">{t('runConfig.extractRelations')}</Label>
                        <Select
                          value={extractRelations}
                          onValueChange={(value) => setExtractRelations(coerceOneOf(KG_EXTRACT_MODE_VALUES, value, 'auto'))}
                        >
                          <SelectTrigger className="h-9 rounded-lg border-border/70 bg-card/95 text-sm shadow-none">
                            <SelectValue placeholder={t('runConfig.extractModePlaceholder')} />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="auto">自动</SelectItem>
                            <SelectItem value="on">开启</SelectItem>
                            <SelectItem value="off">关闭</SelectItem>
                          </SelectContent>
                        </Select>
                      </div>

                      <DiagnosticsToggleCard
                        title={t('runConfig.autoExtractKg')}
                        description={t('workspace.autoExtractHint')}
                        badge={t('workspace.autoExtractBadge')}
                        checked={autoExtractKg}
                        onCheckedChange={setAutoExtractKg}
                        tone="sky"
                        stateLabel={autoExtractKg ? t('workspace.enabled') : t('workspace.disabled')}
                      />

                      <DiagnosticsToggleCard
                        title={t('runConfig.persistRun')}
                        description={t('runs.hint')}
                        badge={t('workspace.persistRunBadge')}
                        checked={persistRun}
                        onCheckedChange={setPersistRun}
                        tone="emerald"
                        stateLabel={persistRun ? t('workspace.enabled') : t('workspace.disabled')}
                      />
                    </div>
                  </DiagnosticsSection>
                </div>
              </div>

              <div className="shrink-0 border-t border-border/70 bg-background px-4 py-3 backdrop-blur">
                <div className="flex flex-wrap items-center gap-2">
                  <DiagnosticsInlineStat label="Cases" value={maxCases} />
                  <DiagnosticsInlineStat label="Top-K" value={k} />
                  <DiagnosticsInlineStat label="Persist" value={persistRun ? 'ON' : 'OFF'} tone={persistRun ? 'neutral' : 'muted'} />
                </div>

                <Button
                  className="mt-2.5 h-10 w-full rounded-lg text-sm shadow-none"
                  onClick={runDiagnostics}
                  disabled={running}
                >
                  <PlayCircle className="mr-2 h-4 w-4" aria-hidden="true" />
                  {running ? `${t('page.actions.run')}…` : t('page.actions.run')}
                </Button>

                <div className="mt-2 grid grid-cols-2 gap-2">
                  <Button
                    variant="outline"
                    className="h-9 rounded-lg border-border/70 bg-card/95 text-xs"
                    onClick={refreshRuns}
                    disabled={runsLoading}
                  >
                    <RefreshCcw className="mr-1.5 h-4 w-4" aria-hidden="true" />
                    {t('page.actions.refreshRuns')}
                  </Button>
                  <Button
                    variant="outline"
                    className="h-9 rounded-lg border-border/70 bg-card/95 text-xs"
                    onClick={() => {
                      const base = sanitizeFilename(`kg_diagnostics_${datasetId.trim() || 'dataset'}`)
                      downloadJson(runResp ?? {}, `${base}.json`)
                      toast.success(t('toasts.runExported'))
                    }}
                    disabled={!runResp}
                  >
                    <Download className="mr-1.5 h-4 w-4" aria-hidden="true" />
                    {t('page.actions.exportRun')}
                  </Button>
                </div>

                <p className="mt-3 text-[11px] leading-5 text-muted-foreground">{t('summary.runHint')}</p>
              </div>
            </div>
          </aside>

          <section className="min-w-0 flex-1 bg-card">
            <Tabs value={activeView} onValueChange={(value) => setActiveView(value as DiagnosticsView)} className="flex h-full min-h-0 flex-col">
              <div className="shrink-0 border-b border-border/70 bg-card">
                <div className="flex flex-col gap-3 px-4 py-3">
                  <div className="flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
                    <div>
                      <div className="text-[11px] font-medium uppercase tracking-[0.14em] text-muted-foreground">Evaluation Workspace</div>
                      <div className="mt-0.5 text-sm font-semibold text-foreground">
                        {activeView === 'run' ? t('summary.title') : activeView === 'quality' ? t('qualityReport.title') : t('compare.title')}
                      </div>
                      <p className="mt-1 text-[11px] leading-5 text-muted-foreground">{viewDescription}</p>
                    </div>

                    <TabsList className="h-10 justify-start gap-1 rounded-none border-none p-0">
                      <TabsTrigger value="run" className="rounded-lg border-b-0 px-3 data-[state=active]:bg-muted/60 data-[state=active]:border-transparent">
                        {t('summary.title')}
                      </TabsTrigger>
                      <TabsTrigger value="quality" className="rounded-lg border-b-0 px-3 data-[state=active]:bg-muted/60 data-[state=active]:border-transparent">
                        {t('qualityReport.title')}
                      </TabsTrigger>
                      <TabsTrigger value="compare" className="rounded-lg border-b-0 px-3 data-[state=active]:bg-muted/60 data-[state=active]:border-transparent">
                        {t('compare.title')}
                      </TabsTrigger>
                    </TabsList>
                  </div>

                  <div className="flex flex-wrap items-center gap-2">
                    <DiagnosticsInlineStat label={t('runConfig.datasetId')} value={datasetLabel} tone="neutral" />
                    <DiagnosticsInlineStat label={t('runConfig.maxCases')} value={maxCases} />
                    <DiagnosticsInlineStat label={t('runConfig.k')} value={k} />
                    {runIdShort ? <DiagnosticsInlineStat label="Run" value={runIdShort} tone="neutral" /> : null}
                  </div>
                </div>
              </div>

              <TabsContent value="run" className="mt-0 min-h-0 flex-1">
                <div className="flex h-full min-h-0 flex-col">
                  <div className="border-b border-border/70 px-4 py-4">
                    <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-6">
                      <DiagnosticsMetricTile
                        label={t('summary.baselineHitRate')}
                        value={formatMetricValue(summary?.baseline_hit_rate)}
                        caption="整体是否命中的基础指标"
                        accent="sky"
                      />
                      <DiagnosticsMetricTile
                        label={t('summary.baselineMrr')}
                        value={formatMetricValue(summary?.baseline_mrr)}
                        caption="命中位置越靠前越高"
                        accent="violet"
                      />
                      <DiagnosticsMetricTile
                        label={t('summary.baselineRecall')}
                        value={formatMetricValue(summary?.baseline_recall)}
                        caption="看召回覆盖是否足够"
                        accent="emerald"
                      />
                      <DiagnosticsMetricTile
                        label={t('summary.baselineNdcg')}
                        value={formatMetricValue(summary?.baseline_ndcg)}
                        caption="兼顾命中位置与整体排序质量"
                        accent="sky"
                      />
                      <DiagnosticsMetricTile
                        label={t('summary.baselineMap')}
                        value={formatMetricValue(summary?.baseline_map)}
                        caption="多证据平均精度"
                        accent="violet"
                      />
                      <DiagnosticsMetricTile
                        label={t('summary.hardcasesGenerated')}
                        value={formatMetricValue(summary?.hardcases_generated)}
                        caption="这轮额外生成的难例数量"
                        accent="amber"
                      />
                    </div>
                  </div>

                  <div className="min-h-0 flex-1 overflow-auto px-4 py-4">
                    {summary ? (
                      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.2fr)_420px]">
                        <div className="space-y-4">
                          <div className="rounded-lg border border-border/70 bg-card">
                            <div className="border-b border-border/70 px-4 py-3">
                              <div className="text-[11px] font-medium uppercase tracking-[0.12em] text-muted-foreground">{t('workspace.runStateTitle')}</div>
                            </div>
                            <div className="grid gap-3 px-4 py-4 md:grid-cols-3">
                              <DiagnosticsMetricTile
                                label="Run ID"
                                value={runIdShort || '-'}
                                caption={persistRun ? t('workspace.runPersisted') : t('workspace.runTransient')}
                                tone="neutral"
                              />
                              <DiagnosticsMetricTile
                                label={t('workspace.itemsLabel')}
                                value={runItems.length}
                                caption={t('workspace.itemsHint')}
                              />
                              <DiagnosticsMetricTile
                                label={t('workspace.failuresLabel')}
                                value={failedCases.length}
                                caption={t('workspace.failuresHint')}
                                tone={failedCases.length > 0 ? 'negative' : 'positive'}
                              />
                            </div>
                          </div>

                          <div className="rounded-lg border border-border/70 bg-card">
                            <div className="border-b border-border/70 px-4 py-3">
                              <div className="text-[11px] font-medium uppercase tracking-[0.12em] text-muted-foreground">{t('workspace.failuresPanelTitle')}</div>
                            </div>
                            <div className="px-4 py-4">
                              {failedCases.length ? (
                                <div className="grid gap-2">
                                  {failedCases.map((item) => (
                                    <div key={`${item.case_id}:${item.question}`} className="rounded-lg border border-border/70 bg-background px-3 py-3">
                                      <div className="text-[11px] font-mono text-muted-foreground">{item.case_id || '--------'}</div>
                                      <div className="mt-1 text-sm text-foreground">{item.question || t('compare.noQuestion')}</div>
                                      <div className="mt-2 text-[11px] tabular-nums text-muted-foreground">
                                        recall {String(item.recall)} · mrr {String(item.mrr)}
                                      </div>
                                    </div>
                                  ))}
                                </div>
                              ) : (
                                <DiagnosticsEmptyState title={t('workspace.failuresEmptyTitle')} description={t('workspace.failuresEmptyDescription')} />
                              )}
                            </div>
                          </div>
                        </div>

                        <DiagnosticsJsonPanel label={t('workspace.rawRunJson')} value={runRespJson} rows={18} />
                      </div>
                    ) : (
                      <DiagnosticsEmptyState title={t('summary.empty')} description={t('summary.runHint')} />
                    )}
                  </div>
                </div>
              </TabsContent>

              <TabsContent value="quality" className="mt-0 min-h-0 flex-1">
                <div className="flex h-full min-h-0 flex-col">
                  <div className="border-b border-border/70 px-4 py-4">
                    <div className="grid gap-3 xl:grid-cols-[180px_minmax(0,1fr)_auto]">
                      <div className="space-y-1.5">
                        <Label className="text-[11px] uppercase tracking-[0.12em] text-muted-foreground">{t('qualityReport.documentLimit')}</Label>
                        <Input
                          type="number"
                          value={String(qualityDocLimit)}
                          onChange={(e) => setQualityDocLimit(Number(e.target.value || 0))}
                          min={1}
                          max={2000}
                          className="h-10 rounded-lg border-border/70 bg-card text-sm shadow-none"
                        />
                      </div>
                      <div className="space-y-1.5">
                        <Label className="text-[11px] uppercase tracking-[0.12em] text-muted-foreground">{t('qualityReport.pipelineHash')}</Label>
                        <Input
                          value={qualityPipelineHash}
                          onChange={(e) => setQualityPipelineHash(e.target.value)}
                          placeholder={t('qualityReport.pipelineHashPlaceholder')}
                          className="h-10 rounded-lg border-border/70 bg-card font-mono text-xs shadow-none"
                        />
                      </div>
                      <div className="flex items-end">
                        <Button
                          variant="outline"
                          className="h-10 rounded-lg border-border/70 bg-card text-xs"
                          onClick={loadQualityReport}
                          disabled={qualityLoading}
                        >
                          <RefreshCcw className="mr-1.5 h-4 w-4" aria-hidden="true" />
                          {t('qualityReport.pull')}
                        </Button>
                      </div>
                    </div>
                    <p className="mt-3 text-[11px] leading-5 text-muted-foreground">{t('qualityReport.hint')}</p>
                  </div>

                  <div className="min-h-0 flex-1 overflow-auto px-4 py-4">
                    <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_420px]">
                      <div className="space-y-4">
                        {qualityObject ? (
                          <div className="rounded-lg border border-border/70 bg-card">
                            <div className="border-b border-border/70 px-4 py-3">
                              <div className="text-[11px] font-medium uppercase tracking-[0.12em] text-muted-foreground">{t('workspace.qualityHighlightsTitle')}</div>
                            </div>
                            <div className="grid gap-3 px-4 py-4 md:grid-cols-2">
                              <DiagnosticsMetricTile
                                label={t('workspace.qualityKeyCount')}
                                value={Object.keys(qualityObject).length}
                                caption={t('workspace.qualityKeyCountHint')}
                              />
                              <DiagnosticsMetricTile
                                label={t('qualityReport.documentLimit')}
                                value={qualityDocLimit}
                                caption={qualityPipelineHash.trim() || t('workspace.currentPipelineLabel')}
                              />
                              {qualityHighlights.map(([key, value]) => (
                                <DiagnosticsMetricTile key={key} label={key} value={formatMetricValue(value)} tone="neutral" />
                              ))}
                            </div>
                          </div>
                        ) : (
                          <DiagnosticsEmptyState title={t('workspace.qualityEmptyTitle')} description={t('qualityReport.hint')} />
                        )}
                      </div>

                      <DiagnosticsJsonPanel label={t('workspace.rawQualityJson')} value={qualityJson} rows={18} />
                    </div>
                  </div>
                </div>
              </TabsContent>

              <TabsContent value="compare" className="mt-0 min-h-0 flex-1">
                <div className="flex h-full min-h-0 flex-col">
                  <div className="border-b border-border/70 px-4 py-4">
                    <div className="grid gap-3 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto_auto]">
                      <div className="space-y-1.5">
                        <Label className="text-[11px] uppercase tracking-[0.12em] text-muted-foreground">{t('runs.runA')}</Label>
                        <div className="flex gap-2">
                          <Select value={selectedRunA} onValueChange={(v) => setSelectedRunA(v)}>
                            <SelectTrigger className="h-10 rounded-lg border-border/70 bg-card text-sm shadow-none">
                              <SelectValue placeholder={t('runs.runAPlaceholder')} />
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
                            className="h-10 rounded-lg border-border/70 bg-card text-xs"
                            onClick={() => loadRun('a', selectedRunA)}
                            disabled={!selectedRunA}
                          >
                            {t('runs.loadA')}
                          </Button>
                        </div>
                      </div>

                      <div className="space-y-1.5">
                        <Label className="text-[11px] uppercase tracking-[0.12em] text-muted-foreground">{t('runs.runB')}</Label>
                        <div className="flex gap-2">
                          <Select value={selectedRunB} onValueChange={(v) => setSelectedRunB(v)}>
                            <SelectTrigger className="h-10 rounded-lg border-border/70 bg-card text-sm shadow-none">
                              <SelectValue placeholder={t('runs.runBPlaceholder')} />
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
                            className="h-10 rounded-lg border-border/70 bg-card text-xs"
                            onClick={() => loadRun('b', selectedRunB)}
                            disabled={!selectedRunB}
                          >
                            {t('runs.loadB')}
                          </Button>
                        </div>
                      </div>

                      <div className="flex items-end">
                        <Button
                          variant="outline"
                          className="h-10 rounded-lg border-border/70 bg-card text-xs"
                          onClick={refreshRuns}
                          disabled={runsLoading}
                        >
                          <RefreshCcw className="mr-1.5 h-4 w-4" aria-hidden="true" />
                          {t('runs.refresh')}
                        </Button>
                      </div>

                      <div className="flex items-end">
                        <Button
                          variant="outline"
                          className="h-10 rounded-lg border-border/70 bg-card text-xs"
                          onClick={() => {
                            const a = String(detailA?.run?.id || '').slice(0, 8) || 'A'
                            const b = String(detailB?.run?.id || '').slice(0, 8) || 'B'
                            downloadJson(diff ?? {}, `${sanitizeFilename(`kg_diagnostics_diff_${a}_vs_${b}`)}.json`)
                            toast.success(t('compare.exported'))
                          }}
                          disabled={!diff}
                        >
                          <Download className="mr-1.5 h-4 w-4" aria-hidden="true" />
                          {t('compare.export')}
                        </Button>
                      </div>
                    </div>

                    <p className="mt-3 text-[11px] leading-5 text-muted-foreground">{t('runs.hint')}</p>
                  </div>

                  <div className="min-h-0 flex-1 overflow-auto px-4 py-4">
                    {diff ? (
                      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.15fr)_420px]">
                        <div className="space-y-4">
                          <div className="grid gap-3 md:grid-cols-4">
                            <DiagnosticsMetricTile label={t('compare.hitFlips')} value={diff.hit_flips.total} />
                            <DiagnosticsMetricTile label={t('workspace.compareImproved')} value={diff.hit_flips.improved} tone="positive" />
                            <DiagnosticsMetricTile label={t('workspace.compareRegressed')} value={diff.hit_flips.regressed} tone="negative" />
                            <DiagnosticsMetricTile label={t('compare.summaryKeys')} value={diffSummaryEntries.length} />
                          </div>

                          <div className="rounded-lg border border-border/70 bg-card">
                            <div className="border-b border-border/70 px-4 py-3">
                              <div className="text-[11px] font-medium uppercase tracking-[0.12em] text-muted-foreground">{t('compare.changedCases')}</div>
                            </div>
                            <div className="px-4 py-4">
                              {diff.changed_cases?.length ? (
                                <div className="grid gap-2">
                                  {diff.changed_cases.map((r: any) => (
                                    <div key={r.case_id} className="rounded-lg border border-border/70 bg-background px-3 py-3">
                                      <div className="text-[11px] font-mono text-muted-foreground">{String(r.case_id).slice(0, 8)}</div>
                                      <div className="mt-1 text-sm text-foreground">{r.question || t('compare.noQuestion')}</div>
                                      <div className="mt-2 text-[11px] leading-5 tabular-nums text-muted-foreground">
                                        hit {String(r.a_hit)} → {String(r.b_hit)} · recall {String(r.a_recall)} → {String(r.b_recall)} · Δ{' '}
                                        {String(r.delta_recall)}
                                      </div>
                                    </div>
                                  ))}
                                </div>
                              ) : (
                                <DiagnosticsEmptyState title={t('workspace.compareCasesEmptyTitle')} description={t('compare.diffHint')} />
                              )}
                            </div>
                          </div>
                        </div>

                        <div className="space-y-4">
                          <div className="rounded-lg border border-border/70 bg-card">
                            <div className="border-b border-border/70 px-4 py-3">
                              <div className="text-[11px] font-medium uppercase tracking-[0.12em] text-muted-foreground">{t('workspace.compareSummaryTitle')}</div>
                            </div>
                            <div className="px-4 py-4">
                              {diffSummaryEntries.length ? (
                                <div className="grid gap-2">
                                  {diffSummaryEntries.map(([key, value]) => {
                                    const row = value as { a?: number | null; b?: number | null; delta?: number | null }
                                    const delta = Number(row.delta ?? 0)
                                    return (
                                      <div key={key} className="rounded-lg border border-border/70 bg-background px-3 py-3">
                                        <div className="text-[11px] uppercase tracking-[0.08em] text-muted-foreground">{key}</div>
                                        <div className="mt-1 text-sm font-medium tabular-nums text-foreground">
                                          {String(row.a ?? '-')} → {String(row.b ?? '-')}
                                        </div>
                                        <div
                                          className={cn(
                                            'mt-1 text-[11px] tabular-nums',
                                            delta > 0 ? 'text-emerald-700' : delta < 0 ? 'text-rose-700' : 'text-muted-foreground'
                                          )}
                                        >
                                          Δ {String(row.delta ?? '-')}
                                        </div>
                                      </div>
                                    )
                                  })}
                                </div>
                              ) : (
                                <DiagnosticsEmptyState title={t('workspace.compareSummaryEmptyTitle')} description={t('compare.diffHint')} />
                              )}
                            </div>
                          </div>

                          <DiagnosticsJsonPanel label={t('compare.diffJson')} value={diffJson} rows={18} />
                        </div>
                      </div>
                    ) : (
                      <DiagnosticsEmptyState title={t('workspace.compareEmptyTitle')} description={t('compare.empty')} />
                    )}
                  </div>
                </div>
              </TabsContent>
            </Tabs>
          </section>
        </div>
      </div>
    </AppFrame>
  )
}
