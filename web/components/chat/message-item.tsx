/**
 * Shared chat message item (ChatArea + History).
 */
'use client'

import { AnimatePresence, motion, useReducedMotion } from 'framer-motion'
import { createContext, memo, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { BarChart3, Check, ChevronDown, Copy, Database, Bot, Loader2, Star, TestTube2, User } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

import { AuthImage } from '@/components/auth-image'
import { useRouter } from '@/i18n/navigation'
import { resolveMarkdownImageSrc, sanitizeMarkdownHref } from '@/components/markdown/markdown-safety'
import type { Citation, Message, MessageFeedback } from '@/types'
import { getDocumentPreviewAnchorFromCitation } from '@/lib/document-preview-anchor'
import { cn } from '@/lib/utils'
import { globalEventBus } from '@/lib/event-bus'
import { toAbsoluteBackendUrl } from '@/lib/env'
import { prefetchDocumentView } from '@/lib/document-view-prefetch'
import { useDocumentView, type DocumentViewSourceContext } from '@/store/document-view'
import { resolveSafeCitationImageUrl } from '@/lib/citation-images'
import { EvidenceViewerDialog } from '@/components/evidence/evidence-viewer-dialog'

import { CinematicTypewriter } from '@/components/ui/cinematic-typewriter'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { documentApi, feedbackApi } from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'
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

type ConfidenceMeta = Readonly<{
  label: string
  summary: string
  badgeClass: string
  lineClass: string
}>
type ClaimEvidenceReference = Record<string, unknown> & {
  document_id?: string
  chunk_id?: string
  start_char?: number
  end_char?: number
  score?: number
  quote?: string
}
type ClaimEvidenceItem = Record<string, unknown> & {
  claim?: string
  evidence?: ClaimEvidenceReference[]
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function claimEvidenceReferences(value: unknown): ClaimEvidenceReference[] {
  return Array.isArray(value)
    ? value.filter((item): item is ClaimEvidenceReference => isRecord(item))
    : []
}

function claimEvidenceItems(value: unknown): ClaimEvidenceItem[] | null {
  return Array.isArray(value)
    ? value.filter((item): item is ClaimEvidenceItem => isRecord(item))
    : null
}

function claimEvidenceReferenceKey(ev: ClaimEvidenceReference): string {
  return String(ev.chunk_id || ev.document_id || '')
}

function getCitationRange(citation: Citation): { start: number; end: number } | undefined {
  let start: number | null = null
  if (typeof citation.evidence_start_char === 'number') {
    start = citation.evidence_start_char
  } else if (typeof citation.start_char === 'number') {
    start = citation.start_char
  }

  let end: number | null = null
  if (typeof citation.evidence_end_char === 'number') {
    end = citation.evidence_end_char
  } else if (typeof citation.end_char === 'number') {
    end = citation.end_char
  }

  return start != null && end != null && end > start ? { start, end } : undefined
}

function parseInlineCitationHref(href?: string): { documentId?: string; chunkId?: string } | null {
  if (!href?.startsWith(INLINE_CITATION_HREF_PREFIX)) return null

  try {
    const parsed = new URL(href)
    const documentId = (parsed.searchParams.get('document_id') || '').trim() || undefined
    const chunkId = (parsed.searchParams.get('chunk_id') || '').trim() || undefined
    if (!documentId && !chunkId) return null
    return { documentId, chunkId }
  } catch {
    return null
  }
}

function buildChatCitationSourceContext(
  messageId: string,
  documentId: string | null | undefined,
  chunkId?: string | null
): DocumentViewSourceContext | null {
  const normalizedMessageId = String(messageId || '').trim()
  const normalizedDocumentId = String(documentId || '').trim()
  if (!normalizedMessageId || !normalizedDocumentId) return null

  const normalizedChunkId = String(chunkId || '').trim()
  return {
    kind: 'chat-citation',
    messageId: normalizedMessageId,
    documentId: normalizedDocumentId,
    chunkId: normalizedChunkId || null,
  }
}

function getConfidenceMeta(confidenceScore: number | null): ConfidenceMeta | null {
  if (confidenceScore == null) return null
  if (confidenceScore >= 0.75) {
    return {
      label: '✓ 高置信度',
      summary: '证据与回答整体一致',
      badgeClass: 'border-emerald-500/20 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300',
      lineClass: 'border-l-emerald-500/80',
    }
  }
  if (confidenceScore >= 0.5) {
    return {
      label: '⚠ 部分支撑',
      summary: '存在有效证据，但仍建议交叉确认',
      badgeClass: 'border-amber-500/20 bg-amber-500/10 text-amber-700 dark:text-amber-300',
      lineClass: 'border-l-amber-500/80',
    }
  }
  return {
    label: '✗ 证据不足',
    summary: '当前回答缺少足够支撑，建议继续追问',
    badgeClass: 'border-rose-500/20 bg-rose-500/10 text-rose-700 dark:text-rose-300',
    lineClass: 'border-l-rose-500/80',
  }
}

function formatMetricValue(value: unknown): string | null {
  if (typeof value === 'string') {
    const normalized = value.trim()
    return normalized || null
  }
  if (typeof value === 'number') {
    return Number.isFinite(value) ? String(value) : null
  }
  if (typeof value === 'boolean') {
    return value ? 'true' : 'false'
  }
  return null
}

function toFiniteScore(value: unknown): number | null {
  const score = Number(value)
  return Number.isFinite(score) ? score : null
}

function formatCitationScore(value: unknown): string {
  const score = toFiniteScore(value)
  if (score == null) return '—'
  if (score >= 0 && score <= 1) return `${Math.round(score * 100)}%`
  return score.toFixed(3)
}

function isUsableScore(value: unknown): boolean {
  const score = toFiniteScore(value)
  return score != null && score > 0
}

function getCitationSecondaryScore(citation: Citation): { label: string; value: string } | null {
  if (isUsableScore(citation.rerank_score)) {
    return { label: '重排', value: formatCitationScore(citation.rerank_score) }
  }
  if (isUsableScore(citation.vector_score)) {
    return { label: '向量', value: formatCitationScore(citation.vector_score) }
  }
  if (isUsableScore(citation.bm25_score)) {
    return { label: '关键词', value: formatCitationScore(citation.bm25_score) }
  }
  if (isUsableScore(citation.retrieval_score)) {
    return { label: '召回', value: formatCitationScore(citation.retrieval_score) }
  }
  return null
}

function buildCitationScoreTitle(citation: Citation): string {
  const parts = [
    `综合分 ${formatCitationScore(citation.relevance_score)}`,
    isUsableScore(citation.rerank_score) ? `重排 ${formatCitationScore(citation.rerank_score)}` : null,
    isUsableScore(citation.vector_score) ? `向量 ${formatCitationScore(citation.vector_score)}` : null,
    isUsableScore(citation.bm25_score) ? `关键词 ${formatCitationScore(citation.bm25_score)}` : null,
    isUsableScore(citation.retrieval_score) ? `召回 ${formatCitationScore(citation.retrieval_score)}` : null,
    citation.hit_type ? `命中类型 ${citation.hit_type}` : null,
  ]
  return parts.filter(Boolean).join(' · ')
}

const markdownPlugins = [remarkGfm]
type MessageMarkdownChildrenProps = Readonly<{ children?: ReactNode }>
type MessageMarkdownLinkProps = Readonly<{ href?: string; children?: ReactNode }>
type MessageMarkdownImageProps = Readonly<{ src?: string | Blob; alt?: string }>
type MessageMarkdownCodeProps = Readonly<{ className?: string; children?: ReactNode }>

function MessageMarkdownParagraph({ children }: MessageMarkdownChildrenProps) {
  return <p className="mb-3 last:mb-0 leading-relaxed">{children}</p>
}

function MessageMarkdownList({ children }: MessageMarkdownChildrenProps) {
  return (
    <ul className="list-disc pl-5 mb-3 space-y-1.5 marker:text-muted-foreground/60">
      {children}
    </ul>
  )
}

function MessageMarkdownOrderedList({ children }: MessageMarkdownChildrenProps) {
  return (
    <ol className="list-decimal pl-5 mb-3 space-y-1.5 marker:text-muted-foreground/60">
      {children}
    </ol>
  )
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
  if (!safeHref) return <span className="text-muted-foreground">{children}</span>

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
  const raw = typeof src === 'string' ? src : ''
  const resolved = resolveMarkdownImageSrc(raw)
  if (!resolved) return null
  return (
    <AuthImage
      src={resolved}
      alt={alt || 'image'}
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
  const match = /language-(\w+)/.exec(className || '')
  if (match) {
    return (
      <code className={className} {...props}>
        {children}
      </code>
    )
  }

  return (
    <code
      className={cn(
        'px-1.5 py-0.5 rounded-md text-sm font-mono text-primary',
        className
      )}
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
  variant = 'default',
}: Readonly<{
  message: Message
  isStreaming?: boolean
  variant?: 'default' | 'minimal'
}>) {
  const router = useRouter()
  const isUser = message.role === 'user'
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
  const { openDocument } = useDocumentView()
  const streamingLayoutTransition = reduceMotion
    ? { duration: 0 }
    : { duration: 0.24, ease: [0.16, 1, 0.3, 1] as const }
  const stepCount = message.steps?.length ?? 0
  const latestStep = stepCount > 0 ? message.steps?.[stepCount - 1] : ''
  const stepsPanelId = `chat-steps-${message.id}`

  useEffect(() => {
    setStepsOpen(isStreaming)
  }, [isStreaming, message.id])

  useEffect(() => {
    return () => {
      if (copyTimerRef.current != null) {
        globalThis.window.clearTimeout(copyTimerRef.current)
      }
    }
  }, [])

  const handleCopy = async () => {
    const text = (message.content || '').trimEnd()
    if (!text) return

    try {
      await navigator.clipboard.writeText(text)
    } catch (error) {
      reportClientError('Failed to copy chat message to clipboard', error)
      toast.error('复制失败，请检查浏览器剪贴板权限')
      return
    }

    setCopied(true)
    if (copyTimerRef.current != null) {
      globalThis.window.clearTimeout(copyTimerRef.current)
    }
    copyTimerRef.current = globalThis.window.setTimeout(() => setCopied(false), 1200)
  }

  const handleCopyDiagnostics = useCallback(async () => {
    const payload = {
      message_id: message.id,
      message_metadata: message.message_metadata || null,
      citations: message.citations || [],
    }
    try {
      await navigator.clipboard.writeText(JSON.stringify(payload, null, 2))
    } catch {
      // ignore
    }
  }, [message.citations, message.id, message.message_metadata])

  const metrics = (message.message_metadata || {})
  const confidenceScoreRaw = metrics.confidence_score
  const confidenceScore = (() => {
    const value = typeof confidenceScoreRaw === 'number' ? confidenceScoreRaw : Number(confidenceScoreRaw)
    return Number.isFinite(value) ? Math.max(0, Math.min(1, value)) : null
  })()
  const confidenceMeta = getConfidenceMeta(confidenceScore)
  const claimEvidence = claimEvidenceItems(metrics.claim_evidence)
  const claimEvidenceCount = claimEvidence?.length ?? 0
  const messageDatasetId =
    typeof metrics.dataset_id === 'string' && metrics.dataset_id.trim() ? metrics.dataset_id.trim() : null
  const followupQuestions = Array.isArray(metrics.followup_questions)
    ? metrics.followup_questions
        .map((item: unknown) => (typeof item === 'string' ? item.trim() : ''))
        .filter((item: string) => item.length > 0)
        .slice(0, 3)
    : []
  const metricEntries = [
    { k: 'request_id', v: metrics.request_id },
    { k: 'retrieval_mode', v: metrics.retrieval_mode ?? metrics.retrieval_mode_requested },
    { k: 'vector_backend', v: metrics.vector_backend },
    { k: 'route', v: metrics.route ?? metrics.model_route },
    { k: 'elapsed_sec', v: metrics.elapsed_sec },
    { k: 'retrieval_elapsed_sec', v: metrics.retrieval_elapsed_sec },
    { k: 'generation_elapsed_sec', v: metrics.generation_elapsed_sec },
    { k: 'docs_returned', v: metrics.docs_returned },
    { k: 'distinct_documents', v: metrics.distinct_documents },
    { k: 'top_k', v: metrics.top_k },
  ].flatMap((entry) => {
    const value = formatMetricValue(entry.v)
    return value == null ? [] : [{ k: entry.k, value }]
  })

  const citationRows = (message.citations || [])
    .slice()
    .sort((a, b) => (Number(b.relevance_score) || 0) - (Number(a.relevance_score) || 0))
  const citationPreviewRows = citationRows.slice(0, 2)

  const citationByChunkId = (() => {
    const map = new Map<string, Citation>()
    for (const c of message.citations || []) {
      if (c && typeof c.chunk_id === 'string' && c.chunk_id) {
        map.set(c.chunk_id, c)
      }
    }
    return map
  })()

  const citationByDocumentId = (() => {
    const map = new Map<string, Citation>()
    for (const c of message.citations || []) {
      if (c && typeof c.document_id === 'string' && c.document_id && !map.has(c.document_id)) {
        map.set(c.document_id, c)
      }
    }
    return map
  })()

  const handleOpenEvidence = useCallback((ev: ClaimEvidenceReference) => {
    const docId = typeof ev?.document_id === 'string' ? ev.document_id : ''
    if (!docId) return
    const chunkId = typeof ev?.chunk_id === 'string' && ev.chunk_id ? ev.chunk_id : undefined
    const start = typeof ev?.start_char === 'number' ? ev.start_char : null
    const end = typeof ev?.end_char === 'number' ? ev.end_char : null
    const range = start != null && end != null && end > start ? { start, end } : undefined
    openDocument(docId, chunkId, range, {
      sourceContext: buildChatCitationSourceContext(message.id, docId, chunkId),
    })
  }, [message.id, openDocument])

  const handleFollowupPrefill = useCallback((question: string) => {
    const prompt = question.trim()
    if (!prompt) return
    globalEventBus.emit('chat:submit', prompt)
  }, [])

  const handleInlineCitationClick = useCallback((href?: string) => {
    const target = parseInlineCitationHref(href)
    if (!target) return

    const citation =
      (target.chunkId ? citationByChunkId.get(target.chunkId) : undefined) ||
      (target.documentId ? citationByDocumentId.get(target.documentId) : undefined)

    const documentId = citation?.document_id || target.documentId
    if (!documentId) return

    openDocument(
      documentId,
      citation?.chunk_id || target.chunkId,
      citation ? getCitationRange(citation) : undefined,
      {
        activeTab: 'preview',
        previewAnchor: getDocumentPreviewAnchorFromCitation(citation),
        sourceContext: buildChatCitationSourceContext(message.id, documentId, citation?.chunk_id || target.chunkId),
      }
    )
  }, [citationByChunkId, citationByDocumentId, message.id, openDocument])

  const prefetchCitationTarget = useCallback((citation?: Citation | null, target?: { documentId?: string; chunkId?: string } | null) => {
    const documentId = citation?.document_id || target?.documentId
    if (!documentId) return

    const chunkId = citation?.chunk_id || target?.chunkId
    const cacheKey = `${documentId}:${chunkId || ''}`
    if (prefetchedCitationTargetsRef.current.has(cacheKey)) return
    prefetchedCitationTargetsRef.current.add(cacheKey)

    prefetchDocumentView({
      documentId,
      chunkId,
      rawFileUrl: toAbsoluteBackendUrl(`/api/v1/documents/${documentId}/download`),
    })
  }, [])

  const handleInlineCitationPrefetch = useCallback((href?: string) => {
    const target = parseInlineCitationHref(href)
    if (!target) return

    const citation =
      (target.chunkId ? citationByChunkId.get(target.chunkId) : undefined) ||
      (target.documentId ? citationByDocumentId.get(target.documentId) : undefined)

    prefetchCitationTarget(citation, target)
  }, [citationByChunkId, citationByDocumentId, prefetchCitationTarget])

  const handleOpenCitation = useCallback((citation: Citation) => {
    if (!citation.document_id) return
    openDocument(
      citation.document_id,
      citation.chunk_id,
      getCitationRange(citation),
      {
        activeTab: 'preview',
        previewAnchor: getDocumentPreviewAnchorFromCitation(citation),
        sourceContext: buildChatCitationSourceContext(message.id, citation.document_id, citation.chunk_id),
      }
    )
  }, [message.id, openDocument])

  const inlineCitationHandlers = useMemo<InlineCitationHandlers>(
    () => ({
      onClick: handleInlineCitationClick,
      onPrefetch: handleInlineCitationPrefetch,
    }),
    [handleInlineCitationClick, handleInlineCitationPrefetch]
  )

  let renderedContent: ReactNode
  if (isUser) {
     renderedContent = <div className="whitespace-pre-wrap font-normal text-primary-foreground [&>*]:text-inherit">{message.content}</div>
  } else if (isStreaming) {
    renderedContent = <CinematicTypewriter content={message.content} isStreaming={true} />
  } else {
    renderedContent = (
      <InlineCitationHandlersContext.Provider value={inlineCitationHandlers}>
        <ReactMarkdown remarkPlugins={markdownPlugins} skipHtml components={markdownBaseComponents}>
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

  const submitRating = useCallback(async (nextRating: number) => {
    if (!canRate) return
    if (ratingSending) return
    setRating(nextRating)
    setRatingSending(true)
    try {
      const created = await feedbackApi.create({ message_id: message.id, rating: nextRating })
      setFeedbackRecord(created)
      toast.success('已提交反馈')
    } catch (err: unknown) {
      toast.error(formatApiError(err, '反馈提交失败'))
    } finally {
      setRatingSending(false)
    }
  }, [canRate, message.id, ratingSending])

  const resolveFeedbackDatasetId = useCallback(async () => {
    if (messageDatasetId) return messageDatasetId

    const firstDocumentId = (message.citations || []).find((citation) => citation.document_id)?.document_id
    if (!firstDocumentId) return null

    const document = await documentApi.get(firstDocumentId, { includeChunks: false })
    return typeof document.dataset_id === 'string' && document.dataset_id.trim() ? document.dataset_id.trim() : null
  }, [message.citations, messageDatasetId])

  const handleSendFeedbackToEvidence = useCallback(async () => {
    const feedbackId = String(feedbackRecord?.id || '').trim()
    if (!feedbackId) return
    if (expertAction) return

    setExpertAction('evidence')
    try {
      const datasetId = await resolveFeedbackDatasetId()
      if (!datasetId) {
        toast.error('未解析到数据集，暂时无法打开证据库')
        return
      }
      router.push(`/datasets/${encodeURIComponent(datasetId)}/evidence?feedback_id=${encodeURIComponent(feedbackId)}`)
    } catch (error: unknown) {
      toast.error(formatApiError(error, '打开证据库失败'))
    } finally {
      setExpertAction(null)
    }
  }, [expertAction, feedbackRecord?.id, resolveFeedbackDatasetId, router])

  const handleCreateRegressionCase = useCallback(async () => {
    const feedbackId = String(feedbackRecord?.id || '').trim()
    if (!feedbackId) return
    if (expertAction) return

    setExpertAction('regression')
    try {
      await feedbackApi.toRegressionCase(feedbackId, {
        include_document_scope: true,
        extra: { source: 'chat_feedback_action' },
      })
      toast.success('已创建回归用例')
    } catch (error: unknown) {
      toast.error(formatApiError(error, '转为回归用例失败'))
    } finally {
      setExpertAction(null)
    }
  }, [expertAction, feedbackRecord?.id])

	  return (
	    <motion.div
        layout={!reduceMotion && isStreaming}
        transition={streamingLayoutTransition}
	      className={cn(
	        'flex gap-3 group animate-in fade-in slide-in-from-bottom-2 duration-300 motion-reduce:animate-none',
          isUser ? (variant === 'minimal' ? 'justify-end' : 'pb-4 justify-end') : 'justify-start',
          variant === 'minimal' ? 'w-full' : ''
	      )}
	    >
      {!isUser && (
        <div className={cn(
          "flex-shrink-0 flex items-center justify-center shadow-sm mt-0.5 transition-all duration-300",
          variant === 'minimal' 
            ? "size-8 rounded-full bg-background/90 border border-border/50 group-hover:border-primary/25 group-hover:shadow-md" 
            : "w-8 h-8 rounded-xl bg-accent/15 border border-accent/30"
        )}>
          <Bot className={cn("size-4", variant === 'minimal' ? "text-primary/60 group-hover:text-primary" : "text-accent")} />
        </div>
      )}

	      <motion.div
          layout={!reduceMotion && isStreaming}
          transition={streamingLayoutTransition}
	        className={cn(
          'relative text-[15px] transition-all duration-300 motion-reduce:transition-none',
            variant === 'minimal' 
              ? (isUser 
                  ? 'max-w-[78%] px-4 py-3 rounded-2xl rounded-br-md border border-[#BDE0FE] bg-[#A2D2FF] text-black shadow-sm backdrop-blur-sm'
                  : 'max-w-[88%] px-4 py-3 flex-1 rounded-2xl rounded-bl-md border border-border/60 bg-background/92 text-foreground shadow-sm backdrop-blur-sm'
                )
              : (isUser 
                  ? 'max-w-3xl px-6 py-4 rounded-2xl rounded-tr-sm border border-[#8FC8E8] bg-[#AAD9F2] text-[#17384D] shadow-sm backdrop-blur-sm'
                  : cn(
                      'max-w-3xl px-6 py-4 glass-card text-foreground rounded-2xl rounded-tl-sm border border-border/60 border-l-4 hover:shadow-lg hover:shadow-primary/10',
                      confidenceMeta?.lineClass || 'border-l-primary/30'
                    )
                ),
            !isUser && variant === 'minimal' ? '' : (confidenceMeta?.lineClass || 'border-l-primary/30').replace('border-l-', 'border-l-')
	        )}
          style={undefined}
	      >
          {/* AI 消息 Header (Minimal 模式独有) */}
          {!isUser && variant === 'minimal' && (
            <div className="flex items-center gap-2 mb-2.5">
              <span className="text-[11px] font-bold text-foreground/80 uppercase ">MimirQ</span>
              <span suppressHydrationWarning className="text-[9px] font-medium text-muted-foreground/40 tabular-nums">
                {new Intl.DateTimeFormat('zh-CN', { hour: '2-digit', minute: '2-digit' }).format(new Date(message.created_at))}
              </span>
            </div>
          )}
        {/* 思维链 / 步骤展示 */}
        <AnimatePresence initial={false}>
          {!isUser && message.steps && message.steps.length > 0 ? (
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
                      {message.steps.length} 步
                    </span>
                  </div>
                  {!stepsOpen && latestStep ? (
                    <div className="mt-0.5 truncate text-[11px] text-muted-foreground">{latestStep}</div>
                  ) : null}
                </div>
                <ChevronDown
                  className={cn(
                    'size-3.5 shrink-0 text-muted-foreground transition-transform duration-200 motion-reduce:transition-none',
                    stepsOpen && 'rotate-180'
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
                            idx === message.steps!.length - 1
                              ? 'font-medium text-foreground motion-safe:animate-pulse'
                              : 'text-muted-foreground/60'
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
                'text-muted-foreground hover:text-foreground hover:bg-muted/60'
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
                              <div className="font-mono text-xs tabular-nums break-all rounded-md border border-border bg-background/50 p-2 select-all">{message.id}</div>
                            </div>

                            {metricEntries.length ? (
                              <dl className="space-y-2 text-xs">
                                {metricEntries.map((entry) => (
                                  <div key={entry.k} className="flex items-start justify-between gap-3">
                                    <dt className="text-muted-foreground">{entry.k}</dt>
                                    <dd className="font-mono tabular-nums text-foreground text-right break-all">{entry.value}</dd>
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
                          <pre className="p-4 text-[11px] font-mono tabular-nums text-muted-foreground overflow-auto max-h-56 custom-scrollbar">{JSON.stringify({ message_metadata: message.message_metadata || null }, null, 2)}</pre>
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
                                  {citationRows.map((c, idx) => {
                                    const score = Number(c.relevance_score)
                                    return (
                                      <tr
                                        key={`${c.document_id}-${c.chunk_id || c.page_number || idx}`}
                                        className="hover:bg-muted/30 transition-colors duration-200 motion-reduce:transition-none"
                                      >
                                        <td className="px-4 py-2.5 text-muted-foreground">{idx + 1}</td>
                                        <td className="px-4 py-2.5">
                                          <div className="max-w-[240px] truncate text-foreground font-medium" title={c.document_name}>
                                            {c.document_name}
                                          </div>
                                        </td>
                                        <td className="px-4 py-2.5 text-right font-mono">{c.page_number ?? "-"}</td>
                                        <td className="px-4 py-2.5 text-right font-mono font-semibold">{Number.isFinite(score) ? score.toFixed(3) : "-"}</td>
                                        <td className="px-4 py-2.5 text-right font-mono">{c.vector_score == null ? "-" : Number(c.vector_score).toFixed(3)}</td>
                                        <td className="px-4 py-2.5 text-right font-mono">{c.bm25_score == null ? "-" : Number(c.bm25_score).toFixed(3)}</td>
                                        <td className="px-4 py-2.5 text-right font-mono">{c.rerank_score == null ? "-" : Number(c.rerank_score).toFixed(3)}</td>
                                      </tr>
                                    )
                                  })}
                                </tbody>
                              </table>
                            </div>
                          ) : (
                            <div className="flex-1 flex items-center justify-center p-8 text-muted-foreground text-sm">未记录 citations</div>
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
                                const claim = String(item?.claim || '').trim()
                                const evidence = claimEvidenceReferences(item?.evidence)
                                return (
                                  <div
                                    key={claim || evidence.map(claimEvidenceReferenceKey).join(':') || 'claim'}
                                    className="rounded-lg border border-border/60 bg-background/40 p-3"
                                  >
                                    <div className="flex items-start justify-between gap-3">
                                      <div className="min-w-0 text-xs font-semibold text-foreground leading-relaxed line-clamp-3">
                                        {claim || `Claim #${idx + 1}`}
                                      </div>
                                      <div className="flex-shrink-0 text-[11px] text-muted-foreground tabular-nums">
                                        {evidence.length} 证据
                                      </div>
                                    </div>

                                    {evidence.length ? (
                                      <div className="mt-2 space-y-2">
                                        {evidence.slice(0, 3).map((ev, eidx) => {
                                          const docId = typeof ev?.document_id === 'string' ? ev.document_id : ''
                                          const chunkId = typeof ev?.chunk_id === 'string' ? ev.chunk_id : ''
                                          const c =
                                            (chunkId ? citationByChunkId.get(chunkId) : undefined) ||
                                            (docId ? citationByDocumentId.get(docId) : undefined)

                                          const score = typeof ev?.score === 'number' ? ev.score : null
                                          const quote = String(ev?.quote || '').trim()
                                          const disabled = !docId

                                          return (
                                            <button
                                              key={`${docId}:${chunkId}:${quote.slice(0, 24)}`}
                                              type="button"
                                              disabled={disabled}
                                              aria-label={disabled ? 'Evidence unavailable' : 'Open evidence in document viewer'}
                                              onClick={() => handleOpenEvidence(ev)}
                                              className={cn(
                                                'w-full text-left rounded-md border border-border/50 bg-background/50 px-3 py-2 transition-colors duration-200 motion-reduce:transition-none',
                                                disabled
                                                  ? 'opacity-60 cursor-not-allowed'
                                                  : 'hover:bg-muted/30 hover:border-primary/25 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60'
                                              )}
                                            >
                                              <div className="flex items-start justify-between gap-3">
                                                <div className="min-w-0">
                                                  <div
                                                    className="text-[11px] font-semibold text-foreground truncate"
                                                    title={c?.document_name || docId || 'Unknown'}
                                                  >
                                                    {c?.document_name || docId || 'Unknown'}
                                                  </div>
                                                  <div className="text-[11px] text-muted-foreground tabular-nums">
                                                    {c?.page_number == null ? '—' : `P.${c.page_number}`}
                                                    {typeof ev?.start_char === 'number' && typeof ev?.end_char === 'number'
                                                      ? ` · ${Math.trunc(ev.start_char)}-${Math.trunc(ev.end_char)}`
                                                      : ''}
                                                  </div>
                                                </div>
                                                <div className="text-[11px] font-mono text-muted-foreground tabular-nums">
                                                  {score == null ? '' : score.toFixed(3)}
                                                </div>
                                              </div>
                                              {quote ? (
                                                <div className="mt-1 text-xs text-muted-foreground line-clamp-2 leading-relaxed">
                                                  {quote}
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
              isUser ? 'bottom-0 right-0 translate-x-1/4 translate-y-1/4 border border-border/60 bg-background/95 shadow-sm' : 'bottom-2 right-2',
	            'opacity-0 group-hover:opacity-100 scale-90 group-hover:scale-100 transition-opacity transition-transform',
	            'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60',
	            'text-muted-foreground hover:text-foreground hover:bg-muted/60'
	          )}
	        >
          {copied ? (
            <Check className="size-3.5" />
          ) : (
            <Copy className="size-3.5" />
          )}
        </button>

        {!isUser && (confidenceMeta || citationPreviewRows.length > 0) && (
          <div className="mb-4 space-y-3 pr-16">
            {confidenceMeta && confidenceScore != null ? (
              <div className="flex flex-wrap items-center gap-2">
                <div
                  className={cn(
                    'inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] font-semibold tabular-nums',
                    confidenceMeta.badgeClass
                  )}
                >
                  <BarChart3 className="size-3" />
                  <span>{confidenceMeta.label}</span>
                  <span>{Math.round(confidenceScore * 100)}%</span>
                </div>
                <div className="text-[11px] text-muted-foreground">{confidenceMeta.summary}</div>
              </div>
            ) : null}

            {citationPreviewRows.length > 0 && (
              <div className="space-y-2">
                <div className="text-[11px] font-bold uppercase tracking-[0.18em] text-muted-foreground/80">
                  来源速览
                </div>
                <div className="flex gap-2 overflow-x-auto pb-1 no-scrollbar">
                  {citationPreviewRows.map((citation, idx) => {
                    const citationKey = `${citation.document_id}-${citation.chunk_id || citation.page_number || idx}`
                    return (
                      <button
                        key={citationKey}
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
               ? 'max-w-none break-words leading-relaxed text-primary-foreground [&>*]:text-inherit'
              : 'prose prose-neutral dark:prose-invert max-w-none break-words leading-relaxed prose-p:my-2 prose-p:leading-7 prose-pre:bg-secondary/50 prose-pre:border prose-pre:border-border/50 prose-pre:text-foreground prose-pre:rounded-xl prose-pre:p-4 prose-pre:my-3 prose-code:bg-[hsl(var(--code-background))] prose-code:px-1.5 prose-code:py-0.5 prose-code:rounded-md prose-code:text-sm prose-code:font-mono prose-code:text-primary prose-code:before:content-none prose-code:after:content-none'
          )}
        >
          {renderedContent}
        </div>

        {!isUser && followupQuestions.length > 0 && (
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

        {!isUser && (citationRows.length > 0 || claimEvidenceCount > 0) && (
          <details className="mt-5 overflow-hidden rounded-2xl border border-border/60 bg-background/35 open:bg-background/45">
            <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-4 py-3 [&::-webkit-details-marker]:hidden">
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
              {citationRows.length > 0 && (
                <div className="space-y-3">
                  <div className="flex items-center gap-2 text-[11px] font-bold uppercase tracking-[0.18em] text-muted-foreground/80">
                    <Database className="size-3" />
                    参考来源
                  </div>
                  <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                    {citationRows.map((citation, idx) => {
                      const citationKey = `${citation.document_id}-${citation.chunk_id || citation.page_number || idx}`
                      return <CitationCard key={citationKey} messageId={message.id} citation={citation} index={idx} />
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
                      const claim = String(item?.claim || '').trim()
                      const evidence = claimEvidenceReferences(item?.evidence)
                      return (
                        <div
                          key={claim || evidence.map(claimEvidenceReferenceKey).join(':') || `claim-${idx}`}
                          className="rounded-xl border border-border/60 bg-card/70 p-3"
                        >
                          <div className="flex items-start justify-between gap-3">
                            <div className="min-w-0 text-sm font-medium leading-6 text-foreground/90">
                              {claim || `Claim #${idx + 1}`}
                            </div>
                            <div className="shrink-0 text-[11px] text-muted-foreground">{evidence.length} 证据</div>
                          </div>

                          {evidence.length ? (
                            <div className="mt-3 flex flex-col gap-2">
                              {evidence.slice(0, 2).map((ev) => {
                                const docId = typeof ev?.document_id === 'string' ? ev.document_id : ''
                                const chunkId = typeof ev?.chunk_id === 'string' ? ev.chunk_id : ''
                                const citation =
                                  (chunkId ? citationByChunkId.get(chunkId) : undefined) ||
                                  (docId ? citationByDocumentId.get(docId) : undefined)
                                const score = typeof ev?.score === 'number' ? ev.score : null
                                const quote = String(ev?.quote || '').trim()
                                const disabled = !docId

                                return (
                                  <button
                                    key={`${docId}:${chunkId}:${quote.slice(0, 24)}`}
                                    type="button"
                                    disabled={disabled}
                                    onClick={() => handleOpenEvidence(ev)}
                                    className={cn(
                                      'w-full rounded-xl border border-border/50 bg-background/70 px-3 py-2 text-left transition-colors',
                                      disabled
                                        ? 'cursor-not-allowed opacity-60'
                                        : 'hover:border-primary/25 hover:bg-muted/30 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60'
                                    )}
                                  >
                                    <div className="flex items-start justify-between gap-3">
                                      <div className="min-w-0">
                                        <div
                                          className="truncate text-[11px] font-semibold text-foreground"
                                          title={citation?.document_name || docId || 'Unknown'}
                                        >
                                          {citation?.document_name || docId || 'Unknown'}
                                        </div>
                                        <div className="text-[11px] text-muted-foreground tabular-nums">
                                          {citation?.page_number == null ? '—' : `P.${citation.page_number}`}
                                          {typeof ev?.start_char === 'number' && typeof ev?.end_char === 'number'
                                            ? ` · ${Math.trunc(ev.start_char)}-${Math.trunc(ev.end_char)}`
                                            : ''}
                                        </div>
                                      </div>
                                      {score == null ? null : (
                                        <div className="text-[11px] font-mono text-muted-foreground tabular-nums">
                                          {score.toFixed(3)}
                                        </div>
                                      )}
                                    </div>
                                    {quote ? (
                                      <div className="mt-1 line-clamp-2 text-xs leading-relaxed text-muted-foreground">
                                        {quote}
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

         {!isUser && canRate && (
           <details className="mt-4 overflow-hidden rounded-2xl border border-border/60 bg-background/35 open:bg-background/45">
             <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-4 py-3 [&::-webkit-details-marker]:hidden">
               <div>
                 <div className="text-[11px] font-bold uppercase tracking-[0.18em] text-muted-foreground/80">
                  反馈评分
                </div>
                <div className="mt-1 text-xs text-muted-foreground">
                  用 1-5 星记录这条回答是否有帮助。
                </div>
              </div>
              <span className="text-[11px] text-muted-foreground">{rating == null ? '展开评分' : `${rating} / 5`}</span>
            </summary>
            <div className="flex flex-col gap-3 border-t border-border/50 px-4 py-4 sm:flex-row sm:items-center sm:justify-between">
              <div className="text-xs text-muted-foreground">
                评分越低，越适合后续进入回归或 evidence workbench 继续分析。
              </div>
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
                        ratingSending && 'cursor-not-allowed opacity-50'
                      )}
                      aria-label={`rate-${v}`}
                      title={`${v} 星`}
                    >
                      <Star
                        className={cn('size-4', active ? 'text-yellow-500' : 'text-muted-foreground')}
                        fill={active ? 'currentColor' : 'none'}
                      />
                    </button>
                  )
                 })}
                 {ratingSending ? <span className="ml-2 text-xs text-muted-foreground">提交中…</span> : null}
               </div>
             </div>
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
                       onClick={() => void handleSendFeedbackToEvidence()}
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
                       onClick={() => void handleCreateRegressionCase()}
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
       </motion.div>

      {isUser && (
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
  const [hideImage, setHideImage] = useState(false)
  const [viewerOpen, setViewerOpen] = useState(false)
  const prefetchedRef = useRef(false)
  const imgUrl = (() => {
    if (!citation.img_url) return null
    return resolveSafeCitationImageUrl(citation.img_url)
  })()

  const isTableEvidence = (() => {
    const hitType = String(citation.hit_type || '').trim().toLowerCase()
    const chunkRole = String(citation.chunk_role || '').trim().toLowerCase()
    const semanticRole = String(citation.chunk_semantic_role || '').trim().toLowerCase()
    return (
      hitType === 'tag' ||
      hitType === 'table' ||
      chunkRole.includes('tag') ||
      chunkRole.includes('table') ||
      semanticRole === 'table'
    )
  })()

  const canViewEvidence = Boolean((citation.has_image && imgUrl && !hideImage) || isTableEvidence)
  const sourceContext = buildChatCitationSourceContext(messageId, citation.document_id, citation.chunk_id)
  const citationScoreTitle = buildCitationScoreTitle(citation)
  const secondaryScore = getCitationSecondaryScore(citation)

  const handleClick = useCallback((e?: React.MouseEvent) => {
    e?.stopPropagation()
    if (citation.document_id) {
      openDocument(
        citation.document_id,
        citation.chunk_id,
        getCitationRange(citation),
        {
          activeTab: 'preview',
          previewAnchor: getDocumentPreviewAnchorFromCitation(citation),
          sourceContext,
        }
      )
    }
  }, [citation, openDocument, sourceContext])

  const handlePrefetch = useCallback(() => {
    if (prefetchedRef.current) return
    if (!citation.document_id) return

    prefetchedRef.current = true
    prefetchDocumentView({
      documentId: citation.document_id,
      chunkId: citation.chunk_id,
      rawFileUrl: toAbsoluteBackendUrl(`/api/v1/documents/${citation.document_id}/download`),
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
                {citation.page_number && <span className="text-muted-foreground font-normal ml-1">· P.{citation.page_number}</span>}
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
            综合分 {formatCitationScore(citation.relevance_score)}
          </span>
          {secondaryScore ? (
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
                'hover:bg-muted/40 hover:text-foreground transition-colors'
              )}
              aria-label="view-evidence"
              title="查看证据（图片/表格溯源）"
            >
              查看证据
            </button>
          ) : null}
        </div>

        {citation.has_image && imgUrl && !hideImage && (
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
                onError={() => setHideImage(true)}
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
