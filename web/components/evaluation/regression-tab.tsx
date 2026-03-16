/**
 * 回归测试 Tab
 * 
 * 功能：
 * - 测试用例管理
 * - AI 生成问题
 * - 批量运行回归测试
 */

'use client'

import { useState, useEffect, useMemo } from 'react'
import { datasetApi, evaluationApi } from '@/lib/api-client'
import type { Dataset, RegressionRun, RegressionRunCreate, RegressionRunDetail } from '@/types'
import { Button } from '@/components/ui/button'
import { TestCaseManager } from '@/components/test-case-manager'
import { TestGenerationDialog } from '@/components/test-generation-dialog'
import { Sparkles, Loader2, BarChart3, CheckCircle2, XCircle } from 'lucide-react'
import { toast } from 'sonner'
import { cn, detachPromise } from '@/lib/utils'
import { StatCard, StatsGrid } from '@/components/ui/stats-card'
import { formatApiError } from '@/lib/api-errors'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'

const METRIC_OPTIONS = [
    { key: 'faithfulness', label: 'Faithfulness（忠实度）' },
    { key: 'response_relevancy', label: 'Response Relevancy（相关性）' },
    { key: 'context_precision', label: 'Context Precision（无参考）' },
]

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

  // 运行历史
  const [runs, setRuns] = useState<RegressionRun[]>([])
  const [selectedRunId, setSelectedRunId] = useState<string>('')
  const [runDetail, setRunDetail] = useState<RegressionRunDetail | null>(null)
  const [isLoadingRuns, setIsLoadingRuns] = useState(false)

  const visibleRuns = useMemo(() => {
    if (!selectedDatasetId) return runs
    return (runs || []).filter((r) => String(r?.dataset_id || '') === selectedDatasetId)
  }, [runs, selectedDatasetId])

  // Keep selected run in sync with dataset filtering.
  useEffect(() => {
    if (!selectedDatasetId) return
    if (selectedRunId && visibleRuns.some((r) => r?.id === selectedRunId)) return
    setSelectedRunId(visibleRuns?.[0]?.id || '')
  }, [selectedDatasetId, visibleRuns])

  // Load datasets for dataset-scoped regression UX.
  useEffect(() => {
    let cancelled = false
    const run = async () => {
      setIsLoadingDatasets(true)
      try {
        const res = await datasetApi.list({ limit: 200 })
        if (cancelled) return
        setDatasets(res.items || [])
        if (!selectedDatasetId && res.items?.[0]?.id) {
          setSelectedDatasetId(res.items[0].id)
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
  const loadRuns = async () => {
    try {
      setIsLoadingRuns(true)
      const result = await evaluationApi.listRegressionRuns({ limit: 50 })
      setRuns(result.items || [])
      if (!selectedRunId && result.items?.length) {
        setSelectedRunId(result.items[0].id)
      }
    } catch (error) {
      console.error('加载运行历史失败:', error)
      toast.error(formatApiError(error, '加载运行历史失败'))
    } finally {
      setIsLoadingRuns(false)
    }
  }

  useEffect(() => {
    loadRuns()
  }, [])

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
  const displayMetrics = Object.entries(summary)
    .filter(([k, v]) => !['items', 'total_tokens', 'total_cost'].includes(k) && typeof v === 'number')
    .map(([k, v]) => ({ key: k, value: Number(v) }))

  const runStatus = runDetail?.run?.status
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
      {embedded ? (
        <div className="mb-6 space-y-4">
          <div className="flex items-start justify-between gap-4">
            <div>
              <h2 className="text-lg font-semibold text-foreground">回归测试</h2>
              <p className="text-sm text-muted-foreground mt-1">
                管理测试用例，批量运行回归测试，跟踪性能变化
              </p>
            </div>
            <Button variant="outline" size="sm" className="gap-2" onClick={() => setShowGenerationDialog(true)}>
              <Sparkles className="w-4 h-4" />
              AI 生成问题
            </Button>
          </div>

          {/* 指标选择 */}
          <div className="rounded-2xl border border-border bg-card/60 backdrop-blur-sm p-4">
            <div className="flex flex-col gap-4">
              <div className="flex flex-col gap-2">
                <div className="text-xs font-medium text-muted-foreground">数据集</div>
                <Select
                  value={selectedDatasetId}
                  onValueChange={setSelectedDatasetId}
                  disabled={isLoadingDatasets || !datasets.length}
                >
                  <SelectTrigger className="h-9 rounded-xl">
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
                {!datasets.length && (
                  <div className="text-[11px] text-muted-foreground">
                    未加载到数据集（你仍可查看历史 runs；创建/运行需要先选数据集）
                  </div>
                )}
              </div>

              <div className="flex items-center justify-between gap-3">
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
                      setMetricKeys([])
                    } else if (!metricKeys.length) {
                      setMetricKeys(['faithfulness', 'response_relevancy'])
                    }
                  }}
                />
              </div>

              <div>
                <div className="text-xs font-medium text-muted-foreground mb-2">评测指标</div>
                <div className="flex flex-wrap gap-3">
                  {METRIC_OPTIONS.map((m) => (
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
                      <span className="text-foreground/90">{m.label}</span>
                    </label>
                  ))}
                  {retrievalOnly && (
                    <div className="text-[11px] text-muted-foreground">
                      （已切换为检索评测，metrics 为空）
                    </div>
                  )}
                </div>
              </div>
            </div>
          </div>
        </div>
      ) : (
        <header className="px-8 py-6 border-b border-border bg-card">
          <div className="flex items-center justify-between mb-4">
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
                        setMetricKeys([])
                      } else if (!metricKeys.length) {
                        setMetricKeys(['faithfulness', 'response_relevancy'])
                      }
                    }}
                  />
                </div>

                <div className="text-xs font-medium text-muted-foreground mt-4 mb-2">评测指标</div>
                <div className="flex flex-wrap gap-2">
                  {METRIC_OPTIONS.map((m) => (
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
      )}

      {/* 主内容区 */}
      <div className={cn("flex-1 overflow-hidden flex gap-6 p-6", embedded && "p-0")}>
        {/* 左侧：测试用例管理 */}
        <div className="w-1/3 flex flex-col bg-card rounded-2xl border border-border">
          <TestCaseManager
            datasetId={selectedDatasetId || null}
            onRunTests={handleRunTests}
            onCaseSelected={(caseId) => {
              // 可以在这里处理用例选中事件
            }}
          />
        </div>

        {/* 右侧：运行结果 */}
        <div className="flex-1 flex flex-col gap-4">
          {/* 运行历史列表 */}
          <div className="bg-card border border-border rounded-2xl overflow-hidden">
            <div className="p-4 border-b border-border flex items-center justify-between">
              <div className="text-sm font-semibold text-foreground">
                运行历史
              </div>
              <div className="text-xs text-muted-foreground">
                {visibleRuns.length} 次{selectedDatasetId ? '（按数据集过滤）' : ''}
              </div>
            </div>
	            <div className="max-h-40 overflow-y-auto overscroll-contain no-scrollbar">
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
            return (visibleRuns.map((run) => (<button key={run.id} onClick={() => setSelectedRunId(run.id)} className={cn('w-full text-left p-4 border-b border-border hover:bg-muted/50 transition-colors motion-reduce:transition-none', selectedRunId === run.id && 'bg-primary/10')}>
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
	                    <div className="mt-2 text-xs text-muted-foreground">
	                      {new Date(run.created_at).toLocaleString()}
	                    </div>
	                  </button>)));
        }
})()}
	            </div>
	          </div>

	          {/* 运行详情 */}
	          <div className="flex-1 bg-card border border-border rounded-2xl p-4 overflow-y-auto overscroll-contain no-scrollbar">
	            <div className="flex items-center justify-between mb-4">
	              <div className="text-sm font-semibold text-foreground">
	                运行详情
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
	                    <StatCard
	                      key={m.key}
	                      icon={BarChart3}
	                      label={m.key}
	                      value={m.value.toFixed(3)}
	                      color="sky"
	                      className="shadow-sm"
	                    />
	                  ))}
	                </StatsGrid>
	                <div className="mt-3 text-xs text-muted-foreground">
	                  items: {summary.items ?? '-'} · tokens: {summary.total_tokens ?? '-'} · cost: {summary.total_cost ?? '-'}
	                </div>
	              </div>
	            ) : (
	              <div className="mt-4 text-sm text-muted-foreground">
	                {selectedRunId ? '暂无分数（可能仍在运行中）' : '请选择一个运行记录'}
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
	                    <div
	                      key={item.id}
	                      className="p-3 rounded-lg border border-border bg-muted/40"
	                    >
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
	                              className="text-[10px] px-2 py-0.5 rounded-full bg-info/10 text-info border border-info/20"
	                            >
	                              {k}: {typeof v === 'number' ? v.toFixed(2) : v}
	                            </span>
	                          ))}
	                        </div>
                      )}
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
