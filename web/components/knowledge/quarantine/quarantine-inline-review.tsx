'use client'

import { useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  Activity,
  ArrowUpRight,
  Calendar,
  Dataset as DatasetIcon,
  HardDrive,
  Loader2,
  RefreshCw,
  RotateCcw,
  Settings2,
  ShieldAlert,
  ShieldCheck,
} from '@/components/icons'
import { getFileTypeMeta } from '@/components/knowledge/file-type'
import { Button } from '@/components/ui/button'
import { documentApi } from '@/lib/api'
import { toApiErrorInfo } from '@/lib/api-errors'
import type { DomainTone } from '@/lib/dataset-domain-tone'
import { cn, formatDate, formatFileSize } from '@/lib/utils'
import type { Document } from '@/types'
import {
  buildReviewAdvice,
  getDropReasons,
  getQuarantineSeverity,
  getQuarantineSource,
  getReasonTone,
  isReviewed,
  reasonLabel,
} from '@/app/knowledge/quarantine/quarantine-signals'
import type { ActingState } from '@/app/knowledge/quarantine/types'
import styles from '@/app/knowledge/quarantine/quarantine.module.css'

export type QuarantineReviewActions = {
  acting: ActingState
  actionError: { id: string; message: string; requestId?: string } | null
  onRelease: (doc: Document) => void
  onRetry: (doc: Document) => void
  onTune: (doc: Document) => void
  onMarkReviewed: (doc: Document) => void
  onDelete: (doc: Document) => Promise<void>
  onOpenDocument: (docId: string) => void
  onShowDetails: (docId: string) => void
}

type Props = Omit<QuarantineReviewActions, 'onMarkReviewed' | 'onDelete' | 'onShowDetails'> & {
  document: Document | null
  datasetLabel: string
  datasetTone?: DomainTone
  demoMode: boolean
}

function RequestDiagnostics({ requestId }: Readonly<{ requestId?: string }>) {
  return requestId ? (
    <details className={styles.diagnostics}>
      <summary>诊断信息</summary>
      <code>request_id={requestId}</code>
    </details>
  ) : null
}

export function QuarantineInlineReview(props: Readonly<Props>) {
  if (props.document === null) {
    return <div className={styles.reviewEmpty}>选择一份隔离文档以查看复核依据与原文摘录。</div>
  }
  return <SelectedQuarantineReview {...props} document={props.document} />
}

