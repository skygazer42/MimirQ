/**
 * 回归测试 Tab
 * 
 * 功能：
 * - 测试用例管理
 * - AI 生成问题
 * - 批量运行回归测试
 */

'use client'

import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import { datasetApi, evaluationApi } from '@/lib/api'
import type { Dataset, RegressionRun, RegressionRunCreate, RegressionRunDetail } from '@/types'
import { Button } from '@/components/ui/button'
import { TestCaseManager } from '@/components/test-case-manager'
import { TestGenerationDialog } from '@/components/test-generation-dialog'
import { Sparkles, Loader2, BarChart3, CheckCircle2, XCircle, Clock3, ChevronRight } from 'lucide-react'
import { toast } from 'sonner'
import { cn, detachPromise } from '@/lib/utils'
import { StatCard, StatsGrid } from '@/components/ui/stats-card'
import { formatApiError } from '@/lib/api-errors'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { RagasMetricSelector, RAGAS_METRIC_OPTIONS, ragasMetricLabel } from '@/components/evaluation/ragas-metric-selector'

function RegressionInlineStat({
  label,
  value,
  tone = 'neutral',
}: Readonly<{
  label: string
  value: ReactNode
  tone?: 'neutral' | 'success' | 'warning' | 'info'
}>) {
  const toneClass =
    tone === 'success'
      ? 'border-emerald-200/80 bg-emerald-50/90'
      : tone === 'warning'
        ? 'border-amber-200/80 bg-amber-50/90'
        : tone === 'info'
          ? 'border-sky-200/80 bg-sky-50/90'
          : 'border-slate-200/80 bg-card/90'

  const valueClass =
    tone === 'success'
      ? 'text-emerald-700'
      : tone === 'warning'
        ? 'text-amber-700'
        : tone === 'info'
          ? 'text-sky-700'
          : 'text-foreground'

  return (
    <div className={cn('inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1', toneClass)}>
      <span className="text-[11px] font-medium leading-none text-muted-foreground">{label}</span>
      <span className={cn('text-[11px] font-semibold leading-none', valueClass)}>{value}</span>
    </div>
  )
}

function EmbeddedSection({
  title,
  description,
  children,
  className,
}: Readonly<{
  title: string
  description?: string
  children: ReactNode
  className?: string
}>) {
  return (
    <section className={cn('rounded-2xl border border-slate-200/80 bg-card px-2.5 py-2.5', className)}>
      <div className="text-[11px] font-medium uppercase tracking-[0.12em] text-muted-foreground">{title}</div>
      {description ? <p className="mt-1 text-[11px] leading-4 text-muted-foreground">{description}</p> : null}
      <div className="mt-3">{children}</div>
    </section>
  )
}

function EmbeddedToggleCard({
  title,
  description,
  checked,
  onCheckedChange,
  disabled = false,
}: Readonly<{
  title: string
  description: string
  checked: boolean
  onCheckedChange: (checked: boolean) => void
  disabled?: boolean
}>) {
  return (
    <div className={cn('rounded-xl border border-slate-200/80 bg-card/90 px-2.5 py-2', disabled && 'opacity-60')}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-sm font-medium text-foreground">{title}</div>
          <div className="mt-1 text-[11px] leading-4 text-muted-foreground">{description}</div>
        </div>
        <Switch checked={checked} disabled={disabled} onCheckedChange={onCheckedChange} />
      </div>
    </div>
  )
}

