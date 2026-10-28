'use client'
import { FeedbackToast } from '@/components/feedback-toast'

import { useMemo, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertCircle, Archive, ArrowLeft, ArrowUpRight, CheckCheck, ChevronLeft, ChevronRight, Copy, Filter, Mail as Inbox, Loader2, MessageSquare, MoreHorizontal, RefreshCw, Search, Star, TestTube2, ThumbsDown, ThumbsUp, UserRound } from '@/components/icons'
import { toast } from 'sonner'

import { AppFrame } from '@/components/app-frame'
import { PageTitleIcon } from '@/components/ui/page-title-icon'
import { Button } from '@/components/ui/button'
import { SearchInput } from '@/components/ui/search-input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { FileTypeIcon } from '@/components/ui/file-type-icon'
import { Link } from '@/i18n/navigation'
import { chatApi, feedbackApi } from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'
import { useDocumentView } from '@/store/document-view'
import type { MessageFeedbackEnriched } from '@/types'
import { archived, displayText, feedbackContext, feedbackIssue, feedbackKind, feedbackQuestion, feedbackSource, feedbackStatus, feedbackTime, filterFeedback, loadFeedback, RANGE_LABELS, SOURCE_LABELS, type FeedbackRange, type FeedbackSource, type FeedbackView } from './feedback-inbox-model'
import { FeedbackCandidatesDialog } from './feedback-candidates-dialog'
import styles from './feedback.module.css'

const PAGE_SIZE = 20
type ActionResult = { error?: string; caseId?: string }

function Rating({ item }: Readonly<{ item: MessageFeedbackEnriched }>) {
  const kind = feedbackKind(item)
  const Icon = kind === 'positive' ? ThumbsUp : kind === 'negative' ? ThumbsDown : Star
  return <span className={styles.rating} data-kind={kind} aria-label={`评分 ${item.rating} / 5`}><Icon aria-hidden="true" />{item.rating}<span>/ 5</span></span>
}
function StateLabel({ item }: Readonly<{ item: MessageFeedbackEnriched }>) {
  return <span className={styles.stateLabel} data-state={archived(item) ? 'archived' : feedbackKind(item)}>{feedbackStatus(item)}</span>
}

