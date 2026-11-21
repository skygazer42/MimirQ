'use client'

import { useEffect, useLayoutEffect, useMemo, useRef, useState, useSyncExternalStore } from 'react'
import { useSearchParams } from 'next/navigation'
import { skipToken, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { evaluationApi } from '@/lib/api/evaluation'
import { chatApi } from '@/lib/api/chat'
import type { RagasRun, RagasRunDetail } from '@/types/evaluation'
import type { Conversation } from '@/types/chat'
import { queryKeys } from '@/lib/query-keys'
import { formatApiError } from '@/lib/api-errors'
import { getAuthSessionKey, subscribeAuthSession } from '@/lib/auth-storage'
import { downloadBlob } from '@/lib/download'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Checkbox } from '@/components/ui/checkbox'
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import { getRagasMetricOptions } from '@/components/evaluation/ragas-metrics'
import {
  AlertCircle,
  ArrowLeft,
  Check,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Clock3,
  Download,
  FileText,
  History,
  Loader2,
  MessageSquare,
  Play,
  RefreshCw,
  Search,
  SlidersHorizontal,
} from '@/components/icons'
import { Link } from '@/i18n/navigation'
import { cn } from '@/lib/utils'
import {
  displayDate,
  hasLowScore,
  itemContexts,
  metricName,
  metricStatistics,
  numericScore,
  runDuration,
  LOW_SCORE_THRESHOLD,
} from './evaluation-model'
import styles from '../evaluations.module.css'

const EMPTY_CONVERSATIONS: Conversation[] = []
const EMPTY_RUNS: RagasRun[] = []
const EMPTY_ITEMS: RagasRunDetail['items'] = []
const EMPTY_METRICS: string[] = []
const DETAIL_OPTIONS = { include_items: true, include_contexts: true } as const
type ConversationEvaluationScope = { conversationId: string | undefined; active: boolean }
function RunStatus({ status }: { status?: string }) {
  if (status === undefined) return null
  const completed = status === 'completed'
  const failed = status === 'failed'
  const Icon = completed ? CheckCircle2 : failed ? AlertCircle : Clock3
  return (
    <span className={cn(styles.status, completed ? styles.success : failed ? styles.danger : styles.processing)}>
      <Icon aria-hidden="true" />
      {completed
        ? '已完成'
        : failed
          ? '失败'
          : status === 'pending'
            ? '待运行'
            : status === 'running'
              ? '运行中'
              : status}
    </span>
  )
}
function Score({ value, bars = false }: { value: unknown; bars?: boolean }) {
  const number = numericScore(value)
  return (
    <span className={cn(styles.score, number !== null && number < LOW_SCORE_THRESHOLD && styles.lowScore)}>
      {number === null ? '—' : number.toFixed(2)}
      {bars && number !== null && number >= 0 && number <= 1 && (
        <i className={styles.track} aria-hidden="true">
          <i style={{ width: `${number * 100}%` }} />
        </i>
      )}
    </span>
  )
}

export function ConversationEvaluation({ active }: { active: boolean }) {
  const searchParams = useSearchParams()
  const sessionKey = useSyncExternalStore(subscribeAuthSession, getAuthSessionKey, getAuthSessionKey)
  const deepLink = searchParams.get('conversation_id')
  const initialConversationId = deepLink === null ? undefined : deepLink.trim().toLowerCase()
  return (
    <ConversationEvaluationWorkspace
      key={`${sessionKey}:${initialConversationId}`}
      sessionKey={sessionKey}
      initialConversationId={initialConversationId}
      active={active}
    />
  )
}

