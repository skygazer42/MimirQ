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
import { API_BASE_URL, toAbsoluteBackendUrl } from '@/lib/env'
import { getAccessToken, getTenantId } from '@/lib/auth-storage'
import { useDocumentView } from '@/store/document-view'

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

const markdownPlugins = [remarkGfm]
const markdownComponents = {
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
  img: ({ src, alt }: { src?: string; alt?: string }) => {
    const raw = typeof src === 'string' ? src : ''
    const resolved = raw
      ? /^https?:\/\//i.test(raw) || /^data:/i.test(raw) || /^blob:/i.test(raw)
        ? raw
        : toAbsoluteBackendUrl(raw)
      : ''
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
}: {
  message: Message
  isStreaming?: boolean
}) {
  const isUser = message.role === 'user'
  const [copied, setCopied] = useState(false)
  const [diagOpen, setDiagOpen] = useState(false)
  const [rating, setRating] = useState<number | null>(null)
  const [ratingSending, setRatingSending] = useState(false)
  const copyTimerRef = useRef<number | null>(null)

  useEffect(() => {
    return () => {
      if (copyTimerRef.current != null) {
        window.clearTimeout(copyTimerRef.current)
      }
    }
  }, [])

  const handleCopy = async () => {
    const text = (message.content || '').trimEnd()
    if (!text) return

    let ok = false
    try {
      await navigator.clipboard.writeText(text)
      ok = true
    } catch {
      try {
        const textarea = document.createElement('textarea')
        textarea.value = text
        textarea.setAttribute('readonly', '')
        textarea.style.position = 'fixed'
        textarea.style.left = '0'
        textarea.style.top = '0'
        textarea.style.opacity = '0'
        document.body.appendChild(textarea)
        textarea.focus()
        textarea.select()
        ok = document.execCommand('copy')
        document.body.removeChild(textarea)
      } catch {
        ok = false
      }
    }

    if (!ok) return

    setCopied(true)
    if (copyTimerRef.current != null) {
      window.clearTimeout(copyTimerRef.current)
    }
    copyTimerRef.current = window.setTimeout(() => setCopied(false), 1200)
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

  const metrics = (message.message_metadata || {}) as Record<string, any>
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
	                  key={idx}
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

                      <div className="md:col-span-7">
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
                                        <td className="px-4 py-2.5 text-right font-mono">{c.vector_score != null ? Number(c.vector_score).toFixed(3) : "-"}</td>
                                        <td className="px-4 py-2.5 text-right font-mono">{c.bm25_score != null ? Number(c.bm25_score).toFixed(3) : "-"}</td>
                                        <td className="px-4 py-2.5 text-right font-mono">{c.rerank_score != null ? Number(c.rerank_score).toFixed(3) : "-"}</td>
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
          {isUser ? (
            <div className="whitespace-pre-wrap font-normal ">{message.content}</div>
          ) : isStreaming ? (
            <CinematicTypewriter content={message.content} isStreaming={true} />
          ) : (
            <ReactMarkdown
              remarkPlugins={markdownPlugins}
              components={markdownComponents}
            >
              {message.content}
            </ReactMarkdown>
          )}
        </div>

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

const CitationCard = memo(function CitationCard({ citation, index }: { citation: Citation; index: number }) {
  const { openDocument } = useDocumentView()
  const [hideImage, setHideImage] = useState(false)
  const imgUrl = (() => {
    if (!citation.img_url) return null
    const raw = citation.img_url
    const resolved = /^https?:\/\//i.test(raw) || /^data:/i.test(raw) || /^blob:/i.test(raw) ? raw : toAbsoluteBackendUrl(raw)
    return maybeAttachImageAuthToken(resolved)
  })()

  const handleClick = useCallback((e: React.MouseEvent) => {
    e.stopPropagation()
    // Open document viewer panel
    if (citation.document_id) {
      const start =
        typeof citation.evidence_start_char === 'number'
          ? citation.evidence_start_char
          : typeof citation.start_char === 'number'
          ? citation.start_char
          : null
      const end =
        typeof citation.evidence_end_char === 'number'
          ? citation.evidence_end_char
          : typeof citation.end_char === 'number'
          ? citation.end_char
          : null
      const range = start != null && end != null && end > start ? { start, end } : undefined
      openDocument(citation.document_id, citation.chunk_id, range)
    }
  }, [citation.document_id, citation.chunk_id, citation.evidence_start_char, citation.evidence_end_char, citation.start_char, citation.end_char, openDocument])

	  return (
	    <div
	      onClick={handleClick}
	      className="group/card text-xs rounded-lg p-3 border bg-card border-border/60 cursor-pointer shadow-sm focus-ring transition-colors transition-shadow duration-200 motion-reduce:transition-none hover:bg-muted/40 hover:border-primary/25 hover:shadow-md"
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
          <div className="flex items-center gap-2 mt-2 pt-1">
            <span className="bg-secondary/50 border border-border text-muted-foreground px-1.5 py-0.5 rounded text-[10px]">
              相似度 {Math.round(citation.relevance_score * 100)}%
            </span>
          </div>

          {citation.has_image && imgUrl && !hideImage && (
            <div className="mt-2 rounded-md overflow-hidden border border-border/50">
	              <a href={imgUrl} target="_blank" rel="noopener noreferrer" className="block relative aspect-video">
	                <Image
	                  src={imgUrl}
	                  alt="引用图片"
	                  fill
	                  unoptimized
	                  sizes="(max-width: 768px) 100vw, 300px"
	                  className="object-cover"
	                  onError={() => setHideImage(true)}
	                />
	              </a>
	            </div>
	          )}
        </div>
      </div>
    </div>
  )
})
