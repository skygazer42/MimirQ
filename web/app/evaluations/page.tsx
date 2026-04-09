'use client'

/**
 * RAGAS 评测页面 - 支持 Tab 切换
 * Tab 1: 对话评测（基于对话历史）
 * Tab 2: 回归测试（基于测试用例）
 * Tab 3: Queryset Health（检索基准集健康度）
 */

import { Suspense, useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import { useSearchParams } from 'next/navigation'
import { AppFrame } from '@/components/app-frame'
import { PageLoading } from '@/components/ui/page-loading'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { AnalysisPageShell } from '@/components/ui/analysis-page-shell'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { StatusBadge } from '@/components/ui/status-badge'
import { evaluationApi, chatApi, type RagasRun, type RagasRunDetail } from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'
import type { Conversation } from '@/types'
import {
  BarChart3,
  ChevronRight,
  Clock3,
  Database,
  Filter,
  Loader2,
  ListChecks,
  PlayCircle,
  RefreshCw,
  SlidersHorizontal,
  Sparkles,
  MessageSquare,
  TestTube2,
} from 'lucide-react'
import { toast } from 'sonner'
import { cn } from '@/lib/utils'
import { RegressionTestTab } from '@/components/evaluation/regression-tab'
import { QuerysetHealthTab } from '@/components/evaluation/queryset-health-tab'
import { RagasMetricSelector, ragasMetricLabel } from '@/components/evaluation/ragas-metric-selector'

type TabType = 'conversation' | 'regression' | 'queryset_health'

const TAB_META: Array<{
  id: TabType
  label: string
  title: string
  description: string
  icon: typeof MessageSquare
}> = [
  {
    id: 'conversation',
    label: '对话评测',
    title: '实时会话评分',
    description: '基于已有对话和引用上下文，快速拉起一轮 RAGAS 评测。',
    icon: MessageSquare,
  },
  {
    id: 'regression',
    label: '回归测试',
    title: '批量样例回归',
    description: '面向固定测试集持续回归，观察版本变更前后的质量波动。',
    icon: TestTube2,
  },
  {
    id: 'queryset_health',
    label: '检索集健康度',
    title: '检索集健康度',
    description: '查看趋势、差异与退化标记，定位检索集层面的异常波动。',
    icon: BarChart3,
  },
]

function metricLabel(key: string): string {
  return ragasMetricLabel(key)
}

function formatCurrency(value: unknown): string {
  const n = Number(value)
  if (!Number.isFinite(n)) return '-'
  if (n === 0) return '$0'
  if (Math.abs(n) < 0.01) return `$${n.toFixed(4)}`
  return `$${n.toFixed(2)}`
}

function formatCompactCount(value: unknown): string {
  const n = Number(value)
  if (!Number.isFinite(n)) return '-'
  return Intl.NumberFormat('zh-CN', { notation: 'compact', maximumFractionDigits: 1 }).format(n)
}

function EvaluationModePill({
  active,
  icon: Icon,
  label,
  title,
  onClick,
}: Readonly<{
  active: boolean
  icon: typeof MessageSquare
  label: string
  title: string
  onClick: () => void
}>) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={title}
      className={cn(
        'inline-flex min-h-[34px] items-center gap-2 rounded-md border px-2.5 text-[12px] font-medium transition-all duration-200',
        active
          ? 'border-primary/25 bg-primary/[0.12] text-foreground shadow-[0_1px_0_rgba(2,132,199,0.14)]'
          : 'border-transparent bg-card text-muted-foreground hover:border-slate-300 hover:bg-slate-50 hover:text-foreground'
      )}
    >
      <Icon className="h-3 w-3" aria-hidden="true" />
      <span>{label}</span>
    </button>
  )
}

