/**
 * 回归测试 Tab
 * 
 * 功能：
 * - 测试用例管理
 * - AI 生成问题
 * - 批量运行回归测试
 */

'use client'

import { useState, useEffect } from 'react'
import { evaluationApi } from '@/lib/api-client'
import type { RegressionRunCreate } from '@/types'
import { Button } from '@/components/ui/button'
import { TestCaseManager } from '@/components/test-case-manager'
import { TestGenerationDialog } from '@/components/test-generation-dialog'
import {
  Sparkles,
  Play,
  Loader2,
  BarChart3,
  CheckCircle2,
  XCircle,
} from 'lucide-react'
import { toast } from 'sonner'
import { cn } from '@/lib/utils'
import { StatCard, StatsGrid } from '@/components/ui/stats-card'

const METRIC_OPTIONS = [
  { key: 'faithfulness', label: 'Faithfulness（忠实度）' },
  { key: 'response_relevancy', label: 'Response Relevancy（相关性）' },
  { key: 'context_precision', label: 'Context Precision（无参考）' },
] as const

export function RegressionTestTab() {
  const [showGenerationDialog, setShowGenerationDialog] = useState(false)
  const [isRunning, setIsRunning] = useState(false)
  const [selectedCaseIds, setSelectedCaseIds] = useState<string[]>([])
  
  // 运行配置
  const [metricKeys, setMetricKeys] = useState<string[]>([
    'faithfulness',
    'response_relevancy',
  ])
  
  // 运行历史
  const [runs, setRuns] = useState<any[]>([])
  const [selectedRunId, setSelectedRunId] = useState<string>('')
  const [runDetail, setRunDetail] = useState<any | null>(null)
  const [isLoadingRuns, setIsLoadingRuns] = useState(false)

  // 加载运行历史
  const loadRuns = async () => {
    try {
      setIsLoadingRuns(true)
      const result = await evaluationApi.listRegressionRuns({ limit: 50 })
      setRuns(result.items)
      if (result.items.length > 0 && !selectedRunId) {
        setSelectedRunId(result.items[0].id)
      }
    } catch (error) {
      console.error('加载运行历史失败:', error)
      toast.error('加载运行历史失败')
    } finally {
      setIsLoadingRuns(false)
    }
  }

  useEffect(() => {
    loadRuns()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // 加载运行详情
  useEffect(() => {
    if (!selectedRunId) {
      setRunDetail(null)
      return
    }

    let cancelled = false
    let timer: any = null

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
    if (caseIds.length === 0) {
      toast.error('请至少选择一个测试用例')
      return
    }

    setIsRunning(true)
    try {
      const params: RegressionRunCreate = {
        case_ids: caseIds,
        metrics: metricKeys,
        skip_empty_contexts: true,
        max_cases: 50,
      }

      const run = await evaluationApi.createRegressionRun(params)
      toast.success('开始运行回归测试')
      await loadRuns()
      setSelectedRunId(run.id)
    } catch (error) {
      console.error('运行测试失败:', error)
      toast.error('运行测试失败')
    } finally {
      setIsRunning(false)
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
  const statusBadge = !runStatus ? null : (
    runStatus === 'completed' ? (
      <span className="inline-flex items-center gap-2 px-3 py-1 rounded-full text-xs font-semibold bg-emerald-50 text-emerald-700 border border-emerald-100">
        <CheckCircle2 className="w-3.5 h-3.5" />
        已完成
      </span>
    ) : runStatus === 'failed' ? (
      <span className="inline-flex items-center gap-2 px-3 py-1 rounded-full text-xs font-semibold bg-red-50 text-red-700 border border-red-100">
        <XCircle className="w-3.5 h-3.5" />
        失败
      </span>
    ) : (
      <span className="inline-flex items-center gap-2 px-3 py-1 rounded-full text-xs font-semibold bg-indigo-50 text-indigo-700 border border-indigo-100">
        <Loader2 className="w-3.5 h-3.5 animate-spin" />
        运行中
      </span>
    )
  )

  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      {/* 头部操作栏 */}
      <header className="px-8 py-6 border-b border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h2 className="text-xl font-semibold text-slate-900 dark:text-white">
              回归测试
            </h2>
            <p className="text-sm text-slate-500 dark:text-slate-400 mt-1">
              管理测试用例，批量运行回归测试，跟踪性能变化
            </p>
          </div>
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              className="gap-2"
              onClick={() => setShowGenerationDialog(true)}
            >
              <Sparkles className="w-4 h-4" />
              AI 生成问题
            </Button>
          </div>
        </div>

        {/* 指标选择 */}
        <div className="bg-slate-50 dark:bg-slate-800/50 rounded-xl p-4">
          <div className="text-xs font-medium text-slate-600 dark:text-slate-400 mb-2">
            评测指标
          </div>
          <div className="flex flex-wrap gap-2">
            {METRIC_OPTIONS.map((m) => (
              <label key={m.key} className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  className="h-4 w-4 rounded border-slate-300"
                  checked={metricKeys.includes(m.key)}
                  onChange={(e) => {
                    setMetricKeys((prev) =>
                      e.target.checked ? [...prev, m.key] : prev.filter((x) => x !== m.key)
                    )
                  }}
                />
                <span className="text-slate-700 dark:text-slate-300">{m.label}</span>
              </label>
            ))}
          </div>
        </div>
      </header>

      {/* 主内容区 */}
      <div className="flex-1 overflow-hidden flex gap-6 p-6">
        {/* 左侧：测试用例管理 */}
        <div className="w-1/3 flex flex-col bg-white dark:bg-slate-900 rounded-2xl border border-slate-200 dark:border-slate-800">
          <TestCaseManager
            onRunTests={handleRunTests}
            onCaseSelected={(caseId) => {
              // 可以在这里处理用例选中事件
            }}
          />
        </div>

        {/* 右侧：运行结果 */}
        <div className="flex-1 flex flex-col gap-4">
          {/* 运行历史列表 */}
          <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-2xl overflow-hidden">
            <div className="p-4 border-b border-slate-100 dark:border-slate-800 flex items-center justify-between">
              <div className="text-sm font-semibold text-slate-800 dark:text-slate-200">
                运行历史
              </div>
              <div className="text-xs text-slate-500">
                {runs.length} 次
              </div>
            </div>
            <div className="max-h-40 overflow-y-auto">
              {isLoadingRuns ? (
                <div className="flex items-center justify-center py-8">
                  <Loader2 className="w-6 h-6 animate-spin text-slate-400" />
                </div>
              ) : runs.length === 0 ? (
                <div className="text-center py-8 text-slate-500 text-sm">
                  暂无运行记录
                </div>
              ) : (
                runs.map((run) => (
                  <button
                    key={run.id}
                    onClick={() => setSelectedRunId(run.id)}
                    className={cn(
                      'w-full text-left p-4 border-b border-slate-100 dark:border-slate-800 hover:bg-slate-50 dark:hover:bg-slate-800/40 transition',
                      selectedRunId === run.id && 'bg-indigo-50/60 dark:bg-indigo-900/10'
                    )}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <div className="text-sm font-medium text-slate-800 dark:text-slate-200 truncate">
                        运行 {run.id.slice(0, 8)}
                      </div>
                      <span
                        className={cn(
                          'text-[11px] px-2 py-0.5 rounded-full border',
                          run.status === 'completed'
                            ? 'bg-emerald-50 text-emerald-700 border-emerald-100'
                            : run.status === 'failed'
                            ? 'bg-red-50 text-red-700 border-red-100'
                            : 'bg-indigo-50 text-indigo-700 border-indigo-100'
                        )}
                      >
                        {run.status}
                      </span>
                    </div>
                    <div className="mt-2 text-xs text-slate-500 dark:text-slate-400">
                      {new Date(run.created_at).toLocaleString()}
                    </div>
                  </button>
                ))
              )}
            </div>
          </div>

          {/* 运行详情 */}
          <div className="flex-1 bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-2xl p-4 overflow-y-auto">
            <div className="flex items-center justify-between mb-4">
              <div className="text-sm font-semibold text-slate-800 dark:text-slate-200">
                运行详情
              </div>
              {statusBadge}
            </div>

            {runDetail?.run?.error_message && (
              <div className="mt-3 text-sm text-red-600 p-3 bg-red-50 rounded-lg">
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
                      color="indigo"
                      className="bg-white/80 dark:bg-slate-900/80 border-slate-200 dark:border-slate-800 shadow-sm"
                    />
                  ))}
                </StatsGrid>
                <div className="mt-3 text-xs text-slate-500 dark:text-slate-400">
                  items: {summary.items ?? '-'} · tokens: {summary.total_tokens ?? '-'} · cost: {summary.total_cost ?? '-'}
                </div>
              </div>
            ) : (
              <div className="mt-4 text-sm text-slate-500">
                {selectedRunId ? '暂无分数（可能仍在运行中）' : '请选择一个运行记录'}
              </div>
            )}

            {/* 明细列表 */}
            {runDetail?.items && runDetail.items.length > 0 && (
              <div className="mt-6">
                <div className="text-sm font-semibold text-slate-800 dark:text-slate-200 mb-3">
                  测试明细 ({runDetail.items.length})
                </div>
                <div className="space-y-2">
                  {runDetail.items.map((item: any, index: number) => (
                    <div
                      key={item.id}
                      className="p-3 rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800/50"
                    >
                      <div className="text-sm font-medium text-slate-800 dark:text-slate-200 mb-1">
                        {index + 1}. {item.question}
                      </div>
                      <div className="text-xs text-slate-600 dark:text-slate-400 mt-2">
                        <span className="font-medium">回答:</span> {item.response?.slice(0, 100)}...
                      </div>
                      {item.scores && Object.keys(item.scores).length > 0 && (
                        <div className="flex gap-2 mt-2">
                          {Object.entries(item.scores).map(([k, v]: [string, any]) => (
                            <span
                              key={k}
                              className="text-[10px] px-2 py-0.5 rounded-full bg-indigo-100 dark:bg-indigo-900/30 text-indigo-700 dark:text-indigo-300"
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