function ConversationEvaluationWorkspace({
  active,
  initialConversationId,
  sessionKey,
}: {
  active: boolean
  initialConversationId: string | undefined
  sessionKey: string
}) {
  const queryClient = useQueryClient()
  const [conversationId, setConversationId] = useState(initialConversationId)
  const [runChoices, setRunChoices] = useState<ReadonlyMap<string, string>>(new Map())
  const [sampleChoice, setSampleChoice] = useState({ runId: '', id: '' })
  const [metricKeys, setMetricKeys] = useState(['faithfulness', 'response_relevancy'])
  const [maxTurns, setMaxTurns] = useState('20')
  const [skipEmpty, setSkipEmpty] = useState(true)
  const [onlyLow, setOnlyLow] = useState(false)
  const [search, setSearch] = useState('')
  const [conversationWindow, setConversationWindow] = useState({ search: '', skip: 0 })
  const [evidenceFilter, setEvidenceFilter] = useState('all')
  const [pickerOpen, setPickerOpen] = useState(false)
  const [recordsOpen, setRecordsOpen] = useState(false)
  const [recordSearch, setRecordSearch] = useState('')
  const startRequests = useRef(new Map<string, Promise<RagasRun>>())
  const [pendingConversations, setPendingConversations] = useState<ReadonlySet<string>>(new Set())
  const scopeRef = useRef<ConversationEvaluationScope | null>(null)
  const focusFrame = useRef<number | null>(null)
  const runSelectionIntent = useRef(0)
  const [mobileReader, setMobileReader] = useState(false)
  const readerRef = useRef<HTMLHeadingElement>(null)
  const readerScrollRef = useRef<HTMLDivElement>(null)
  const selectedButtonRef = useRef<HTMLButtonElement | null>(null)
  const conversationParams = { limit: 100, skip: conversationWindow.skip, q: conversationWindow.search }
  const conversationsQuery = useQuery({
    queryKey: queryKeys.chat.conversations(conversationParams),
    queryFn: ({ signal }) => chatApi.listConversations(conversationParams, { signal }),
    enabled: active,
  })
  const conversations = conversationsQuery.data?.items ?? EMPTY_CONVERSATIONS
  const scopedId = conversationId
  const isStarting = scopedId !== undefined && pendingConversations.has(scopedId)
  const currentConversation = conversations.find((conversation) => conversation.id === scopedId)
  const conversationLabel =
    scopedId === undefined
      ? '选择对话'
      : currentConversation?.title === undefined ||
          currentConversation.title === null ||
          currentConversation.title.trim() === ''
        ? scopedId
        : currentConversation.title
  useEffect(() => {
    if (conversationId === undefined && conversations[0] !== undefined) setConversationId(conversations[0].id)
  }, [conversationId, conversations])
  useLayoutEffect(() => {
    const scope = { conversationId: scopedId, active }
    scopeRef.current = scope
    return () => {
      scope.active = false
      scopeRef.current = null
      if (focusFrame.current !== null) cancelAnimationFrame(focusFrame.current)
    }
  }, [scopedId, active])
  const ids = useMemo(() => {
    const conversationIds = conversations.map((conversation) => conversation.id)
    if (scopedId !== undefined && !conversationIds.includes(scopedId)) conversationIds.push(scopedId)
    return conversationIds
  }, [conversations, scopedId])
  const readinessQuery = useQuery({
    queryKey: queryKeys.evaluations.ragasConversationReadiness(ids),
    queryFn:
      ids.length === 0
        ? skipToken
        : ({ signal }) => evaluationApi.getRagasConversationReadiness({ conversation_ids: ids }, { signal }),
    enabled: active && ids.length > 0,
    staleTime: 60000,
  })
  const readiness = useMemo(
    () => new Map(readinessQuery.data?.items.map((item) => [item.conversation_id, item])),
    [readinessQuery.data?.items],
  )
  const runListParams = { limit: 50, conversation_id: scopedId }
  const runsQuery = useQuery({
    queryKey: queryKeys.evaluations.ragasRuns(runListParams),
    queryFn:
      scopedId === undefined ? skipToken : ({ signal }) => evaluationApi.listRagasRuns(runListParams, { signal }),
    enabled: active,
  })
  const runs = runsQuery.data?.items ?? EMPTY_RUNS
  const selectedRunId = scopedId === undefined ? undefined : runChoices.get(scopedId)
  useEffect(() => {
    const firstRun = runs[0]
    if (scopedId !== undefined && !runChoices.has(scopedId) && firstRun !== undefined) {
      setRunChoices((previous) => new Map(previous).set(scopedId, firstRun.id))
    }
  }, [scopedId, runChoices, runs])
  const detailQuery = useQuery({
    queryKey: [...queryKeys.evaluations.ragasRunDetail(selectedRunId, DETAIL_OPTIONS), scopedId],
    queryFn:
      selectedRunId === undefined || scopedId === undefined
        ? skipToken
        : async ({ signal }) => {
            const result = await evaluationApi.getRagasRun(selectedRunId, DETAIL_OPTIONS, { signal })
            if (result.run.conversation_id?.toLowerCase() !== scopedId.toLowerCase()) {
              throw new Error('评测结果不属于当前对话，请重新读取运行记录')
            }
            return result
          },
    enabled: active,
    refetchInterval: (query) => {
      const status = query.state.data?.run.status
      return active && (status === 'pending' || status === 'running') ? 2000 : false
    },
  })
  const detail = detailQuery.data === undefined ? null : detailQuery.data
  const loadedRunId = detail?.run.id
  const loadedRunStatus = detail?.run.status
  useEffect(() => {
    if (
      scopedId !== undefined &&
      loadedRunId !== undefined &&
      (loadedRunStatus === 'completed' || loadedRunStatus === 'failed')
    ) {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.evaluations.ragasRuns({ limit: 50, conversation_id: scopedId }),
        exact: true,
      })
    }
  }, [queryClient, scopedId, loadedRunId, loadedRunStatus])
  const initialQuery = scopedId === undefined ? conversationsQuery : runsQuery
  const awaitingSelection =
    selectedRunId === undefined &&
    (initialQuery.isPending || (scopedId === undefined ? conversations.length > 0 : runs.length > 0))
  const selectedRun = detail === null ? runs.find((run) => run.id === selectedRunId) : detail.run
  const items = detail?.items ?? EMPTY_ITEMS
  const resultMetricKeys = selectedRun === undefined ? EMPTY_METRICS : selectedRun.metrics
  const statistics = useMemo(() => metricStatistics(items, resultMetricKeys), [items, resultMetricKeys])
  const lowCount = items.filter((item) => hasLowScore(item, resultMetricKeys)).length
  const visibleItems = useMemo(
    () =>
      items.filter(
        (item) =>
          (!onlyLow || hasLowScore(item, resultMetricKeys)) &&
          (!search.trim() || item.user_input.toLocaleLowerCase().includes(search.trim().toLocaleLowerCase())),
      ),
    [items, onlyLow, resultMetricKeys, search],
  )
  const selectedItem =
    visibleItems.find((item) => sampleChoice.runId === selectedRunId && item.id === sampleChoice.id) ??
    visibleItems[0] ??
    null
  const selectedIndex = selectedItem ? visibleItems.indexOf(selectedItem) : -1
  const currentReadiness = scopedId === undefined ? undefined : readiness.get(scopedId)
  const checkingEvidence = scopedId !== undefined && readinessQuery.isPending
  const missingEvidence = currentReadiness !== undefined && !currentReadiness.is_evaluable
  const validTurns = Number.isInteger(Number(maxTurns)) && Number(maxTurns) >= 1 && Number(maxTurns) <= 200
  const canStart =
    active &&
    scopedId !== undefined &&
    readinessQuery.isSuccess &&
    currentReadiness !== undefined &&
    currentReadiness.is_evaluable &&
    metricKeys.length > 0 &&
    validTurns &&
    !isStarting
  const filteredConversations = conversations.filter((conversation) => {
    const item = readiness.get(conversation.id)
    return evidenceFilter === 'all' || (item && (evidenceFilter === 'ready' ? item.is_evaluable : !item.is_evaluable))
  })
  const runError = selectedRun?.error_message
  const deterministic = selectedRun?.summary.mode === 'deterministic_conversation'
  const tokenCount = numericScore(selectedRun?.summary.total_tokens)
  const modelCostUsd = numericScore(selectedRun?.summary.total_cost)
  const duration = runDuration(selectedRun?.started_at, selectedRun?.finished_at)
  const selectedContexts = selectedItem === null ? [] : itemContexts(selectedItem)
  function chooseRun(id: string) {
    if (scopedId === undefined) return
    runSelectionIntent.current += 1
    setRunChoices((previous) => new Map(previous).set(scopedId, id))
    setSearch('')
    setOnlyLow(false)
    setMobileReader(false)
    setRecordsOpen(false)
  }
  function chooseSample(item: RagasRunDetail['items'][number]) {
    setSampleChoice({ runId: item.run_id, id: item.id })
    setMobileReader(true)
    if (focusFrame.current !== null) cancelAnimationFrame(focusFrame.current)
    focusFrame.current = requestAnimationFrame(() => {
      focusFrame.current = null
      readerScrollRef.current?.scrollTo({ top: 0 })
      readerRef.current?.focus({ preventScroll: true })
    })
  }
  function returnToMatrix() {
    setMobileReader(false)
    if (focusFrame.current !== null) cancelAnimationFrame(focusFrame.current)
    focusFrame.current = requestAnimationFrame(() => {
      focusFrame.current = null
      selectedButtonRef.current?.focus()
    })
  }
  async function start() {
    const scope = scopeRef.current
    if (!canStart || scopedId === undefined || scope === null || !scope.active || startRequests.current.has(scopedId))
      return
    const selectionIntent = runSelectionIntent.current
    const request = evaluationApi.createRagasRun({
      conversation_id: scopedId,
      metrics: metricKeys,
      max_turns: Number(maxTurns),
      skip_empty_contexts: skipEmpty,
      include_contexts_in_response: false,
    })
    startRequests.current.set(scopedId, request)
    setPendingConversations(new Set(startRequests.current.keys()))
    try {
      const run = await request
      if (scopeRef.current === null || getAuthSessionKey() !== sessionKey) return
      void queryClient.invalidateQueries({
        queryKey: queryKeys.evaluations.ragasRuns({ limit: 50, conversation_id: scope.conversationId }),
        exact: true,
      })
      if (!scope.active || scopeRef.current !== scope || getAuthSessionKey() !== sessionKey) return
      if (runSelectionIntent.current === selectionIntent) chooseRun(run.id)
      toast.success('评测请求已接受，正在等待后台结果')
    } catch (error) {
      if (scope.active && scopeRef.current === scope && getAuthSessionKey() === sessionKey) {
        toast.error('未确认创建成功，请先刷新运行记录再决定是否重试', {
          description: formatApiError(error, '创建请求未得到有效回执'),
        })
      }
    } finally {
      startRequests.current.delete(scopedId)
      if (scopeRef.current !== null && getAuthSessionKey() === sessionKey) {
        setPendingConversations(new Set(startRequests.current.keys()))
      }
    }
  }
  function exportItems() {
    if (detail === null) return
    downloadBlob(
      `ragas-run-items.${detail.run.id}.json`,
      new Blob([JSON.stringify(detail.items, null, 2)], { type: 'application/json;charset=utf-8' }),
    )
    toast.success('已发起结果下载')
  }
  const reason =
    scopedId === undefined
      ? '选择对话后开始'
      : checkingEvidence
        ? '正在检查引用'
        : readinessQuery.isError
          ? '评测状态读取失败，请重试'
          : currentReadiness === undefined
            ? '未返回当前对话的评测状态，请确认对话仍可访问'
            : missingEvidence
              ? '这条对话没有引用上下文'
              : !metricKeys.length
                ? '至少选择一项指标'
                : !validTurns
                  ? '最近轮次应为 1–200 的整数'
                  : ''
  const contextCount = items.reduce((sum, item) => sum + item.citations.length, 0)
  return (
    <div className={styles.conversation} data-evaluation-matrix>
      <div className={styles.runbar}>
        <Dialog open={pickerOpen} onOpenChange={setPickerOpen}>
          <DialogTrigger asChild>
            <Button variant="ghost" className={styles.conversationPicker}>
              <MessageSquare aria-hidden="true" />
              <span>{conversationLabel}</span>
              <ChevronRight aria-hidden="true" />
            </Button>
          </DialogTrigger>
          <DialogContent className={styles.dialog}>
            <DialogHeader>
              <DialogTitle>选择对话</DialogTitle>
              <DialogDescription>
                搜索全部已有对话，使用它的回答和引用进行评测。引用筛选作用于当前页。
              </DialogDescription>
            </DialogHeader>
            {scopedId !== undefined && <p className={styles.muted}>当前对话：{scopedId}</p>}
            <div className={styles.dialogToolbar}>
              <Search aria-hidden="true" />
              <Input
                aria-label="搜索对话"
                placeholder="搜索对话"
                maxLength={500}
                value={conversationWindow.search}
                onChange={(event) => setConversationWindow({ search: event.target.value, skip: 0 })}
              />
            </div>
            <div className={styles.viewFilters}>
              {[
                ['all', '全部'],
                ['ready', '可评测'],
                ['missing', '缺证据'],
              ].map(([id, label]) => (
                <button
                  key={id}
                  type="button"
                  aria-pressed={evidenceFilter === id}
                  onClick={() => setEvidenceFilter(id)}
                >
                  {label}
                </button>
              ))}
            </div>
            {readinessQuery.isError && (
              <div className={styles.notice} role="alert">
                <span>{formatApiError(readinessQuery.error, '引用状态读取失败')}</span>
                <Button variant="ghost" onClick={() => readinessQuery.refetch()}>
                  重试
                </Button>
              </div>
            )}
            {conversationsQuery.isError && conversationsQuery.data !== undefined && (
              <div className={styles.notice} role="alert">
                <span>{formatApiError(conversationsQuery.error, '刷新失败，继续显示已读取的对话')}</span>
                <Button variant="ghost" onClick={() => conversationsQuery.refetch()}>
                  重试
                </Button>
              </div>
            )}
            <div className={styles.dialogList}>
              {conversationsQuery.isError && conversationsQuery.data === undefined ? (
                <div className={styles.state}>
                  <p>对话加载失败</p>
                  <Button variant="outline" onClick={() => conversationsQuery.refetch()}>
                    重试
                  </Button>
                </div>
              ) : conversationsQuery.isPending ? (
                <div className={styles.state}>
                  <Loader2 className="animate-spin" />
                  正在加载对话…
                </div>
              ) : conversations.length > 0 && evidenceFilter !== 'all' && readinessQuery.data === undefined ? (
                <div className={styles.state} role="status">
                  {readinessQuery.isError ? '引用状态未知，无法按引用筛选。' : '正在读取本页引用状态…'}
                </div>
              ) : filteredConversations.length ? (
                filteredConversations.map((conversation) => {
                  const evidence = readiness.get(conversation.id)
                  return (
                    <button
                      key={conversation.id}
                      type="button"
                      className={styles.listItem}
                      aria-pressed={scopedId === conversation.id}
                      onClick={() => {
                        setConversationId(conversation.id)
                        setSearch('')
                        setOnlyLow(false)
                        setMobileReader(false)
                        setPickerOpen(false)
                      }}
                    >
                      <span>
                        <strong>
                          {conversation.title === null ||
                          conversation.title === undefined ||
                          conversation.title.trim() === ''
                            ? conversation.id
                            : conversation.title}
                        </strong>
                        <small>{conversation.id}</small>
                        <small>{displayDate(conversation.created_at)}</small>
                      </span>
                      <span className={cn(styles.listHint, evidence && !evidence.is_evaluable && styles.lowScore)}>
                        {evidence
                          ? evidence.is_evaluable
                            ? `${evidence.evaluable_turns} 个可评轮次`
                            : '缺少引用'
                          : readinessQuery.isError
                            ? '证据状态未知'
                            : readinessQuery.isPending
                              ? '检查引用中'
                              : '未返回引用状态'}
                        {scopedId === conversation.id && <Check aria-hidden="true" />}
                      </span>
                    </button>
                  )
                })
              ) : (
                <div className={styles.state}>
                  <p>
                    {conversationWindow.search.trim() !== ''
                      ? '当前页没有匹配的对话'
                      : conversations.length === 0
                        ? '当前页没有对话'
                        : '当前页没有符合引用条件的对话'}
                  </p>
                  {evidenceFilter !== 'all' && (
                    <Button variant="outline" onClick={() => setEvidenceFilter('all')}>
                      查看全部
                    </Button>
                  )}
                  <Link href="/">新对话</Link>
                </div>
              )}
            </div>
            <div className={styles.dialogFooter}>
              <span>
                {conversationsQuery.data === undefined ? '对话总数未知' : `共 ${conversationsQuery.data.total} 条对话`}
              </span>
              <Button
                variant="outline"
                disabled={conversationWindow.skip === 0 || conversationsQuery.isFetching}
                onClick={() =>
                  setConversationWindow((previous) => ({ ...previous, skip: Math.max(0, previous.skip - 100) }))
                }
              >
                上一页
              </Button>
              <Button
                variant="outline"
                disabled={
                  conversationsQuery.isFetching ||
                  conversationsQuery.data === undefined ||
                  !conversationsQuery.data.has_more
                }
                onClick={() => {
                  const nextSkip = conversationsQuery.data?.next_skip
                  if (nextSkip !== undefined && nextSkip !== null)
                    setConversationWindow((previous) => ({ ...previous, skip: nextSkip }))
                }}
              >
                下一页
              </Button>
            </div>
          </DialogContent>
        </Dialog>
        <div className={styles.runMeta}>
          <span>{selectedRunId ? selectedRunId.slice(0, 12) : '尚未运行'}</span>
          <RunStatus status={selectedRun?.status} />
          <span>{displayDate(selectedRun?.created_at)}</span>
          {duration !== null && <span>耗时 {duration}</span>}
        </div>
        <div className={styles.runActions}>
          <Dialog open={recordsOpen} onOpenChange={setRecordsOpen}>
            <DialogTrigger asChild>
              <Button variant="outline" disabled={scopedId === undefined}>
                <History aria-hidden="true" />
                <span>运行记录 {runsQuery.data === undefined ? '—' : runsQuery.data.total}</span>
              </Button>
            </DialogTrigger>
            <DialogContent className={styles.dialog}>
              <DialogHeader>
                <DialogTitle>运行记录</DialogTitle>
                <DialogDescription>{conversationLabel}的最近 50 次运行</DialogDescription>
              </DialogHeader>
              <div className={styles.dialogToolbar}>
                <Search aria-hidden="true" />
                <Input
                  aria-label="搜索运行记录"
                  placeholder="搜索运行编号或状态"
                  value={recordSearch}
                  onChange={(event) => setRecordSearch(event.target.value)}
                />
                <Button
                  variant="ghost"
                  aria-label="刷新运行记录"
                  disabled={runsQuery.isFetching}
                  onClick={() => runsQuery.refetch()}
                >
                  <RefreshCw />
                </Button>
              </div>
              {runsQuery.isError && runsQuery.data !== undefined && (
                <div className={styles.notice} role="alert">
                  <span>{formatApiError(runsQuery.error, '刷新失败，继续显示已读取的运行记录')}</span>
                  <Button variant="ghost" onClick={() => runsQuery.refetch()}>
                    重试
                  </Button>
                </div>
              )}
              <div className={styles.dialogList}>
                {runsQuery.isError && runsQuery.data === undefined ? (
                  <div className={styles.state}>
                    <p>运行记录加载失败</p>
                    <Button variant="outline" onClick={() => runsQuery.refetch()}>
                      重试
                    </Button>
                  </div>
                ) : runsQuery.isPending ? (
                  <div className={styles.state}>正在加载记录…</div>
                ) : (
                  runs
                    .filter((run) => !recordSearch.trim() || `${run.id} ${run.status}`.includes(recordSearch.trim()))
                    .map((run) => (
                      <button
                        key={run.id}
                        type="button"
                        className={styles.listItem}
                        aria-pressed={selectedRunId === run.id}
                        onClick={() => chooseRun(run.id)}
                      >
                        <span>
                          <strong>{run.id}</strong>
                          <small>
                            {displayDate(run.created_at)} · {run.metrics.map(metricName).join('／')}
                          </small>
                        </span>
                        <RunStatus status={run.status} />
                      </button>
                    ))
                )}
                {runsQuery.data !== undefined &&
                  runs.length > 0 &&
                  !runs.some(
                    (run) => recordSearch.trim() === '' || `${run.id} ${run.status}`.includes(recordSearch.trim()),
                  ) && <div className={styles.state}>最近 50 次运行中没有匹配记录，请调整搜索条件。</div>}
                {runsQuery.data !== undefined && runs.length === 0 && (
                  <div className={styles.state}>
                    <p>暂无运行记录</p>
                    <p>运行完成后，可在这里切换查看结果。</p>
                  </div>
                )}
              </div>
            </DialogContent>
          </Dialog>
          <Button
            variant="ghost"
            aria-label="导出结果"
            title="导出结果"
            disabled={!detail?.items.length || detailQuery.isFetching}
            onClick={exportItems}
          >
            <Download aria-hidden="true" />
          </Button>
          <Button className={styles.primary} disabled={!canStart} onClick={start}>
            {isStarting ? (
              <Loader2 className="animate-spin motion-reduce:animate-none" aria-hidden="true" />
            ) : (
              <Play aria-hidden="true" />
            )}
            <span>{isStarting ? '启动中…' : '开始评测'}</span>
          </Button>
        </div>
      </div>
      <div className={styles.parameterbar}>
        <span>
          下次评测 <b>{metricKeys.length} 项指标</b>
        </span>
        <span>
          最近 <b>{maxTurns === '' ? '—' : maxTurns} 轮</b>
        </span>
        <span className={styles.skip}>
          {skipEmpty && <Check aria-hidden="true" />}
          {skipEmpty ? '跳过无引用轮次' : '包括无引用轮次'}
        </span>
        <Dialog>
          <DialogTrigger asChild>
            <Button variant="ghost">
              <SlidersHorizontal aria-hidden="true" />
              评测参数
            </Button>
          </DialogTrigger>
          <DialogContent className={styles.configDialog}>
            <DialogHeader>
              <DialogTitle>评测参数</DialogTitle>
              <DialogDescription>
                参数用于下一次运行。引用状态统计整条对话，实际评测以最近轮次和可读取的上下文为准。
              </DialogDescription>
            </DialogHeader>
            <div className={styles.configBody}>
              <fieldset>
                <legend>评测指标</legend>
                {getRagasMetricOptions('conversation').map((metric) => (
                  <label key={metric.key} className={styles.metricOption}>
                    <Checkbox
                      checked={metricKeys.includes(metric.key)}
                      disabled={isStarting}
                      onCheckedChange={(checked) =>
                        setMetricKeys((previous) =>
                          checked === true
                            ? [...new Set([...previous, metric.key])]
                            : previous.filter((key) => key !== metric.key),
                        )
                      }
                    />
                    <span>
                      <strong>{metricName(metric.key)}</strong>
                      <small>{metric.hint}</small>
                    </span>
                  </label>
                ))}
                {!metricKeys.length && <p className={styles.formError}>至少选择一项指标。</p>}
              </fieldset>
              <label className={styles.numberField}>
                最近轮次
                <Input
                  type="number"
                  aria-label="最近轮次"
                  min={1}
                  max={200}
                  step={1}
                  value={maxTurns}
                  disabled={isStarting}
                  aria-invalid={!validTurns}
                  onChange={(event) => setMaxTurns(event.target.value)}
                />
              </label>
              {!validTurns && <p className={styles.formError}>请输入 1–200 的整数。</p>}
              <label className={styles.checkboxField}>
                <Checkbox
                  checked={skipEmpty}
                  disabled={isStarting}
                  onCheckedChange={(value) => setSkipEmpty(value === true)}
                />
                跳过无引用轮次
              </label>
            </div>
            <div className={styles.dialogFooter}>
              <Button
                variant="ghost"
                disabled={isStarting}
                onClick={() => {
                  setMetricKeys(['faithfulness', 'response_relevancy'])
                  setMaxTurns('20')
                  setSkipEmpty(true)
                }}
              >
                恢复默认
              </Button>
              <DialogClose asChild>
                <Button className={styles.primary}>完成</Button>
              </DialogClose>
            </div>
          </DialogContent>
        </Dialog>
      </div>
      {reason && (
        <div
          className={cn(styles.notice, missingEvidence && styles.warning)}
          role={readinessQuery.isError ? 'alert' : 'status'}
        >
          {checkingEvidence ? (
            <Loader2 className="animate-spin motion-reduce:animate-none" aria-hidden="true" />
          ) : (
            <AlertCircle aria-hidden="true" />
          )}
          <span>{reason}</span>
          {(readinessQuery.isError ||
            (scopedId !== undefined && readinessQuery.isSuccess && currentReadiness === undefined)) && (
            <Button variant="ghost" size="sm" onClick={() => readinessQuery.refetch()}>
              重试
            </Button>
          )}
          {(scopedId === undefined || missingEvidence) && (
            <Button variant="ghost" size="sm" onClick={() => setPickerOpen(true)}>
              {missingEvidence ? '更换对话' : '选择对话'}
            </Button>
          )}
        </div>
      )}
      {runsQuery.isError && (
        <div className={styles.notice} role="alert">
          <AlertCircle />
          <span>运行记录加载失败</span>
          <Button variant="ghost" size="sm" onClick={() => runsQuery.refetch()}>
            重试
          </Button>
        </div>
      )}
      {deterministic && (
        <div className={styles.notice}>
          <span>确定性证据校验</span>
          <span className={styles.muted}>
            {selectedRun?.summary.ragas_skipped_reason === 'ragas_wall_timeout'
              ? 'RAGAS 超时，当前分数来自证据一致性校验。'
              : '当前分数来自证据一致性校验。'}
          </span>
        </div>
      )}
      <div className={styles.matrixWorkspace} data-mobile-reader={mobileReader}>
        <section className={styles.matrixPane} aria-label="样本矩阵">
          <div className={styles.matrixToolbar}>
            <h2>
              样本矩阵 <small>{detail === null ? '样本数未知' : `${items.length} 个样本`}</small>
            </h2>
            <div className={styles.viewFilters}>
              <button type="button" aria-pressed={!onlyLow} onClick={() => setOnlyLow(false)}>
                全部
              </button>
              <button type="button" aria-pressed={onlyLow} onClick={() => setOnlyLow(true)}>
                低分 {detail === null ? '—' : lowCount}
              </button>
            </div>
            <div className={styles.sampleSearch}>
              <Search aria-hidden="true" />
              <Input
                type="search"
                aria-label="搜索评测问题"
                placeholder="搜索问题"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
              />
            </div>
          </div>
          <div className={styles.tableScroll}>
            <table className={styles.matrixTable} aria-label="逐轮评分矩阵">
              <colgroup>
                <col className={styles.indexColumn} />
                <col />
                {resultMetricKeys.map((key) => (
                  <col
                    key={key}
                    className={cn(styles.scoreColumn, resultMetricKeys.length < 3 && styles.wideScoreColumn)}
                  />
                ))}
                <col className={styles.contextColumn} />
              </colgroup>
              <thead>
                <tr>
                  <th scope="col">#</th>
                  <th scope="col">问题</th>
                  {resultMetricKeys.map((key) => (
                    <th scope="col" key={key}>
                      {metricName(key)}
                    </th>
                  ))}
                  <th scope="col">引用</th>
                </tr>
              </thead>
              <tbody>
                {detail !== null && (
                  <tr className={styles.meanRow}>
                    <td />
                    <th scope="row">
                      <strong>样本均值</strong>
                      <small>{detail === null ? '尚未读取样本' : `${items.length} 个样本`}</small>
                    </th>
                    {statistics.map((metric) => (
                      <td key={metric.key}>
                        <Score value={metric.mean} />
                        <small>{metric.scoredCount} 项有效评分</small>
                      </td>
                    ))}
                    <td>{items.length ? `${contextCount} 条` : '—'}</td>
                  </tr>
                )}
                {visibleItems.map((item) => (
                  <tr key={item.id} data-sample-row data-selected={selectedItem?.id === item.id}>
                    <td>{String(item.turn_index).padStart(2, '0')}</td>
                    <th scope="row">
                      <button
                        ref={selectedItem?.id === item.id ? selectedButtonRef : undefined}
                        type="button"
                        onClick={() => chooseSample(item)}
                        aria-pressed={selectedItem?.id === item.id}
                      >
                        {item.user_input === '' ? '问题正文为空' : item.user_input}
                      </button>
                      {hasLowScore(item, resultMetricKeys) && <small className={styles.lowScore}>低分</small>}
                    </th>
                    {resultMetricKeys.map((key) => (
                      <td key={key}>
                        <Score value={item.scores[key]} bars />
                      </td>
                    ))}
                    <td>{item.citations.length} 条</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {selectedRunId === undefined && initialQuery.isError ? (
              <div className={styles.state} role="alert">
                <AlertCircle />
                <h3>{scopedId === undefined ? '对话加载失败' : '运行记录加载失败'}</h3>
                <p>{formatApiError(initialQuery.error, '无法确定可查看的运行记录')}</p>
                <Button variant="outline" onClick={() => initialQuery.refetch()}>
                  重试
                </Button>
              </div>
            ) : awaitingSelection ? (
              <div className={styles.state} role="status">
                <Loader2 className="animate-spin motion-reduce:animate-none" aria-hidden="true" />
                <p>{scopedId === undefined ? '正在读取对话…' : '正在读取运行记录…'}</p>
              </div>
            ) : detailQuery.isError ? (
              <div className={styles.state} role="alert">
                <AlertCircle />
                <h3>评测结果加载失败</h3>
                <p>{formatApiError(detailQuery.error, '无法读取结果')}</p>
                <Button variant="outline" onClick={() => detailQuery.refetch()}>
                  重试
                </Button>
              </div>
            ) : detailQuery.isPending && selectedRunId ? (
              <div className={styles.state} role="status">
                <Loader2 className="animate-spin motion-reduce:animate-none" />
                <p>正在读取评测结果…</p>
              </div>
            ) : !visibleItems.length ? (
              <div className={styles.state}>
                <h3>
                  {items.length
                    ? '没有匹配的样本'
                    : selectedRun?.status === 'failed'
                      ? '评测失败'
                      : selectedRun?.status === 'running' || selectedRun?.status === 'pending'
                        ? '正在评测'
                        : '暂无评测结果'}
                </h3>
                <p>
                  {items.length
                    ? '调整搜索条件或查看全部样本。'
                    : runError !== null && runError !== undefined && runError !== ''
                      ? runError
                      : !selectedRunId
                        ? '选择包含引用的对话，点击「开始评测」。'
                        : selectedRun?.status === 'completed'
                          ? '这次运行没有返回逐轮样本。'
                          : '完成后将自动显示逐轮评分。'}
                </p>
                {items.length > 0 && (
                  <Button
                    variant="outline"
                    onClick={() => {
                      setSearch('')
                      setOnlyLow(false)
                    }}
                  >
                    查看全部样本
                  </Button>
                )}
              </div>
            ) : null}
          </div>
          <footer className={styles.footer}>
            <span>评分范围 0–1</span>
            <span>低分：任一指标 &lt; 0.80</span>
            <span>
              {detailQuery.isFetching && !detailQuery.isPending
                ? '更新中…'
                : detail === null
                  ? '尚未读取样本'
                  : `${visibleItems.length} / ${items.length} 个样本`}
            </span>
          </footer>
        </section>
        <aside className={styles.reader} aria-label="样本阅读区" role="region">
          <div className={styles.readerToolbar}>
            <Button variant="ghost" className={styles.mobileBack} aria-label="返回样本矩阵" onClick={returnToMatrix}>
              <ArrowLeft />
            </Button>
            <span>样本 {selectedItem ? String(selectedItem.turn_index).padStart(2, '0') : '—'}</span>
            {selectedItem && hasLowScore(selectedItem, resultMetricKeys) && (
              <span className={styles.lowScore}>低分</span>
            )}
            <div className={styles.readerNav}>
              <small>{selectedItem ? `${selectedIndex + 1} / ${visibleItems.length}` : '0 / 0'}</small>
              <Button
                variant="ghost"
                aria-label="上一个样本"
                disabled={selectedIndex <= 0}
                onClick={() => chooseSample(visibleItems[selectedIndex - 1])}
              >
                <ChevronLeft />
              </Button>
              <Button
                variant="ghost"
                aria-label="下一个样本"
                disabled={selectedIndex < 0 || selectedIndex >= visibleItems.length - 1}
                onClick={() => chooseSample(visibleItems[selectedIndex + 1])}
              >
                <ChevronRight />
              </Button>
            </div>
          </div>
          <div className={styles.readerScroll} ref={readerScrollRef}>
            {selectedItem ? (
              <div
                key={`${selectedRunId}:${selectedItem.id}`}
                className={styles.readerContent}
                data-evaluation-reader-item={selectedItem.id}
              >
                <h3 ref={readerRef} tabIndex={-1}>
                  {selectedItem.user_input === '' ? '问题正文为空' : selectedItem.user_input}
                </h3>
                <dl className={styles.readerScores}>
                  {resultMetricKeys.map((key) => (
                    <div key={key}>
                      <dt>{metricName(key)}</dt>
                      <dd>
                        <Score value={selectedItem.scores[key]} />
                      </dd>
                    </div>
                  ))}
                </dl>
                <section className={styles.readerSection}>
                  <h4>回答</h4>
                  <p>{selectedItem.response === '' ? '回答正文为空' : selectedItem.response}</p>
                </section>
                <section className={styles.readerSection}>
                  <h4>
                    <FileText aria-hidden="true" />
                    引用上下文{' '}
                    <small>
                      {selectedItem.retrieved_contexts === null ? '未保存正文' : `${selectedContexts.length} 段`}
                    </small>
                  </h4>
                  {selectedContexts.length > 0 ? (
                    selectedContexts.map((text, index) => (
                      <blockquote key={index}>
                        <span>{String(index + 1).padStart(2, '0')}</span>
                        <p>{text === '' ? '上下文正文为空' : text}</p>
                      </blockquote>
                    ))
                  ) : (
                    <p className={styles.muted}>
                      {selectedItem.citations.length > 0
                        ? '这次运行保留了引用记录，但没有保存上下文正文。'
                        : '这个样本没有引用上下文。'}
                    </p>
                  )}
                </section>
                {selectedItem.citations.length > 0 && (
                  <details className={styles.sourceDetails}>
                    <summary>引用记录</summary>
                    <pre>{JSON.stringify(selectedItem.citations, null, 2)}</pre>
                  </details>
                )}
                <details className={styles.sourceDetails}>
                  <summary>运行统计</summary>
                  <dl className={styles.runStats}>
                    <div>
                      <dt>评测令牌消耗</dt>
                      <dd>{tokenCount === null ? '—' : tokenCount}</dd>
                    </div>
                    <div>
                      <dt>评测成本（美元）</dt>
                      <dd>{modelCostUsd === null ? '—' : `$${modelCostUsd}`}</dd>
                    </div>
                  </dl>
                  <table aria-label="指标统计">
                    <thead>
                      <tr>
                        <th>指标</th>
                        <th>P50</th>
                        <th>P90</th>
                        <th>通过率</th>
                      </tr>
                    </thead>
                    <tbody>
                      {statistics.map((row) => (
                        <tr key={row.key}>
                          <th>{row.label}</th>
                          <td>{row.p50?.toFixed(2) ?? '—'}</td>
                          <td>{row.p90?.toFixed(2) ?? '—'}</td>
                          <td>{row.passRate !== null ? `${Math.round(row.passRate * 100)}%` : '—'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </details>
              </div>
            ) : (
              <div className={styles.readerEmpty}>
                <FileText aria-hidden="true" />
                <p>选择一个样本</p>
                <span>在这里核对回答与引用</span>
              </div>
            )}
          </div>
        </aside>
      </div>
    </div>
  )
}
