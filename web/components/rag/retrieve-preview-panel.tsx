'use client'

import { useRef, useState, type ReactNode } from 'react'
import Link from 'next/link'
import { toast } from 'sonner'
import { ArrowLeft, ArrowUp, ArrowUpRight, ChevronLeft, ChevronRight, Copy, File, FileMarkdown, FilePdf, Fingerprint, History, Loader2, Search } from '@/components/icons'
import { AuthImage } from '@/components/auth-image'
import { KnowledgeRetrievalPanel } from '@/components/knowledge/knowledge-retrieval-panel'
import { Button } from '@/components/ui/button'
import { IconButton } from '@/components/ui/icon-button'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle, SheetTrigger } from '@/components/ui/sheet'
import { resolveSafeCitationImageUrl } from '@/lib/citation-images'
import { getDocumentPreviewAnchorFromCitation } from '@/lib/document-preview-anchor'
import { prefetchDocumentView } from '@/lib/document-view-prefetch'
import { cn, detachPromise } from '@/lib/utils'
import { useDocumentView } from '@/store/document-view'
import { useRetrievalPreview, type RetrievePreviewCitation, type RetrievalRun } from './use-retrieval-preview'
import styles from './retrieve-preview-panel.module.css'

type RetrievePreviewPanelProps = {
  selectedDatasetId: string | null | undefined
  availableDatasetIds?: readonly string[]
  scopeLabel?: string
  aggregateDocuments?: number
  aggregateChunks?: number
  scopeLoading?: boolean
  onGoToDocuments?: () => void
  className?: string
}

function getHitScore(hit: RetrievePreviewCitation): string {
  const score = hit.score ?? hit.relevance_score ?? hit.retrieval_score
  return typeof score === 'number' && Number.isFinite(score) ? score.toFixed(3) : '—'
}

function matchedTerms(hit: RetrievePreviewCitation): string[] {
  return Array.isArray(hit.matched_terms)
    ? [...new Set(hit.matched_terms.filter((term): term is string => typeof term === 'string' && Boolean(term.trim())))].slice(0, 24)
    : []
}

function HighlightedText({ text, terms }: Readonly<{ text: string; terms: string[] }>) {
  if (!terms.length) return text
  const escaped = [...terms].sort((a, b) => b.length - a.length).map(term => term.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
  const pattern = new RegExp(`(${escaped.join('|')})`, 'gi')
  const matches = new Set(terms.map(term => term.toLocaleLowerCase()))
  return text.split(pattern).map((part, index) => matches.has(part.toLocaleLowerCase()) ? <mark key={index}>{part}</mark> : part)
}

function DocumentMark({ name }: Readonly<{ name: string }>) {
  const Icon = /\.pdf$/i.test(name) ? FilePdf : /\.(md|mdx|markdown)$/i.test(name) ? FileMarkdown : File
  return <Icon appearance="color" aria-hidden="true" className={styles.documentIcon} />
}

function HistoryList({ items, currentId, disabled, onSelect, onClear }: Readonly<{
  items: RetrievalRun[]; currentId?: number; disabled: boolean
  onSelect: (run: RetrievalRun) => void; onClear: () => void
}>) {
  return <>
    <header className={styles.historyHeader}>
      <h2>最近检索</h2>
      <Button variant="ghost" disabled={!items.length} onClick={onClear}>清空</Button>
    </header>
    <div className={styles.historyList}>
      {items.length ? items.map(item => <button
        type="button" key={item.id} className={styles.historyItem} disabled={disabled}
        aria-current={item.id === currentId ? 'true' : undefined} onClick={() => onSelect(item)}
      >
        <span className={styles.historyQuery}>{item.query}</span>
        <span className={styles.historyMeta}>
          <time dateTime={new Date(item.timestamp).toISOString()}>{new Date(item.timestamp).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false })}</time>
          <span>· {item.hits.length} 个片段</span>
        </span>
      </button>) : <p className={styles.historyEmpty}>检索后，问题会显示在这里。</p>}
    </div>
    <footer className={styles.historyFooter}><span>本次会话</span><Link href="/settings#sec-rag">检索设置<ArrowUpRight className="size-3.5" /></Link></footer>
  </>
}

function EmptyState({ icon, title, description, children }: Readonly<{ icon: ReactNode; title: string; description: string; children?: ReactNode }>) {
  return <div className={styles.emptyState}>
    <div className={styles.emptyIcon}>{icon}</div>
    <h3>{title}</h3><p>{description}</p>{children}
  </div>
}

