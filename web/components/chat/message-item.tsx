/**
 * Shared chat message item (ChatArea + History).
 */
'use client'

import { memo, useEffect, useRef, useState, useCallback } from 'react'
import type { ReactNode } from 'react'
import Image from 'next/image'
import { BarChart3, Check, Copy, Database, Bot, Star, User } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

import type { Citation, Message } from '@/types'
import { cn } from '@/lib/utils'
import { globalEventBus } from '@/lib/event-bus'
import { API_BASE_URL, toAbsoluteBackendUrl } from '@/lib/env'
import { getAccessToken, getTenantId } from '@/lib/auth-storage'
import { useDocumentView } from '@/store/document-view'
import { resolveSafeCitationImageUrl } from '@/lib/citation-images'
import { EvidenceViewerDialog } from '@/components/evidence/evidence-viewer-dialog'

import { CinematicTypewriter } from '@/components/ui/cinematic-typewriter'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { feedbackApi } from '@/lib/api-client'
import { formatApiError } from '@/lib/api-errors'
import { toast } from 'sonner'

let BACKEND_ORIGIN = ''
try {
  BACKEND_ORIGIN = new URL(API_BASE_URL).origin
} catch {
  BACKEND_ORIGIN = ''
}

function maybeAttachImageAuthToken(url: string): string {
  const token = getAccessToken()
  const tenantId = getTenantId()
  if (!token && !tenantId) return url

  let parsed: URL
  try {
    parsed = new URL(url, API_BASE_URL)
  } catch {
    return url
  }

  if (BACKEND_ORIGIN && parsed.origin !== BACKEND_ORIGIN) return url

  const path = parsed.pathname || ''
  const needsToken =
    path.includes('/api/v1/documents/image/') || path.includes('/api/v1/documents/image-url/')
  if (!needsToken) return url

  if (
    tenantId &&
    !parsed.searchParams.has('tenant_id') &&
    !parsed.searchParams.has('x_tenant_id') &&
    !parsed.searchParams.has('tenant')
  ) {
    parsed.searchParams.set('tenant_id', tenantId)
  }

  if (!parsed.searchParams.has('token') && !parsed.searchParams.has('access_token')) {
    if (token) parsed.searchParams.set('token', token)
  }
  return parsed.toString()
}

const INLINE_CITATION_HREF_PREFIX = 'mimirq-citation://'

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

const markdownPlugins = [remarkGfm]
const markdownBaseComponents = {
  p: ({ children }: { children?: ReactNode }) => <p className="mb-3 last:mb-0 leading-relaxed">{children}</p>,
  ul: ({ children }: { children?: ReactNode }) => (
    <ul className="list-disc pl-5 mb-3 space-y-1.5 marker:text-muted-foreground/60">{children}</ul>
  ),
  ol: ({ children }: { children?: ReactNode }) => (
    <ol className="list-decimal pl-5 mb-3 space-y-1.5 marker:text-muted-foreground/60">{children}</ol>
  ),
  li: ({ children }: { children?: ReactNode }) => <li className="pl-1">{children}</li>,
  a: ({ href, children }: { href?: string; children?: ReactNode }) => (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className="text-primary font-medium hover:underline decoration-primary/30 underline-offset-4 transition-colors"
    >
      {children}
    </a>
  ),
  img: ({ src, alt }: { src?: string | Blob; alt?: string }) => {
    const raw = typeof src === 'string' ? src : ''
    const resolved = (() => {
    if (raw) {
        if (/^https?:\/\//i.test(raw) || /^data:/i.test(raw) || /^blob:/i.test(raw)) {
            return raw;
        }
        else {
            return toAbsoluteBackendUrl(raw);
        }
    }
    else {
        return '';
    }
})()
    if (!resolved) return null
    const finalSrc = maybeAttachImageAuthToken(resolved)
    return (
      <Image
        src={finalSrc}
        alt={alt || 'image'}
        width={1200}
        height={800}
        unoptimized
        sizes="(max-width: 768px) 100vw, 768px"
        loading="lazy"
        className="my-3 w-full h-auto max-h-96 object-contain rounded-xl border border-border/50 bg-background/50 shadow-sm"
      />
    )
  },
  blockquote: ({ children }: { children?: React.ReactNode }) => (
    <blockquote className="border-l-4 border-primary/30 pl-4 italic text-muted-foreground my-3 bg-secondary/30 py-2 pr-2 rounded-r-lg">
      {children}
    </blockquote>
  ),
  code: ({ className, children, ...props }: { className?: string; children?: ReactNode }) => {
    const match = /language-(\w+)/.exec(className || '')
    return match ? (
      <code className={className} {...props}>
        {children}
      </code>
    ) : (
      <code
        className={cn(
          'bg-secondary/50 px-1.5 py-0.5 rounded-md text-sm font-mono text-primary',
          className
        )}
        {...props}
      >
        {children}
      </code>
    )
  },
}