function FeedbackReader({ item, position, total, busy, locked, result, onPrevious, onNext, onBack, onArchive, onCreate }: Readonly<{
  item: MessageFeedbackEnriched; position: number; total: number; busy: 'archive' | 'case' | null; locked: boolean; result?: ActionResult
  onPrevious: () => void; onNext: () => void; onBack: () => void; onArchive: () => void; onCreate: () => void
}>) {
  const { openDocument } = useDocumentView()
  const context = useQuery({
    queryKey: ['feedback-conversation', item.conversation_id],
    queryFn: () => chatApi.getMessages(item.conversation_id),
    staleTime: 60_000,
    retry: false,
  })
  const original = feedbackContext(context.data?.messages || [], item.message_id)
  const citations = original?.answer.citations || []
  const answer = displayText(item.message_content, original?.answer.content)
  const question = displayText(original?.question) || feedbackQuestion(item)
  const copy = async () => {
    try { await navigator.clipboard.writeText(JSON.stringify(item, null, 2)); toast.success('已复制反馈详情') }
    catch (error) { toast.error(formatApiError(error, '复制失败')) }
  }

  return <section className={styles.reader} data-feedback-reader aria-label="反馈详情">
    <div className={styles.readerScroll} tabIndex={0} aria-label="反馈内容">
      <article className={styles.reading} key={item.id}>
        <div className={styles.recordBar}>
          <Button variant="ghost" size="icon" className={styles.back} onClick={onBack} aria-label="返回反馈队列"><ArrowLeft /></Button>
          <span className={styles.recordId} title={item.id}>{item.id.slice(0, 8)}</span><StateLabel item={item} />
          <div className={styles.recordNav}>
            <span>{position + 1} / {total}</span>
            <Button variant="ghost" size="icon" onClick={onPrevious} disabled={position === 0} aria-label="上一条反馈"><ChevronLeft /></Button>
            <Button variant="ghost" size="icon" onClick={onNext} disabled={position >= total - 1} aria-label="下一条反馈"><ChevronRight /></Button>
            <DropdownMenu><DropdownMenuTrigger asChild><Button variant="ghost" size="icon" aria-label="反馈更多操作"><MoreHorizontal /></Button></DropdownMenuTrigger><DropdownMenuContent align="end"><DropdownMenuItem onSelect={() => void copy()}><Copy />复制详情</DropdownMenuItem></DropdownMenuContent></DropdownMenu>
          </div>
        </div>
        <h2 className={styles.question}>{question}</h2>
        <div className={styles.context}>
          <span><UserRound aria-hidden="true" />{item.account_id || '未知用户'}</span>
          <span>{SOURCE_LABELS[feedbackSource(item)]}</span>
          <time dateTime={item.created_at} title={feedbackTime(item.created_at, true)}>{feedbackTime(item.created_at)}</time>
          {typeof item.extra?.dataset_name === 'string' && <span>知识库 · {item.extra.dataset_name}</span>}
        </div>
        <section className={styles.section}>
          <div className={styles.sectionHeading}><h3>用户反馈</h3><span className={styles.tag}>{feedbackIssue(item)}</span><Rating item={item} /></div>
          <p className={item.reason ? styles.copy : styles.missing}>{item.reason || '用户未填写反馈原因。'}</p>
          {!!item.tags?.length && <div className={styles.tags}>{item.tags.map((tag, index) => <span key={`${tag}-${index}`} className={styles.tag}>{tag}</span>)}</div>}
        </section>
        <section className={styles.section}>
          <div className={styles.sectionHeading}><h3>原回答</h3></div>
          <div className={answer ? styles.copy : styles.missing}>{answer || (context.isPending ? '正在读取原回答…' : '未记录原回答。')}</div>
        </section>
        <section className={styles.section}>
          <div className={styles.sectionHeading}><h3>期望回答</h3></div>
          <div className={item.expected_answer ? styles.copy : styles.missing}>{item.expected_answer || '用户未填写期望回答。'}</div>
        </section>
        <section className={styles.section}>
          <div className={styles.sectionHeading}><h3>原回答引用</h3>{original && <span className={styles.sectionMeta}>{citations.length} 个来源</span>}</div>
          {context.isPending ? <p className={styles.missing} role="status">正在读取会话引用…</p> : context.isError ? <div className={styles.contextError}><p>会话内容加载失败，仍可查看已记录的反馈。</p><Button variant="ghost" onClick={() => void context.refetch()}>重新读取</Button></div> : !original ? <p className={styles.missing}>未找到这条原回答的会话记录，可前往原会话查看。</p> : !citations.length ? <p className={styles.missing}>这条回答没有引用来源。</p> : <ol className={styles.sources}>{citations.map((citation, index) => <li key={`${citation.document_id}-${citation.chunk_id || index}`}>
            <span className={styles.sourceOrder}>{index + 1}</span><FileTypeIcon filename={citation.document_name} />
            <div className={styles.sourceContent}>
              <Button variant="link" className={styles.sourceTitle} onClick={() => openDocument(citation.document_id, citation.chunk_id)}>{citation.document_name || '未命名文档'}<ArrowUpRight aria-hidden="true" /></Button>
              {(citation.page_number || citation.header_path) && <span className={styles.sourceLocation}>{[citation.page_number ? `第 ${citation.page_number} 页` : '', citation.header_path].filter(Boolean).join(' · ')}</span>}
              {citation.chunk_content && <p className={styles.sourceExcerpt}>{citation.chunk_content}</p>}
            </div>
          </li>)}</ol>}
        </section>
      </article>
    </div>
    <footer className={styles.recordFooter} data-task-center-dock>
      <FeedbackToast type="error" message={result?.error} id={`feedback-action-${item.id}`} />
      <div className={styles.actions}>
        <StateLabel item={item} />
        <Button asChild variant="outline"><Link href={`/history?id=${encodeURIComponent(item.conversation_id)}`}><MessageSquare />原会话</Link></Button>
        {result?.caseId ? <Button asChild variant="outline"><Link href="/evaluations?tab=regression" title={`用例 ${result.caseId}`}><TestTube2 />查看回归用例</Link></Button> : <Button variant="outline" onClick={onCreate} disabled={locked}>{busy === 'case' ? <Loader2 className="animate-spin motion-reduce:animate-none" /> : <TestTube2 />}{busy === 'case' ? '正在创建…' : '创建回归用例'}</Button>}
        <Button onClick={onArchive} disabled={locked}>{busy === 'archive' ? <Loader2 className="animate-spin motion-reduce:animate-none" /> : archived(item) ? <Archive /> : <CheckCheck />}{busy === 'archive' ? '正在保存…' : archived(item) ? '取消归档' : '归档反馈'}</Button>
      </div>
    </footer>
  </section>
}