export function RegressionTestTab({ embedded = false }: Readonly<{ embedded?: boolean }>) {
  const [showGenerationDialog, setShowGenerationDialog] = useState(false)

  // Dataset scope (required by backend for cases and runs)
  const [datasets, setDatasets] = useState<Dataset[]>([])
  const [selectedDatasetId, setSelectedDatasetId] = useState<string>('')
  const [isLoadingDatasets, setIsLoadingDatasets] = useState(false)
  
  // 运行配置
  const [metricKeys, setMetricKeys] = useState<string[]>([
    'faithfulness',
    'response_relevancy',
  ])
  const [retrievalOnly, setRetrievalOnly] = useState(false)
  const [useLlmJudge, setUseLlmJudge] = useState(false)

  // 运行历史
  const [runs, setRuns] = useState<RegressionRun[]>([])
  const [selectedRunId, setSelectedRunId] = useState<string>('')
  const [runDetail, setRunDetail] = useState<RegressionRunDetail | null>(null)
  const [isLoadingRuns, setIsLoadingRuns] = useState(false)
  const [isConfigPanelCollapsed, setIsConfigPanelCollapsed] = useState(false)

  const visibleRuns = useMemo(() => {
    if (!selectedDatasetId) return runs
    return (runs || []).filter((r) => String(r?.dataset_id || '') === selectedDatasetId)
  }, [runs, selectedDatasetId])

  // Keep selected run in sync with dataset filtering.
  useEffect(() => {
    if (!selectedDatasetId) return
    if (selectedRunId && visibleRuns.some((r) => r?.id === selectedRunId)) return
    setSelectedRunId(visibleRuns?.[0]?.id || '')
  }, [selectedDatasetId, selectedRunId, visibleRuns])

  // Load datasets for dataset-scoped regression UX.
  useEffect(() => {
    let cancelled = false
    const run = async () => {
      setIsLoadingDatasets(true)
      try {
        const res = await datasetApi.list({ limit: 200 })
        if (cancelled) return
        setDatasets(res.items || [])
        const firstId = res.items?.[0]?.id
        if (firstId) {
          // Avoid capturing selectedDatasetId in this effect; keep defaulting behavior.
          setSelectedDatasetId((prev) => prev || firstId)
        }
      } catch (e) {
        // Non-fatal: users can still view existing runs; creating new runs will be blocked.
        if (!cancelled) console.error('Failed to load datasets', e)
      } finally {
        if (!cancelled) setIsLoadingDatasets(false)
      }
    }
    detachPromise(run())
    return () => {
      cancelled = true
    }
  }, [])

  // 加载运行历史
  const loadRuns = useCallback(async () => {
    try {
      setIsLoadingRuns(true)
      const result = await evaluationApi.listRegressionRuns({ limit: 50 })
      setRuns(result.items || [])
      const firstRunId = result.items?.[0]?.id
      if (firstRunId) setSelectedRunId((prev) => prev || firstRunId)
    } catch (error) {
      console.error('加载运行历史失败:', error)
      toast.error(formatApiError(error, '加载运行历史失败'))
    } finally {
      setIsLoadingRuns(false)
    }
  }, [])

  useEffect(() => {
    detachPromise(loadRuns())
  }, [loadRuns])

  // 加载运行详情
  useEffect(() => {
    if (!selectedRunId) {
      setRunDetail(null)
      return
    }

    let cancelled = false
    let timer: ReturnType<typeof setTimeout> | null = null

    const fetchDetail = async () => {
      try {
        const detail = await evaluationApi.getRegressionRun(selectedRunId, {
          include_items: true,
          include_contexts: false,
        })
        if (cancelled) return
        setRunDetail(detail)
        const status = detail?.run?.status
        if (status === 'pending' || status === 'running') {
          timer = setTimeout(fetchDetail, 2000)
        }
      } catch (e) {
        if (!cancelled) console.error('加载运行详情失败', e)
      }
    }

    fetchDetail()
    return () => {
      cancelled = true
      if (timer) clearTimeout(timer)
    }
  }, [selectedRunId])

  // 运行选中的测试
  const handleRunTests = async (caseIds: string[]) => {
    if (!selectedDatasetId) {
      toast.error('请先选择数据集')
      return
    }
    if (caseIds.length === 0) {
      toast.error('请至少选择一个测试用例')
      return
    }

    try {
      const params: RegressionRunCreate = {
        case_ids: caseIds,
        dataset_id: selectedDatasetId,
        metrics: retrievalOnly ? [] : metricKeys,
        use_llm_judge: Boolean(!retrievalOnly && useLlmJudge),
        skip_empty_contexts: true,
        max_cases: 50,
      }

      const run = await evaluationApi.createRegressionRun(params)
      toast.success('开始运行回归测试')
      await loadRuns()
      setSelectedRunId(run.id)
    } catch (error) {
      console.error('运行测试失败:', error)
      toast.error(formatApiError(error, '运行测试失败'))
    }
  }

  // 生成完成回调
  const handleGenerated = () => {
    toast.success('问题生成完成')
    // 刷新用例列表会由 TestCaseManager 组件自动处理
  }

  const summary = runDetail?.run?.summary || {}
  const summaryItems = typeof summary.items === 'number' ? summary.items : '-'
  const summaryTokens = typeof summary.total_tokens === 'number' ? summary.total_tokens : '-'
  const summaryCost =
    typeof summary.total_cost === 'number' || typeof summary.total_cost === 'string' ? summary.total_cost : '-'
  const displayMetrics = Object.entries(summary)
    .filter(([k, v]) => !['items', 'total_tokens', 'total_cost'].includes(k) && typeof v === 'number')
    .map(([k, v]) => ({ key: k, value: Number(v) }))

  const runStatus = runDetail?.run?.status
  const selectedDataset = useMemo(
    () => datasets.find((dataset) => dataset.id === selectedDatasetId) || null,
    [datasets, selectedDatasetId]
  )
  const embeddedGridCols = isConfigPanelCollapsed
    ? 'xl:grid-cols-[0px_minmax(0,1fr)_360px] 2xl:grid-cols-[0px_minmax(0,1fr)_400px]'
    : 'xl:grid-cols-[300px_minmax(0,1fr)_360px] 2xl:grid-cols-[320px_minmax(0,1fr)_400px]'
  const statusBadge = runStatus ? (
    (() => {
    if (runStatus === 'completed') {
        return (<span className="inline-flex items-center gap-2 px-3 py-1 rounded-full text-xs font-semibold bg-success/10 text-success border border-success/20">
        <CheckCircle2 className="w-3.5 h-3.5"/>
        已完成
      </span>);
    }
    else if (runStatus === 'failed') {
            return (<span className="inline-flex items-center gap-2 px-3 py-1 rounded-full text-xs font-semibold bg-destructive/10 text-destructive border border-destructive/20">
        <XCircle className="w-3.5 h-3.5"/>
        失败
      </span>);
        }
        else {
            return (<span className="inline-flex items-center gap-2 px-3 py-1 rounded-full text-xs font-semibold bg-info/10 text-info border border-info/20">
	        <Loader2 className="w-3.5 h-3.5 animate-spin motion-reduce:animate-none"/>
	        运行中
	      </span>);
        }
})()
	  ) : null

  return (
    <div className={cn("flex-1 flex flex-col overflow-hidden", embedded && "overflow-visible")}>
      {/* Inline header (when embedded in a parent PageScaffold) */}
      {!embedded ? (
        <header className="px-8 py-6 border-b border-border bg-card">
          <div className="flex items-center justify-between mb-3">
            <div>
              <h2 className="text-xl font-semibold text-foreground">回归测试</h2>
              <p className="text-sm text-muted-foreground mt-1">
                管理测试用例，批量运行回归测试，跟踪性能变化
              </p>
            </div>
            <div className="flex items-center gap-2">
              <Button variant="outline" className="gap-2" onClick={() => setShowGenerationDialog(true)}>
                <Sparkles className="w-4 h-4" />
                AI 生成问题
              </Button>
            </div>
          </div>

          {/* 指标选择 */}
          <div className="bg-muted/40 rounded-xl p-4">
            <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
              <div className="lg:col-span-5">
              <div className="text-xs font-medium text-muted-foreground mb-2">数据集</div>
                <Select
                  value={selectedDatasetId}
                  onValueChange={setSelectedDatasetId}
                  disabled={isLoadingDatasets || !datasets.length}
                >
                  <SelectTrigger className="h-9">
                    <SelectValue placeholder={isLoadingDatasets ? '加载中...' : '选择数据集'} />
                  </SelectTrigger>
                  <SelectContent>
                    {(datasets || []).map((d) => (
                      <SelectItem key={d.id} value={d.id}>
                        {d.name || d.id}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="lg:col-span-7">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <div className="text-xs font-medium text-muted-foreground">仅检索评测（无 LLM / 无 RAGAS）</div>
                    <div className="text-[11px] text-muted-foreground mt-1">
                      开启后将使用 `metrics=[]`，只计算 recall/hit@k/MRR/NDCG/abstain_rate。
                    </div>
                  </div>
                  <Switch
                    checked={retrievalOnly}
                    onCheckedChange={(checked) => {
                      setRetrievalOnly(checked)
                      if (checked) {
                        setUseLlmJudge(false)
                        setMetricKeys([])
                      } else if (!metricKeys.length) {
                        setMetricKeys(['faithfulness', 'response_relevancy'])
                      }
                    }}
                  />
                </div>

                <div className="flex items-start justify-between gap-3 mt-4">
                  <div>
                    <div className="text-xs font-medium text-muted-foreground">LLM-as-Judge（可选）</div>
                    <div className="text-[11px] text-muted-foreground mt-1">
                      为每个 case 生成 llm_judge（score / reason / evidence_quotes；额外成本；检索-only 模式下不可用）。
                    </div>
                  </div>
                  <Switch
                    checked={useLlmJudge}
                    disabled={retrievalOnly}
                    onCheckedChange={(v) => setUseLlmJudge(Boolean(v))}
                  />
                </div>

                <div className="text-xs font-medium text-muted-foreground mt-4 mb-2">评测指标</div>
                <div className="flex flex-wrap gap-2">
                  {RAGAS_METRIC_OPTIONS.map((m) => (
                    <label key={m.key} className={cn("flex items-center gap-2 text-sm", retrievalOnly && "opacity-50")}>
                      <input
                        type="checkbox"
                        className="h-4 w-4 rounded border-border"
                        checked={metricKeys.includes(m.key)}
                        disabled={retrievalOnly}
                        onChange={(e) => {
                          setMetricKeys((prev) =>
                            e.target.checked ? [...prev, m.key] : prev.filter((x) => x !== m.key)
                          )
                        }}
                      />
                      <span className="text-foreground/80">{m.label}</span>
                    </label>
                  ))}
                  {retrievalOnly && (
                    <span className="text-[11px] text-muted-foreground">（metrics 为空）</span>
                  )}
                </div>
              </div>
            </div>
          </div>
        </header>
      ) : null}

      {/* 主内容区 */}
      <div
        className={embedded ? `flex-1 overflow-hidden grid p-0 ${isConfigPanelCollapsed ? 'gap-0' : 'gap-2.5'} ${embeddedGridCols}` : 'flex-1 overflow-hidden flex gap-6 p-6'}
      >
        {embedded ? (
          isConfigPanelCollapsed ? (
            <aside className="group relative flex min-h-0 items-center justify-center rounded-[28px] border border-slate-200/80 bg-card shadow-[0_16px_40px_rgba(15,23,42,0.04)]">
              <button
                type="button"
                className="focus-ring relative h-full w-2.5 rounded-full transition-colors hover:bg-slate-200/70"
                onClick={() => setIsConfigPanelCollapsed(false)}
                title="展开回归配置"
                aria-label="展开回归配置"
              >
                <span className="absolute inset-y-0 left-1/2 w-px -translate-x-1/2 bg-border/70" aria-hidden="true" />
                <span className="pointer-events-none absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 rounded-full border border-border/70 bg-card/95 p-1 opacity-0 shadow-sm transition-opacity group-hover:opacity-100 group-focus-within:opacity-100">
                  <ChevronRight className="h-3 w-3 text-muted-foreground" aria-hidden="true" />
                </span>
              </button>
            </aside>
          ) : (
            <aside className="flex min-h-0 flex-col overflow-hidden rounded-[28px] border border-slate-200/80 bg-card shadow-[0_16px_40px_rgba(15,23,42,0.04)]">
              <div className="shrink-0 border-b border-slate-200/80 bg-primary/[0.12] px-3 py-2.5">
                <div className="flex items-start justify-between gap-2">
                  <div>
                    <div className="text-[11px] font-medium uppercase tracking-[0.14em] text-muted-foreground">Regression Studio</div>
                    <div className="mt-1 text-sm font-semibold text-foreground">回归配置</div>
                    <p className="mt-1 text-[11px] leading-4 text-muted-foreground">固定数据集后，配置评测模式与评分维度，再到测试用例库批量发起回归。</p>
                  </div>
                  <div className="flex items-center gap-1.5">
                    <Button variant="outline" size="sm" className="h-7 gap-1.5 rounded-lg border-slate-200/80 bg-card/90 px-2 text-[11px]" onClick={() => setShowGenerationDialog(true)}>
                      <Sparkles className="h-3.5 w-3.5" />
                      AI 生成问题
                    </Button>
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      className="h-7 rounded-md px-2 text-[11px] text-muted-foreground hover:bg-slate-100 hover:text-foreground"
                      onClick={() => setIsConfigPanelCollapsed(true)}
                    >
                      收起
                    </Button>
                  </div>
                </div>
                <div className="mt-2 flex flex-wrap items-center gap-2">
                  <RegressionInlineStat label="数据集" value={selectedDataset?.name || '未选择'} />
                  <RegressionInlineStat label="运行数" value={visibleRuns.length} />
                  <RegressionInlineStat label="模式" value={retrievalOnly ? '仅检索' : 'RAGAS'} tone={retrievalOnly ? 'info' : 'neutral'} />
                  <RegressionInlineStat label="评委" value={useLlmJudge && !retrievalOnly ? '开启' : '关闭'} tone={useLlmJudge && !retrievalOnly ? 'success' : 'neutral'} />
                </div>
              </div>

              <div className="min-h-0 flex-1 space-y-2.5 overflow-y-auto overscroll-contain p-2.5 no-scrollbar">
                <EmbeddedSection
                  title="数据集"
                  description="回归 case 和 runs 都是数据集作用域；先把目标数据集固定下来。"
                  className="bg-[linear-gradient(180deg,rgba(245,251,255,0.96)_0%,rgba(255,255,255,0.94)_100%)]"
                >
                  <Select value={selectedDatasetId} onValueChange={setSelectedDatasetId} disabled={isLoadingDatasets || !datasets.length}>
                    <SelectTrigger className="h-9 rounded-xl border-slate-200/80 bg-card/95">
                      <SelectValue placeholder={isLoadingDatasets ? '加载中...' : '选择数据集'} />
                    </SelectTrigger>
                    <SelectContent>
                      {(datasets || []).map((dataset) => (
                        <SelectItem key={dataset.id} value={dataset.id}>
                          {dataset.name || dataset.id}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>

                  <div className="mt-2.5 flex flex-wrap items-center gap-2">
                    <RegressionInlineStat label="状态" value={selectedDataset ? '就绪' : '未选'} tone={selectedDataset ? 'success' : 'warning'} />
                    <RegressionInlineStat label="样例范围" value={selectedDatasetId ? '已绑定' : '未绑定'} tone={selectedDatasetId ? 'info' : 'warning'} />
                  </div>

                  {!datasets.length ? (
                    <div className="mt-2.5 text-[11px] leading-4 text-muted-foreground">
                      未加载到数据集。你仍可查看历史 runs，但创建/运行测试前需要先选一个数据集。
                    </div>
                  ) : null}
                </EmbeddedSection>

                <EmbeddedSection
                  title="模式与判定"
                  description="先决定是否只做检索评测，再决定要不要引入 LLM 评委。"
                  className="bg-[linear-gradient(180deg,rgba(247,255,250,0.96)_0%,rgba(255,255,255,0.94)_100%)]"
                >
                  <div className="space-y-2">
                    <EmbeddedToggleCard
                      title="仅检索评测"
                      description="开启后 `metrics=[]`，只计算 recall、hit@k、MRR、NDCG 与 abstain_rate。"
                      checked={retrievalOnly}
                      onCheckedChange={(checked) => {
                        setRetrievalOnly(checked)
                        if (checked) {
                          setUseLlmJudge(false)
                          setMetricKeys([])
                        } else if (!metricKeys.length) {
                          setMetricKeys(['faithfulness', 'response_relevancy'])
                        }
                      }}
                    />
                    <EmbeddedToggleCard
                      title="LLM-as-Judge"
                      description="为每个 case 额外生成 score、reason 和 evidence quotes；检索-only 模式不可用。"
                      checked={useLlmJudge}
                      disabled={retrievalOnly}
                      onCheckedChange={(checked) => setUseLlmJudge(Boolean(checked))}
                    />
                  </div>
                </EmbeddedSection>

                <EmbeddedSection
                  title="回归评分维度"
                  description="仅作用于回归测试；默认推荐保留忠实度与相关性，如需更强约束再叠加 context precision。"
                  className="bg-[linear-gradient(180deg,rgba(250,252,255,0.96)_0%,rgba(255,255,255,0.94)_100%)]"
                >
                  <RagasMetricSelector
                    metricKeys={metricKeys}
                    onMetricKeysChange={setMetricKeys}
                    disabled={retrievalOnly}
                    scope="regression"
                    className="grid gap-2"
                    itemClassName="gap-3 rounded-xl border border-slate-200/80 bg-card/90 px-2.5 py-1.5"
                    textWrapClassName="space-y-1"
                    labelClassName="text-sm"
                  />
                </EmbeddedSection>
              </div>
            </aside>
          )
        ) : null}

        {/* 左侧：测试用例管理 */}
        <div className={cn("flex flex-col bg-card rounded-2xl border border-border", embedded ? "min-w-0 rounded-[28px] border-slate-200/80 bg-card shadow-[0_16px_40px_rgba(15,23,42,0.04)]" : "w-1/3")}>
          <TestCaseManager
            datasetId={selectedDatasetId || null}
            dense={embedded}
            onRunTests={handleRunTests}
            onCaseSelected={(caseId) => {
              // 可以在这里处理用例选中事件
            }}
          />
        </div>

        {/* 右侧：运行结果 */}
        <div className={cn("flex-1 flex flex-col gap-2.5", embedded && "min-w-0")}>
          {/* 运行历史列表 */}
          <div className={cn("bg-card border border-border rounded-2xl overflow-hidden", embedded && "rounded-[28px] border-slate-200/80 bg-card")}>
            <div className={cn("p-3 border-b border-border flex items-center justify-between", embedded && "border-slate-200/80 bg-[#fffef9]")}>
              <div>
                <div className="text-[11px] uppercase tracking-[0.12em] text-muted-foreground">Run Timeline</div>
                <div className="mt-1 text-sm font-semibold text-foreground">运行历史</div>
              </div>
              <div className="text-[11px] text-muted-foreground">
                {visibleRuns.length} 次{selectedDatasetId ? '（按数据集过滤）' : ''}
              </div>
            </div>
		            <div className={cn("overflow-y-auto overscroll-contain no-scrollbar", embedded ? "max-h-[200px]" : "max-h-40")}>
			              {(() => {
    if (isLoadingRuns) {
        return (<div className="flex items-center justify-center py-8">
		                  <Loader2 className="w-6 h-6 animate-spin motion-reduce:animate-none text-muted-foreground"/>
		                </div>);
    }
    else if (visibleRuns.length === 0) {
            return (<div className="text-center py-8 text-muted-foreground text-sm">
	                  暂无运行记录
	                </div>);
        }
        else {
            return (visibleRuns.map((run) => (<button key={run.id} onClick={() => setSelectedRunId(run.id)} className={cn('w-full text-left border-b transition-colors motion-reduce:transition-none', embedded ? 'border-slate-200/70 px-2.5 py-2 hover:bg-slate-50/80' : 'border-border p-4 hover:bg-muted/50', selectedRunId === run.id && (embedded ? 'bg-sky-50/70' : 'bg-primary/10'))}>
	                    <div className="flex items-center justify-between gap-2">
	                      <div className="text-sm font-medium text-foreground truncate">
	                        运行 {run.id.slice(0, 8)}
	                      </div>
	                      <span className={cn('text-[11px] px-2 py-0.5 rounded-full border', (() => {
                    if (run.status === 'completed') {
                        return 'bg-success/10 text-success border-success/20';
                    }
                    else if (run.status === 'failed') {
                            return 'bg-destructive/10 text-destructive border-destructive/20';
                        }
                        else {
                            return 'bg-info/10 text-info border-info/20';
                        }
                })())}>
	                        {run.status}
	                      </span>
	                    </div>
	                    <div className="mt-2 flex items-center gap-2 text-xs text-muted-foreground">
	                      {embedded ? <Clock3 className="h-3.5 w-3.5" /> : null}
	                      <span>{new Date(run.created_at).toLocaleString()}</span>
	                    </div>
	                  </button>)));
        }
})()}
	            </div>
	          </div>

	          {/* 运行详情 */}
	          <div className={cn("flex-1 bg-card border border-border rounded-2xl p-2.5 overflow-y-auto overscroll-contain no-scrollbar", embedded && "rounded-[28px] border-slate-200/80 bg-card")}>
	            <div className="flex items-center justify-between mb-3">
	              <div>
	                <div className="text-[11px] uppercase tracking-[0.12em] text-muted-foreground">Run Detail</div>
	                <div className="mt-1 text-sm font-semibold text-foreground">运行详情</div>
	              </div>
	              {statusBadge}
	            </div>

	            {runDetail?.run?.error_message && (
	              <div className="mt-3 text-sm text-destructive p-3 bg-destructive/10 border border-destructive/20 rounded-lg">
	                {runDetail.run.error_message}
	              </div>
	            )}

	            {displayMetrics.length > 0 ? (
	              <div className="mt-4">
	                <StatsGrid className="lg:grid-cols-3">
	                  {displayMetrics.map((m) => (
	                    <StatCard key={m.key} icon={BarChart3} label={ragasMetricLabel(m.key)} value={m.value.toFixed(3)} color="sky" className="shadow-sm" />
	                  ))}
		                </StatsGrid>
		                <div className="mt-3 flex flex-wrap items-center gap-2">
		                  <RegressionInlineStat label="样本" value={summaryItems} />
		                  <RegressionInlineStat label="Token" value={summaryTokens} />
		                  <RegressionInlineStat label="费用" value={summaryCost} />
		                </div>
                  {(() => {
                    const slices = (summary as any)?.retrieval_slices
                    const pq = (slices as any)?.parse_quality?.buckets
                    const cq = (slices as any)?.chunk_quality?.buckets
                    const hasPq = Array.isArray(pq) && pq.length
                    const hasCq = Array.isArray(cq) && cq.length
                    if (!hasPq && !hasCq) return null

                    const renderTable = (title: string, rows: any[]) => {
                      const top = (rows || []).slice(0, 8)
                      return (
                        <div className="rounded-xl border border-border bg-muted/20 p-3">
                          <div className="text-xs font-semibold text-foreground mb-2">{title}</div>
                          <div className="overflow-auto">
                            <table aria-label={`${title} 分桶统计`} className="w-full text-xs">
                              <thead>
                                <tr className="text-muted-foreground border-b border-border/60">
                                  <th className="text-left py-1 pr-2">bucket</th>
                                  <th className="text-right py-1 pr-2">items</th>
                                  <th className="text-right py-1 pr-2">recall</th>
                                  <th className="text-right py-1 pr-2">mrr</th>
                                  <th className="text-right py-1 pr-2">ndcg@10</th>
                                </tr>
                              </thead>
                              <tbody>
                                {top.map((r: any) => (
                                  <tr key={String(r?.key || '')} className="border-b border-border/40">
                                    <td className="py-1 pr-2 font-mono text-muted-foreground">{String(r?.key || '')}</td>
                                    <td className="py-1 pr-2 text-right tabular-nums">{String(r?.items ?? '—')}</td>
                                    <td className="py-1 pr-2 text-right tabular-nums">
                                      {typeof r?.retrieval_recall === 'number' ? r.retrieval_recall.toFixed(3) : '—'}
                                    </td>
                                    <td className="py-1 pr-2 text-right tabular-nums">
                                      {typeof r?.retrieval_mrr === 'number' ? r.retrieval_mrr.toFixed(3) : '—'}
                                    </td>
                                    <td className="py-1 pr-2 text-right tabular-nums">
                                      {typeof r?.retrieval_ndcg_at_10 === 'number' ? r.retrieval_ndcg_at_10.toFixed(3) : '—'}
                                    </td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </div>
                        </div>
                      )
                    }

                    return (
                      <div className="mt-4">
                        <div className="text-sm font-semibold text-foreground mb-3">质量归因（Slices）</div>
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                          {hasPq ? renderTable('parse_quality → retrieval', pq as any[]) : null}
                          {hasCq ? renderTable('chunk_quality → retrieval', cq as any[]) : null}
                        </div>
                      </div>
                    )
                  })()}
	              </div>
	            ) : (
	              <div className="mt-4 rounded-2xl border border-dashed border-slate-200 bg-[#fcfcfa] px-4 py-8 text-center">
	                <div className="text-sm font-medium text-foreground">
	                  {selectedRunId ? '当前还没有可展示分数' : '先选一个运行记录'}
	                </div>
	                <div className="mt-2 text-[12px] leading-6 text-muted-foreground">
	                  {selectedRunId ? '这条 run 可能仍在处理中，或后端尚未返回 summary 指标。' : '右上方的运行历史里选中一条 run 后，这里会显示状态、指标与质量切片。'}
	                </div>
	              </div>
	            )}

	            {/* 明细列表 */}
	            {runDetail?.items && runDetail.items.length > 0 && (
	              <div className="mt-6">
		                <div className="text-sm font-semibold text-foreground mb-3">
		                  测试明细 ({runDetail.items.length})
		                </div>
		                <div className="space-y-2">
	                  {runDetail.items.map((item, index: number) => (
	                    <div key={item.id} className={cn("p-3 rounded-lg border", embedded ? "border-slate-200/80 bg-[#fffef9]" : "border-border bg-muted/40")}>
	                      <div className="text-sm font-medium text-foreground mb-1">
	                        {index + 1}. {item.question}
	                      </div>
	                      <div className="text-xs text-muted-foreground mt-2">
	                        <span className="font-medium">回答:</span> {item.response?.slice(0, 100)}...
	                      </div>
	                      {item.scores && Object.keys(item.scores).length > 0 && (
	                        <div className="flex gap-2 mt-2">
	                          {Object.entries(item.scores).map(([k, v]: [string, any]) => (
	                            <span
	                              key={k}
	                              className="text-[11px] px-2 py-0.5 rounded-full bg-info/10 text-info border border-info/20"
	                            >
	                              {k}: {typeof v === 'number' ? v.toFixed(2) : v}
	                            </span>
	                          ))}
	                        </div>
                      )}
                      {(() => {
                        const exps = (item as any)?.meta?.explanations
                        if (!exps || typeof exps !== 'object') return null
                        const entries = Object.entries(exps as Record<string, any>).filter(([, v]) => typeof v === 'string' && v)
                        if (!entries.length) return null
                        return (
                          <details className="mt-2">
                            <summary className="text-[11px] text-muted-foreground cursor-pointer select-none">
                              解释
                            </summary>
                            <div className="mt-2 space-y-1 text-[11px] text-muted-foreground">
                              {entries.map(([k, v]) => (
                                <div key={k} className="flex gap-2">
                                  <span className="font-medium text-foreground/80">{k}:</span>
                                  <span className="break-words">{String(v)}</span>
                                </div>
                              ))}
                            </div>
                          </details>
                        )
                      })()}
                      {(() => {
                        const judge = (item as any)?.meta?.llm_judge
                        if (!judge || typeof judge !== 'object') return null
                        if (!Boolean((judge as any)?.enabled)) return null
                        const overall = (judge as any)?.overall_score
                        const modelUsed = (judge as any)?.model_used
                        const parts: Array<{ key: string; obj: any }> = [
                          { key: 'retrieval', obj: (judge as any)?.retrieval },
                          { key: 'generation', obj: (judge as any)?.generation },
                        ]
                        return (
                          <details className="mt-2">
                            <summary className="text-[11px] text-muted-foreground cursor-pointer select-none">
                              LLM Judge{typeof overall === 'number' ? ` (overall=${overall.toFixed(3)})` : ''}
                            </summary>
                            <div className="mt-2 space-y-2 text-[11px] text-muted-foreground">
                              {modelUsed ? (
                                <div className="font-mono text-[11px] text-muted-foreground">model: {String(modelUsed)}</div>
                              ) : null}
                              {parts.map(({ key, obj }) => {
                                if (!obj || typeof obj !== 'object') return null
                                const score = (obj as any)?.score
                                const reason = (obj as any)?.reason
                                const quotes = Array.isArray((obj as any)?.evidence_quotes)
                                  ? ((obj as any)?.evidence_quotes as any[]).filter((x) => typeof x === 'string' && x)
                                  : []
                                return (
                                  <div key={key} className="rounded-md border border-border/60 bg-muted/30 p-2">
                                    <div className="flex items-center justify-between gap-2">
                                      <span className="font-medium text-foreground/80">{key}</span>
                                      <span className="tabular-nums">
                                        {typeof score === 'number' ? score.toFixed(3) : '—'}
                                      </span>
                                    </div>
                                    {typeof reason === 'string' && reason ? (
                                      <div className="mt-1 text-muted-foreground">{reason}</div>
                                    ) : null}
                                    {quotes.length ? (
                                      <div className="mt-2 space-y-1">
                                        {quotes.slice(0, 3).map((q, i) => (
                                          <div key={i} className="font-mono text-[11px] text-muted-foreground">
                                            “{q}”
                                          </div>
                                        ))}
                                      </div>
                                    ) : null}
                                  </div>
                                )
                              })}
                            </div>
                          </details>
                        )
                      })()}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* AI 生成对话框 */}
      <TestGenerationDialog
        open={showGenerationDialog}
        onClose={() => setShowGenerationDialog(false)}
        onGenerated={handleGenerated}
      />
    </div>
  )
}
