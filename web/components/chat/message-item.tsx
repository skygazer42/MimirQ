/**
 * Shared chat message item (ChatArea + History).
 */
'use client'

import { AnimatePresence, motion, useReducedMotion } from 'framer-motion'
import { createContext, memo, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import {
  ArrowUpRight,
  BarChart3,
  Check,
  ChevronDown,
  Copy,
  Database,
  Bot,
  FileText,
  Loader2,
  Star,
  TestTube2,
  User,
} from '@/components/icons'
import ReactMarkdown, { defaultUrlTransform } from 'react-markdown'
import remarkGfm from 'remark-gfm'

import { AuthImage } from '@/components/auth-image'
import { BrandLogo } from '@/components/brand-logo'
import { useRouter } from '@/i18n/navigation'
import { resolveMarkdownImageSrc, sanitizeMarkdownHref } from '@/components/markdown/markdown-safety'
import type { Citation } from '@/types/processing'
import type { FeedbackCategory, MessageFeedback } from '@/types/feedback'
import type { ClaimEvidenceReference, Message } from '@/types/chat'
import { getCitationRange } from '@/lib/citations'
import { getDocumentPreviewAnchorFromCitation } from '@/lib/document-preview-anchor'
import { cn, detachPromise } from '@/lib/utils'
import { BRAND_NAME } from '@/lib/brand'
import { globalEventBus } from '@/lib/event-bus'
import { prefetchDocumentView } from '@/lib/document-view-prefetch'
import { useDocumentView, type DocumentViewSourceContext } from '@/store/document-view'
import { resolveSafeCitationImageUrl } from '@/lib/citation-images'
import { EvidenceViewerDialog } from '@/components/evidence/evidence-viewer-dialog'

import { CinematicTypewriter } from '@/components/ui/cinematic-typewriter'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { feedbackApi } from '@/lib/api/feedback'
import { formatApiError } from '@/lib/api-errors'
import { AUTH_SCOPE_CHANGED_EVENT, getAuthSessionRevision } from '@/lib/auth-storage'
import { reportClientError } from '@/lib/client-logging'
import { toast } from 'sonner'

const INLINE_CITATION_HREF_PREFIX = 'mimirq-citation://'

type InlineCitationHandlers = Readonly<{
  onClick: (href?: string) => void
  onPrefetch: (href?: string) => void
}>

const InlineCitationHandlersContext = createContext<InlineCitationHandlers>({
  onClick: () => {},
  onPrefetch: () => {},
})

function isCurrentMessageOperation(owner: { active: boolean }, sessionRevision: number): boolean {
  return owner.active && sessionRevision === getAuthSessionRevision()
}

type ConfidenceMeta = Readonly<{
  label: string
  badgeClass: string
  lineClass: string
}>

type CitationRow = Readonly<{ key: string; citation: Citation }>

function getCitationRows(citations: readonly Citation[] | undefined): CitationRow[] {
  if (citations === undefined) return []
  const occurrences = new Map<string, number>()
  return citations
    .slice()
    .sort((first, second) => second.relevance_score - first.relevance_score)
    .map((citation) => {
      const identity = JSON.stringify([
        citation.document_id,
        citation.chunk_id,
        citation.page_number,
        citation.start_char,
        citation.end_char,
        citation.evidence_start_char,
        citation.evidence_end_char,
        citation.img_id,
        citation.img_url,
      ])
      const occurrence = occurrences.get(identity) ?? 0
      occurrences.set(identity, occurrence + 1)
      return { key: `${identity}:${occurrence}`, citation }
    })
}

type CitationTarget = {
  documentId?: string | null
  chunkId?: string | null
  range?: { start: number; end: number }
  pageNumber?: number
}

function readInlineCitationInteger(params: URLSearchParams, name: string): number | undefined {
  const raw = params.get(name)
  if (raw === null) return undefined
  if (!/^(0|[1-9]\d*)$/.test(raw)) throw new TypeError(`Invalid citation ${name}`)
  const value = Number(raw)
  if (!Number.isSafeInteger(value)) throw new TypeError(`Invalid citation ${name}`)
  return value
}

function parseInlineCitationHref(href?: string): CitationTarget | null {
  if (!href?.startsWith(INLINE_CITATION_HREF_PREFIX)) return null

  try {
    const parsed = new URL(href)
    const documentId = parsed.searchParams.get('document_id')?.trim()
    const chunkId = parsed.searchParams.get('chunk_id')?.trim()
    if (!documentId && !chunkId) return null
    const start = readInlineCitationInteger(parsed.searchParams, 'start_char')
    const end = readInlineCitationInteger(parsed.searchParams, 'end_char')
    const pageNumber = readInlineCitationInteger(parsed.searchParams, 'page')
    if ((start === undefined) !== (end === undefined)) return null
    if (start !== undefined && end !== undefined && end <= start) return null
    if (pageNumber === 0) return null
    return {
      documentId: documentId === '' ? undefined : documentId,
      chunkId: chunkId === '' ? undefined : chunkId,
      range: start === undefined || end === undefined ? undefined : { start, end },
      pageNumber,
    }
  } catch {
    return null
  }
}

function transformMessageMarkdownUrl(url: string, key: string): string {
  return key === 'href' && parseInlineCitationHref(url) ? url : defaultUrlTransform(url)
}

function findTargetCitation(citations: readonly Citation[] | undefined, target: CitationTarget): Citation | undefined {
  if (!target.chunkId) return undefined
  return citations?.find(
    (citation) =>
      citation.chunk_id === target.chunkId && (target.documentId == null || citation.document_id === target.documentId),
  )
}

function buildChatCitationSourceContext(
  messageId: string,
  documentId: string,
  chunkId?: string | null,
  citation?: Partial<Pick<Citation, 'document_name' | 'chunk_content' | 'chunk_index' | 'page_number'>>,
): DocumentViewSourceContext {
  return {
    kind: 'chat-citation',
    messageId,
    documentId,
    chunkId,
    documentName: citation?.document_name,
    chunkContent: citation?.chunk_content,
    chunkIndex: citation?.chunk_index,
    pageNumber: citation?.page_number,
  }
}

function getConfidenceMeta(band: unknown): ConfidenceMeta | null {
  if (band === 'high') {
    return {
      label: '✓ 高置信度',
      badgeClass: 'border-success/20 bg-success/10 text-success',
      lineClass: 'border-l-emerald-500/80',
    }
  }
  if (band === 'medium') {
    return {
      label: '中置信度',
      badgeClass: 'border-warning/20 bg-warning/10 text-warning',
      lineClass: 'border-l-amber-500/80',
    }
  }
  if (band === 'low') {
    return {
      label: '低置信度',
      badgeClass: 'border-destructive/20 bg-destructive/10 text-destructive',
      lineClass: 'border-l-rose-500/80',
    }
  }
  return null
}

function formatMetricValue(value: unknown): string | undefined {
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') return String(value)
  return undefined
}

function formatCitationScore(score: number): string {
  if (score >= 0 && score <= 1) return `${Math.round(score * 100)}%`
  return score.toFixed(3)
}

function getCitationScoreDetails(citation: Citation) {
  const relevanceScore = formatCitationScore(citation.relevance_score)
  const titleParts = [`综合分 ${relevanceScore}`]
  const optionalScores = [
    { label: '重排', score: citation.rerank_score },
    { label: '向量', score: citation.vector_score },
    { label: '关键词', score: citation.bm25_score },
    { label: '召回', score: citation.retrieval_score },
  ]
  let secondaryScore: { label: string; value: string } | undefined

  for (const { label, score } of optionalScores) {
    if (score === undefined) continue
    const value = formatCitationScore(score)
    secondaryScore ??= { label, value }
    titleParts.push(`${label} ${value}`)
  }
  if (citation.hit_type !== undefined) titleParts.push(`命中类型 ${citation.hit_type}`)
  return { relevanceScore, title: titleParts.join(' · '), secondaryScore }
}

const markdownPlugins = [remarkGfm]
const DIAGNOSTIC_METRICS = [
  'request_id',
  'retrieval_mode',
  'retrieval_mode_requested',
  'vector_backend',
  'route',
  'model_route',
  'elapsed_sec',
  'retrieval_elapsed_sec',
  'generation_elapsed_sec',
  'docs_returned',
  'distinct_documents',
  'top_k',
]
type MessageMarkdownChildrenProps = Readonly<{ children?: ReactNode }>
type MessageMarkdownLinkProps = Readonly<{ href?: string; children?: ReactNode }>
type MessageMarkdownImageProps = Readonly<{ src?: string | Blob; alt?: string }>
type MessageMarkdownCodeProps = Readonly<{ className?: string; children?: ReactNode }>

function MessageMarkdownParagraph({ children }: MessageMarkdownChildrenProps) {
  return <p className="mb-3 last:mb-0 leading-relaxed">{children}</p>
}

function MessageMarkdownList({ children }: MessageMarkdownChildrenProps) {
  return <ul className="list-disc pl-5 mb-3 space-y-1.5 marker:text-muted-foreground/60">{children}</ul>
}

function MessageMarkdownOrderedList({ children }: MessageMarkdownChildrenProps) {
  return <ol className="list-decimal pl-5 mb-3 space-y-1.5 marker:text-muted-foreground/60">{children}</ol>
}

function MessageMarkdownListItem({ children }: MessageMarkdownChildrenProps) {
  return <li className="pl-1">{children}</li>
}

function MessageMarkdownAnchor({ href, children }: MessageMarkdownLinkProps) {
  const { onClick, onPrefetch } = useContext(InlineCitationHandlersContext)
  const inlineCitation = parseInlineCitationHref(href)
  if (inlineCitation) {
    return (
      <button
        type="button"
        onClick={() => onClick(href)}
        onMouseEnter={() => onPrefetch(href)}
        onFocus={() => onPrefetch(href)}
        className="inline-flex items-center rounded-md border border-primary/20 bg-primary/5 px-1.5 py-0.5 text-[0.75em] font-semibold text-primary no-underline transition-colors hover:bg-primary/10 hover:text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60"
      >
        {children}
      </button>
    )
  }

  const safeHref = sanitizeMarkdownHref(href)
  if (safeHref === null) return <span className="text-muted-foreground">{children}</span>

  return (
    <a
      href={safeHref}
      target="_blank"
      rel="noopener noreferrer"
      className="text-primary font-medium hover:underline decoration-primary/30 underline-offset-4 transition-colors"
    >
      {children}
    </a>
  )
}

function MessageMarkdownImage({ src, alt }: MessageMarkdownImageProps) {
  const resolved = resolveMarkdownImageSrc(src)
  if (resolved === null) return null
  return (
    <AuthImage
      src={resolved}
      alt={alt === undefined ? 'image' : alt}
      width={1200}
      height={800}
      unoptimized
      sizes="(max-width: 768px) 100vw, 768px"
      loading="lazy"
      className="my-3 w-full h-auto max-h-96 object-contain rounded-xl border border-border/50 bg-background/50 shadow-sm"
    />
  )
}

function MessageMarkdownBlockquote({ children }: MessageMarkdownChildrenProps) {
  return (
    <blockquote className="border-l-4 border-primary/30 pl-4 italic text-muted-foreground my-3 bg-secondary/30 py-2 pr-2 rounded-r-lg">
      {children}
    </blockquote>
  )
}

function MessageMarkdownCode({ className, children, ...props }: MessageMarkdownCodeProps) {
  if (className !== undefined && /language-\w+/.test(className)) {
    return (
      <code className={className} {...props}>
        {children}
      </code>
    )
  }

  return (
    <code
      className={cn('px-1.5 py-0.5 rounded-md text-sm font-mono text-primary', className)}
      style={{ backgroundColor: 'hsl(var(--code-background))' }}
      {...props}
    >
      {children}
    </code>
  )
}

const markdownBaseComponents = {
  a: MessageMarkdownAnchor,
  blockquote: MessageMarkdownBlockquote,
  code: MessageMarkdownCode,
  img: MessageMarkdownImage,
  li: MessageMarkdownListItem,
  ol: MessageMarkdownOrderedList,
  p: MessageMarkdownParagraph,
  ul: MessageMarkdownList,
}

export const ChatMessageItem = memo(function ChatMessageItem({
  message,
  isStreaming = false,
  onFollowupSelect,
  variant = 'default',
}: Readonly<{
  message: Message
  isStreaming?: boolean
  onFollowupSelect?: (prompt: string) => void
  variant?: 'default' | 'minimal' | 'history'
}>) {
  const router = useRouter()
  const isUser = message.role === 'user'
  const isHistory = variant === 'history'
  const isCompact = variant === 'minimal' || isHistory
  const reduceMotion = useReducedMotion()
  const [copied, setCopied] = useState(false)
  const [diagOpen, setDiagOpen] = useState(false)
  const [rating, setRating] = useState<number | null>(null)
  const [ratingSending, setRatingSending] = useState(false)
  const [feedbackRecord, setFeedbackRecord] = useState<MessageFeedback | null>(null)
  const [expertAction, setExpertAction] = useState<'evidence' | 'regression' | null>(null)
  const [stepsOpen, setStepsOpen] = useState(() => isStreaming)
  const copyTimerRef = useRef<number | null>(null)
  const prefetchedCitationTargetsRef = useRef<Set<string>>(new Set())
  const messageOwnerRef = useRef<{
    active: boolean
    ratingSending: boolean
    expertAction: 'evidence' | 'regression' | null
  }>({ active: true, ratingSending: false, expertAction: null })
  const { openDocument } = useDocumentView()
  const streamingLayoutTransition = reduceMotion
    ? { duration: 0 }
    : { duration: 0.24, ease: [0.16, 1, 0.3, 1] as const }
  const stepCount = message.steps?.length ?? 0
  const latestStep = message.steps?.[stepCount - 1]
  const stepsPanelId = `chat-steps-${message.id}`

  const clearCopyTimer = useCallback(() => {
    if (copyTimerRef.current !== null) {
      globalThis.window.clearTimeout(copyTimerRef.current)
      copyTimerRef.current = null
    }
  }, [])

  useEffect(() => {
    setStepsOpen(isStreaming)
  }, [isStreaming, message.id])

  useEffect(() => {
    messageOwnerRef.current = { active: true, ratingSending: false, expertAction: null }

    function resetMessageOperations() {
      messageOwnerRef.current.active = false
      messageOwnerRef.current = { active: true, ratingSending: false, expertAction: null }
      setRating(null)
      setRatingSending(false)
      setFeedbackRecord(null)
      setExpertAction(null)
      clearCopyTimer()
      setCopied(false)
    }

    globalThis.window.addEventListener(AUTH_SCOPE_CHANGED_EVENT, resetMessageOperations)
    return () => {
      messageOwnerRef.current.active = false
      globalThis.window.removeEventListener(AUTH_SCOPE_CHANGED_EVENT, resetMessageOperations)
      clearCopyTimer()
    }
  }, [clearCopyTimer])

  const handleCopy = async () => {
    const owner = messageOwnerRef.current
    const sessionRevision = getAuthSessionRevision()
    if (message.content.length === 0) return

    try {
      await navigator.clipboard.writeText(message.content)
    } catch (error) {
      if (isCurrentMessageOperation(owner, sessionRevision)) {
        reportClientError('Failed to copy chat message to clipboard', error)
        toast.error('复制失败，请检查浏览器剪贴板权限')
      }
      return
    }

    if (!isCurrentMessageOperation(owner, sessionRevision)) return
    setCopied(true)
    clearCopyTimer()
    copyTimerRef.current = globalThis.window.setTimeout(() => {
      copyTimerRef.current = null
      setCopied(false)
    }, 1200)
  }

  const diagnostics = {
    message_id: message.id,
    message_metadata: message.message_metadata,
    citations: message.citations,
  }
  const handleCopyDiagnostics = async () => {
    const owner = messageOwnerRef.current
    const sessionRevision = getAuthSessionRevision()
    try {
      await navigator.clipboard.writeText(JSON.stringify(diagnostics, null, 2))
      if (isCurrentMessageOperation(owner, sessionRevision)) toast.success('已复制诊断信息')
    } catch (error) {
      if (isCurrentMessageOperation(owner, sessionRevision)) {
        reportClientError('Failed to copy chat diagnostics to clipboard', error)
        toast.error('诊断信息复制失败，请检查浏览器剪贴板权限')
      }
    }
  }

  const metrics = message.message_metadata
  const confidenceScore = metrics?.confidence_score
  const confidenceMeta = getConfidenceMeta(metrics?.confidence_band)
  const hasConfidence = confidenceScore != null || confidenceMeta !== null
  const claimEvidence = metrics?.claim_evidence
  const claimEvidenceCount = claimEvidence?.length ?? 0
  const messageDatasetId = metrics?.dataset_id?.trim()
  const followupQuestions = metrics?.followup_questions
    ?.map((question) => question.trim())
    .filter((question) => question.length > 0)
    .slice(0, 3)
  const metricEntries = DIAGNOSTIC_METRICS.flatMap((name) => {
    const value = formatMetricValue(metrics?.[name])
    return value === undefined ? [] : [{ name, value }]
  })

  const citationRows = getCitationRows(message.citations)
  const citationPreviewRows = citationRows.slice(0, 2)

  const handleOpenEvidence = useCallback(
    (reference: ClaimEvidenceReference) => {
      const documentId = reference.document_id
      if (!documentId) return
      const chunkId = reference.chunk_id ?? undefined
      const start = reference.start_char
      const end = reference.end_char
      const range = start != null && end != null && end > start ? { start, end } : undefined
      const citation = findTargetCitation(message.citations, { documentId, chunkId })
      openDocument(documentId, chunkId, range, {
        previewAnchor: { searchText: reference.quote },
        sourceContext: buildChatCitationSourceContext(message.id, documentId, chunkId, citation),
      })
    },
    [message.citations, message.id, openDocument],
  )

  const handleFollowupPrefill = useCallback(
    (question: string) => {
      const prompt = question.trim()
      if (prompt === '') return
      if (onFollowupSelect) onFollowupSelect(prompt)
      else globalEventBus.emit('chat:submit', prompt)
    },
    [onFollowupSelect],
  )

  const handleInlineCitationClick = useCallback(
    (href?: string) => {
      const target = parseInlineCitationHref(href)
      if (!target) return

      const citation = findTargetCitation(message.citations, target)

      const documentId = target.documentId ?? citation?.document_id
      if (!documentId) return
      const range = target.range ?? (citation ? getCitationRange(citation) : undefined)

      openDocument(documentId, target.chunkId ?? undefined, range, {
        activeTab: 'preview',
        previewAnchor: target.pageNumber === undefined ? undefined : { pageNumber: target.pageNumber },
        sourceContext: buildChatCitationSourceContext(message.id, documentId, target.chunkId, citation),
      })
    },
    [message.citations, message.id, openDocument],
  )

  const prefetchCitationTarget = useCallback((citation?: Citation | null, target?: CitationTarget | null) => {
    const documentId = target?.documentId ?? citation?.document_id
    if (!documentId) return

    const chunkId = target?.chunkId ?? citation?.chunk_id
    const cacheKey = JSON.stringify([documentId, chunkId])
    if (prefetchedCitationTargetsRef.current.has(cacheKey)) return
    prefetchedCitationTargetsRef.current.add(cacheKey)

    prefetchDocumentView({
      documentId,
      chunkId: chunkId ?? undefined,
    })
  }, [])

  const handleInlineCitationPrefetch = useCallback(
    (href?: string) => {
      const target = parseInlineCitationHref(href)
      if (!target) return

      const citation = findTargetCitation(message.citations, target)

      prefetchCitationTarget(citation, target)
    },
    [message.citations, prefetchCitationTarget],
  )

  const handleOpenCitation = useCallback(
    (citation: Citation) => {
      if (!citation.document_id) return
      openDocument(citation.document_id, citation.chunk_id, getCitationRange(citation), {
        activeTab: 'preview',
        previewAnchor: getDocumentPreviewAnchorFromCitation(citation),
        sourceContext: buildChatCitationSourceContext(message.id, citation.document_id, citation.chunk_id, citation),
      })
    },
    [message.id, openDocument],
  )

  const inlineCitationHandlers = useMemo<InlineCitationHandlers>(
    () => ({
      onClick: handleInlineCitationClick,
      onPrefetch: handleInlineCitationPrefetch,
    }),
    [handleInlineCitationClick, handleInlineCitationPrefetch],
  )

  let renderedContent: ReactNode
  if (isUser) {
    renderedContent = (
      <div
        className={cn(
          'whitespace-pre-wrap font-normal [&>*]:text-inherit',
          isHistory ? 'text-foreground' : 'text-primary-foreground',
        )}
      >
        {message.content}
      </div>
    )
  } else if (isStreaming) {
    renderedContent = <CinematicTypewriter content={message.content} isStreaming={true} />
  } else {
    renderedContent = (
      <InlineCitationHandlersContext.Provider value={inlineCitationHandlers}>
        <ReactMarkdown
          remarkPlugins={markdownPlugins}
          skipHtml
          components={markdownBaseComponents}
          urlTransform={transformMessageMarkdownUrl}
        >
          {message.content}
        </ReactMarkdown>
      </InlineCitationHandlersContext.Provider>
    )
  }

  const canRate = (() => {
    if (isUser) return false
    if (isStreaming) return false
    // Feedback API requires persisted assistant message UUID.
    return /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(message.id)
  })()

  const submitRating = useCallback(
    async (nextRating: number) => {
      const owner = messageOwnerRef.current
      if (!canRate || !owner.active || owner.ratingSending) return
      const sessionRevision = getAuthSessionRevision()
      const previousRating = rating
      owner.ratingSending = true
      setRating(nextRating)
      setRatingSending(true)
      try {
        const created = await feedbackApi.create({
          message_id: message.id,
          rating: nextRating,
          reason: feedbackRecord?.reason,
          tags: feedbackRecord?.tags,
          expected_answer: feedbackRecord?.expected_answer,
        })
        if (!isCurrentMessageOperation(owner, sessionRevision)) return
        setRating(created.rating)
        setFeedbackRecord(created)
        toast.success('已提交反馈')
      } catch (err: unknown) {
        if (isCurrentMessageOperation(owner, sessionRevision)) {
          setRating(previousRating)
          toast.error(formatApiError(err, '反馈提交失败'))
        }
      } finally {
        owner.ratingSending = false
        if (owner.active) {
          if (sessionRevision !== getAuthSessionRevision()) setRating(previousRating)
          setRatingSending(false)
        }
      }
    },
    [canRate, feedbackRecord, message.id, rating],
  )

  const submitFeedbackCategory = useCallback(
    async (category: FeedbackCategory) => {
      const owner = messageOwnerRef.current
      if (!canRate || rating == null || rating > 2 || !owner.active || owner.ratingSending) return
      const sessionRevision = getAuthSessionRevision()
      owner.ratingSending = true
      setRatingSending(true)
      try {
        const updated = await feedbackApi.create({
          message_id: message.id,
          rating,
          category,
          reason: feedbackRecord?.reason,
          tags: feedbackRecord?.tags,
          expected_answer: feedbackRecord?.expected_answer,
        })
        if (!isCurrentMessageOperation(owner, sessionRevision)) return
        setFeedbackRecord(updated)
        toast.success('已记录问题分类')
      } catch (err: unknown) {
        if (isCurrentMessageOperation(owner, sessionRevision)) toast.error(formatApiError(err, '问题分类提交失败'))
      } finally {
        owner.ratingSending = false
        if (owner.active) setRatingSending(false)
      }
    },
    [canRate, feedbackRecord, message.id, rating],
  )

  const handleSendFeedbackToEvidence = useCallback(() => {
    const feedbackId = feedbackRecord?.id.trim()
    const owner = messageOwnerRef.current
    if (!feedbackId || !owner.active || owner.expertAction) return
    const sessionRevision = getAuthSessionRevision()

    owner.expertAction = 'evidence'
    setExpertAction('evidence')
    try {
      const feedbackDatasetId = feedbackRecord?.extra?.dataset_id
      const datasetId = typeof feedbackDatasetId === 'string' ? feedbackDatasetId.trim() : messageDatasetId
      if (!datasetId) {
        toast.error('未解析到数据集，暂时无法打开证据库')
        return
      }
      router.push(`/datasets/${encodeURIComponent(datasetId)}/evidence?feedback_id=${encodeURIComponent(feedbackId)}`)
    } catch (error: unknown) {
      if (isCurrentMessageOperation(owner, sessionRevision)) toast.error(formatApiError(error, '打开证据库失败'))
    } finally {
      owner.expertAction = null
      if (owner.active) setExpertAction(null)
    }
  }, [feedbackRecord?.extra, feedbackRecord?.id, messageDatasetId, router])

  const handleCreateRegressionCase = useCallback(async () => {
    const feedbackId = feedbackRecord?.id.trim()
    const owner = messageOwnerRef.current
    if (!feedbackId || !owner.active || owner.expertAction) return
    const sessionRevision = getAuthSessionRevision()

    owner.expertAction = 'regression'
    setExpertAction('regression')
    try {
      await feedbackApi.toRegressionCase(feedbackId, {
        include_document_scope: true,
        extra: { source: 'chat_feedback_action' },
      })
      if (!isCurrentMessageOperation(owner, sessionRevision)) return
      toast.success('已创建回归用例')
    } catch (error: unknown) {
      if (isCurrentMessageOperation(owner, sessionRevision)) toast.error(formatApiError(error, '转为回归用例失败'))
    } finally {
      owner.expertAction = null
      if (owner.active) setExpertAction(null)
    }
  }, [feedbackRecord?.id])

  return (
    <motion.div
      data-chat-message-variant={variant}
      layout={!reduceMotion && isStreaming}
      transition={streamingLayoutTransition}
      className={cn(
        'flex gap-3 group animate-in fade-in slide-in-from-bottom-2 duration-300 motion-reduce:animate-none',
        isHistory ? 'justify-start' : isUser ? (isCompact ? 'justify-end' : 'pb-4 justify-end') : 'justify-start',
        isCompact ? 'w-full' : '',
      )}
    >
      {!isUser && !isHistory && (
        <div
          className={cn(
            'flex-shrink-0 flex items-center justify-center shadow-sm mt-0.5 transition-all duration-300',
            variant === 'minimal'
              ? 'size-8 rounded-full bg-background/90 border border-border/50 group-hover:border-primary/25 group-hover:shadow-md'
              : 'w-8 h-8 rounded-xl bg-accent/15 border border-accent/30',
          )}
        >
          <Bot
            className={cn('size-4', variant === 'minimal' ? 'text-primary/60 group-hover:text-primary' : 'text-accent')}
          />
        </div>
      )}

      <motion.div
        layout={!reduceMotion && isStreaming}
        transition={streamingLayoutTransition}
        className={cn(
          'relative text-[15px] transition-all duration-300 motion-reduce:transition-none',
          isHistory
            ? 'min-w-0 flex-1 text-foreground'
            : variant === 'minimal'
              ? isUser
                ? 'max-w-[78%] px-4 py-3 rounded-2xl rounded-br-md border border-[#BDE0FE] bg-[#A2D2FF] text-black shadow-sm backdrop-blur-sm'
                : 'max-w-[88%] px-4 py-3 flex-1 rounded-2xl rounded-bl-md border border-border/60 bg-background/92 text-foreground shadow-sm backdrop-blur-sm'
              : isUser
                ? 'max-w-3xl px-6 py-4 rounded-2xl rounded-tr-sm border border-[#8FC8E8] bg-[#AAD9F2] text-[#17384D] shadow-sm backdrop-blur-sm'
                : 'max-w-3xl px-6 py-4 glass-card text-foreground rounded-2xl rounded-tl-sm border border-border/60 border-l-4 hover:shadow-lg hover:shadow-primary/10',
          (isUser || !isCompact) && (confidenceMeta?.lineClass ?? 'border-l-primary/30'),
        )}
      >
        {isHistory && isUser && (
          <div className="mb-3 flex items-center gap-2.5 text-[12.5px] font-medium text-foreground">
            <span className="flex size-[22px] items-center justify-center rounded-full border border-border text-muted-foreground">
              <User className="size-[13px]" />
            </span>
            <span>你</span>
            <time
              suppressHydrationWarning
              dateTime={message.created_at}
              className="ml-auto text-[11.5px] font-normal tabular-nums text-muted-foreground"
            >
              {new Intl.DateTimeFormat('zh-CN', { hour: '2-digit', minute: '2-digit' }).format(
                new Date(message.created_at),
              )}
            </time>
          </div>
        )}
        {!isUser && isCompact && (
          <div className="flex items-center gap-2 mb-2.5">
            {isHistory && <BrandLogo variant="mark" decorative className="size-6" />}
            <span
              className={
                isHistory ? 'text-[13.5px] font-semibold text-foreground' : 'text-[11px] font-medium text-foreground/80'
              }
            >
              {BRAND_NAME}
            </span>
            <span
              suppressHydrationWarning
              className={
                isHistory
                  ? 'ml-auto text-[11.5px] text-muted-foreground tabular-nums'
                  : 'text-[9px] font-medium text-muted-foreground/40 tabular-nums'
              }
            >
              {new Intl.DateTimeFormat('zh-CN', { hour: '2-digit', minute: '2-digit' }).format(
                new Date(message.created_at),
              )}
            </span>
          </div>
        )}
        {/* 思维链 / 步骤展示 */}
        <AnimatePresence initial={false}>
          {!isUser && message.steps && stepCount > 0 ? (
            <motion.div
              layout={!reduceMotion && isStreaming}
              transition={streamingLayoutTransition}
              initial={reduceMotion ? false : { opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={reduceMotion ? undefined : { opacity: 0, y: -8 }}
              className="mb-4 overflow-hidden rounded-2xl border border-primary/15 bg-primary/[0.035] motion-safe:animate-fade-in"
            >
              <button
                type="button"
                aria-expanded={stepsOpen}
                aria-controls={stepsPanelId}
                onClick={() => setStepsOpen((open) => !open)}
                className="flex w-full items-center gap-3 px-3 py-2.5 text-left transition-colors hover:bg-primary/[0.05] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60"
              >
                <div className="relative flex h-2 w-2 shrink-0">
                  {isStreaming ? (
                    <span className="motion-safe:animate-ping absolute inline-flex h-full w-full rounded-full bg-primary opacity-75" />
                  ) : null}
                  <span className="relative inline-flex h-2 w-2 rounded-full bg-primary" />
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="text-[11px] font-bold uppercase text-primary/75">思考路径</span>
                    <span className="rounded-full border border-primary/15 bg-background/60 px-2 py-0.5 text-[10px] font-medium text-muted-foreground">
                      {stepCount} 步
                    </span>
                  </div>
                  {!stepsOpen && latestStep ? (
                    <div className="mt-0.5 truncate text-[11px] text-muted-foreground">{latestStep}</div>
                  ) : null}
                </div>
                <ChevronDown
                  className={cn(
                    'size-3.5 shrink-0 text-muted-foreground transition-transform duration-200 motion-reduce:transition-none',
                    stepsOpen && 'rotate-180',
                  )}
                  aria-hidden="true"
                />
              </button>

              <AnimatePresence initial={false}>
                {stepsOpen ? (
                  <motion.div
                    id={stepsPanelId}
                    initial={reduceMotion ? false : { height: 0, opacity: 0 }}
                    animate={{ height: 'auto', opacity: 1 }}
                    exit={reduceMotion ? undefined : { height: 0, opacity: 0 }}
                    transition={streamingLayoutTransition}
                    className="overflow-hidden"
                  >
                    <div className="space-y-1 border-t border-primary/10 px-4 py-3">
                      {message.steps.map((step, idx) => (
                        <div
                          key={`${idx}-${step}`}
                          className={cn(
                            'text-xs transition-opacity duration-200 motion-reduce:transition-none',
                            idx === stepCount - 1
                              ? 'font-medium text-foreground motion-safe:animate-pulse'
                              : 'text-muted-foreground/60',
                          )}
                        >
                          {step}
                        </div>
                      ))}
                    </div>
                  </motion.div>
                ) : null}
              </AnimatePresence>
            </motion.div>
          ) : null}
        </AnimatePresence>

        {!isUser && message.message_metadata && (
          <>
            <button
              type="button"
              onClick={() => setDiagOpen(true)}
              aria-label="Diagnostics"
              title="检索诊断"
              className={cn(
                'absolute bottom-2 right-11 z-10 rounded-md p-1 transition-colors duration-200 motion-reduce:transition-none',
                'opacity-0 group-hover:opacity-100 scale-90 group-hover:scale-100 transition-opacity transition-transform',
                'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60',
                'text-muted-foreground hover:text-foreground hover:bg-muted/60',
              )}
            >
              <BarChart3 className="size-3.5" />
            </button>

            <Dialog open={diagOpen} onOpenChange={setDiagOpen}>
              <DialogContent className="max-w-4xl border border-border bg-popover text-popover-foreground p-0 overflow-hidden shadow-strong sm:rounded-2xl">
                <DialogHeader className="px-6 py-5 border-b border-border bg-card">
                  <div className="flex items-start justify-between gap-4">
                    <DialogTitle className="flex items-center gap-3">
                      <div className="size-10 rounded-xl bg-primary/10 border border-primary/20 text-primary flex items-center justify-center">
                        <BarChart3 className="size-5" aria-hidden="true" />
                      </div>
                      <div className="min-w-0">
                        <div className="text-base font-semibold text-foreground">检索诊断</div>
                        <div className="text-xs text-muted-foreground">message_metadata / citations（仅用于调试）</div>
                      </div>
                    </DialogTitle>
                    <Button size="sm" variant="outline" onClick={handleCopyDiagnostics} className="text-xs">
                      <Copy className="size-3.5 mr-2" />
                      复制 JSON
                    </Button>
                  </div>
                </DialogHeader>

                <div className="p-6 md:p-8 space-y-6 max-h-[70vh] overflow-y-auto overscroll-contain no-scrollbar">
                  <div className="grid grid-cols-1 md:grid-cols-12 gap-6">
                    <div className="md:col-span-5 space-y-6">
                      <div className="rounded-xl border border-border bg-card overflow-hidden">
                        <div className="px-4 py-2.5 border-b border-border bg-muted/30">
                          <div className="text-xs font-semibold text-foreground">元数据</div>
                        </div>
                        <div className="p-4 space-y-4">
                          <div>
                            <div className="text-[11px] text-muted-foreground mb-1">Message ID</div>
                            <div className="font-mono text-xs tabular-nums break-all rounded-md border border-border bg-background/50 p-2 select-all">
                              {message.id}
                            </div>
                          </div>

                          {metricEntries.length ? (
                            <dl className="space-y-2 text-xs">
                              {metricEntries.map((entry) => (
                                <div key={entry.name} className="flex items-start justify-between gap-3">
                                  <dt className="text-muted-foreground">{entry.name}</dt>
                                  <dd className="font-mono tabular-nums text-foreground text-right break-all">
                                    {entry.value}
                                  </dd>
                                </div>
                              ))}
                            </dl>
                          ) : (
                            <div className="text-xs text-muted-foreground">无可用指标。</div>
                          )}
                        </div>
                      </div>

                      <div className="rounded-xl border border-border bg-card overflow-hidden">
                        <div className="px-4 py-2.5 border-b border-border bg-muted/30">
                          <div className="text-xs font-semibold text-foreground">Raw payload</div>
                        </div>
                        <pre className="p-4 text-[11px] font-mono tabular-nums text-muted-foreground overflow-auto max-h-56 custom-scrollbar">
                          {diagOpen ? JSON.stringify(diagnostics, null, 2) : null}
                        </pre>
                      </div>
                    </div>

                    <div className="md:col-span-7 space-y-6">
                      <div className="rounded-xl border border-border bg-card overflow-hidden min-h-[300px] flex flex-col">
                        <div className="px-4 py-2.5 border-b border-border bg-muted/30 flex items-center justify-between gap-3">
                          <div className="text-xs font-semibold text-foreground">引用来源</div>
                          <div className="text-xs text-muted-foreground tabular-nums">{citationRows.length} 条</div>
                        </div>

                        {citationRows.length ? (
                          <div className="overflow-x-auto flex-1">
                            <table aria-label="消息引用明细" className="w-full text-xs text-left tabular-nums">
                              <thead className="text-muted-foreground">
                                <tr className="border-b border-border">
                                  <th className="px-4 py-2.5 font-medium">#</th>
                                  <th className="px-4 py-2.5 font-medium">Document / Source</th>
                                  <th className="px-4 py-2.5 font-medium text-right">Page</th>
                                  <th className="px-4 py-2.5 font-medium text-right">Score</th>
                                  <th className="px-4 py-2.5 font-medium text-right">Vector</th>
                                  <th className="px-4 py-2.5 font-medium text-right">BM25</th>
                                  <th className="px-4 py-2.5 font-medium text-right">Rerank</th>
                                </tr>
                              </thead>
                              <tbody className="divide-y divide-border">
                                {citationRows.map(({ citation, key }, idx) => {
                                  return (
                                    <tr
                                      key={key}
                                      className="hover:bg-muted/30 transition-colors duration-200 motion-reduce:transition-none"
                                    >
                                      <td className="px-4 py-2.5 text-muted-foreground">{idx + 1}</td>
                                      <td className="px-4 py-2.5">
                                        <div
                                          className="max-w-[240px] truncate text-foreground font-medium"
                                          title={citation.document_name}
                                        >
                                          {citation.document_name}
                                        </div>
                                      </td>
                                      <td className="px-4 py-2.5 text-right font-mono">
                                        {citation.page_number ?? '-'}
                                      </td>
                                      <td className="px-4 py-2.5 text-right font-mono font-semibold">
                                        {citation.relevance_score.toFixed(3)}
                                      </td>
                                      <td className="px-4 py-2.5 text-right font-mono">
                                        {citation.vector_score === undefined ? '-' : citation.vector_score.toFixed(3)}
                                      </td>
                                      <td className="px-4 py-2.5 text-right font-mono">
                                        {citation.bm25_score === undefined ? '-' : citation.bm25_score.toFixed(3)}
                                      </td>
                                      <td className="px-4 py-2.5 text-right font-mono">
                                        {citation.rerank_score === undefined ? '-' : citation.rerank_score.toFixed(3)}
                                      </td>
                                    </tr>
                                  )
                                })}
                              </tbody>
                            </table>
                          </div>
                        ) : (
                          <div className="flex-1 flex items-center justify-center p-8 text-muted-foreground text-sm">
                            未记录 citations
                          </div>
                        )}
                      </div>

                      <div className="rounded-xl border border-border bg-card overflow-hidden min-h-[240px] flex flex-col">
                        <div className="px-4 py-2.5 border-b border-border bg-muted/30 flex items-center justify-between gap-3">
                          <div className="text-xs font-semibold text-foreground">Claim Evidence</div>
                          <div className="text-xs text-muted-foreground tabular-nums">
                            {claimEvidence ? `${claimEvidence.length} 条` : '-'}
                          </div>
                        </div>

                        {claimEvidence?.length ? (
                          <div className="p-4 space-y-3 overflow-auto max-h-72 custom-scrollbar">
                            {claimEvidence.slice(0, 24).map((item, idx) => {
                              const claim = item.claim
                              const evidence = item.evidence
                              return (
                                <div
                                  key={`${idx}:${claim}`}
                                  className="rounded-lg border border-border/60 bg-background/40 p-3"
                                >
                                  <div className="flex items-start justify-between gap-3">
                                    <div className="min-w-0 text-xs font-semibold text-foreground leading-relaxed line-clamp-3">
                                      {claim}
                                    </div>
                                    <div className="flex-shrink-0 text-[11px] text-muted-foreground tabular-nums">
                                      {evidence.length} 证据
                                    </div>
                                  </div>

                                  {evidence.length ? (
                                    <div className="mt-2 space-y-2">
                                      {evidence.slice(0, 3).map((reference, referenceIndex) => {
                                        const documentId = reference.document_id
                                        const chunkId = reference.chunk_id
                                        const citation = findTargetCitation(message.citations, { documentId, chunkId })
                                        const documentName =
                                          citation?.document_name ?? (documentId === null ? '未提供文档' : documentId)
                                        const disabled = !documentId

                                        return (
                                          <button
                                            key={JSON.stringify([documentId, chunkId, referenceIndex])}
                                            type="button"
                                            disabled={disabled}
                                            aria-label={
                                              disabled ? 'Evidence unavailable' : 'Open evidence in document viewer'
                                            }
                                            onClick={() => handleOpenEvidence(reference)}
                                            className={cn(
                                              'w-full text-left rounded-md border border-border/50 bg-background/50 px-3 py-2 transition-colors duration-200 motion-reduce:transition-none',
                                              disabled
                                                ? 'opacity-60 cursor-not-allowed'
                                                : 'hover:bg-muted/30 hover:border-primary/25 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60',
                                            )}
                                          >
                                            <div className="flex items-start justify-between gap-3">
                                              <div className="min-w-0">
                                                <div
                                                  className="text-[11px] font-semibold text-foreground truncate"
                                                  title={documentName}
                                                >
                                                  {documentName}
                                                </div>
                                                <div className="text-[11px] text-muted-foreground tabular-nums">
                                                  {citation?.page_number === undefined
                                                    ? '—'
                                                    : `P.${citation.page_number}`}
                                                  {reference.start_char !== null && reference.end_char !== null
                                                    ? ` · ${reference.start_char}-${reference.end_char}`
                                                    : null}
                                                </div>
                                              </div>
                                              <div className="text-[11px] font-mono text-muted-foreground tabular-nums">
                                                {reference.score.toFixed(3)}
                                              </div>
                                            </div>
                                            {reference.quote ? (
                                              <div className="mt-1 text-xs text-muted-foreground line-clamp-2 leading-relaxed">
                                                {reference.quote}
                                              </div>
                                            ) : null}
                                          </button>
                                        )
                                      })}
                                    </div>
                                  ) : (
                                    <div className="mt-2 text-xs text-muted-foreground">未找到可见证据。</div>
                                  )}
                                </div>
                              )
                            })}
                          </div>
                        ) : (
                          <div className="flex-1 flex items-center justify-center p-8 text-muted-foreground text-sm text-center">
                            <div className="max-w-md">
                              <div className="text-xs font-semibold text-foreground/80">未记录 Claim Evidence</div>
                              <div className="mt-1 text-xs text-muted-foreground">
                                提示：开启 “严格可见证据” 或 “claim check” 后会自动生成。
                              </div>
                            </div>
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                </div>
              </DialogContent>
            </Dialog>
          </>
        )}

        <button
          type="button"
          onClick={handleCopy}
          aria-label={copied ? 'Copied' : 'Copy message'}
          title={copied ? 'Copied' : 'Copy'}
          className={cn(
            'absolute z-10 rounded-md p-1 transition-colors duration-200 motion-reduce:transition-none',
            isUser
              ? 'bottom-0 right-0 translate-x-1/4 translate-y-1/4 border border-border/60 bg-background/95 shadow-sm'
              : 'bottom-2 right-2',
            'opacity-0 group-hover:opacity-100 scale-90 group-hover:scale-100 transition-opacity transition-transform',
            'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60',
            'text-muted-foreground hover:text-foreground hover:bg-muted/60',
            isHistory && !isUser && 'hidden',
          )}
        >
          {copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
        </button>

        {!isUser && (hasConfidence || (!isHistory && citationPreviewRows.length > 0)) && (
          <div className="mb-4 space-y-3 pr-16">
            {hasConfidence ? (
              <div className="flex flex-wrap items-center gap-2">
                <div
                  className={cn(
                    'inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] font-semibold tabular-nums',
                    confidenceMeta?.badgeClass,
                  )}
                >
                  <BarChart3 className="size-3" />
                  <span>{confidenceMeta?.label ?? '置信度'}</span>
                  {confidenceScore != null ? <span>{Math.round(confidenceScore * 100)}%</span> : null}
                </div>
              </div>
            ) : null}

            {!isHistory && citationPreviewRows.length > 0 && (
              <div className="space-y-2">
                <div className="text-[11px] font-bold uppercase tracking-[0.18em] text-muted-foreground/80">
                  来源速览
                </div>
                <div className="flex gap-2 overflow-x-auto pb-1 no-scrollbar">
                  {citationPreviewRows.map(({ citation, key }, idx) => {
                    return (
                      <button
                        key={key}
                        type="button"
                        onClick={() => handleOpenCitation(citation)}
                        className="flex shrink-0 items-center gap-2 rounded-full border border-border/60 bg-background/70 px-3 py-1.5 text-xs text-foreground transition-colors hover:border-primary/25 hover:bg-muted/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60"
                      >
                        <span className="inline-flex h-5 min-w-5 items-center justify-center rounded-full bg-primary/10 px-1.5 text-[11px] font-semibold text-primary">
                          {idx + 1}
                        </span>
                        <span className="max-w-[180px] truncate font-medium">{citation.document_name}</span>
                        {citation.page_number == null ? null : (
                          <span className="text-muted-foreground">P.{citation.page_number}</span>
                        )}
                      </button>
                    )
                  })}
                  {citationRows.length > citationPreviewRows.length ? (
                    <div className="flex shrink-0 items-center rounded-full border border-dashed border-border/70 px-3 py-1.5 text-xs text-muted-foreground">
                      +{citationRows.length - citationPreviewRows.length} 条来源
                    </div>
                  ) : null}
                </div>
              </div>
            )}
          </div>
        )}

        <div
          className={cn(
            isUser
              ? cn(
                  'max-w-none break-words leading-relaxed [&>*]:text-inherit',
                  isHistory ? 'text-[16px] leading-[1.85] text-foreground' : 'text-primary-foreground',
                )
              : 'prose prose-neutral dark:prose-invert max-w-none break-words leading-relaxed prose-p:my-2 prose-p:leading-7 prose-pre:bg-secondary/50 prose-pre:border prose-pre:border-border/50 prose-pre:text-foreground prose-pre:rounded-xl prose-pre:p-4 prose-pre:my-3 prose-code:bg-[hsl(var(--code-background))] prose-code:px-1.5 prose-code:py-0.5 prose-code:rounded-md prose-code:text-sm prose-code:font-mono prose-code:text-primary prose-code:before:content-none prose-code:after:content-none',
            isHistory && !isUser && 'text-[15.5px] leading-[1.85] prose-p:leading-[1.85]',
          )}
        >
          {renderedContent}
        </div>

        {isUser && message.message_metadata?.send_state === 'sending' && (
          <p role="status" className="mt-2 text-xs text-primary-foreground/80">
            正在发送…
          </p>
        )}
        {isUser && message.message_metadata?.send_state === 'unconfirmed' && (
          <p role="status" className="mt-2 text-xs text-primary-foreground/80">
            尚未确认发送，请查看错误后再重试
          </p>
        )}
        {!isUser && message.message_metadata?.stopped === true && (
          <p className="mt-2 text-xs text-muted-foreground">已停止，部分回答暂存在本页</p>
        )}

        {isHistory && !isUser && citationRows.length > 0 && (
          <section aria-label="引用来源" className="mt-6 border-t border-border pt-4">
            <h3 className="mb-2 text-xs font-medium text-muted-foreground">引用来源</h3>
            <div className="space-y-1">
              {citationRows.map(({ citation, key }, idx) => (
                <button
                  key={key}
                  type="button"
                  onClick={() => handleOpenCitation(citation)}
                  className="flex min-h-8 w-full items-center gap-2 rounded-sm py-1 text-left text-[13px] leading-5 text-foreground transition-colors hover:bg-muted/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring motion-reduce:transition-none max-md:min-h-11"
                >
                  <FileText className="size-3.5 shrink-0 text-muted-foreground" />
                  <span className="w-4 shrink-0 text-[11.5px] tabular-nums text-muted-foreground">{idx + 1}.</span>
                  <span className="min-w-0 break-words">{citation.document_name}</span>
                  {citation.page_number != null && (
                    <span className="shrink-0 text-[11.5px] text-muted-foreground">第 {citation.page_number} 页</span>
                  )}
                  <ArrowUpRight className="size-3 shrink-0 text-muted-foreground" />
                </button>
              ))}
            </div>
          </section>
        )}

        {!isUser && followupQuestions && followupQuestions.length > 0 && (
          <div className="mt-5 pt-3 border-t border-border/40 space-y-3">
            <div className="flex items-center gap-2 text-[11px] font-bold text-muted-foreground uppercase opacity-80">
              继续追问
            </div>
            <div className="flex flex-wrap gap-2">
              {followupQuestions.map((question) => (
                <Button
                  key={question}
                  type="button"
                  size="sm"
                  variant="outline"
                  onClick={() => handleFollowupPrefill(question)}
                  className="h-auto whitespace-normal rounded-full px-3 py-1.5 text-left text-xs leading-5"
                >
                  {question}
                </Button>
              ))}
            </div>
          </div>
        )}

        {!isUser && ((!isHistory && citationRows.length > 0) || claimEvidenceCount > 0) && (
          <details
            className={
              isHistory
                ? 'mt-5 border-t border-border'
                : 'mt-5 overflow-hidden rounded-2xl border border-border/60 bg-background/35 open:bg-background/45'
            }
          >
            <summary
              className={cn(
                'flex cursor-pointer list-none items-center justify-between gap-3 py-3 [&::-webkit-details-marker]:hidden',
                !isHistory && 'px-4',
              )}
            >
              <div>
                <div className="text-[11px] font-bold uppercase tracking-[0.18em] text-muted-foreground/80">
                  来源与证据
                </div>
                <div className="mt-1 text-xs text-muted-foreground">
                  {citationRows.length ? `${citationRows.length} 条来源` : '暂无引用来源'}
                  {claimEvidenceCount > 0 ? ` · ${claimEvidenceCount} 条 claim evidence` : ''}
                </div>
              </div>
              <span className="text-[11px] text-muted-foreground">展开详情</span>
            </summary>
            <div className="space-y-4 border-t border-border/50 px-4 py-4">
              {!isHistory && citationRows.length > 0 && (
                <div className="space-y-3">
                  <div className="flex items-center gap-2 text-[11px] font-bold uppercase tracking-[0.18em] text-muted-foreground/80">
                    <Database className="size-3" />
                    参考来源
                  </div>
                  <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                    {citationRows.map(({ citation, key }, idx) => {
                      return <CitationCard key={key} messageId={message.id} citation={citation} index={idx} />
                    })}
                  </div>
                </div>
              )}

              {claimEvidenceCount > 0 && (
                <div className="space-y-3">
                  <div className="flex items-center justify-between gap-2">
                    <div className="text-[11px] font-bold uppercase tracking-[0.18em] text-muted-foreground/80">
                      Claim Evidence
                    </div>
                    <div className="text-[11px] text-muted-foreground">{claimEvidenceCount} 条</div>
                  </div>
                  <div className="space-y-3">
                    {claimEvidence?.slice(0, 6).map((item, idx) => {
                      const claim = item.claim
                      const evidence = item.evidence
                      return (
                        <div key={`${idx}:${claim}`} className="rounded-xl border border-border/60 bg-card/70 p-3">
                          <div className="flex items-start justify-between gap-3">
                            <div className="min-w-0 text-sm font-medium leading-6 text-foreground/90">{claim}</div>
                            <div className="shrink-0 text-[11px] text-muted-foreground">{evidence.length} 证据</div>
                          </div>

                          {evidence.length ? (
                            <div className="mt-3 flex flex-col gap-2">
                              {evidence.slice(0, 2).map((reference, referenceIndex) => {
                                const documentId = reference.document_id
                                const chunkId = reference.chunk_id
                                const citation = findTargetCitation(message.citations, { documentId, chunkId })
                                const documentName =
                                  citation?.document_name ?? (documentId === null ? '未提供文档' : documentId)
                                const disabled = !documentId

                                return (
                                  <button
                                    key={JSON.stringify([documentId, chunkId, referenceIndex])}
                                    type="button"
                                    disabled={disabled}
                                    onClick={() => handleOpenEvidence(reference)}
                                    className={cn(
                                      'w-full rounded-xl border border-border/50 bg-background/70 px-3 py-2 text-left transition-colors',
                                      disabled
                                        ? 'cursor-not-allowed opacity-60'
                                        : 'hover:border-primary/25 hover:bg-muted/30 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60',
                                    )}
                                  >
                                    <div className="flex items-start justify-between gap-3">
                                      <div className="min-w-0">
                                        <div
                                          className="truncate text-[11px] font-semibold text-foreground"
                                          title={documentName}
                                        >
                                          {documentName}
                                        </div>
                                        <div className="text-[11px] text-muted-foreground tabular-nums">
                                          {citation?.page_number === undefined ? '—' : `P.${citation.page_number}`}
                                          {reference.start_char !== null && reference.end_char !== null
                                            ? ` · ${reference.start_char}-${reference.end_char}`
                                            : null}
                                        </div>
                                      </div>
                                      <div className="text-[11px] font-mono text-muted-foreground tabular-nums">
                                        {reference.score.toFixed(3)}
                                      </div>
                                    </div>
                                    {reference.quote ? (
                                      <div className="mt-1 line-clamp-2 text-xs leading-relaxed text-muted-foreground">
                                        {reference.quote}
                                      </div>
                                    ) : null}
                                  </button>
                                )
                              })}
                            </div>
                          ) : (
                            <div className="mt-2 text-xs text-muted-foreground">未找到可见证据。</div>
                          )}
                        </div>
                      )
                    })}
                  </div>
                </div>
              )}
            </div>
          </details>
        )}

        {!isUser && (isHistory || canRate) && (
          <div className={isHistory ? 'mt-3 flex flex-wrap items-start gap-x-5' : undefined}>
            {isHistory && (
              <button
                type="button"
                onClick={handleCopy}
                aria-label={copied ? 'Copied' : 'Copy message'}
                className="inline-flex min-h-8 items-center gap-1.5 rounded-sm text-[11.5px] text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring max-md:min-h-11"
              >
                {copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
                {copied ? '已复制' : '复制回答'}
              </button>
            )}
            {canRate && (
              <details
                className={
                  isHistory
                    ? 'open:w-full'
                    : 'mt-4 overflow-hidden rounded-2xl border border-border/60 bg-background/35 open:bg-background/45'
                }
              >
                <summary
                  className={cn(
                    'cursor-pointer list-none [&::-webkit-details-marker]:hidden',
                    isHistory
                      ? 'inline-flex min-h-8 items-center gap-1.5 rounded-sm text-[11.5px] text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring max-md:min-h-11'
                      : 'flex items-center justify-between gap-3 px-4 py-3',
                  )}
                >
                  {isHistory ? (
                    <>
                      <Star className="size-3.5" />
                      <span>{rating == null ? '评价回答' : `我的评分 ${rating} / 5`}</span>
                    </>
                  ) : (
                    <>
                      <div>
                        <div className="text-[11px] font-bold uppercase tracking-[0.18em] text-muted-foreground/80">
                          反馈评分
                        </div>
                        <div className="mt-1 text-xs text-muted-foreground">用 1-5 星记录这条回答是否有帮助。</div>
                      </div>
                      <span className="text-[11px] text-muted-foreground">
                        {rating == null ? '展开评分' : `${rating} / 5`}
                      </span>
                    </>
                  )}
                </summary>
                <div className="flex flex-col gap-3 border-t border-border/50 px-4 py-4 sm:flex-row sm:items-center sm:justify-between">
                  {!isHistory && (
                    <div className="text-xs text-muted-foreground">
                      评分越低，越适合后续进入回归或 evidence workbench 继续分析。
                    </div>
                  )}
                  <div className="flex items-center gap-1">
                    {[1, 2, 3, 4, 5].map((v) => {
                      const active = rating != null && v <= rating
                      return (
                        <button
                          key={v}
                          type="button"
                          disabled={ratingSending}
                          onClick={() => submitRating(v)}
                          className={cn(
                            'inline-flex h-8 w-8 items-center justify-center rounded-lg transition-colors',
                            'hover:bg-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60',
                            isHistory && 'max-md:size-11',
                            ratingSending && 'cursor-not-allowed opacity-50',
                          )}
                          aria-label={`rate-${v}`}
                          title={`${v} 星`}
                        >
                          <Star
                            className={cn('size-4', active ? 'text-warning' : 'text-muted-foreground')}
                            fill={active ? 'currentColor' : 'none'}
                          />
                        </button>
                      )
                    })}
                    {ratingSending ? <span className="ml-2 text-xs text-muted-foreground">提交中…</span> : null}
                  </div>
                </div>
                {rating != null && rating <= 2 ? (
                  <div className="flex flex-wrap items-center gap-2 border-t border-border/50 px-4 py-3">
                    <span className="mr-1 text-[11px] text-muted-foreground">主要问题</span>
                    {(
                      [
                        ['retrieval_miss', '没找到'],
                        ['wrong_answer', '答错了'],
                        ['out_of_scope', '超出范围'],
                      ] as const
                    ).map(([category, label]) => (
                      <Button
                        key={category}
                        type="button"
                        size="sm"
                        variant={feedbackRecord?.category === category ? 'default' : 'outline'}
                        className="h-7 rounded-full px-3 text-[11px]"
                        disabled={ratingSending}
                        onClick={() => submitFeedbackCategory(category)}
                      >
                        {label}
                      </Button>
                    ))}
                  </div>
                ) : null}
                {feedbackRecord?.id ? (
                  <div className="border-t border-border/50 px-4 py-3">
                    <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                      <div className="space-y-1">
                        <div className="text-[11px] font-medium text-foreground">已写入 expert loop</div>
                        <div className="text-[11px] text-muted-foreground font-mono">
                          feedback_id={feedbackRecord.id}
                        </div>
                      </div>
                      <div className="flex flex-wrap items-center gap-2">
                        <Button
                          type="button"
                          size="sm"
                          variant="outline"
                          onClick={() => detachPromise(handleSendFeedbackToEvidence())}
                          disabled={expertAction != null}
                          className="h-8 rounded-full gap-2"
                        >
                          {expertAction === 'evidence' ? (
                            <Loader2 className="size-3.5 animate-spin motion-reduce:animate-none" />
                          ) : (
                            <Database className="size-3.5" />
                          )}
                          送入证据库
                        </Button>
                        <Button
                          type="button"
                          size="sm"
                          variant="outline"
                          onClick={() => detachPromise(handleCreateRegressionCase())}
                          disabled={expertAction != null}
                          className="h-8 rounded-full gap-2"
                        >
                          {expertAction === 'regression' ? (
                            <Loader2 className="size-3.5 animate-spin motion-reduce:animate-none" />
                          ) : (
                            <TestTube2 className="size-3.5" />
                          )}
                          转为回归用例
                        </Button>
                      </div>
                    </div>
                  </div>
                ) : null}
              </details>
            )}
          </div>
        )}
      </motion.div>

      {isUser && !isHistory && (
        <div className="mt-0.5 flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-xl border border-primary/30 bg-primary/15 text-primary text-xs font-bold shadow-sm">
          <User className="size-4" />
        </div>
      )}
    </motion.div>
  )
})

const CitationCard = memo(function CitationCard({
  messageId,
  citation,
  index,
}: Readonly<{ messageId: string; citation: Citation; index: number }>) {
  const { openDocument } = useDocumentView()
  const [viewerOpen, setViewerOpen] = useState(false)
  const prefetchedRef = useRef(false)
  const imgUrl = (() => {
    if (!citation.img_url) return null
    return resolveSafeCitationImageUrl(citation.img_url)
  })()

  const isTableEvidence = (() => {
    const hitType = citation.hit_type?.trim().toLowerCase()
    const chunkRole = citation.chunk_role?.trim().toLowerCase()
    const semanticRole = citation.chunk_semantic_role?.trim().toLowerCase()
    return (
      hitType === 'tag' ||
      hitType === 'table' ||
      chunkRole?.includes('tag') ||
      chunkRole?.includes('table') ||
      semanticRole === 'table'
    )
  })()

  const canViewEvidence = Boolean((citation.has_image && imgUrl) || isTableEvidence)
  const sourceContext = buildChatCitationSourceContext(messageId, citation.document_id, citation.chunk_id, citation)
  const { relevanceScore, title: citationScoreTitle, secondaryScore } = getCitationScoreDetails(citation)

  const handleClick = useCallback(
    (e?: React.MouseEvent) => {
      e?.stopPropagation()
      if (citation.document_id) {
        openDocument(citation.document_id, citation.chunk_id, getCitationRange(citation), {
          activeTab: 'preview',
          previewAnchor: getDocumentPreviewAnchorFromCitation(citation),
          sourceContext,
        })
      }
    },
    [citation, openDocument, sourceContext],
  )

  const handlePrefetch = useCallback(() => {
    if (prefetchedRef.current) return
    if (!citation.document_id) return

    prefetchedRef.current = true
    prefetchDocumentView({
      documentId: citation.document_id,
      chunkId: citation.chunk_id,
    })
  }, [citation])

  return (
    <>
      <div className="group/card text-xs rounded-lg p-3 border bg-card border-border/60 transition-colors duration-150 motion-reduce:transition-none hover:bg-foreground/[0.04]">
        <button
          type="button"
          onClick={handleClick}
          onMouseEnter={handlePrefetch}
          onFocus={handlePrefetch}
          className="block w-full rounded-md text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60 focus-visible:ring-offset-2 focus-visible:ring-offset-background"
        >
          <div className="flex items-start gap-3">
            <span className="flex-shrink-0 w-5 h-5 bg-secondary text-primary border border-border rounded flex items-center justify-center text-[11px] font-bold group-hover/card:bg-primary group-hover/card:text-primary-foreground transition-colors">
              {index + 1}
            </span>
            <div className="flex-1 min-w-0 space-y-1">
              <p className="font-semibold text-foreground truncate transition-colors">
                {citation.document_name}
                {citation.page_number != null && (
                  <span className="text-muted-foreground font-normal ml-1">· P.{citation.page_number}</span>
                )}
              </p>
              <p className="text-muted-foreground mt-1 line-clamp-2 leading-relaxed group-hover/card:text-foreground/80 transition-colors">
                &quot;{citation.chunk_content}&quot;
              </p>
            </div>
          </div>
        </button>

        <div className="flex flex-wrap items-center gap-2 mt-2 pt-1">
          <span
            className="bg-secondary/50 border border-border text-muted-foreground px-1.5 py-0.5 rounded text-[11px]"
            title={citationScoreTitle}
          >
            综合分 {relevanceScore}
          </span>
          {secondaryScore !== undefined ? (
            <span
              className="bg-secondary/35 border border-border/70 text-muted-foreground px-1.5 py-0.5 rounded text-[11px]"
              title={citationScoreTitle}
            >
              {secondaryScore.label} {secondaryScore.value}
            </span>
          ) : null}
          {canViewEvidence ? (
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation()
                setViewerOpen(true)
              }}
              className={cn(
                'inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[11px] font-medium',
                'border border-border bg-background/60 text-foreground/80',
                'hover:bg-muted/40 hover:text-foreground transition-colors',
              )}
              aria-label="view-evidence"
              title="查看证据（图片/表格溯源）"
            >
              查看证据
            </button>
          ) : null}
        </div>

        {citation.has_image && imgUrl && (
          <div className="mt-2 rounded-md overflow-hidden border border-border/50">
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation()
                setViewerOpen(true)
              }}
              className="block relative aspect-video w-full focus:outline-none focus-visible:ring-2 focus-visible:ring-primary/60"
              aria-label="open-evidence-viewer"
              title="打开 Evidence Viewer"
            >
              <AuthImage
                src={imgUrl}
                alt="引用图片"
                fill
                unoptimized
                sizes="(max-width: 768px) 100vw, 300px"
                className="object-cover"
              />
            </button>
          </div>
        )}
      </div>
      <EvidenceViewerDialog
        open={viewerOpen}
        onOpenChange={setViewerOpen}
        citation={viewerOpen ? citation : null}
        sourceContext={sourceContext}
      />
    </>
  )
})