function SelectedQuarantineReview({
  document: doc,
  datasetLabel,
  datasetTone,
  demoMode,
  acting,
  actionError,
  onRelease,
  onRetry,
  onTune,
  onOpenDocument,
}: Readonly<Props & { document: Document }>) {
  const busy = Boolean(acting)
  const reasons = getDropReasons(doc)
  const severity = getQuarantineSeverity(doc)
  const reviewed = isReviewed(doc)
  const fileType = getFileTypeMeta(doc)
  const TypeIcon = fileType.icon
  const RiskIcon = severity === '高' ? ShieldAlert : ShieldCheck

  const { data, isPending, error, refetch, isFetching } = useQuery({
    queryKey: ['quarantine-parsed-content', demoMode ? null : doc.id],
    queryFn: ({ signal }) => documentApi.getParsedContent(doc.id, { max_chars: 1400 }, { signal }),
    enabled: !demoMode,
    staleTime: 60_000,
    retry: false,
  })
  const sourceContent = !demoMode && data?.available === true ? data : null
  const hasOriginal = sourceContent !== null && sourceContent.original_markdown_content.trim() !== ''
  const excerpt =
    sourceContent === null
      ? null
      : hasOriginal
        ? sourceContent.original_markdown_content
        : sourceContent.markdown_content
  const hasExcerpt = excerpt !== null && excerpt.trim() !== ''
  const excerptTruncated =
    sourceContent !== null &&
    (hasOriginal ? sourceContent.original_markdown_truncated : sourceContent.markdown_truncated)
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
  const sourceError = !demoMode && error !== null ? toApiErrorInfo(error, '原文暂时无法读取') : null

  return (
    <section className={styles.reviewPanel} data-severity={severity} aria-label={`${doc.filename}复核`}>
      <div className={styles.reviewScroll}>
        <div className={styles.reviewIdentity} role="group" aria-label="当前复核文档">
          <span className={cn(styles.reviewFileBadge, fileType.bg)}>
            <TypeIcon appearance="color" aria-hidden="true" />
          </span>
          <div className={styles.reviewIdentityCopy}>
            <h3 title={doc.filename}>{doc.filename}</h3>
            <div className={styles.reviewStatusRow}>
              <span className={styles.risk} data-severity={severity}>
                <RiskIcon aria-hidden="true" />
                {severity}风险
              </span>
              <span className={styles.reviewState} data-reviewed={reviewed}>
                {reviewed ? '已复核' : '待复核'}
              </span>
            </div>
          </div>
        </div>

        <div className={styles.reviewMetrics}>
          <div>
            <span>
              <Activity className="icon-ink-process" aria-hidden="true" />
              来源
            </span>
            <strong title={getQuarantineSource(doc)}>{getQuarantineSource(doc)}</strong>
          </div>
          <div>
            <span>
              <HardDrive className="icon-ink-governance" aria-hidden="true" />
              大小
            </span>
            <strong>{formatFileSize(doc.file_size)}</strong>
          </div>
          <div>
            <span>
              <Calendar className="icon-ink-analysis" aria-hidden="true" />
              处理时间
            </span>
            <strong title={doc.updated_at || doc.created_at}>{formatDate(doc.updated_at || doc.created_at)}</strong>
          </div>
        </div>

        <div className={styles.reviewMetaRow}>
          <span className={styles.reviewMetaLabel}>
            <DatasetIcon aria-hidden="true" />
            所属数据集
          </span>
          <span className={styles.datasetPill} data-tone={datasetTone} title={datasetLabel}>
            {datasetLabel}
          </span>
        </div>

        <div className={styles.reviewSection}>
          <h4>隔离依据</h4>
          {reasons.length > 0 ? (
            <div className={styles.basisReasons}>
              {reasons.map((reason) => (
                <span key={reason} className={styles.reasonPill} data-tone={getReasonTone(reason)}>
                  {reasonLabel(reason)}
                </span>
              ))}
            </div>
          ) : (
            <p className={styles.reasonMuted}>待确认原因</p>
          )}
          {reasons.length > 0 && <div className={styles.ruleCode}>{reasons.join(' · ')}</div>}
          {doc.error_message && (
            <div className={styles.diagnosticBox} data-severity={severity}>
              <p>{doc.error_message}</p>
            </div>
          )}
        </div>

        <div className={styles.reviewSection}>
          <div className={styles.excerptHeading}>
            <h4>原文摘录</h4>
            {hasExcerpt && excerptOverflow && <span>可滚动查看</span>}
          </div>
          {loading ? (
            <p className={styles.excerptStatus} role="status">
              <Loader2 className="animate-spin motion-reduce:animate-none" aria-hidden="true" />
              正在读取原文…
            </p>
          ) : null}
          {sourceError !== null ? (
            <div className={styles.excerptStatus}>
              <div>
                <p role="alert">{sourceError.message}</p>
                <RequestDiagnostics requestId={sourceError.requestId} />
              </div>
              <Button size="sm" variant="ghost" disabled={isFetching} onClick={() => void refetch()}>
                重新读取
              </Button>
            </div>
          ) : null}
          {hasExcerpt ? (
            <>
              <pre ref={excerptRef} tabIndex={0} aria-label={`${doc.filename}的原文摘录`}>
                {excerpt}
              </pre>
              {excerptTruncated && <p className={styles.excerptLimit}>仅显示部分原文，可查看完整文档。</p>}
            </>
          ) : !loading && sourceError === null ? (
            <p className={styles.excerptEmpty}>暂无可用的解析文本，可查看原文或入库详情。</p>
          ) : null}
          <p className={styles.advice}>{buildReviewAdvice(doc).join(' ')}</p>
          {currentError && <RequestDiagnostics requestId={actionError?.requestId} />}
        </div>
      </div>

      <div className={styles.reviewFooter}>
        <div className={styles.reviewPrimaryActions}>
          <Button size="sm" className={styles.primaryAction} disabled={busy} onClick={() => onRelease(doc)}>
            <RotateCcw
              className={cn(
                acting?.id === doc.id && acting.action === 'release' && 'animate-spin motion-reduce:animate-none',
              )}
              aria-hidden="true"
            />
            {acting?.id === doc.id && acting.action === 'release' ? '正在放行…' : '放行并重试'}
          </Button>
          <Button size="sm" variant="outline" disabled={busy} onClick={() => onRetry(doc)}>
            <RefreshCw
              className={cn(
                acting?.id === doc.id && acting.action === 'retry' && 'animate-spin motion-reduce:animate-none',
              )}
              aria-hidden="true"
            />
            {acting?.id === doc.id && acting.action === 'retry' ? '正在重试…' : '重试'}
          </Button>
          <Button size="sm" variant="outline" disabled={busy} onClick={() => onTune(doc)}>
            <Settings2 aria-hidden="true" />
            调参
          </Button>
        </div>
        <Button size="sm" variant="ghost" className={styles.originalButton} onClick={() => onOpenDocument(doc.id)}>
          <ArrowUpRight aria-hidden="true" />
          查看原文
        </Button>
      </div>
    </section>
  )
}
