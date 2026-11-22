'use client'

import { useLayoutEffect, useMemo, useRef, useState, useSyncExternalStore } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AlertCircle,
  Archive,
  ArrowLeft,
  ArrowUpRight,
  CheckCheck,
  ChevronLeft,
  ChevronRight,
  Copy,
  Filter,
  Mail as Inbox,
  MessageSquare,
  MoreHorizontal,
  RefreshCw,
  Search,
  Star,
  TestTube2,
  ThumbsDown,
  ThumbsUp,
  UserRound,
} from '@/components/icons'
import { toast } from 'sonner'

import { AppFrame } from '@/components/app-frame'
import { PageTitleIcon } from '@/components/ui/page-title-icon'
import { Button } from '@/components/ui/button'
import { LoadingButton } from '@/components/ui/loading-button'
import { Skeleton } from '@/components/ui/skeleton'
import { SearchInput } from '@/components/ui/search-input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { FileTypeIcon } from '@/components/ui/file-type-icon'
import { Link } from '@/i18n/navigation'
import { chatApi } from '@/lib/api/chat'
import { feedbackApi } from '@/lib/api/feedback'
import { formatApiError } from '@/lib/api-errors'
import { getAuthSessionKey, subscribeAuthSession } from '@/lib/auth-storage'
import { useDocumentView } from '@/store/document-view'
import type { Message, MessageFeedbackEnriched } from '@/types'
import {
  isFeedbackArchived,
  getFeedbackIssue,
  getFeedbackKind,
  getFeedbackLabel,
  getFeedbackSource,
  getFeedbackStatus,
  formatFeedbackTime,
  filterFeedback,
  RANGE_LABELS,
  SOURCE_LABELS,
  type FeedbackRange,
  type FeedbackSource,
  type FeedbackView,
} from './feedback-inbox-model'
import { FeedbackCandidatesDialog } from './feedback-candidates-dialog'
import styles from './feedback.module.css'

const PAGE_SIZE = 20
const FEEDBACK_PAGE_SIZE = 200
type ActionResult = { error?: string; caseId?: string }

// Load every API page so local filters and counts include older feedback.
async function loadFeedback(signal: AbortSignal) {
  const firstPage = await feedbackApi.listEnriched({ skip: 0, limit: FEEDBACK_PAGE_SIZE }, { signal })
  const items = [...firstPage.items]
  const ids = new Set(items.map((item) => item.id))
  const total = firstPage.total
  if (ids.size !== items.length) throw new Error('反馈列表包含重复记录，请刷新后重试。')
  while (items.length < total) {
    signal.throwIfAborted()
    const page = await feedbackApi.listEnriched({ skip: items.length, limit: FEEDBACK_PAGE_SIZE }, { signal })
    if (page.total !== total || page.items.length === 0) throw new Error('反馈列表已变化，请刷新后重新读取。')
    for (const item of page.items) {
      if (ids.has(item.id)) throw new Error('反馈列表已变化，请刷新后重新读取。')
      ids.add(item.id)
      items.push(item)
    }
  }
  if (items.length !== total) throw new Error('反馈列表数量不一致，请刷新后重试。')
  return { items }
}

async function loadFeedbackContext(conversationId: string, messageId: string, signal: AbortSignal) {
  let before: string | undefined
  let answer: Message | undefined
  for (;;) {
    signal.throwIfAborted()
    const page = await chatApi.getMessages(conversationId, { limit: 200, before }, { signal })
    for (let index = page.messages.length - 1; index >= 0; index -= 1) {
      const message = page.messages[index]
      if (answer === undefined) {
        if (message.id === messageId && message.role === 'assistant') answer = message
      } else if (message.role === 'user') {
        return { answer, question: message.content }
      }
    }
    if (!page.has_more) return answer === undefined ? null : { answer, question: undefined }
    const nextBefore = page.messages[0].id
    if (nextBefore === before) throw new Error('历史消息分页未前进，请重新读取。')
    before = nextBefore
  }
}

function Rating({ item }: Readonly<{ item: MessageFeedbackEnriched }>) {
  const kind = getFeedbackKind(item)
  const Icon = kind === 'positive' ? ThumbsUp : kind === 'negative' ? ThumbsDown : Star
  return (
    <span className={styles.rating} data-kind={kind} aria-label={`评分 ${item.rating} / 5`}>
      <Icon aria-hidden="true" />
      {item.rating}
      <span>/ 5</span>
    </span>
  )
}
function StateLabel({ item }: Readonly<{ item: MessageFeedbackEnriched }>) {
  return (
    <span className={styles.stateLabel} data-state={isFeedbackArchived(item) ? 'archived' : getFeedbackKind(item)}>
      {getFeedbackStatus(item)}
    </span>
  )
}