export function RetrievePreviewPanel({
  selectedDatasetId, availableDatasetIds, scopeLabel = '全部数据集',
  aggregateDocuments, aggregateChunks = 0, scopeLoading = false, onGoToDocuments, className,
}: Readonly<RetrievePreviewPanelProps>) {
  const preview = useRetrievalPreview(selectedDatasetId, availableDatasetIds)
  const { openDocument } = useDocumentView()
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const detailRef = useRef<HTMLElement>(null)
  const selectedHitRef = useRef<HTMLButtonElement>(null)
  const auditTriggerRef = useRef<HTMLButtonElement>(null)
  const [selection, setSelection] = useState<{ runId: number; index: number } | null>(null)
  const [mobileDetail, setMobileDetail] = useState(false)
  const [historyOpen, setHistoryOpen] = useState(false)
  const [auditOpen, setAuditOpen] = useState(false)
  const { run, isSearching, error } = preview
  const hits = run?.hits ?? []
  const selectedIndex = run && selection?.runId === run.id ? Math.min(selection.index, hits.length - 1) : 0
  const activeHit = hits[selectedIndex]
  const terms = activeHit ? matchedTerms(activeHit) : []
  const activeName = activeHit?.document_name || '未命名文档'
  const imageUrl = activeHit ? resolveSafeCitationImageUrl(activeHit.img_url) : null
  const showingDetail = Boolean(mobileDetail && activeHit && !isSearching)
  const scopeIsEmpty = !scopeLoading && aggregateDocuments === 0
  const canSearch = Boolean(preview.draft.trim() && preview.hasScope && !isSearching && !scopeLoading && !scopeIsEmpty)

  function submitQuestion() {
    if (!canSearch) return
    setMobileDetail(false)
    detachPromise(preview.search())
  }

  function selectHit(index: number, reveal = false) {
    if (!run || index < 0 || index >= hits.length) return
    setSelection({ runId: run.id, index })
    if (reveal) {
      setMobileDetail(true)
      requestAnimationFrame(() => detailRef.current?.focus())
    }
  }

  function restoreRun(item: RetrievalRun) {
    preview.restore(item)
    setMobileDetail(false)
    setHistoryOpen(false)
  }

  function prefetchHit(hit: RetrievePreviewCitation) {
    if (!hit.document_id) return
    prefetchDocumentView({ documentId: hit.document_id, chunkId: hit.chunk_id || null, rawFileUrl: hit.file_url || null })
  }

  function openHit(hit: RetrievePreviewCitation) {
    if (!hit.document_id) return
    const range = hit.text_range
    openDocument(hit.document_id, hit.chunk_id || undefined,
      range && typeof range.start === 'number' && typeof range.end === 'number' ? { start: range.start, end: range.end } : undefined,
      { previewAnchor: getDocumentPreviewAnchorFromCitation(hit) })
  }

  async function copyHit() {
    if (!activeHit?.chunk_content) return
    try {
      await navigator.clipboard.writeText(activeHit.chunk_content)
      toast.success('已复制片段')
    } catch { toast.error('复制失败，请重试') }
  }

  const history = <HistoryList items={preview.history} currentId={run?.id} disabled={isSearching} onSelect={restoreRun} onClear={preview.clearHistory} />

  return <div className={cn(styles.console, className)} data-retrieval-console data-mobile-detail={showingDetail}>
    <aside className={styles.historyPane} aria-label="最近检索">{history}</aside>
    <section className={styles.resultsPane} aria-label="检索问题与命中片段">
      <form className={styles.composer} onSubmit={event => { event.preventDefault(); submitQuestion() }}>
        <div className={styles.composerHeading}>
          <label htmlFor="retrieval-question">检索问题</label>
          <Sheet open={historyOpen} onOpenChange={setHistoryOpen}>
            <SheetTrigger asChild><Button type="button" variant="ghost" className={styles.mobileHistory}><History className="size-3.5" />最近检索</Button></SheetTrigger>
            <SheetContent side="left" className={styles.historySheet}>
              <SheetHeader className="sr-only"><SheetTitle>最近检索</SheetTitle><SheetDescription>本次会话中当前数据集范围的检索记录</SheetDescription></SheetHeader>
              {history}
            </SheetContent>
          </Sheet>
        </div>
        <div className={styles.inputWrap}>
          <textarea id="retrieval-question" ref={inputRef} value={preview.draft}
            onChange={event => preview.setDraft(event.target.value)}
            placeholder="输入问题，检索文档内容" rows={2} maxLength={8000}
            onKeyDown={event => {
              if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing && event.keyCode !== 229) {
                event.preventDefault()
                submitQuestion()
              }
            }}
          />
          <IconButton type="submit" label={isSearching ? '正在检索' : '检索'} title="检索（Enter）" disabled={!canSearch} className={styles.submit}>
            {isSearching ? <Loader2 className="size-4 animate-spin motion-reduce:animate-none" /> : <ArrowUp className="size-4" />}
          </IconButton>
        </div>
        <div className={styles.composerMeta}><span title={scopeLabel}>{scopeLabel}</span><span>Enter 检索 · Shift + Enter 换行</span></div>
      </form>
      <div className={styles.resultsHeading}>
        <h2>命中片段{run ? <span>{hits.length}</span> : null}</h2>
        <span role="status" aria-live="polite">{isSearching ? '正在检索…' : run ? `${(run.durationMs / 1000).toFixed(2)} 秒` : '按相关度排序'}</span>
      </div>
      <div className={styles.resultsScroll} aria-busy={isSearching || (!run && scopeLoading)}>
        {isSearching ? <EmptyState icon={<Loader2 className="size-6 animate-spin motion-reduce:animate-none" />} title="正在检索" description="正在查找相关文档片段。" />
        : error ? <div role="alert"><EmptyState icon={<Search className="size-6" />} title="检索未完成" description={error}><Button variant="outline" disabled={!canSearch} onClick={submitQuestion}>重试</Button></EmptyState></div>
        : !run && scopeLoading ? <EmptyState icon={<Loader2 className="size-6 animate-spin motion-reduce:animate-none" />} title="正在加载文档范围" description="正在读取当前范围的文档信息。" />
        : !preview.hasScope ? <EmptyState icon={<File className="size-6" />} title="还没有可检索的数据集" description="先导入文档，再到这里测试检索结果。">{onGoToDocuments ? <Button variant="outline" onClick={onGoToDocuments}>前往文档</Button> : null}</EmptyState>
        : !run && scopeIsEmpty ? <EmptyState icon={<File className="size-6" />} title="当前范围还没有文档" description="先导入并完成文档处理，再测试检索结果。">{onGoToDocuments ? <Button variant="outline" onClick={onGoToDocuments}>前往文档</Button> : null}</EmptyState>
        : !run ? <EmptyState icon={<Search className="size-6" />} title="从一个问题开始" description="输入问题，查看知识库返回的相关片段。" />
        : !hits.length ? <EmptyState icon={<Search className="size-6" />} title="没有找到相关片段" description="试试原文关键词，或切换顶部的数据集范围。"><Button variant="outline" onClick={() => inputRef.current?.focus()}>修改问题</Button></EmptyState>
        : <ol className={styles.hitList} aria-label="命中片段">
          {hits.map((hit, index) => <li key={`${run.id}-${index}`}>
            <button type="button" ref={index === selectedIndex ? selectedHitRef : undefined} className={styles.hit}
              aria-pressed={index === selectedIndex} aria-label={`查看片段 ${index + 1}：${hit.document_name || '未命名文档'}`}
              onClick={() => selectHit(index, true)} onMouseEnter={() => prefetchHit(hit)} onFocus={() => prefetchHit(hit)}
              onKeyDown={event => {
                const next = event.key === 'ArrowDown' ? index + 1 : event.key === 'ArrowUp' ? index - 1 : event.key === 'Home' ? 0 : event.key === 'End' ? hits.length - 1 : -1
                if (['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) {
                  event.preventDefault()
                  selectHit(next)
                  const buttons = event.currentTarget.closest('ol')?.querySelectorAll('button')
                  buttons?.[Math.max(0, Math.min(next, hits.length - 1))]?.focus()
                }
              }}
            >
              <span className={styles.rank}>{String(index + 1).padStart(2, '0')}</span>
              <span className={styles.hitBody}>
                <span className={styles.hitTitle}><DocumentMark name={hit.document_name || ''} /><strong>{hit.document_name || '未命名文档'}</strong><span className={styles.hitScore}>{getHitScore(hit)}</span></span>
                <span className={styles.hitExcerpt}>{hit.chunk_content || '该片段未返回正文。'}</span>
                <span className={styles.hitMeta}>{hit.policy_clause_number ? `§ ${hit.policy_clause_number} · ` : ''}{hit.chunk_id || '未返回分片 ID'}{hit.family_hit ? <span className={styles.familyTag}>同源命中</span> : null}</span>
              </span>
            </button>
          </li>)}
        </ol>}
      </div>
      <footer className={styles.resultsFooter} data-task-center-dock="true"><Link href="/settings#sec-rag">检索设置<ArrowUpRight className="size-3.5" /></Link><button type="button" onClick={event => { auditTriggerRef.current = event.currentTarget; setAuditOpen(true) }}><Fingerprint className="size-3.5" />索引检查</button></footer>
    </section>
    <section ref={detailRef} tabIndex={-1} className={styles.detailPane} aria-label="片段详情">
      <header className={styles.detailHeader}>
        <Button variant="ghost" className={styles.back} onClick={() => { setMobileDetail(false); requestAnimationFrame(() => selectedHitRef.current?.focus()) }}><ArrowLeft className="size-4" />返回结果</Button>
        <h2>片段详情</h2><span className={styles.detailCounter}>{activeHit ? `${String(selectedIndex + 1).padStart(2, '0')} / ${String(hits.length).padStart(2, '0')}` : '—'}</span>
        <div className={styles.detailPaging}><IconButton variant="ghost" label="上一个片段" disabled={!activeHit || selectedIndex <= 0} onClick={() => selectHit(selectedIndex - 1)}><ChevronLeft className="size-4" /></IconButton><IconButton variant="ghost" label="下一个片段" disabled={!activeHit || selectedIndex >= hits.length - 1} onClick={() => selectHit(selectedIndex + 1)}><ChevronRight className="size-4" /></IconButton></div>
      </header>
      <div className={styles.detailScroll}>
        {activeHit && !isSearching ? <article key={`${run?.id}-${selectedIndex}`} className={styles.fragment}>
          <div className={styles.fragmentHeading}><h3><DocumentMark name={activeName} /><span>{activeName}</span></h3><div className={styles.relevance}><span>相关度</span><strong>{getHitScore(activeHit)}</strong></div></div>
          <dl className={styles.metadata}>
            {activeHit.policy_path_str ? <><dt>章节路径</dt><dd>{activeHit.policy_path_str}</dd></> : null}
            {activeHit.policy_clause_number ? <><dt>条款编号</dt><dd>{activeHit.policy_clause_number}</dd></> : null}
            {activeHit.chunk_id ? <><dt>分片 ID</dt><dd>{activeHit.chunk_id}</dd></> : null}
            {activeHit.family_hit ? <><dt>匹配方式</dt><dd>同源命中</dd></> : null}
            {activeHit.retrieval_role ? <><dt>召回来源</dt><dd>{activeHit.retrieval_role}</dd></> : null}
          </dl>
          {run?.queryForRetrieval && run.queryForRetrieval !== run.query ? <div className={styles.rewritten}><h4>实际检索问题</h4><p>{run.queryForRetrieval}</p></div> : null}
          <section className={styles.contentSection}><h4>命中内容</h4><p className={styles.chunkText}><HighlightedText text={activeHit.chunk_content || '该片段未返回正文。'} terms={terms} /></p>
            {imageUrl ? <AuthImage src={imageUrl} alt="命中片段中的图片" width={900} height={600} unoptimized className={styles.chunkImage} /> : null}
          </section>
          {terms.length ? <section className={styles.terms}><h4>匹配词</h4><div>{terms.map(term => <span key={term}>{term}</span>)}</div></section> : null}
          <div className={styles.detailActions}>
            <Button variant="outline" disabled={!activeHit.document_id} onClick={() => openHit(activeHit)} onMouseEnter={() => prefetchHit(activeHit)} onFocus={() => prefetchHit(activeHit)}><ArrowUpRight className="size-4" />查看原文</Button>
            <Button variant="ghost" disabled={!activeHit.chunk_content} onClick={() => detachPromise(copyHit())}><Copy className="size-4" />复制内容</Button>
          </div>
        </article> : <EmptyState icon={<File className="size-7" />} title="查看片段详情" description="检索后，选择一条命中查看完整内容和来源。" />}
      </div>
      <footer className={styles.detailFooter} data-task-center-dock="true"><span>{aggregateDocuments ?? '—'} 份文档 · {aggregateChunks} 个分片</span><button type="button" onClick={event => { auditTriggerRef.current = event.currentTarget; setAuditOpen(true) }}>索引检查<ChevronRight className="size-3.5" /></button></footer>
    </section>
    <Sheet open={auditOpen} onOpenChange={setAuditOpen}>
      <SheetContent className={styles.auditSheet} onCloseAutoFocus={event => { event.preventDefault(); auditTriggerRef.current?.focus() }}>
        <SheetHeader><SheetTitle>索引检查</SheetTitle><SheetDescription>检查当前数据集的索引与文档是否一致。</SheetDescription></SheetHeader>
        <div className={styles.auditBody}>{auditOpen ? <KnowledgeRetrievalPanel selectedDatasetId={selectedDatasetId || undefined} aggregateDocuments={aggregateDocuments} aggregateChunks={aggregateChunks} compact /> : null}</div>
      </SheetContent>
    </Sheet>
  </div>
}