export const ChatMessageItem = memo(function ChatMessageItem({
  message,
  isStreaming = false,
}: Readonly<{
  message: Message
  isStreaming?: boolean
}>) {
  const isUser = message.role === 'user'
  const [copied, setCopied] = useState(false)
  const [diagOpen, setDiagOpen] = useState(false)
  const [rating, setRating] = useState<number | null>(null)
  const [ratingSending, setRatingSending] = useState(false)
  const copyTimerRef = useRef<number | null>(null)
  const { openDocument } = useDocumentView()

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
      console.error('clipboard.writeText failed:', error)
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
  const confidenceTone =
    confidenceScore == null
      ? null
      : confidenceScore >= 0.75
        ? 'border-emerald-500/20 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300'
        : confidenceScore >= 0.5
          ? 'border-amber-500/20 bg-amber-500/10 text-amber-700 dark:text-amber-300'
          : 'border-rose-500/20 bg-rose-500/10 text-rose-700 dark:text-rose-300'
  const confidenceLabel =
    confidenceScore == null ? null : confidenceScore >= 0.75 ? '高' : confidenceScore >= 0.5 ? '中' : '低'
  const claimEvidence = Array.isArray(metrics.claim_evidence) ? metrics.claim_evidence : null
  const followupQuestions = Array.isArray(metrics.followup_questions)
    ? metrics.followup_questions
        .map((item: unknown) => (typeof item === 'string' ? item.trim() : ''))
        .filter((item: string) => item.length > 0)
        .slice(0, 3)
    : []
  const metricEntries: Array<{ k: string; v: any }> = [
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
  ].filter((e) => e.v !== undefined && e.v !== null && String(e.v).trim() !== '')

  const citationRows = (message.citations || [])
    .slice()
    .sort((a, b) => (Number(b.relevance_score) || 0) - (Number(a.relevance_score) || 0))

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

  const handleOpenEvidence = useCallback((ev: any) => {
    const docId = typeof ev?.document_id === 'string' ? ev.document_id : ''
    if (!docId) return
    const chunkId = typeof ev?.chunk_id === 'string' && ev.chunk_id ? ev.chunk_id : undefined
    const start = typeof ev?.start_char === 'number' ? ev.start_char : null
    const end = typeof ev?.end_char === 'number' ? ev.end_char : null
    const range = start != null && end != null && end > start ? { start, end } : undefined
    openDocument(docId, chunkId, range)
  }, [openDocument])

  const handleFollowupPrefill = useCallback((question: string) => {
    const prompt = question.trim()
    if (!prompt) return
    globalEventBus.emit('chat:send', prompt)
  }, [])

  const handleInlineCitationClick = useCallback((href?: string) => {
    const target = parseInlineCitationHref(href)
    if (!target) return

    const citation =
      (target.chunkId ? citationByChunkId.get(target.chunkId) : undefined) ||
      (target.documentId ? citationByDocumentId.get(target.documentId) : undefined)

    const documentId = citation?.document_id || target.documentId
    if (!documentId) return

    openDocument(documentId, citation?.chunk_id || target.chunkId, citation ? getCitationRange(citation) : undefined)
  }, [citationByChunkId, citationByDocumentId, openDocument])

  const markdownComponents = {
    ...markdownBaseComponents,
    a: ({ href, children }: { href?: string; children?: ReactNode }) => {
      const inlineCitation = parseInlineCitationHref(href)
      if (inlineCitation) {
        return (
          <button
            type="button"
            onClick={() => handleInlineCitationClick(href)}
            className="inline-flex items-center rounded-md border border-primary/20 bg-primary/5 px-1.5 py-0.5 text-[0.75em] font-semibold text-primary no-underline transition-colors hover:bg-primary/10 hover:text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60"
          >
            {children}
          </button>
        )
      }

      return (
        <a
          href={href}
          target="_blank"
          rel="noopener noreferrer"
          className="text-primary font-medium hover:underline decoration-primary/30 underline-offset-4 transition-colors"
        >
          {children}
        </a>
      )
    },
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
      await feedbackApi.create({ message_id: message.id, rating: nextRating })
      toast.success('已提交反馈')
    } catch (err: any) {
      toast.error(formatApiError(err, '反馈提交失败'))
    } finally {
      setRatingSending(false)
    }
  }, [canRate, message.id, ratingSending])

	  return (
	    <div
	      className={cn(
	        'flex gap-4 px-2 group animate-in fade-in slide-in-from-bottom-2 duration-300 motion-reduce:animate-none',
	        isUser ? 'justify-end' : 'justify-start'
	      )}
	    >
      {!isUser && (
        <div className="flex-shrink-0 w-8 h-8 rounded-xl bg-background border border-border flex items-center justify-center shadow-sm mt-0.5">
          <Bot className="h-4 w-4 text-primary" />
        </div>
      )}

	      <div
	        className={cn(
	          'max-w-3xl px-6 py-4 shadow-sm relative text-[15px] transition-shadow duration-200 motion-reduce:transition-none',
	          isUser
	            ? 'bg-primary text-primary-foreground rounded-2xl rounded-tr-sm shadow-strong border border-primary/20 backdrop-blur-sm'
	            : 'glass-card text-foreground rounded-2xl rounded-tl-sm hover:shadow-lg hover:shadow-primary/10'
	        )}
	      >
        {/* 思维链 / 步骤展示 */}
	        {!isUser && message.steps && message.steps.length > 0 && (
	          <div className="mb-4 space-y-2 motion-safe:animate-fade-in">
	            <div className="flex items-center gap-2 text-[10px] font-bold text-primary/70 uppercase ">
	              <div className="relative flex h-2 w-2">
	                <span className="motion-safe:animate-ping absolute inline-flex h-full w-full rounded-full bg-primary opacity-75"></span>
	                <span className="relative inline-flex rounded-full h-2 w-2 bg-primary"></span>
	              </div>
	              思考路径
	            </div>
	            <div className="pl-4 border-l border-primary/20 space-y-1">
              {message.steps.map((step, idx) => (
	                <div
	                  key={step}
	                  className={cn(
	                    "text-xs transition-opacity duration-200 motion-reduce:transition-none",
	                    idx === message.steps!.length - 1 ? "text-foreground font-medium motion-safe:animate-pulse" : "text-muted-foreground/60"
	                  )}
	                >
	                  {step}
	                </div>
              ))}
            </div>
          </div>
        )}

        {!isUser && message.message_metadata && (
          <>
            <button
              type="button"
              onClick={() => setDiagOpen(true)}
              aria-label="Diagnostics"
              title="检索诊断"
              className={cn(
                'absolute bottom-2 right-11 z-10 rounded-md p-1.5 transition-opacity transition-transform transition-colors duration-200 motion-reduce:transition-none',
                'opacity-0 group-hover:opacity-100 scale-90 group-hover:scale-100',
                'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60',
                'text-muted-foreground hover:text-foreground hover:bg-secondary'
              )}
            >
              <BarChart3 className="h-3.5 w-3.5" />
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
                        <Copy className="w-3.5 h-3.5 mr-2" />
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
                                {metricEntries.map((e) => (
                                  <div key={e.k} className="flex items-start justify-between gap-3">
                                    <dt className="text-muted-foreground">{e.k}</dt>
                                    <dd className="font-mono tabular-nums text-foreground text-right break-all">{String(e.v)}</dd>
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
                              <table className="w-full text-xs text-left tabular-nums">
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
                              {claimEvidence.slice(0, 24).map((item: any, idx: number) => {
                                const claim = String(item?.claim || '').trim()
                                const evidence = Array.isArray(item?.evidence) ? item.evidence : []
                                return (
                                  <div
                                    key={claim || evidence.map((ev: any) => String(ev?.chunk_id || ev?.document_id || '')).join(':') || 'claim'}
                                    className="rounded-lg border border-border/60 bg-background/40 p-3"
                                  >
                                    <div className="flex items-start justify-between gap-3">
                                      <div className="min-w-0 text-xs font-semibold text-foreground leading-relaxed line-clamp-3">
                                        {claim || `Claim #${idx + 1}`}
                                      </div>
                                      <div className="flex-shrink-0 text-[10px] text-muted-foreground tabular-nums">
                                        {evidence.length} 证据
                                      </div>
                                    </div>

                                    {evidence.length ? (
                                      <div className="mt-2 space-y-2">
                                        {evidence.slice(0, 3).map((ev: any, eidx: number) => {
                                          const docId = typeof ev?.document_id === 'string' ? ev.document_id : ''
                                          const chunkId = typeof ev?.chunk_id === 'string' ? ev.chunk_id : ''
                                          const c =
                                            (chunkId && citationByChunkId.get(chunkId)) ||
                                            (docId && citationByDocumentId.get(docId))

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
                                                  <div className="text-[10px] text-muted-foreground tabular-nums">
                                                    {c?.page_number == null ? '—' : `P.${c.page_number}`}
                                                    {typeof ev?.start_char === 'number' && typeof ev?.end_char === 'number'
                                                      ? ` · ${Math.trunc(ev.start_char)}-${Math.trunc(ev.end_char)}`
                                                      : ''}
                                                  </div>
                                                </div>
                                                <div className="text-[10px] font-mono text-muted-foreground tabular-nums">
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
	            'absolute bottom-2 right-2 z-10 rounded-md p-1.5 transition-opacity transition-transform transition-colors duration-200 motion-reduce:transition-none',
	            'opacity-0 group-hover:opacity-100 scale-90 group-hover:scale-100',
	            'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60',
	            isUser
	              ? 'text-primary-foreground/80 hover:text-primary-foreground hover:bg-primary-foreground/10'
	              : 'text-muted-foreground hover:text-foreground hover:bg-secondary'
	          )}
	        >
          {copied ? (
            <Check className="h-3.5 w-3.5" />
          ) : (
            <Copy className="h-3.5 w-3.5" />
          )}
        </button>

        {!isUser && confidenceScore != null && confidenceTone && confidenceLabel && (
          <div className="mb-3 flex flex-wrap items-center gap-2 pr-16">
            <div
              className={cn(
                'inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] font-semibold tabular-nums',
                confidenceTone
              )}
            >
              <BarChart3 className="h-3 w-3" />
              <span>置信度</span>
              <span>{Math.round(confidenceScore * 100)}%</span>
            </div>
            <div className="text-[11px] text-muted-foreground">{confidenceLabel}可信度</div>
          </div>
        )}

        <div
	          className={cn(
	            'prose max-w-none break-words leading-relaxed dark:prose-invert',
	            isUser ? 'prose-invert' : 'prose-neutral',
	            'prose-p:my-2 prose-p:leading-7',
	            'prose-pre:bg-secondary/50 prose-pre:border prose-pre:border-border/50 prose-pre:text-foreground prose-pre:rounded-xl prose-pre:p-4 prose-pre:my-3',
	            'prose-code:bg-secondary/50 prose-code:px-1.5 prose-code:py-0.5 prose-code:rounded-md prose-code:text-sm font-mono text-primary prose-code:before:content-none prose-code:after:content-none',
	            isUser && 'prose-code:bg-primary-foreground/10 prose-code:text-primary-foreground'
	          )}
	        >
          {(() => {
    if (isUser) {
        return (<div className="whitespace-pre-wrap font-normal ">{message.content}</div>);
    }
    else if (isStreaming) {
            return (<CinematicTypewriter content={message.content} isStreaming={true}/>);
        }
        else {
            return (<ReactMarkdown remarkPlugins={markdownPlugins} components={markdownComponents}>
              {message.content}
            </ReactMarkdown>);
        }
})()}
        </div>

        {!isUser && followupQuestions.length > 0 && (
          <div className="mt-5 pt-3 border-t border-border/40 space-y-3">
            <div className="flex items-center gap-2 text-[10px] font-bold text-muted-foreground uppercase opacity-80">
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

        {!isUser && message.citations && message.citations.length > 0 && (
          <div className="mt-5 pt-3 border-t border-border/40 space-y-3">
            <div className="flex items-center gap-2 text-[10px] font-bold text-muted-foreground uppercase  opacity-80">
              <Database className="w-3 h-3" />
              参考来源
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              {message.citations.map((citation, idx) => {
                const citationKey = `${citation.document_id}-${citation.chunk_id || citation.page_number || idx}`
                return (
                  <CitationCard key={citationKey} citation={citation} index={idx} />
                )
              })}
            </div>
          </div>
        )}

        {!isUser && canRate && (
          <div className="mt-5 pt-3 border-t border-border/40 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
            <div className="text-[10px] font-bold text-muted-foreground uppercase  opacity-80">
              反馈评分
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
                      'h-8 w-8 inline-flex items-center justify-center rounded-lg transition-colors',
                      'hover:bg-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60',
                      ratingSending && 'opacity-50 cursor-not-allowed'
                    )}
                    aria-label={`rate-${v}`}
                    title={`${v} 星`}
                  >
                    <Star
                      className={cn('h-4 w-4', active ? 'text-yellow-500' : 'text-muted-foreground')}
                      fill={active ? 'currentColor' : 'none'}
                    />
                  </button>
                )
              })}
              {ratingSending && <span className="text-xs text-muted-foreground ml-2">提交中…</span>}
            </div>
          </div>
        )}
      </div>

      {isUser && (
        <div className="flex-shrink-0 w-8 h-8 rounded-xl bg-primary text-primary-foreground flex items-center justify-center text-xs font-bold shadow-md shadow-primary/20 mt-0.5">
          <User className="h-4 w-4" />
        </div>
      )}
    </div>
  )
})

const CitationCard = memo(function CitationCard({ citation, index }: Readonly<{ citation: Citation; index: number }>) {
  const { openDocument } = useDocumentView()
  const [hideImage, setHideImage] = useState(false)
  const [viewerOpen, setViewerOpen] = useState(false)
  const imgUrl = (() => {
    if (!citation.img_url) return null
    return resolveSafeCitationImageUrl(citation.img_url)
  })()

  const isTableEvidence = (() => {
    const hitType = String((citation as any).hit_type || '').trim().toLowerCase()
    const chunkRole = String((citation as any).chunk_role || '').trim().toLowerCase()
    const semanticRole = String((citation as any).chunk_semantic_role || '').trim().toLowerCase()
    return (
      hitType === 'tag' ||
      hitType === 'table' ||
      chunkRole.includes('tag') ||
      chunkRole.includes('table') ||
      semanticRole === 'table'
    )
  })()

  const canViewEvidence = Boolean((citation.has_image && imgUrl && !hideImage) || isTableEvidence)

  const handleClick = useCallback((e?: React.MouseEvent) => {
    e?.stopPropagation()
    if (citation.document_id) {
      openDocument(citation.document_id, citation.chunk_id, getCitationRange(citation))
    }
  }, [citation, openDocument])

  return (
    <>
      <div className="group/card text-xs rounded-lg p-3 border bg-card border-border/60 shadow-sm transition-colors transition-shadow duration-200 motion-reduce:transition-none hover:bg-muted/40 hover:border-primary/25 hover:shadow-md">
        <button
          type="button"
          onClick={handleClick}
          className="block w-full rounded-md text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60 focus-visible:ring-offset-2 focus-visible:ring-offset-background"
        >
          <div className="flex items-start gap-3">
            <span className="flex-shrink-0 w-5 h-5 bg-secondary text-primary border border-border rounded flex items-center justify-center text-[10px] font-bold group-hover/card:bg-primary group-hover/card:text-primary-foreground transition-colors">
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

        <div className="flex items-center gap-2 mt-2 pt-1">
          <span className="bg-secondary/50 border border-border text-muted-foreground px-1.5 py-0.5 rounded text-[10px]">
            相似度 {Math.round(citation.relevance_score * 100)}%
          </span>
          {canViewEvidence ? (
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation()
                setViewerOpen(true)
              }}
              className={cn(
                'inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-medium',
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
              <Image
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
        />
    </>
  )
})
