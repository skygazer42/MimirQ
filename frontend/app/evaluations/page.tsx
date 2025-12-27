'use client'

/**
 * RAGAS 评测页面
 * - 基于对话历史 + 引用上下文运行 RAGAS 指标
 * - 展示评测运行记录、汇总分数与逐轮明细
 */

import { Suspense, useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'next/navigation'
import { Navbar } from '@/components/navbar'
import { Button } from '@/components/ui/button'
import { StatCard, StatsGrid } from '@/components/ui/stats-card'
import { evaluationApi, chatApi } from '@/lib/api-client'
import type { Conversation } from '@/types'
import {
  BarChart3,
  CheckCircle,
  Loader2,
  PlayCircle,
  RefreshCw,
  XCircle,
} from 'lucide-react'
import { cn } from '@/lib/utils'

const METRIC_OPTIONS = [
  { key: 'faithfulness', label: 'Faithfulness（忠实度）' },
  { key: 'response_relevancy', label: 'Response Relevancy（相关性）' },
  { key: 'context_precision', label: 'Context Precision（无参考）' },
] as const

export default function EvaluationsPage() {
  return (
    <div className="flex h-screen overflow-hidden bg-slate-50/50 dark:bg-slate-950 transition-colors duration-300">
      <Navbar />
      <Suspense fallback={<EvaluationsLoading />}>
        <EvaluationsPageContent />
      </Suspense>
    </div>
  )
}

function EvaluationsLoading() {
  return (
    <div className="flex-1 flex items-center justify-center">
      <Loader2 className="h-8 w-8 animate-spin text-slate-400" />
    </div>
  )
}

function EvaluationsPageContent() {
  const searchParams = useSearchParams()
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [selectedConversationId, setSelectedConversationId] = useState<string>('')

  const [runs, setRuns] = useState<any[]>([])
  const [selectedRunId, setSelectedRunId] = useState<string>('')
  const [runDetail, setRunDetail] = useState<any | null>(null)

  const [metricKeys, setMetricKeys] = useState<string[]>([
    'faithfulness',
    'response_relevancy',
  ])
  const [maxTurns, setMaxTurns] = useState(20)
  const [skipEmptyContexts, setSkipEmptyContexts] = useState(true)

  const [isLoading, setIsLoading] = useState(false)
  const [isStarting, setIsStarting] = useState(false)

  // Support deep-linking: /evaluations?conversation_id=...
  useEffect(() => {
    const cid = searchParams.get('conversation_id')
    if (cid) setSelectedConversationId(cid)
  }, [searchParams])

  const loadConversations = async () => {
    try {
      const res = await chatApi.listConversations({ limit: 100 })
      setConversations(res.items || [])
      if (!selectedConversationId && res.items?.[0]?.id) {
        setSelectedConversationId(res.items[0].id)
      }
    } catch (e) {
      console.error('Failed to load conversations', e)
    }
  }

  const loadRuns = async (conversationId?: string) => {
    try {
      const res = await evaluationApi.listRagasRuns({
        limit: 50,
        conversation_id: conversationId || undefined,
      })
      setRuns(res.items || [])
      if (!selectedRunId && res.items?.[0]?.id) {
        setSelectedRunId(res.items[0].id)
      }
    } catch (e) {
      console.error('Failed to load runs', e)
    }
  }

  // Initial data
  useEffect(() => {
    setIsLoading(true)
    Promise.all([loadConversations(), loadRuns()]).finally(() => setIsLoading(false))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // When switching conversation, focus run list on that conversation
  useEffect(() => {
    if (!selectedConversationId) return
    setSelectedRunId('')
    setRunDetail(null)
    loadRuns(selectedConversationId)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedConversationId])

  // Poll run detail
  useEffect(() => {
    if (!selectedRunId) {
      setRunDetail(null)
      return
    }

    let cancelled = false
    let timer: any = null

    const fetchDetail = async () => {
      try {
        const detail = await evaluationApi.getRagasRun(selectedRunId, {
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
        if (!cancelled) console.error('Failed to load run detail', e)
      }
    }

    fetchDetail()
    return () => {
      cancelled = true
      if (timer) clearTimeout(timer)
    }
  }, [selectedRunId])

  const handleStart = async () => {
    if (!selectedConversationId) return
    setIsStarting(true)
    try {
      const run = await evaluationApi.createRagasRun({
        conversation_id: selectedConversationId,
        metrics: metricKeys,
        max_turns: maxTurns,
        skip_empty_contexts: skipEmptyContexts,
        include_contexts_in_response: false,
      })
      await loadRuns(selectedConversationId)
      setSelectedRunId(run.id)
    } catch (e) {
      console.error('Failed to start evaluation', e)
      alert('启动评测失败，请检查后端日志/配置。')
    } finally {
      setIsStarting(false)
    }
  }

  const summary = useMemo(() => runDetail?.run?.summary || {}, [runDetail?.run?.summary])
  const displayMetrics = useMemo(() => {
    const ignore = new Set(['items', 'total_tokens', 'total_cost'])
    return Object.entries(summary)
      .filter(([k, v]) => !ignore.has(k) && typeof v === 'number')
      .map(([k, v]) => ({ key: k, value: Number(v) }))
  }, [summary])

  const runStatus = runDetail?.run?.status
  const statusBadge = useMemo(() => {
    if (!runStatus) return null
    const base = 'inline-flex items-center gap-2 px-3 py-1 rounded-full text-xs font-semibold'
    if (runStatus === 'completed') {
      return (
        <span className={cn(base, 'bg-emerald-50 text-emerald-700 border border-emerald-100')}>
          <CheckCircle className="w-3.5 h-3.5" />
          已完成
        </span>
      )
    }
    if (runStatus === 'failed') {
      return (
        <span className={cn(base, 'bg-red-50 text-red-700 border border-red-100')}>
          <XCircle className="w-3.5 h-3.5" />
          失败
        </span>
      )
    }
    return (
      <span className={cn(base, 'bg-indigo-50 text-indigo-700 border border-indigo-100')}>
        <Loader2 className="w-3.5 h-3.5 animate-spin" />
        运行中
      </span>
    )
  }, [runStatus])

  return (
    <main className="flex-1 flex flex-col overflow-hidden relative">
        <div className="absolute top-0 left-0 right-0 h-64 bg-gradient-to-b from-indigo-50/50 dark:from-indigo-900/10 to-transparent pointer-events-none" />

        <header className="px-8 py-6 flex-shrink-0 z-10">
          <div className="flex items-center justify-between mb-6">
            <div className="flex items-center gap-4">
              <div className="w-12 h-12 bg-white dark:bg-slate-900 rounded-2xl flex items-center justify-center shadow-sm border border-slate-100 dark:border-slate-800">
                <BarChart3 className="w-6 h-6 text-indigo-600 dark:text-indigo-400" />
              </div>
              <div>
                <h1 className="text-2xl font-bold text-slate-900 dark:text-white tracking-tight">
                  RAGAS 评测
                </h1>
                <p className="text-sm text-slate-500 dark:text-slate-400 mt-1">
                  基于对话记录与引用上下文，评估 RAG 链路质量
                </p>
              </div>
            </div>

            <div className="flex items-center gap-2">
              <Button
                variant="outline"
                className="gap-2 rounded-xl"
                onClick={() => {
                  setIsLoading(true)
                  Promise.all([loadConversations(), loadRuns()]).finally(() => setIsLoading(false))
                }}
              >
                <RefreshCw className={cn('w-4 h-4', isLoading && 'animate-spin')} />
                刷新
              </Button>
              <Button
                className="gap-2 bg-indigo-600 hover:bg-indigo-700 text-white shadow-lg shadow-indigo-200 dark:shadow-indigo-900/20 rounded-xl"
                disabled={isStarting || !selectedConversationId}
                onClick={handleStart}
              >
                {isStarting ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <PlayCircle className="w-4 h-4" />
                )}
                开始评测
              </Button>
            </div>
          </div>

          {/* 配置区 */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
            <div className="bg-white/80 dark:bg-slate-900/80 backdrop-blur-sm border border-slate-200 dark:border-slate-800 rounded-2xl p-4">
              <div className="text-sm font-semibold text-slate-800 dark:text-slate-200 mb-3">
                选择对话
              </div>
              <select
                value={selectedConversationId}
                onChange={(e) => setSelectedConversationId(e.target.value)}
                className="w-full px-3 py-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-950 text-sm"
              >
                {conversations.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.title || c.id}
                  </option>
                ))}
              </select>
              <div className="mt-3 text-xs text-slate-500 dark:text-slate-400">
                评测会从该对话中抽取「用户→助手」轮次，并通过引用 chunk 还原检索上下文。
              </div>
            </div>

            <div className="bg-white/80 dark:bg-slate-900/80 backdrop-blur-sm border border-slate-200 dark:border-slate-800 rounded-2xl p-4">
              <div className="text-sm font-semibold text-slate-800 dark:text-slate-200 mb-3">
                指标选择
              </div>
              <div className="space-y-2">
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
              <div className="mt-3 text-xs text-slate-500 dark:text-slate-400">
                指标越多，耗时与 token/cost 越高。
              </div>
            </div>

            <div className="bg-white/80 dark:bg-slate-900/80 backdrop-blur-sm border border-slate-200 dark:border-slate-800 rounded-2xl p-4">
              <div className="text-sm font-semibold text-slate-800 dark:text-slate-200 mb-3">
                评测范围
              </div>
              <div className="grid grid-cols-2 gap-3">
                <label className="text-sm text-slate-600 dark:text-slate-300">
                  最近轮次
                  <input
                    type="number"
                    min={1}
                    max={200}
                    value={maxTurns}
                    onChange={(e) => setMaxTurns(Number(e.target.value))}
                    className="mt-1 w-full px-3 py-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-950 text-sm"
                  />
                </label>
                <label className="flex items-center gap-2 text-sm text-slate-700 dark:text-slate-300 mt-6">
                  <input
                    type="checkbox"
                    className="h-4 w-4 rounded border-slate-300"
                    checked={skipEmptyContexts}
                    onChange={(e) => setSkipEmptyContexts(e.target.checked)}
                  />
                  跳过无引用轮次
                </label>
              </div>
            </div>
          </div>
        </header>

        {/* 内容区 */}
        <div className="flex-1 overflow-y-auto px-8 pb-8">
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            {/* 运行列表 */}
            <div className="lg:col-span-1">
              <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-2xl overflow-hidden">
                <div className="p-4 border-b border-slate-100 dark:border-slate-800 flex items-center justify-between">
                  <div className="text-sm font-semibold text-slate-800 dark:text-slate-200">
                    运行记录
                  </div>
                  <div className="text-xs text-slate-500">
                    {runs.length} 条
                  </div>
                </div>
                <div className="max-h-[520px] overflow-y-auto">
                  {runs.length === 0 ? (
                    <div className="p-6 text-sm text-slate-500">暂无评测记录</div>
                  ) : (
                    runs.map((r: any) => (
                      <button
                        key={r.id}
                        onClick={() => setSelectedRunId(r.id)}
                        className={cn(
                          'w-full text-left p-4 border-b border-slate-100 dark:border-slate-800 hover:bg-slate-50 dark:hover:bg-slate-800/40 transition',
                          selectedRunId === r.id && 'bg-indigo-50/60 dark:bg-indigo-900/10'
                        )}
                      >
                        <div className="flex items-center justify-between gap-2">
                          <div className="text-sm font-medium text-slate-800 dark:text-slate-200 truncate">
                            {r.conversation_id ? `对话 ${String(r.conversation_id).slice(0, 8)}…` : r.id}
                          </div>
                          <span
                            className={cn(
                              'text-[11px] px-2 py-0.5 rounded-full border',
                              r.status === 'completed'
                                ? 'bg-emerald-50 text-emerald-700 border-emerald-100'
                                : r.status === 'failed'
                                ? 'bg-red-50 text-red-700 border-red-100'
                                : 'bg-indigo-50 text-indigo-700 border-indigo-100'
                            )}
                          >
                            {r.status}
                          </span>
                        </div>
                        <div className="mt-2 text-xs text-slate-500 dark:text-slate-400">
                          {new Date(r.created_at).toLocaleString()}
                        </div>
                      </button>
                    ))
                  )}
                </div>
              </div>
            </div>

            {/* 运行详情 */}
            <div className="lg:col-span-2 space-y-4">
              <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-2xl p-4">
                <div className="flex items-center justify-between">
                  <div className="text-sm font-semibold text-slate-800 dark:text-slate-200">
                    运行详情
                  </div>
                  {statusBadge}
                </div>

                {runDetail?.run?.error_message && (
                  <div className="mt-3 text-sm text-red-600">
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
                    {selectedRunId ? '暂无分数（可能仍在运行中）' : '请选择一个评测运行'}
                  </div>
                )}
              </div>

              {/* 明细表 */}
              <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-2xl overflow-hidden">
                <div className="p-4 border-b border-slate-100 dark:border-slate-800 flex items-center justify-between">
                  <div className="text-sm font-semibold text-slate-800 dark:text-slate-200">
                    逐轮明细
                  </div>
                  <div className="text-xs text-slate-500">
                    {runDetail?.items?.length || 0} 条
                  </div>
                </div>

                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead className="bg-slate-50 dark:bg-slate-800/40 text-slate-600 dark:text-slate-300">
                      <tr>
                        <th className="text-left px-4 py-3 w-16">#</th>
                        <th className="text-left px-4 py-3">问题</th>
                        <th className="text-left px-4 py-3">回答</th>
                        {(runDetail?.run?.metrics || []).map((k: string) => (
                          <th key={k} className="text-left px-4 py-3 w-40">
                            {k}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                      {(runDetail?.items || []).map((it: any) => (
                        <tr key={it.id} className="hover:bg-slate-50 dark:hover:bg-slate-800/30">
                          <td className="px-4 py-3 text-slate-500">{it.turn_index}</td>
                          <td className="px-4 py-3 align-top">
                            <div className="line-clamp-3 text-slate-800 dark:text-slate-200">
                              {it.user_input}
                            </div>
                          </td>
                          <td className="px-4 py-3 align-top">
                            <div className="line-clamp-3 text-slate-700 dark:text-slate-300">
                              {it.response}
                            </div>
                          </td>
                          {(runDetail?.run?.metrics || []).map((k: string) => {
                            const v = it.scores?.[k]
                            const isNum = typeof v === 'number' && !Number.isNaN(v)
                            return (
                              <td key={k} className="px-4 py-3 text-slate-700 dark:text-slate-300">
                                {isNum ? v.toFixed(3) : '-'}
                              </td>
                            )
                          })}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          </div>
        </div>
      </main>
  )
}
