'use client'

/**
 * RAGAS 评测页面 - 支持 Tab 切换
 * Tab 1: 对话评测（基于对话历史）
 * Tab 2: 回归测试（基于测试用例）
 * Tab 3: Queryset Health（检索基准集健康度）
 */

import { Suspense, useCallback, useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'next/navigation'
import { AppFrame } from '@/components/app-frame'
import { PageLoading } from '@/components/ui/page-loading'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Panel } from '@/components/ui/panel'
import { PageScaffold } from '@/components/ui/page-scaffold'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { StatusBadge } from '@/components/ui/status-badge'
import { StatCard, StatsGrid } from '@/components/ui/stats-card'
import { evaluationApi, chatApi, type RagasRun, type RagasRunDetail } from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'
import type { Conversation } from '@/types'
import {
  BarChart3,
  Loader2,
  PlayCircle,
  RefreshCw,
  MessageSquare,
  TestTube2,
} from 'lucide-react'
import { toast } from 'sonner'
import { cn } from '@/lib/utils'
import { RegressionTestTab } from '@/components/evaluation/regression-tab'
import { QuerysetHealthTab } from '@/components/evaluation/queryset-health-tab'

type TabType = 'conversation' | 'regression' | 'queryset_health'

const METRIC_OPTIONS = [
    { key: 'faithfulness', label: 'Faithfulness（忠实度）' },
    { key: 'response_relevancy', label: 'Response Relevancy（相关性）' },
    { key: 'context_precision', label: 'Context Precision（无参考）' },
]

type MetricColor = 'green' | 'teal' | 'orange' | 'blue' | 'rose' | 'indigo' | 'cyan'

function metricColor(key: string): MetricColor {
  const k = key.toLowerCase()
  if (k.includes('faithfulness') || k.includes('faithful')) return 'green'
  if (k.includes('precision')) return 'teal'
  if (k.includes('recall')) return 'orange'
  if (k.includes('relevancy') || k.includes('relevance')) return 'blue'
  if (k.includes('harmfulness') || k.includes('harm')) return 'rose'
  if (k.includes('answer_correctness') || k.includes('correctness')) return 'indigo'
  return 'cyan'
}

export default function EvaluationsPage() {
  return (
    <AppFrame>
      <Suspense fallback={<EvaluationsLoading />}>
        <EvaluationsPageContent />
      </Suspense>
    </AppFrame>
  )
}

function EvaluationsLoading() {
  return (
    <PageLoading message="正在加载评测数据..." srMessage="Loading evaluations" />
  )
}