function FeedbackReader({
  item,
  sessionKey,
  position,
  total,
  busy,
  result,
  onPrevious,
  onNext,
  onBack,
  onArchive,
  onCreate,
}: Readonly<{
  item: MessageFeedbackEnriched
  sessionKey: string
  position: number
  total: number
  busy: 'archive' | 'case' | null
  result?: ActionResult
  onPrevious: () => void
  onNext: () => void
  onBack: () => void
  onArchive: () => void
  onCreate: () => void
}>) {
  const { openDocument } = useDocumentView()
  const ownerRef = useRef({ active: true })
  useLayoutEffect(() => {
    const owner = { active: true }
    ownerRef.current = owner
    return () => {
      owner.active = false
    }
  }, [])
  const context = useQuery({
    queryKey: ['feedback-conversation', sessionKey, item.conversation_id, item.message_id],
    queryFn: ({ signal }) => loadFeedbackContext(item.conversation_id, item.message_id, signal),
    staleTime: 60_000,
    retry: false,
  })
  const original = context.data
  const citations = original?.answer.citations
  const answer = original == null ? item.message_content : original.answer.content
  const answerIsPreview = original == null && item.message_content !== null
  const question = original?.question
  const storedCaseId = item.extra.eval_case_id
  const caseId =
    result?.caseId ?? (typeof storedCaseId === 'string' && storedCaseId.length > 0 ? storedCaseId : undefined)
  const copy = async () => {
    const owner = ownerRef.current
    const isCurrent = () => owner.active && sessionKey === getAuthSessionKey()
    try {
      await navigator.clipboard.writeText(JSON.stringify(item, null, 2))
      if (isCurrent()) toast.success('已复制反馈详情')
    } catch (error) {
      if (isCurrent()) toast.error(formatApiError(error, '复制失败'))
    }
  }

  return (
    <section className={styles.reader} data-feedback-reader aria-label="反馈详情">
      <div className={styles.readerScroll} tabIndex={0} aria-label="反馈内容">
        <article className={styles.reading}>
          <div className={styles.recordBar}>
            <Button variant="ghost" size="icon" className={styles.back} onClick={onBack} aria-label="返回反馈队列">
              <ArrowLeft />
            </Button>
            <span className={styles.recordId} title={item.id}>
              {item.id.slice(0, 8)}
            </span>
            <StateLabel item={item} />
            <div className={styles.recordNav}>
              <span>
                {position + 1} / {total}
              </span>
              <Button
                variant="ghost"
                size="icon"
                onClick={onPrevious}
                disabled={position === 0}
                aria-label="上一条反馈"
              >
                <ChevronLeft />
              </Button>
              <Button
                variant="ghost"
                size="icon"
                onClick={onNext}
                disabled={position >= total - 1}
                aria-label="下一条反馈"
              >
                <ChevronRight />
              </Button>
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button variant="ghost" size="icon" aria-label="反馈更多操作">
                    <MoreHorizontal />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  <DropdownMenuItem onSelect={() => void copy()}>
                    <Copy />
                    复制详情
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            </div>
          </div>
          <h2 className={styles.question}>
            {question === undefined ? getFeedbackLabel(item) : question.length === 0 ? '提问内容为空' : question}
          </h2>
          <div className={styles.context}>
            <span>
              <UserRound aria-hidden="true" />
              {item.account_id}
            </span>
            <span>{SOURCE_LABELS[getFeedbackSource(item)]}</span>
            <time dateTime={item.created_at} title={formatFeedbackTime(item.created_at, true)}>
              {formatFeedbackTime(item.created_at)}
            </time>
            {typeof item.extra.dataset_name === 'string' && <span>知识库 · {item.extra.dataset_name}</span>}
          </div>
          {context.isFetching && (
            <p className={styles.missing} role="status">
              {context.data === undefined ? '正在读取原会话…' : '正在刷新原会话…'}
            </p>
          )}
          {context.isError && (
            <div className={styles.contextError} role="alert">
              <p>{formatApiError(context.error, '原会话读取失败')}</p>
              <Button
                type="button"
                variant="ghost"
                disabled={context.isFetching}
                onClick={() => void context.refetch({ cancelRefetch: false })}
              >
                重新读取
              </Button>
            </div>
          )}
          <section className={styles.section}>
            <div className={styles.sectionHeading}>
              <h3>用户反馈</h3>
              <span className={styles.tag}>{getFeedbackIssue(item)}</span>
              <Rating item={item} />
            </div>
            <p className={item.reason === null || item.reason.length === 0 ? styles.missing : styles.copy}>
              {item.reason === null
                ? '用户未填写反馈原因。'
                : item.reason.length === 0
                  ? '反馈原因为空。'
                  : item.reason}
            </p>
            {item.tags.length > 0 && (
              <div className={styles.tags}>
                {item.tags.map((tag, index) => (
                  <span key={`${tag}-${index}`} className={styles.tag}>
                    {tag}
                  </span>
                ))}
              </div>
            )}
          </section>
          <section className={styles.section}>
            <div className={styles.sectionHeading}>
              <h3>原回答</h3>
              {answerIsPreview && <span className={styles.sectionMeta}>列表中的回答预览，最多 4,000 字符</span>}
            </div>
            <div className={answer === null || answer.length === 0 ? styles.missing : styles.copy}>
              {answer === null
                ? original === null
                  ? '未找到这条原回答。'
                  : '原回答暂不可用。'
                : answer.length === 0
                  ? '原回答内容为空。'
                  : answer}
            </div>
          </section>
          <section className={styles.section}>
            <div className={styles.sectionHeading}>
              <h3>期望回答</h3>
            </div>
            <div
              className={
                item.expected_answer === null || item.expected_answer.length === 0 ? styles.missing : styles.copy
              }
            >
              {item.expected_answer === null
                ? '用户未填写期望回答。'
                : item.expected_answer.length === 0
                  ? '期望回答为空。'
                  : item.expected_answer}
            </div>
          </section>
          <section className={styles.section}>
            <div className={styles.sectionHeading}>
              <h3>原回答引用</h3>
              {citations !== undefined && <span className={styles.sectionMeta}>{citations.length} 个来源</span>}
            </div>
            {original === null ? (
              <p className={styles.missing}>未找到这条原回答的会话记录，可前往原会话查看。</p>
            ) : citations === undefined ? (
              <p className={styles.missing}>
                {original === undefined ? '读取原会话后显示引用。' : '原回答未记录引用字段。'}
              </p>
            ) : citations.length === 0 ? (
              <p className={styles.missing}>这条回答没有引用来源。</p>
            ) : (
              <ol className={styles.sources}>
                {citations.map((citation, index) => (
                  <li key={JSON.stringify([citation, index])}>
                    <span className={styles.sourceOrder}>{index + 1}</span>
                    <FileTypeIcon filename={citation.document_name} />
                    <div className={styles.sourceContent}>
                      <Button
                        variant="link"
                        className={styles.sourceTitle}
                        onClick={() => openDocument(citation.document_id, citation.chunk_id)}
                      >
                        {citation.document_name.length === 0 ? '文档名称为空' : citation.document_name}
                        <ArrowUpRight aria-hidden="true" />
                      </Button>
                      {(citation.page_number !== undefined || citation.header_path !== undefined) && (
                        <span className={styles.sourceLocation}>
                          {[
                            citation.page_number === undefined ? undefined : `第 ${citation.page_number} 页`,
                            citation.header_path,
                          ]
                            .filter((value) => value !== undefined)
                            .join(' · ')}
                        </span>
                      )}
                      {citation.chunk_content && <p className={styles.sourceExcerpt}>{citation.chunk_content}</p>}
                    </div>
                  </li>
                ))}
              </ol>
            )}
          </section>
        </article>
      </div>
      <footer className={styles.recordFooter} data-task-center-dock>
        {result?.error !== undefined && (
          <p className={styles.actionError} role="alert">
            <AlertCircle aria-hidden="true" />
            {result.error}
          </p>
        )}
        <div className={styles.actions}>
          <StateLabel item={item} />
          <Button asChild variant="outline">
            <Link href={`/history?id=${encodeURIComponent(item.conversation_id)}`}>
              <MessageSquare />
              原会话
            </Link>
          </Button>
          {caseId !== undefined ? (
            <Button asChild variant="outline">
              <Link href="/evaluations?tab=regression" title={`用例 ${caseId}`}>
                <TestTube2 />
                查看回归用例
              </Link>
            </Button>
          ) : (
            <LoadingButton variant="outline" onClick={onCreate} disabled={busy !== null} loading={busy === 'case'}>
              <TestTube2 />
              创建回归用例
            </LoadingButton>
          )}
          <LoadingButton onClick={onArchive} disabled={busy !== null} loading={busy === 'archive'}>
            {isFeedbackArchived(item) ? <Archive /> : <CheckCheck />}
            {isFeedbackArchived(item) ? '取消归档' : '归档反馈'}
          </LoadingButton>
        </div>
      </footer>
    </section>
  )
}

