'use client'

import { useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { AlertCircle, ArrowUpRight, CheckCircle2, Layers, Loader2, MoreHorizontal, RefreshCw, RotateCcw, Settings2, Trash2 } from '@/components/icons'
import { Button } from '@/components/ui/button'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { documentApi } from '@/lib/api'
import { toApiErrorInfo } from '@/lib/api-errors'
import { cn, formatDate, formatFileSize } from '@/lib/utils'
import type { Document } from '@/types'
import { buildReviewAdvice, getDropReasons, getQuarantineSource, isReviewed, reasonLabel } from '@/app/knowledge/quarantine/quarantine-signals'
import type { ActingState } from '@/app/knowledge/quarantine/types'
import styles from '@/app/knowledge/quarantine/quarantine.module.css'

export type QuarantineReviewActions = {
  acting: ActingState
  actionError: { id: string; message: string; requestId?: string } | null
  onRelease: (doc: Document) => void
  onRetry: (doc: Document) => void
  onTune: (doc: Document) => void
  onMarkReviewed: (doc: Document) => void
  onDelete: (doc: Document) => void
  onOpenDocument: (docId: string) => void
  onShowDetails: (docId: string) => void
}

type Props = QuarantineReviewActions & {
  document: Document
  datasetLabel: string
  demoMode: boolean
}

function RequestDiagnostics({ requestId }: Readonly<{ requestId?: string }>) {
  return requestId ? <details className={styles.diagnostics}><summary>诊断信息</summary><code>request_id={requestId}</code></details> : null
}

export function QuarantineInlineReview({ document: doc, datasetLabel, demoMode, acting, actionError, onRelease, onRetry, onTune, onMarkReviewed, onDelete, onOpenDocument, onShowDetails }: Readonly<Props>) {
  const busy = Boolean(acting)
  const reasons = getDropReasons(doc)
  const { data, isPending, error, refetch, isFetching } = useQuery({
    queryKey: ['quarantine-parsed-content', doc.id],
    queryFn: () => documentApi.getParsedContent(doc.id, { max_chars: 1400 }),
    enabled: !demoMode,
    staleTime: 60_000,
    retry: false,
  })
  const excerpt = data?.original_markdown_content?.trim() || data?.markdown_content?.trim()
  const excerptTruncated = data?.original_markdown_content?.trim() ? data.original_markdown_truncated : data?.markdown_truncated
  const excerptRef = useRef<HTMLPreElement>(null)
  const [excerptOverflow, setExcerptOverflow] = useState(false)
  useEffect(() => {
    const element = excerptRef.current
    if (!element) return
    const update = () => setExcerptOverflow(element.scrollHeight > element.clientHeight + 1)
    update()
    if (typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver(update)
    observer.observe(element)
    return () => observer.disconnect()
  }, [excerpt, error])
  const loading = !demoMode && isPending
  const currentError = actionError?.id === doc.id ? actionError.message : null
  const sourceError = error ? toApiErrorInfo(error, '原文暂时无法读取') : null

  return (
    <section className={styles.inlineReview} aria-label={`${doc.filename}复核`}>
      <div className={styles.basis}>
        <h2>隔离依据</h2>
        <h3>{reasons.map(reasonLabel).join('、') || '待确认原因'}</h3>
        {reasons.length > 0 && <div className={styles.ruleCode}>{reasons.join(' · ')}</div>}
        {doc.error_message && <p>{doc.error_message}</p>}
        <dl className={styles.documentFacts}>
          <dt>数据集</dt><dd>{datasetLabel}</dd>
          <dt>来源</dt><dd>{getQuarantineSource(doc)}</dd>
          <dt>文件大小</dt><dd>{formatFileSize(doc.file_size)}</dd>
          <dt>处理时间</dt><dd>{formatDate(doc.updated_at || doc.created_at)}</dd>
        </dl>
      </div>
      <div className={styles.reviewContent}>
        <div className={styles.excerpt}>
          <div className={styles.excerptHeading}><h3>原文摘录</h3>{excerptOverflow && <span>可滚动查看</span>}</div>
          {loading ? <p className={styles.excerptStatus} role="status"><Loader2 className="animate-spin motion-reduce:animate-none" aria-hidden="true" />正在读取原文…</p>
            : sourceError ? <div className={styles.excerptStatus}><div><p role="status">{sourceError.message}</p><RequestDiagnostics requestId={sourceError.requestId} /></div><Button size="sm" variant="ghost" disabled={isFetching} onClick={() => void refetch()}>重新读取</Button></div>
            : excerpt ? <><pre ref={excerptRef} tabIndex={0} aria-label={`${doc.filename}的原文摘录`}>{excerpt}</pre>{excerptTruncated && <p className={styles.excerptLimit}>仅显示部分原文，可查看完整文档。</p>}</>
            : <p>暂无可用的解析文本，可查看原文或入库详情。</p>}
        </div>
        <p className={styles.advice}>{buildReviewAdvice(doc).join(' ')}</p>
        {currentError && <RequestDiagnostics requestId={actionError?.requestId} />}
        <div className={styles.inlineActions}>
          <Button size="sm" className={styles.primaryAction} disabled={busy} onClick={() => onRelease(doc)}>
            <RotateCcw className={cn(acting?.id === doc.id && acting.action === 'release' && 'animate-spin motion-reduce:animate-none')} aria-hidden="true" />
            {acting?.id === doc.id && acting.action === 'release' ? '正在放行…' : '放行并重试'}
          </Button>
          <Button size="sm" variant="outline" disabled={busy} onClick={() => onRetry(doc)}>
            <RefreshCw className={cn(acting?.id === doc.id && acting.action === 'retry' && 'animate-spin motion-reduce:animate-none')} aria-hidden="true" />
            {acting?.id === doc.id && acting.action === 'retry' ? '正在重试…' : '重试'}
          </Button>
          <Button size="sm" variant="ghost" disabled={busy} onClick={() => onTune(doc)}><Settings2 aria-hidden="true" />调参</Button>
          <Button size="sm" variant="ghost" className={styles.original} onClick={() => onOpenDocument(doc.id)}><ArrowUpRight aria-hidden="true" />查看原文</Button>
          <DropdownMenu>
            <DropdownMenuTrigger asChild><Button size="icon" variant="ghost" className={styles.moreAction} aria-label={`${doc.filename}的更多操作`} disabled={busy}><MoreHorizontal aria-hidden="true" /></Button></DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem onSelect={() => onShowDetails(doc.id)}><Layers className="mr-2 size-4" aria-hidden="true" />入库详情</DropdownMenuItem>
              {!isReviewed(doc) && <DropdownMenuItem onSelect={() => onMarkReviewed(doc)}><CheckCircle2 className="mr-2 size-4" aria-hidden="true" />标记已复核</DropdownMenuItem>}
              <DropdownMenuSeparator />
              <ConfirmDialog title={`删除「${doc.filename}」？`} description="文档及相关入库记录将被删除，此操作无法撤销。" confirmLabel="删除文档" onConfirm={() => onDelete(doc)} confirmDisabled={busy}>
                <DropdownMenuItem onSelect={event => event.preventDefault()} className="text-destructive focus:text-destructive"><Trash2 className="mr-2 size-4" aria-hidden="true" />删除文档</DropdownMenuItem>
              </ConfirmDialog>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>
    </section>
  )
}