function EvaluationConfigSection({
  title,
  description,
  children,
  className,
  icon: Icon,
}: Readonly<{
  title: string
  description?: string
  children: ReactNode
  className?: string
  icon?: typeof MessageSquare
}>) {
  return (
    <section className={cn('border-b border-slate-200/80 px-3.5 py-3.5 last:border-b-0', className)}>
      <div className="flex items-start gap-2.5">
        {Icon ? (
          <span className="mt-0.5 inline-flex h-5 w-5 items-center justify-center rounded-md border border-sky-200/60 bg-sky-100/70 text-sky-700">
            <Icon className="h-3.5 w-3.5" aria-hidden="true" />
          </span>
        ) : null}
        <div className="min-w-0">
          <div className="text-[11px] font-medium uppercase tracking-[0.12em] text-muted-foreground">{title}</div>
          {description ? <p className="mt-1 text-[11px] leading-4 text-muted-foreground">{description}</p> : null}
        </div>
      </div>
      <div className="mt-2.5">{children}</div>
    </section>
  )
}

function EvaluationInlineStat({
  label,
  value,
}: Readonly<{
  label: string
  value: ReactNode
}>) {
  return (
    <div className="inline-flex items-center gap-1.5 rounded-md border border-slate-200/80 bg-card/90 px-2 py-0.5 shadow-[inset_0_1px_0_rgba(255,255,255,0.9)]">
      <span className="text-[9px] font-medium uppercase tracking-[0.14em] text-muted-foreground">{label}</span>
      <span className="font-mono text-[11px] font-semibold tabular-nums text-foreground">{value}</span>
    </div>
  )
}

