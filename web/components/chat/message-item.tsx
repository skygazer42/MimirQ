/**
 * Shared chat message item (ChatArea + History).
 */
'use client'

import { memo, useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import Image from 'next/image'
import { Check, Copy, Database, Bot, User } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

import type { Citation, Message } from '@/types'
import { cn } from '@/lib/utils'
import { API_BASE_URL, toAbsoluteBackendUrl } from '@/lib/env'
import { getAccessToken, getTenantId } from '@/lib/auth-storage'
import { useDocumentView } from '@/store/document-view'

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

  return (
    <div
      className={cn(
        'flex gap-4 px-2 group animate-in fade-in slide-in-from-bottom-2 duration-500',
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
          'max-w-3xl px-6 py-4 shadow-sm relative text-[15px] transition-all duration-300',
          isUser
            ? 'bg-primary text-primary-foreground rounded-2xl rounded-tr-sm shadow-md shadow-primary/10'
            : 'bg-card text-foreground border border-border/60 rounded-2xl rounded-tl-sm hover:shadow-md hover:border-border/80'
          )}
      >
        {/* 思维链 / 步骤展示 */}
        {!isUser && message.steps && message.steps.length > 0 && (
          <div className="mb-4 space-y-2 animate-fade-in">
             <div className="flex items-center gap-2 text-[10px] font-bold text-primary/70 uppercase tracking-widest">
                <div className="relative flex h-2 w-2">
                    <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-primary opacity-75"></span>
                    <span className="relative inline-flex rounded-full h-2 w-2 bg-primary"></span>
                </div>
                思考路径
             </div>
             <div className="pl-4 border-l border-primary/20 space-y-1">
                {message.steps.map((step, idx) => (
                    <div 
                        key={idx} 
                        className={cn(
                            "text-xs transition-opacity duration-500",
                            idx === message.steps!.length - 1 ? "text-foreground font-medium animate-pulse" : "text-muted-foreground/60"
                        )}
                    >
                        {step}
                    </div>
                ))}
             </div>
          </div>
        )}

        <button
          type="button"
          onClick={handleCopy}
          aria-label={copied ? 'Copied' : 'Copy message'}
          title={copied ? 'Copied' : 'Copy'}
          className={cn(
            'absolute bottom-2 right-2 z-10 rounded-md p-1.5 transition-all duration-200',
            'opacity-0 group-hover:opacity-100 scale-90 group-hover:scale-100',
            'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60',
            isUser
              ? 'text-primary-foreground/70 hover:text-primary-foreground hover:bg-white/10'
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
            isUser && 'prose-code:bg-white/20 prose-code:text-white'
          )}
        >
          {isUser ? (
            <div className="whitespace-pre-wrap font-normal tracking-wide">{message.content}</div>
          ) : isStreaming ? (
            <div className="whitespace-pre-wrap font-normal">
              {message.content}
              <span className="inline-block w-2 h-4 ml-1 bg-primary animate-blink align-middle" />
            </div>
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
            <div className="flex items-center gap-2 text-[10px] font-bold text-muted-foreground uppercase tracking-widest opacity-80">
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
        openDocument(citation.document_id, citation.chunk_id)
    }
  }, [citation.document_id, citation.chunk_id, openDocument])

  return (
    <div 
        onClick={handleClick}
        className="group/card text-xs bg-card hover:bg-secondary/30 rounded-lg p-3 border border-border/60 hover:border-primary/30 transition-all duration-300 cursor-pointer shadow-sm hover:shadow-md hover:-translate-y-0.5"
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
                  className="object-cover group-hover/card:scale-105 transition-transform duration-500"
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