function FeedbackReaderLoading() {
  return (
    <section className={styles.reader} aria-busy="true" aria-label="正在读取反馈详情">
      <p role="status" className="sr-only">
        正在读取反馈详情…
      </p>
      <div className={styles.readerScroll}>
        <div className={styles.reading} aria-hidden="true">
          <div className={styles.recordBar}>
            <Skeleton className="size-8" />
            <Skeleton className="h-4 w-24" />
          </div>
          <Skeleton className="mt-5 h-8 w-3/4" />
          <Skeleton className="mt-4 h-4 w-1/2" />
          {['用户反馈', '原回答', '期望回答', '原回答引用'].map((label) => (
            <section key={label} className={styles.section}>
              <div className={styles.sectionHeading}>
                <h3>{label}</h3>
              </div>
              <Skeleton className="h-4 w-full" />
              <Skeleton className="mt-2 h-4 w-2/3" />
            </section>
          ))}
        </div>
      </div>
    </section>
  )
}

export default function FeedbackTriagePage() {
  const sessionKey = useSyncExternalStore(subscribeAuthSession, getAuthSessionKey, getAuthSessionKey)
  return <FeedbackTriageWorkspace key={sessionKey} sessionKey={sessionKey} />
}

function FeedbackTriageWorkspace({ sessionKey }: Readonly<{ sessionKey: string }>) {
  const queryClient = useQueryClient()
  const feedbackQueryKey = ['feedback-enriched', sessionKey] as const
  const [view, setView] = useState<FeedbackView>('all')
  const [rating, setRating] = useState('all')
  const [kind, setKind] = useState('all')
  const [source, setSource] = useState<FeedbackSource>('all')
  const [range, setRange] = useState<FeedbackRange>('all')
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(1)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [mobileDetail, setMobileDetail] = useState(false)
  const [candidatesOpen, setCandidatesOpen] = useState(false)
  const [busyById, setBusyById] = useState<Record<string, 'archive' | 'case'>>({})
  const [results, setResults] = useState<Record<string, ActionResult>>({})
  const requestsRef = useRef(new Set<string>())
  const mountedRef = useRef(false)
  const readerVisitRef = useRef<object>({})
  useLayoutEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
    }
  }, [])
  const queueButtons = useRef(new Map<string, HTMLButtonElement>())
  const queueScroll = useRef<HTMLDivElement>(null)
  const query = useQuery({
    queryKey: feedbackQueryKey,
    queryFn: ({ signal }) => loadFeedback(signal),
    staleTime: 5_000,
    retry: false,
  })
  const items = query.data?.items
  const filtered = useMemo(
    () => (items === undefined ? [] : filterFeedback(items, { view, rating, kind, source, range, search })),
    [items, view, rating, kind, source, range, search],
  )
  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE))
  const safePage = Math.min(page, totalPages)
  const paginated = filtered.slice((safePage - 1) * PAGE_SIZE, safePage * PAGE_SIZE)
  const selected = paginated.find((item) => item.id === selectedId) ?? paginated[0]
  useLayoutEffect(() => {
    readerVisitRef.current = {}
  }, [selected?.id])
  const position = selected ? filtered.findIndex((item) => item.id === selected.id) : -1
  const activeFilters =
    view !== 'all' || rating !== 'all' || kind !== 'all' || source !== 'all' || range !== 'all' || search.trim() !== ''
  const extraFilters = kind !== 'all' || source !== 'all'
  const statusCounts = useMemo(() => {
    if (items === undefined) return undefined
    let archived = 0
    let priority = 0
    for (const item of items) {
      if (isFeedbackArchived(item)) archived += 1
      else if (getFeedbackKind(item) === 'negative') priority += 1
    }
    return { total: items.length, pending: items.length - archived, priority, archived }
  }, [items])
  const count = statusCounts?.total
  const waitingForNetwork = query.isPending && query.isPaused

  const resetPosition = () => {
    setPage(1)
    setSelectedId(null)
    queueScroll.current?.scrollTo({ top: 0 })
  }
  const clearFilters = () => {
    setView('all')
    setRating('all')
    setKind('all')
    setSource('all')
    setRange('all')
    setSearch('')
    resetPosition()
  }
  const selectRecord = (id: string) => {
    setSelectedId(id)
    setMobileDetail(true)
  }
  const navigateRecord = (offset: number) => {
    const target = filtered[position + offset]
    if (!target) return
    setPage(Math.floor((position + offset) / PAGE_SIZE) + 1)
    setSelectedId(target.id)
    requestAnimationFrame(() => queueButtons.current.get(target.id)?.scrollIntoView({ block: 'nearest' }))
  }
  const changePage = (next: number) => {
    setPage(next)
    setSelectedId(null)
    queueScroll.current?.scrollTo({ top: 0 })
  }
  const runAction = async (item: MessageFeedbackEnriched, action: 'archive' | 'case') => {
    const isSessionCurrent = () => sessionKey === getAuthSessionKey()
    if (!isSessionCurrent() || requestsRef.current.has(item.id)) return
    requestsRef.current.add(item.id)
    const visit = readerVisitRef.current
    const ownsView = () => mountedRef.current && isSessionCurrent() && readerVisitRef.current === visit
    setBusyById((previous) => ({ ...previous, [item.id]: action }))
    setResults((previous) => ({ ...previous, [item.id]: { ...previous[item.id], error: undefined } }))
    try {
      if (action === 'archive') {
        const response = await feedbackApi.update(item.id, { archived: !isFeedbackArchived(item) })
        if (!isSessionCurrent()) return
        await queryClient.cancelQueries({ queryKey: feedbackQueryKey, exact: true })
        if (!isSessionCurrent()) return
        queryClient.setQueryData<Awaited<ReturnType<typeof loadFeedback>>>(feedbackQueryKey, (previous) =>
          previous
            ? {
                ...previous,
                items: previous.items.map((record) => (record.id === item.id ? { ...record, ...response } : record)),
              }
            : previous,
        )
        await queryClient.invalidateQueries({ queryKey: feedbackQueryKey, exact: true, refetchType: 'all' })
        if (ownsView()) toast.success(isFeedbackArchived(item) ? '已取消归档' : '已归档反馈')
      } else {
        const regression = await feedbackApi.toRegressionCase(item.id, { include_document_scope: true })
        if (!isSessionCurrent()) return
        if (mountedRef.current) setResults((previous) => ({ ...previous, [item.id]: { caseId: regression.id } }))
        await queryClient.invalidateQueries({ queryKey: feedbackQueryKey, exact: true, refetchType: 'all' })
        if (ownsView()) toast.success('已创建回归用例')
      }
    } catch (error) {
      if (!mountedRef.current || !isSessionCurrent()) return
      const fallback = action === 'case' ? '创建回归用例失败' : isFeedbackArchived(item) ? '取消归档失败' : '归档失败'
      setResults((previous) => ({
        ...previous,
        [item.id]: { ...previous[item.id], error: `${fallback}：${formatApiError(error, '请重试')}` },
      }))
    } finally {
      requestsRef.current.delete(item.id)
      if (mountedRef.current)
        setBusyById((previous) => {
          const next = { ...previous }
          delete next[item.id]
          return next
        })
    }
  }

  return (
    <AppFrame showBackground={false} withDocumentViewerPadding mainClassName="min-w-0">
      <div className={styles.shell}>
        <header className={styles.header} data-testid="page-title-shell">
          <div className={styles.heading}>
            <PageTitleIcon name="feedback-quality" />
            <h1>反馈质检</h1>
            <span className={styles.headerView}>
              <Inbox aria-hidden="true" />
              收件箱
            </span>
          </div>
          <div className={styles.headerActions}>
            <Button
              variant="ghost"
              className={styles.candidatesButton}
              aria-label="反哺候选"
              onClick={() => setCandidatesOpen(true)}
            >
              <TestTube2 />
              <span>反哺候选</span>
            </Button>
            <Select
              value={range}
              onValueChange={(value) => {
                setRange(value as FeedbackRange)
                resetPosition()
              }}
            >
              <SelectTrigger className={styles.rangeControl} aria-label="反馈时间">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {Object.entries(RANGE_LABELS).map(([value, label]) => (
                  <SelectItem key={value} value={value}>
                    {label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <LoadingButton
              variant="ghost"
              size="icon"
              className={styles.refresh}
              onClick={() => void query.refetch()}
              loading={query.isFetching}
              aria-label="刷新反馈"
            >
              <RefreshCw />
            </LoadingButton>
          </div>
        </header>
        <div className={styles.workspace} data-detail-open={mobileDetail && !!selected}>
          <aside className={styles.queue} data-feedback-queue aria-label="反馈队列">
            <div className={styles.queueTools}>
              <div className={styles.searchRow}>
                <SearchInput
                  value={search}
                  onValueChange={(value) => {
                    setSearch(value)
                    resetPosition()
                  }}
                  placeholder="搜索问题、反馈或用户"
                  aria-label="搜索反馈"
                  containerClassName={styles.search}
                  inputClassName={styles.searchInput}
                />
                <Popover>
                  <PopoverTrigger asChild>
                    <Button
                      variant="ghost"
                      size="icon"
                      className={styles.filterButton}
                      data-active={extraFilters}
                      aria-label="更多反馈筛选"
                    >
                      <Filter />
                    </Button>
                  </PopoverTrigger>
                  <PopoverContent align="start" className={styles.filterPopover}>
                    <label>
                      反馈类型
                      <Select
                        value={kind}
                        onValueChange={(value) => {
                          setKind(value)
                          resetPosition()
                        }}
                      >
                        <SelectTrigger aria-label="反馈类型">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="all">全部类型</SelectItem>
                          <SelectItem value="negative">低分反馈</SelectItem>
                          <SelectItem value="neutral">中立反馈</SelectItem>
                          <SelectItem value="positive">正向反馈</SelectItem>
                        </SelectContent>
                      </Select>
                    </label>
                    <label>
                      反馈来源
                      <Select
                        value={source}
                        onValueChange={(value) => {
                          setSource(value as FeedbackSource)
                          resetPosition()
                        }}
                      >
                        <SelectTrigger aria-label="反馈来源">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {Object.entries(SOURCE_LABELS).map(([value, label]) => (
                            <SelectItem key={value} value={value}>
                              {label}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </label>
                    {activeFilters && (
                      <Button variant="ghost" onClick={clearFilters}>
                        清除全部筛选
                      </Button>
                    )}
                  </PopoverContent>
                </Popover>
              </div>
              <div className={styles.queueFilters}>
                <Select
                  value={view}
                  onValueChange={(value) => {
                    setView(value as FeedbackView)
                    resetPosition()
                  }}
                >
                  <SelectTrigger className={styles.filterControl} aria-label="反馈处理状态">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">全部反馈{count === undefined ? '' : ` · ${count}`}</SelectItem>
                    <SelectItem value="pending">待分析{statusCounts && ` · ${statusCounts.pending}`}</SelectItem>
                    <SelectItem value="priority">优先分析{statusCounts && ` · ${statusCounts.priority}`}</SelectItem>
                    <SelectItem value="archived">已归档{statusCounts && ` · ${statusCounts.archived}`}</SelectItem>
                  </SelectContent>
                </Select>
                <Select
                  value={rating}
                  onValueChange={(value) => {
                    setRating(value)
                    resetPosition()
                  }}
                >
                  <SelectTrigger className={styles.filterControl} aria-label="反馈评分">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">评分 · 全部</SelectItem>
                    {[1, 2, 3, 4, 5].map((value) => (
                      <SelectItem key={value} value={String(value)}>
                        {value} / 5 分
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              {activeFilters && (
                <Button variant="ghost" className={styles.clearFilters} onClick={clearFilters}>
                  清除筛选
                </Button>
              )}
            </div>
            {query.isError && (
              <div className={styles.queueError} role="alert">
                <AlertCircle />
                <span>反馈加载失败</span>
                <Button variant="ghost" onClick={() => void query.refetch()}>
                  重试
                </Button>
                <details>
                  <summary>错误详情</summary>
                  {formatApiError(query.error, '请稍后重试')}
                </details>
              </div>
            )}
            <div className={styles.queueList} ref={queueScroll} aria-busy={query.isFetching}>
              {waitingForNetwork ? (
                <p className={styles.queueState} role="status">
                  等待网络连接
                </p>
              ) : query.isPending ? (
                <div role="status">
                  <span className="sr-only">正在加载反馈…</span>
                  <div aria-hidden="true">
                    {[0, 1, 2, 3].map((index) => (
                      <div key={index} className={`${styles.queueItem} pointer-events-none`}>
                        <Skeleton className="h-4 w-3/4" />
                        <div className={styles.queueMeta}>
                          <Skeleton className="h-3 w-12" />
                          <Skeleton className="h-3 w-16" />
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              ) : paginated.length ? (
                paginated.map((item) => (
                  <button
                    key={item.id}
                    ref={(element) => {
                      if (element) queueButtons.current.set(item.id, element)
                      else queueButtons.current.delete(item.id)
                    }}
                    type="button"
                    className={styles.queueItem}
                    data-feedback-item={item.id}
                    aria-current={selected?.id === item.id ? 'true' : undefined}
                    onClick={() => selectRecord(item.id)}
                  >
                    <span className={styles.queueQuestion}>{getFeedbackLabel(item)}</span>
                    <span className={styles.queueMeta}>
                      <Rating item={item} />
                      <span className={styles.queueIssue}>
                        {isFeedbackArchived(item) ? '已归档' : getFeedbackIssue(item)}
                      </span>
                      <time dateTime={item.created_at}>{formatFeedbackTime(item.created_at)}</time>
                    </span>
                  </button>
                ))
              ) : (
                !query.isError && (
                  <div className={styles.queueState} data-empty={!items?.length}>
                    <Search />
                    <p>{items?.length ? '没有匹配的反馈' : '暂无反馈'}</p>
                    {activeFilters && (
                      <Button variant="ghost" onClick={clearFilters}>
                        清除筛选
                      </Button>
                    )}
                  </div>
                )
              )}
            </div>
            <footer className={styles.queueFooter}>
              <span>
                {count === undefined
                  ? '—'
                  : activeFilters
                    ? `筛选 ${filtered.length} / ${count} 条`
                    : `共 ${count} 条反馈`}
              </span>
              <div className={styles.pagination}>
                <span>
                  {items === undefined ? '—' : filtered.length === 0 ? '0 / 0' : `${safePage} / ${totalPages}`}
                </span>
                <Button
                  variant="ghost"
                  size="icon"
                  disabled={safePage <= 1}
                  aria-label="上一页反馈"
                  onClick={() => changePage(safePage - 1)}
                >
                  <ChevronLeft />
                </Button>
                <Button
                  variant="ghost"
                  size="icon"
                  disabled={safePage >= totalPages}
                  aria-label="下一页反馈"
                  onClick={() => changePage(safePage + 1)}
                >
                  <ChevronRight />
                </Button>
              </div>
            </footer>
          </aside>
          {waitingForNetwork ? null : query.isPending ? (
            <FeedbackReaderLoading />
          ) : selected ? (
            <FeedbackReader
              key={selected.id}
              item={selected}
              sessionKey={sessionKey}
              position={position}
              total={filtered.length}
              busy={busyById[selected.id] ?? null}
              result={results[selected.id]}
              onPrevious={() => navigateRecord(-1)}
              onNext={() => navigateRecord(1)}
              onBack={() => {
                setMobileDetail(false)
                requestAnimationFrame(() => queueButtons.current.get(selected.id)?.focus())
              }}
              onArchive={() => void runAction(selected, 'archive')}
              onCreate={() => void runAction(selected, 'case')}
            />
          ) : (
            <div className={styles.emptyReader}>
              {query.isError ? (
                <>
                  <AlertCircle />
                  <h2>暂时无法读取反馈</h2>
                  <p>可在左侧重试。</p>
                </>
              ) : (
                <>
                  <Inbox />
                  <h2>{items?.length ? '没有匹配的反馈' : '暂无反馈'}</h2>
                  <p>{items?.length ? '调整左侧筛选后再查看。' : '用户提交评分或意见后，会显示在这里。'}</p>
                  {activeFilters && (
                    <Button variant="outline" onClick={clearFilters}>
                      清除筛选
                    </Button>
                  )}
                </>
              )}
            </div>
          )}
        </div>
        <FeedbackCandidatesDialog open={candidatesOpen} onOpenChange={setCandidatesOpen} />
      </div>
    </AppFrame>
  )
}