function EvaluationEmptyState({
  title,
  description,
}: Readonly<{
  title: string
  description: string
}>) {
  return (
    <div className="rounded-lg border border-dashed border-slate-200/80 bg-background px-6 py-12 text-center">
      <div className="text-sm font-medium text-foreground">{title}</div>
      <p className="mx-auto mt-2 max-w-xl text-[12px] leading-6 text-muted-foreground">{description}</p>
    </div>
  )
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
  const [isSetupPanelCollapsed, setIsSetupPanelCollapsed] = useState(false)
  const [isTimelinePanelCollapsed, setIsTimelinePanelCollapsed] = useState(false)

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

  const runErrorMessage = String(runDetail?.run?.error_message || '').trim()

  const runStatus = runDetail?.run?.status
  const statusBadge = useMemo(() => {
    if (!runStatus) return null

    const status = runStatus === 'completed' ? 'completed' : runStatus === 'failed' ? 'failed' : 'processing'
    const label = runStatus === 'completed' ? '已完成' : runStatus === 'failed' ? '失败' : '运行中'
    const badge = <StatusBadge status={status} label={label} dense />

    if (runStatus === 'failed' && runErrorMessage) {
      return (
        <span className="inline-flex cursor-help" title={runErrorMessage} aria-label="失败原因，悬停查看">
          {badge}
        </span>
      )
    }

    return badge
  }, [runErrorMessage, runStatus])

  const activeTabMeta = TAB_META.find((item) => item.id === activeTab) || TAB_META[0]
  const ActiveTabIcon = activeTabMeta.icon
  const selectedConversation = conversations.find((conversation) => conversation.id === selectedConversationId) || null
  const conversationLayoutColumns =
    isSetupPanelCollapsed && isTimelinePanelCollapsed
      ? 'xl:grid-cols-[0px_0px_minmax(0,1fr)]'
      : isSetupPanelCollapsed
        ? 'xl:grid-cols-[0px_272px_minmax(0,1fr)]'
        : isTimelinePanelCollapsed
          ? 'xl:grid-cols-[304px_0px_minmax(0,1fr)]'
          : 'xl:grid-cols-[304px_272px_minmax(0,1fr)]'
  const runStatusCounts = useMemo(() => {
    return runs.reduce(
      (acc, run) => {
        if (run.status === 'completed') acc.completed += 1
        else if (run.status === 'failed') acc.failed += 1
        else acc.running += 1
        return acc
      },
      { completed: 0, failed: 0, running: 0 }
    )
  }, [runs])

  return (
    <div className="relative flex flex-1 flex-col overflow-hidden">
      <AnalysisPageShell
        title="评测中心"
        description="把实时会话评测、回归测试与检索集健康度放到同一个工作台里，减少来回切页。"
        icon={BarChart3}
        iconColor="text-primary"
        badge="评测"
        size="full"
        showHeader={false}
        bodyGutter="none"
        bodyClassName="!pb-0"
        bodyContainerClassName="max-w-none"
      >
        <div className="overflow-hidden rounded-2xl border border-slate-200/80 bg-[linear-gradient(180deg,#f8fafc_0%,#ffffff_22%)] shadow-[0_1px_0_rgba(15,23,42,0.04)]">
          <div className="flex flex-col gap-2.5 border-b border-slate-200/80 bg-muted/35 px-4 py-3 lg:flex-row lg:items-end lg:justify-between">
            <div className="min-w-0">
              <div className="text-[11px] font-medium uppercase tracking-[0.12em] text-muted-foreground">评测中心 · 统一工作台</div>
              <div className="mt-1 flex items-center gap-2 text-sm font-semibold tracking-[-0.01em] text-foreground"><span className="inline-flex h-6 w-6 items-center justify-center rounded-md border border-sky-200/70 bg-card/85 text-sky-700"><ActiveTabIcon className="h-3.5 w-3.5" aria-hidden="true" /></span>{activeTabMeta.title}</div>
              <p className="mt-1 text-[12px] leading-4 text-muted-foreground">选择评测模式后，在同一工作区完成参数配置、运行触发与结果排查。</p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <EvaluationInlineStat label="模式" value={activeTabMeta.label} />
              <EvaluationInlineStat label="会话" value={conversations.length} />
              <EvaluationInlineStat label="运行" value={runs.length} />
              <EvaluationInlineStat label="完成" value={runStatusCounts.completed} />
              <EvaluationInlineStat label="进行中" value={runStatusCounts.running} />
              {activeTab === 'conversation' ? <EvaluationInlineStat label="指标" value={metricKeys.length} /> : null}
            </div>
          </div>

          <div className="border-t border-slate-200/80 px-3 py-2.5">
            <div className="inline-flex w-full flex-wrap items-center gap-1 rounded-lg border border-slate-200 bg-card/85 p-1 shadow-[inset_0_1px_0_rgba(255,255,255,0.9)]">
              {TAB_META.map((tab) => (
                <EvaluationModePill
                  key={tab.id}
                  active={isActiveTab(tab.id)}
                  icon={tab.icon}
                  label={tab.label}
                  title={tab.title}
                  onClick={() => setActiveTab(tab.id)}
                />
              ))}
            </div>
            <p className="mt-1.5 text-[12px] leading-5 text-muted-foreground">{activeTabMeta.description}</p>
          </div>

          {activeTab === 'conversation' ? (
            <div className="border-t border-slate-200/80">
            <div className={cn('grid min-h-[660px]', conversationLayoutColumns)}>
              <aside className="flex min-h-0 flex-col border-b border-slate-200/80 bg-slate-50/60 xl:border-b-0 xl:border-r">
                {isSetupPanelCollapsed ? (
                  <div className="group relative flex h-full items-center justify-center px-1 py-4">
                    <button
                      type="button"
                      className="focus-ring relative h-full w-2.5 rounded-full transition-colors hover:bg-slate-200/70"
                      onClick={() => setIsSetupPanelCollapsed(false)}
                      title="展开参数侧栏"
                      aria-label="展开参数侧栏"
                    >
                      <span className="absolute inset-y-0 left-1/2 w-px -translate-x-1/2 bg-border/70" aria-hidden="true" />
                      <span className="pointer-events-none absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 rounded-full border border-slate-200/80 bg-card/95 p-1 opacity-0 shadow-sm transition-opacity group-hover:opacity-100 group-focus-within:opacity-100">
                        <ChevronRight className="h-3 w-3 text-muted-foreground" aria-hidden="true" />
                      </span>
                    </button>
                  </div>
                ) : (
                  <>
                    <div className="shrink-0 border-b border-slate-200/80 bg-primary/[0.12] px-3 py-2.5">
                      <div className="flex items-start justify-between gap-3">
                        <div>
                          <div className="inline-flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-[0.12em] text-sky-700"><SlidersHorizontal className="h-3.5 w-3.5" aria-hidden="true" />参数设置</div>
                          <div className="mt-1 text-sm font-semibold text-foreground">对话评测参数</div>
                          <p className="mt-1 text-[11px] leading-4 text-muted-foreground">先选会话，再设指标与过滤范围，最后一键触发评测。</p>
                        </div>
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          className="h-7 rounded-md px-2.5 text-[11px] text-muted-foreground hover:bg-slate-100 hover:text-foreground"
                          onClick={() => setIsSetupPanelCollapsed(true)}
                        >
                          收起侧栏
                        </Button>
                      </div>
                    </div>

                    <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain">
                      <EvaluationConfigSection
                        icon={Database}
                        title="对话来源"
                        description="从已有会话里选一条对话，评测会按用户-助手轮次重建上下文。"
                      >
                        <Select value={selectedConversationId} onValueChange={setSelectedConversationId}>
                          <SelectTrigger className="h-9 rounded-lg border-slate-200/80 bg-card/95 text-xs">
                            <SelectValue placeholder="选择对话" />
                          </SelectTrigger>
                          <SelectContent>
                            {conversations.map((conversation) => (
                              <SelectItem key={conversation.id} value={conversation.id}>
                                {conversation.title || conversation.id}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                        <div className="mt-3 flex flex-wrap items-center gap-2">
                          <EvaluationInlineStat label="已选" value={selectedConversation ? '1' : '0'} />
                          <EvaluationInlineStat label="总数" value={conversations.length} />
                        </div>
                      </EvaluationConfigSection>

                      <EvaluationConfigSection
                        icon={Sparkles}
                        title="会话评分维度"
                        description="仅作用于对话评测；指标越多，耗时与 token 成本越高。默认保留最核心两项。"
                      >
                        <RagasMetricSelector
                          metricKeys={metricKeys}
                          onMetricKeysChange={setMetricKeys}
                          className="space-y-2"
                          itemClassName="rounded-lg border border-slate-200/80 bg-card px-2.5 py-1.5"
                        />
                      </EvaluationConfigSection>

                      <EvaluationConfigSection
                        icon={Filter}
                        title="范围与过滤"
                        description="控制抽取最近多少轮，以及是否过滤掉无引用上下文的轮次。"
                        className="border-b-0"
                      >
                        <div className="grid gap-3">
                          <div className="space-y-1.5">
                            <Label htmlFor="max-turns" className="text-[11px] uppercase tracking-[0.12em] text-muted-foreground">
                              最近轮次
                            </Label>
                            <Input
                              id="max-turns"
                              type="number"
                              min={1}
                              max={200}
                              value={maxTurns}
                              onChange={(e) => setMaxTurns(Number(e.target.value))}
                              className="h-9 rounded-lg border-slate-200/80 bg-card/95 text-xs"
                            />
                          </div>

                          <label className="flex items-start gap-2.5 rounded-lg border border-slate-200/80 bg-card px-2.5 py-1.5">
                            <Checkbox checked={skipEmptyContexts} onCheckedChange={(value) => setSkipEmptyContexts(value === true)} />
                            <span className="space-y-0.5">
                              <span className="block text-[12px] font-medium text-foreground">跳过无引用轮次</span>
                              <span className="block text-[11px] leading-4 text-muted-foreground">减少空样本干扰，让结果更接近真实 RAG 场景。</span>
                            </span>
                          </label>
                        </div>
                      </EvaluationConfigSection>
                    </div>

                    <div className="shrink-0 border-t border-slate-200/80 bg-card px-3 py-2.5">
                      <div className="flex flex-wrap items-center gap-2">
                        <EvaluationInlineStat label="指标" value={metricKeys.length} />
                        <EvaluationInlineStat label="轮次" value={maxTurns} />
                        <EvaluationInlineStat label="过滤" value={skipEmptyContexts ? '开' : '关'} />
                      </div>

                      <Button
                        className="mt-2.5 h-9 w-full rounded-lg"
                        disabled={isStarting || !selectedConversationId}
                        onClick={handleStart}
                      >
                        {isStarting ? (
                          <Loader2 className="mr-2 h-4 w-4 animate-spin motion-reduce:animate-none" />
                        ) : (
                          <PlayCircle className="mr-2 h-4 w-4" />
                        )}
                        开始评测
                      </Button>

                      <Button
                        variant="outline"
                        className="mt-2 h-8 w-full rounded-lg border-slate-200/80 bg-card"
                        onClick={() => {
                          setIsLoading(true)
                          Promise.all([loadConversations(), loadRuns()]).finally(() => setIsLoading(false))
                        }}
                      >
                        <RefreshCw className={cn('mr-2 h-4 w-4', isLoading && 'animate-spin motion-reduce:animate-none')} />
                        刷新会话与运行
                      </Button>
                    </div>
                  </>
                )}
              </aside>

              <section className="flex min-h-0 flex-col border-b border-slate-200/80 bg-card xl:border-b-0 xl:border-r">
                {isTimelinePanelCollapsed ? (
                  <div className="group relative flex h-full items-center justify-center px-1 py-4">
                    <button
                      type="button"
                      className="focus-ring relative h-full w-2.5 rounded-full transition-colors hover:bg-slate-200/70"
                      onClick={() => setIsTimelinePanelCollapsed(false)}
                      title="展开运行记录"
                      aria-label="展开运行记录"
                    >
                      <span className="absolute inset-y-0 left-1/2 w-px -translate-x-1/2 bg-border/70" aria-hidden="true" />
                      <span className="pointer-events-none absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 rounded-full border border-slate-200/80 bg-card/95 p-1 opacity-0 shadow-sm transition-opacity group-hover:opacity-100 group-focus-within:opacity-100">
                        <ChevronRight className="h-3 w-3 text-muted-foreground" aria-hidden="true" />
                      </span>
                    </button>
                  </div>
                ) : (
                  <>
                    <div className="shrink-0 border-b border-slate-200/80 bg-primary/[0.10] px-2.5 py-2">
                      <div className="flex items-start justify-between gap-2">
                        <div>
                          <div className="inline-flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-[0.12em] text-sky-700"><Clock3 className="h-3.5 w-3.5" aria-hidden="true" />运行时间线</div>
                          <div className="mt-1 text-sm font-semibold text-foreground">运行记录</div>
                        </div>
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          className="h-7 rounded-md px-2.5 text-[11px] text-muted-foreground hover:bg-slate-100 hover:text-foreground"
                          onClick={() => setIsTimelinePanelCollapsed(true)}
                        >
                          收起侧栏
                        </Button>
                      </div>
                      <div className="mt-2 flex flex-wrap items-center gap-2">
                        <EvaluationInlineStat label="全部" value={runs.length} />
                        <EvaluationInlineStat label="完成" value={runStatusCounts.completed} />
                        <EvaluationInlineStat label="进行中" value={runStatusCounts.running} />
                        <EvaluationInlineStat label="失败" value={runStatusCounts.failed} />
                      </div>
                    </div>

                    <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain">
                      {runs.length === 0 ? (
                        <div className="p-4 text-sm text-muted-foreground">暂无评测记录</div>
                      ) : (
                        runs.map((run) => {
                          const currentStatus = run?.status
                          const badgeStatus =
                            currentStatus === 'completed' ? 'completed' : currentStatus === 'failed' ? 'failed' : 'processing'
                          const badgeLabel =
                            currentStatus === 'completed' ? '已完成' : currentStatus === 'failed' ? '失败' : '运行中'
                          return (
                            <button
                              key={run.id}
                              type="button"
                              onClick={() => setSelectedRunId(run.id)}
                              className={cn(
                                'w-full border-b border-slate-200/80 px-2.5 py-2 text-left transition-all duration-200 hover:bg-slate-50 focus-ring',
                                selectedRunId === run.id && 'bg-sky-50/85 ring-1 ring-inset ring-sky-200/70'
                              )}
                            >
                              <div className="flex items-center justify-between gap-2">
                                <div className="flex min-w-0 items-center gap-2"><span className={cn('h-1.5 w-1.5 shrink-0 rounded-full', currentStatus === 'completed' ? 'bg-emerald-500' : currentStatus === 'failed' ? 'bg-rose-500' : 'bg-amber-500')} aria-hidden="true" /><div className="truncate text-[13px] font-medium text-foreground">
                                  {run.conversation_id ? '对话 ' + String(run.conversation_id).slice(0, 8) + '…' : run.id}
                                </div></div>
                                <StatusBadge status={badgeStatus} label={badgeLabel} dense />
                              </div>
                              <div className="mt-1.5 flex items-center gap-2 text-[11px] text-muted-foreground">
                                <Clock3 className="h-3.5 w-3.5" aria-hidden="true" />
                                <span>{new Date(run.created_at).toLocaleString('zh-CN')}</span>
                              </div>
                            </button>
                          )
                        })
                      )}
                    </div>
                  </>
                )}
              </section>

              <section className="flex min-h-0 flex-col bg-card">
                <div className="shrink-0 border-b border-slate-200/80">
                  <div className="grid gap-px bg-border/70 sm:grid-cols-4">
                    <div className="bg-primary/[0.08] px-2.5 py-2">
                      <div className="inline-flex items-center gap-1.5 text-[10px] uppercase tracking-[0.12em] text-sky-700"><MessageSquare className="h-3.5 w-3.5" aria-hidden="true" />当前对话</div>
                      <div className="mt-1 truncate text-[13px] font-semibold text-foreground">
                        {selectedConversation?.title || (selectedConversationId ? '对话 ' + selectedConversationId.slice(0, 8) + '…' : '未选择')}
                      </div>
                    </div>
                    <div className="bg-muted/35 px-2.5 py-2">
                      <div className="inline-flex items-center gap-1.5 text-[10px] uppercase tracking-[0.12em] text-slate-700"><ListChecks className="h-3.5 w-3.5" aria-hidden="true" />样本数</div>
                      <div className="mt-1 text-base font-semibold tabular-nums text-foreground">{formatCompactCount(summary.items)}</div>
                    </div>
                    <div className="bg-primary/[0.08] px-2.5 py-2">
                      <div className="inline-flex items-center gap-1.5 text-[10px] uppercase tracking-[0.12em] text-sky-700"><BarChart3 className="h-3.5 w-3.5" aria-hidden="true" />令牌开销</div>
                      <div className="mt-1 text-base font-semibold tabular-nums text-foreground">{formatCompactCount(summary.total_tokens)}</div>
                    </div>
                    <div className="bg-muted/35 px-2.5 py-2">
                      <div className="inline-flex items-center gap-1.5 text-[10px] uppercase tracking-[0.12em] text-slate-700"><Sparkles className="h-3.5 w-3.5" aria-hidden="true" />LLM 成本</div>
                      <div className="mt-1 text-base font-semibold tabular-nums text-foreground">{formatCurrency(summary.total_cost)}</div>
                    </div>
                  </div>
                </div>

                <div className="shrink-0 border-b border-slate-200/80 bg-muted/25 px-3 py-2.5">
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <div className="inline-flex items-center gap-1.5 text-[11px] uppercase tracking-[0.12em] text-sky-700"><Sparkles className="h-3.5 w-3.5" aria-hidden="true" />运行摘要</div>
                      <div className="mt-1 text-sm font-semibold text-foreground">运行详情</div>
                    </div>
                    <div className="flex items-center gap-2">
                      {statusBadge}
                    </div>
                  </div>

                  {displayMetrics.length > 0 ? (
                    <>
                      <div className="mt-3 grid gap-1.5 sm:grid-cols-2 xl:grid-cols-3">
                        {displayMetrics.map((metric) => (
                          <div key={metric.key} className="rounded-lg border border-slate-200/80 bg-slate-50/55 px-2 py-1.5">
                            <div className="text-[10px] uppercase tracking-[0.1em] text-muted-foreground">{metricLabel(metric.key)}</div>
                            <div className="mt-1 text-[15px] font-semibold tabular-nums text-foreground">{metric.value.toFixed(3)}</div>
                          </div>
                        ))}
                      </div>
                      <div className="mt-3 flex flex-wrap items-center gap-2">
                        <EvaluationInlineStat label="样本" value={summary.items ?? '-'} />
                        <EvaluationInlineStat label="令牌" value={summary.total_tokens ?? '-'} />
                        <EvaluationInlineStat label="成本" value={formatCurrency(summary.total_cost)} />
                      </div>
                    </>
                  ) : (
                    <div className="mt-4">
                      <EvaluationEmptyState
                        title={selectedRunId ? '当前还没有可展示分数' : '先选一个评测运行'}
                        description={selectedRunId ? '这条 run 可能还在处理中，或者后端尚未返回 summary 分数。' : '左侧运行列表选中一条 run 后，这里会显示指标摘要与状态。'}
                      />
                    </div>
                  )}
                </div>

                <div className="min-h-0 flex-1">
                  <div className="flex items-center justify-between border-b border-slate-200/80 bg-muted/30 px-3 py-2">
                    <div className="flex items-center gap-2">
                      <ListChecks className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
                      <div className="text-sm font-semibold text-foreground">逐轮明细</div>
                    </div>
                    <div className="text-xs text-muted-foreground">{runDetail?.items?.length || 0} 条</div>
                  </div>

                  {runDetail?.items?.length ? (
                    <div className="h-full overflow-auto">
                      <table aria-label="评测结果列表" className="w-full text-sm">
                        <thead className="sticky top-0 z-10 bg-slate-50 text-muted-foreground">
                          <tr>
                            <th className="w-14 px-2.5 py-1.5 text-left text-[11px] font-medium">#</th>
                            <th className="min-w-[280px] px-2.5 py-1.5 text-left text-[11px] font-medium">问题</th>
                            <th className="min-w-[320px] px-2.5 py-1.5 text-left text-[11px] font-medium">回答</th>
                            {(runDetail?.run?.metrics || []).map((metricKey: string) => (
                              <th key={metricKey} className="w-28 px-2.5 py-1.5 text-left text-[11px] font-medium">
                                {metricLabel(metricKey)}
                              </th>
                            ))}
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-border/70">
                          {(runDetail?.items || []).map((item) => (
                            <tr key={item.id} className="align-top hover:bg-slate-50/70">
                              <td className="px-2.5 py-1.5 text-[12px] text-muted-foreground">{item.turn_index}</td>
                              <td className="px-2.5 py-1.5">
                                <div className="line-clamp-3 text-[12px] leading-5 text-foreground">{item.user_input}</div>
                              </td>
                              <td className="px-2.5 py-1.5">
                                <div className="line-clamp-3 text-[12px] leading-5 text-foreground/90">{item.response}</div>
                              </td>
                              {(runDetail?.run?.metrics || []).map((metricKey: string) => {
                                const value = item.scores?.[metricKey]
                                const isNum = typeof value === 'number' && !Number.isNaN(value)
                                return (
                                  <td key={metricKey} className="px-2.5 py-1.5 text-[12px] tabular-nums text-foreground/90">
                                    {isNum ? value.toFixed(3) : '-'}
                                  </td>
                                )
                              })}
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  ) : (
                    <div className="p-4">
                      <EvaluationEmptyState
                        title={selectedRunId ? '当前运行暂无逐轮明细' : '先选择运行记录'}
                        description={selectedRunId ? '这条 run 可能仍在处理中，或后端未返回 item 列表。' : '在中间运行列表中选择一条记录后，这里会显示逐轮评分细节。'}
                      />
                    </div>
                  )}
                </div>
              </section>
            </div>
          </div>
        ) : activeTab === 'regression' ? (
            <div className="border-t border-slate-200/80 p-3">
            <RegressionTestTab embedded />
          </div>
        ) : (
            <div className="border-t border-slate-200/80 p-3">
            <QuerysetHealthTab embedded />
          </div>
        )}
        </div>
      </AnalysisPageShell>
    </div>
  )
}