function EvaluationsPageContent() {
  const searchParams = useSearchParams()
  const [activeTab, setActiveTab] = useState<TabType>('conversation')
  const isActiveTab = (tab: TabType) => activeTab === tab
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [selectedConversationId, setSelectedConversationId] = useState<string>('')

  const [runs, setRuns] = useState<RagasRun[]>([])
  const [selectedRunId, setSelectedRunId] = useState<string>('')
  const [runDetail, setRunDetail] = useState<RagasRunDetail | null>(null)

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

  // Support deep-linking: /evaluations?tab=regression|conversation
  useEffect(() => {
    const tab = (searchParams.get('tab') || '').trim().toLowerCase()
    if (tab === 'regression' || tab === 'conversation' || tab === 'queryset_health') {
      setActiveTab(tab as TabType)
    }
  }, [searchParams])

  const loadConversations = useCallback(async () => {
    try {
      const res = await chatApi.listConversations({ limit: 100 })
      setConversations(res.items || [])
      setSelectedConversationId((prev) => prev || res.items?.[0]?.id || '')
    } catch (e) {
      console.error('Failed to load conversations', e)
    }
  }, [])

  const loadRuns = useCallback(async (conversationId?: string) => {
    try {
      const res = await evaluationApi.listRagasRuns({
        limit: 50,
        conversation_id: conversationId || undefined,
      })
      setRuns(res.items || [])
      setSelectedRunId((prev) => prev || res.items?.[0]?.id || '')
    } catch (e) {
      console.error('Failed to load runs', e)
    }
  }, [])

  // Initial data
  useEffect(() => {
    setIsLoading(true)
    Promise.all([loadConversations(), loadRuns()]).finally(() => setIsLoading(false))
  }, [loadConversations, loadRuns])

  // When switching conversation, focus run list on that conversation
  useEffect(() => {
    if (!selectedConversationId) return
    setSelectedRunId('')
    setRunDetail(null)
    loadRuns(selectedConversationId)
  }, [loadRuns, selectedConversationId])

  // Poll run detail
  useEffect(() => {
    if (!selectedRunId) {
      setRunDetail(null)
      return
    }

    let cancelled = false
    let timer: ReturnType<typeof setTimeout> | null = null

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
      toast.error(formatApiError(e, '启动评测失败'))
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
    const status = (() => {
    if (runStatus === 'completed') {
        return 'completed';
    }
    else if (runStatus === 'failed') {
            return 'failed';
        }
        else {
            return 'processing';
        }
})()
    const label = (() => {
    if (runStatus === 'completed') {
        return '已完成';
    }
    else if (runStatus === 'failed') {
            return '失败';
        }
        else {
            return '运行中';
        }
})()
    return <StatusBadge status={status} label={label} dense />
  }, [runStatus])

  return (
    <div className="flex-1 flex flex-col overflow-hidden relative">
      <PageScaffold
        title="RAGAS 评测"
        description="基于对话记录与引用上下文，评估 RAG 链路质量"
        icon={BarChart3}
        iconColor="text-info"
        size="7xl"
        actions={
          activeTab === 'conversation' ? (
            <div className="flex items-center gap-2">
              <Button
                variant="outline"
                size="sm"
                className="gap-2 rounded-xl"
                onClick={() => {
                  setIsLoading(true)
                  Promise.all([loadConversations(), loadRuns()]).finally(() => setIsLoading(false))
                }}
              >
	                <RefreshCw className={cn('w-4 h-4', isLoading && 'animate-spin motion-reduce:animate-none')} />
	                刷新
	              </Button>
              <Button
                size="sm"
                className="gap-2 rounded-xl"
                disabled={isStarting || !selectedConversationId}
                onClick={handleStart}
              >
                {isStarting ? (
                  <Loader2 className="w-4 h-4 animate-spin motion-reduce:animate-none" />
                ) : (
                  <PlayCircle className="w-4 h-4" />
                )}
                开始评测
              </Button>
            </div>
          ) : null
        }
        toolbar={
          <div className="flex items-center gap-2">
            <Button
              type="button"
              size="sm"
              variant={isActiveTab('conversation') ? 'outline' : 'ghost'}
              onClick={() => setActiveTab('conversation')}
              className={cn(
                'gap-2 rounded-lg',
                isActiveTab('conversation') && 'bg-background/70 text-info'
              )}
            >
              <MessageSquare className="w-4 h-4" />
              对话评测
            </Button>
            <Button
              type="button"
              size="sm"
              variant={isActiveTab('regression') ? 'outline' : 'ghost'}
              onClick={() => setActiveTab('regression')}
              className={cn(
                'gap-2 rounded-lg',
                isActiveTab('regression') && 'bg-background/70 text-info'
              )}
            >
              <TestTube2 className="w-4 h-4" />
              回归测试
            </Button>
            <Button
              type="button"
              size="sm"
              variant={isActiveTab('queryset_health') ? 'outline' : 'ghost'}
              onClick={() => setActiveTab('queryset_health')}
              className={cn(
                'gap-2 rounded-lg',
                isActiveTab('queryset_health') && 'bg-background/70 text-info'
              )}
            >
              <BarChart3 className="w-4 h-4" />
              Queryset Health
            </Button>
          </div>
        }
      >
        {activeTab === 'conversation' ? (
          <div className="space-y-6">
            {/* 配置区 */}
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
              <Panel variant="glass" className="rounded-2xl">
                <div className="text-sm font-semibold text-foreground mb-3">
                  选择对话
                </div>
                <Select value={selectedConversationId} onValueChange={setSelectedConversationId}>
                  <SelectTrigger className="w-full rounded-xl">
                    <SelectValue placeholder="选择对话" />
                  </SelectTrigger>
                  <SelectContent>
                    {conversations.map((c) => (
                      <SelectItem key={c.id} value={c.id}>
                        {c.title || c.id}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <div className="mt-3 text-xs text-muted-foreground">
                  评测会从该对话中抽取「用户→助手」轮次，并通过引用 chunk 还原检索上下文。
                </div>
              </Panel>

              <Panel variant="glass" className="rounded-2xl">
                <div className="text-sm font-semibold text-foreground mb-3">
                  指标选择
                </div>
                <div className="space-y-2">
                  {METRIC_OPTIONS.map((m) => (
                    <label key={m.key} className="flex items-center gap-2 text-sm">
                      <Checkbox
                        checked={metricKeys.includes(m.key)}
                        onCheckedChange={(v) => {
                          setMetricKeys((prev) =>
                            v === true ? [...prev, m.key] : prev.filter((x) => x !== m.key)
                          )
                        }}
                      />
                      <span className="text-foreground">{m.label}</span>
                    </label>
                  ))}
                </div>
                <div className="mt-3 text-xs text-muted-foreground">
                  指标越多，耗时与 token/cost 越高。
                </div>
              </Panel>

              <Panel variant="glass" className="rounded-2xl">
                <div className="text-sm font-semibold text-foreground mb-3">
                  评测范围
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div className="grid gap-1.5">
                    <Label htmlFor="max-turns" className="text-sm text-muted-foreground">
                      最近轮次
                    </Label>
                    <Input
                      id="max-turns"
                      type="number"
                      min={1}
                      max={200}
                      value={maxTurns}
                      onChange={(e) => setMaxTurns(Number(e.target.value))}
                      className="rounded-xl"
                    />
                  </div>
                  <div className="flex items-center gap-2 text-sm mt-7">
                    <Checkbox
                      checked={skipEmptyContexts}
                      onCheckedChange={(v) => setSkipEmptyContexts(v === true)}
                    />
                    <span className="text-foreground">跳过无引用轮次</span>
                  </div>
                </div>
              </Panel>
            </div>
            {/* 内容区 */}
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            {/* 运行列表 */}
            <div className="lg:col-span-1">
              <Panel padding="none" className="rounded-2xl overflow-hidden">
                <div className="p-4 border-b border-border/60 flex items-center justify-between bg-muted/20">
                  <div className="text-sm font-semibold text-foreground">
                    运行记录
                  </div>
                  <div className="text-xs text-muted-foreground">
                    {runs.length} 条
                  </div>
                </div>
                <div className="max-h-[520px] overflow-y-auto overscroll-contain no-scrollbar">
                  {runs.length === 0 ? (
                    <div className="p-6 text-sm text-muted-foreground">暂无评测记录</div>
                  ) : (
                    runs.map((r) => {
                      const runStatus = r?.status
                      const badgeStatus = (() => {
    if (runStatus === 'completed') {
        return 'completed';
    }
    else if (runStatus === 'failed') {
            return 'failed';
        }
        else {
            return 'processing';
        }
})()
                      const badgeLabel = (() => {
    if (runStatus === 'completed') {
        return '已完成';
    }
    else if (runStatus === 'failed') {
            return '失败';
        }
        else {
            return '运行中';
        }
})()
                      return (
                        <button
                          key={r.id}
                          type="button"
                          onClick={() => setSelectedRunId(r.id)}
                          className={cn(
                            'w-full text-left p-4 border-b border-border/60 hover:bg-muted/30 transition-colors focus-ring',
                            selectedRunId === r.id && 'bg-primary/10'
                          )}
                        >
                          <div className="flex items-center justify-between gap-2">
                            <div className="text-sm font-medium text-foreground truncate">
                              {r.conversation_id ? `对话 ${String(r.conversation_id).slice(0, 8)}…` : r.id}
                            </div>
                            <StatusBadge status={badgeStatus} label={badgeLabel} dense />
                          </div>
                          <div className="mt-2 text-xs text-muted-foreground">
                            {new Date(r.created_at).toLocaleString()}
                          </div>
                        </button>
                      )
                    })
                  )}
                </div>
              </Panel>
            </div>

            {/* 运行详情 */}
            <div className="lg:col-span-2 space-y-4">
              <Panel className="rounded-2xl">
                <div className="flex items-center justify-between">
                  <div className="text-sm font-semibold text-foreground">
                    运行详情
                  </div>
                  {statusBadge}
                </div>

                {runDetail?.run?.error_message ? (
                  <Alert variant="destructive" className="mt-3">
                    <AlertTitle>评测失败</AlertTitle>
                    <AlertDescription className="text-foreground/80">
                      {runDetail.run.error_message}
                    </AlertDescription>
                  </Alert>
                ) : null}

                {displayMetrics.length > 0 ? (
                  <div className="mt-4">
                    <StatsGrid className="lg:grid-cols-3">
                      {displayMetrics.map((m) => (
                        <StatCard
                          key={m.key}
                          icon={BarChart3}
                          label={m.key}
                          value={m.value.toFixed(3)}
                          color={metricColor(m.key)}
                        />
                      ))}
                    </StatsGrid>
                    <div className="mt-3 text-xs text-muted-foreground">
                      items: {summary.items ?? '-'} · tokens: {summary.total_tokens ?? '-'} · cost: {summary.total_cost ?? '-'}
                    </div>
                  </div>
                ) : (
                  <div className="mt-4 text-sm text-muted-foreground">
                    {selectedRunId ? '暂无分数（可能仍在运行中）' : '请选择一个评测运行'}
                  </div>
                )}
              </Panel>

              {/* 明细表 */}
              <Panel padding="none" className="rounded-2xl overflow-hidden">
                <div className="p-4 border-b border-border/60 flex items-center justify-between bg-muted/20">
                  <div className="text-sm font-semibold text-foreground">
                    逐轮明细
                  </div>
                  <div className="text-xs text-muted-foreground">
                    {runDetail?.items?.length || 0} 条
                  </div>
                </div>

                <div className="overflow-x-auto">
                  <table aria-label="评测结果列表" className="w-full text-sm">
                    <thead className="bg-muted/30 text-muted-foreground">
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
                    <tbody className="divide-y divide-border/60">
                      {(runDetail?.items || []).map((it) => (
                        <tr key={it.id} className="hover:bg-muted/20">
                          <td className="px-4 py-3 text-muted-foreground">{it.turn_index}</td>
                          <td className="px-4 py-3 align-top">
                            <div className="line-clamp-3 text-foreground">
                              {it.user_input}
                            </div>
                          </td>
                          <td className="px-4 py-3 align-top">
                            <div className="line-clamp-3 text-foreground/90">
                              {it.response}
                            </div>
                          </td>
                          {(runDetail?.run?.metrics || []).map((k: string) => {
                            const v = it.scores?.[k]
                            const isNum = typeof v === 'number' && !Number.isNaN(v)
                            return (
                              <td key={k} className="px-4 py-3 text-foreground/90">
                                {isNum ? v.toFixed(3) : '-'}
                              </td>
                            )
                          })}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </Panel>
            </div>
          </div>
          </div>
        ) : activeTab === 'regression' ? (
          <RegressionTestTab embedded />
        ) : (
          <QuerysetHealthTab embedded />
        )}
      </PageScaffold>
    </div>
  )
}