export default function FeedbackTriagePage() {
  const queryClient = useQueryClient()
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
  const [busy, setBusy] = useState<{ id: string; kind: 'archive' | 'case' } | null>(null)
  const [results, setResults] = useState<Record<string, ActionResult>>({})
  const mutationLock = useRef(false)
  const queueButtons = useRef(new Map<string, HTMLButtonElement>())
  const queueScroll = useRef<HTMLDivElement>(null)
  const query = useQuery({ queryKey: ['feedback-enriched'], queryFn: ({ signal }) => loadFeedback(signal), staleTime: 5_000, retry: false })
  const items = query.data?.items
  const filtered = useMemo(() => filterFeedback(items || [], { view, rating, kind, source, range, search }), [items, view, rating, kind, source, range, search])
  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE))
  const safePage = Math.min(page, totalPages)
  const paginated = filtered.slice((safePage - 1) * PAGE_SIZE, safePage * PAGE_SIZE)
  const selected = paginated.find(item => item.id === selectedId) || paginated[0]
  const position = selected ? filtered.findIndex(item => item.id === selected.id) : -1
  const activeFilters = view !== 'all' || rating !== 'all' || kind !== 'all' || source !== 'all' || range !== 'all' || !!search.trim()
  const extraFilters = kind !== 'all' || source !== 'all'
  const count = items?.length
  const pending = items?.filter(item => !archived(item)).length
  const priority = items?.filter(item => !archived(item) && feedbackKind(item) === 'negative').length
  const archivedCount = items?.filter(archived).length

  const resetPosition = () => { setPage(1); setSelectedId(null); queueScroll.current?.scrollTo({ top: 0 }) }
  const clearFilters = () => { setView('all'); setRating('all'); setKind('all'); setSource('all'); setRange('all'); setSearch(''); resetPosition() }
  const selectRecord = (id: string) => { setSelectedId(id); setMobileDetail(true) }
  const navigateRecord = (offset: number) => {
    const target = filtered[position + offset]
    if (!target) return
    setPage(Math.floor((position + offset) / PAGE_SIZE) + 1)
    setSelectedId(target.id)
    requestAnimationFrame(() => queueButtons.current.get(target.id)?.scrollIntoView({ block: 'nearest' }))
  }
  const changePage = (next: number) => { setPage(next); setSelectedId(null); queueScroll.current?.scrollTo({ top: 0 }) }
  const runAction = async (item: MessageFeedbackEnriched, action: 'archive' | 'case') => {
    if (mutationLock.current) return
    mutationLock.current = true
    setBusy({ id: item.id, kind: action })
    setResults(previous => ({ ...previous, [item.id]: { ...previous[item.id], error: undefined } }))
    try {
      if (action === 'archive') {
        const response = await feedbackApi.update(item.id, { archived: !archived(item) })
        queryClient.setQueryData<Awaited<ReturnType<typeof loadFeedback>>>(['feedback-enriched'], previous => previous ? { ...previous, items: previous.items.map(record => record.id === item.id ? { ...record, ...response, extra: { ...record.extra, ...response.extra } } : record) } : previous)
        await queryClient.invalidateQueries({ queryKey: ['feedback-enriched'] })
        toast.success(archived(item) ? '已取消归档' : '已归档反馈')
      } else {
        const regression = await feedbackApi.toRegressionCase(item.id, { include_document_scope: true })
        setResults(previous => ({ ...previous, [item.id]: { caseId: regression.id } }))
        toast.success('已创建回归用例')
      }
    } catch (error) {
      const fallback = action === 'case' ? '创建回归用例失败' : archived(item) ? '取消归档失败' : '归档失败'
      setResults(previous => ({ ...previous, [item.id]: { ...previous[item.id], error: `${fallback}：${formatApiError(error, '请重试')}` } }))
    } finally { mutationLock.current = false; setBusy(null) }
  }

  return <AppFrame showBackground={false} withDocumentViewerPadding mainClassName="min-w-0">
    <div className={styles.shell}>
      <header className={styles.header} data-testid="page-title-shell">
        <div className={styles.heading}><PageTitleIcon name="feedback-quality" /><h1>反馈质检</h1><span className={styles.headerView}><Inbox aria-hidden="true" />收件箱</span></div>
        <div className={styles.headerActions}>
          <Button variant="ghost" className={styles.candidatesButton} onClick={() => setCandidatesOpen(true)}><TestTube2 /><span>反哺候选</span></Button>
          <Select value={range} onValueChange={value => { setRange(value as FeedbackRange); resetPosition() }}><SelectTrigger className={styles.rangeControl} aria-label="反馈时间"><SelectValue /></SelectTrigger><SelectContent>{Object.entries(RANGE_LABELS).map(([value, label]) => <SelectItem key={value} value={value}>{label}</SelectItem>)}</SelectContent></Select>
          <Button variant="ghost" size="icon" className={styles.refresh} onClick={() => void query.refetch()} disabled={query.isFetching} aria-label="刷新反馈"><RefreshCw className={query.isFetching ? 'animate-spin motion-reduce:animate-none' : ''} /></Button>
        </div>
      </header>
      <div className={styles.workspace} data-detail-open={mobileDetail && !!selected}>
        <aside className={styles.queue} data-feedback-queue aria-label="反馈队列">
          <div className={styles.queueTools}>
            <div className={styles.searchRow}>
              <SearchInput value={search} onValueChange={value => { setSearch(value); resetPosition() }} placeholder="搜索问题、反馈或用户" aria-label="搜索反馈" containerClassName={styles.search} inputClassName={styles.searchInput} />
              <Popover><PopoverTrigger asChild><Button variant="ghost" size="icon" className={styles.filterButton} data-active={extraFilters} aria-label="更多反馈筛选"><Filter /></Button></PopoverTrigger><PopoverContent align="start" className={styles.filterPopover}>
                <label>反馈类型<Select value={kind} onValueChange={value => { setKind(value); resetPosition() }}><SelectTrigger aria-label="反馈类型"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="all">全部类型</SelectItem><SelectItem value="negative">低分反馈</SelectItem><SelectItem value="neutral">中立反馈</SelectItem><SelectItem value="positive">正向反馈</SelectItem></SelectContent></Select></label>
                <label>反馈来源<Select value={source} onValueChange={value => { setSource(value as FeedbackSource); resetPosition() }}><SelectTrigger aria-label="反馈来源"><SelectValue /></SelectTrigger><SelectContent>{Object.entries(SOURCE_LABELS).map(([value, label]) => <SelectItem key={value} value={value}>{label}</SelectItem>)}</SelectContent></Select></label>
                {activeFilters && <Button variant="ghost" onClick={clearFilters}>清除全部筛选</Button>}
              </PopoverContent></Popover>
            </div>
            <div className={styles.queueFilters}>
              <Select value={view} onValueChange={value => { setView(value as FeedbackView); resetPosition() }}><SelectTrigger className={styles.filterControl} aria-label="反馈处理状态"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="all">全部反馈{count === undefined ? '' : ` · ${count}`}</SelectItem><SelectItem value="pending">待分析{pending === undefined ? '' : ` · ${pending}`}</SelectItem><SelectItem value="priority">优先分析{priority === undefined ? '' : ` · ${priority}`}</SelectItem><SelectItem value="archived">已归档{archivedCount === undefined ? '' : ` · ${archivedCount}`}</SelectItem></SelectContent></Select>
              <Select value={rating} onValueChange={value => { setRating(value); resetPosition() }}><SelectTrigger className={styles.filterControl} aria-label="反馈评分"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="all">评分 · 全部</SelectItem>{[1, 2, 3, 4, 5].map(value => <SelectItem key={value} value={String(value)}>{value} / 5 分</SelectItem>)}</SelectContent></Select>
            </div>
            {activeFilters && <Button variant="ghost" className={styles.clearFilters} onClick={clearFilters}>清除筛选</Button>}
          </div>
          {query.isError && <div className={styles.queueError} role="alert"><AlertCircle /><span>反馈加载失败</span><Button variant="ghost" onClick={() => void query.refetch()}>重试</Button><details><summary>错误详情</summary>{formatApiError(query.error, '请稍后重试')}</details></div>}
          <div className={styles.queueList} ref={queueScroll} aria-busy={query.isFetching}>
            {query.isPending ? <div className={styles.queueState} role="status"><Loader2 className="animate-spin motion-reduce:animate-none" /><p>正在加载反馈…</p></div> : paginated.length ? paginated.map(item => <button key={item.id} ref={element => { if (element) queueButtons.current.set(item.id, element); else queueButtons.current.delete(item.id) }} type="button" className={styles.queueItem} data-feedback-item={item.id} aria-current={selected?.id === item.id ? 'true' : undefined} onClick={() => selectRecord(item.id)}>
              <span className={styles.queueQuestion}>{feedbackQuestion(item)}</span>
              <span className={styles.queueMeta}><Rating item={item} /><span className={styles.queueIssue}>{archived(item) ? '已归档' : feedbackIssue(item)}</span><time dateTime={item.created_at}>{feedbackTime(item.created_at)}</time></span>
            </button>) : !query.isError && <div className={styles.queueState} data-empty={!items?.length}><Search /><p>{items?.length ? '没有匹配的反馈' : '暂无反馈'}</p>{activeFilters && <Button variant="ghost" onClick={clearFilters}>清除筛选</Button>}</div>}
          </div>
          <footer className={styles.queueFooter}><span>{count === undefined ? '—' : activeFilters ? `筛选 ${filtered.length} / ${count} 条` : `共 ${count} 条反馈`}</span><div className={styles.pagination}><span>{safePage} / {totalPages}</span><Button variant="ghost" size="icon" disabled={safePage <= 1} aria-label="上一页反馈" onClick={() => changePage(safePage - 1)}><ChevronLeft /></Button><Button variant="ghost" size="icon" disabled={safePage >= totalPages} aria-label="下一页反馈" onClick={() => changePage(safePage + 1)}><ChevronRight /></Button></div></footer>
        </aside>
        {selected ? <FeedbackReader key={selected.id} item={selected} position={position} total={filtered.length} busy={busy?.id === selected.id ? busy.kind : null} locked={!!busy} result={results[selected.id]} onPrevious={() => navigateRecord(-1)} onNext={() => navigateRecord(1)} onBack={() => { setMobileDetail(false); requestAnimationFrame(() => queueButtons.current.get(selected.id)?.focus()) }} onArchive={() => void runAction(selected, 'archive')} onCreate={() => void runAction(selected, 'case')} /> : <div className={styles.emptyReader}>
          {query.isPending ? <><Loader2 className="animate-spin motion-reduce:animate-none" /><h2>正在读取反馈</h2></> : query.isError ? <><AlertCircle /><h2>暂时无法读取反馈</h2><p>可在左侧重试。</p></> : <><Inbox /><h2>{items?.length ? '没有匹配的反馈' : '暂无反馈'}</h2><p>{items?.length ? '调整左侧筛选后再查看。' : '用户提交评分或意见后，会显示在这里。'}</p>{activeFilters && <Button variant="outline" onClick={clearFilters}>清除筛选</Button>}</>}
        </div>}
      </div>
      <FeedbackCandidatesDialog open={candidatesOpen} onOpenChange={setCandidatesOpen} />
    </div>
  </AppFrame>
}
