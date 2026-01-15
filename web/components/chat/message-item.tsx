/**
 * Shared chat message item (ChatArea + History).
 */
'use client'

import { memo, useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import Image from 'next/image'
import { Check, Copy, Database, Sparkles } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

import type { Citation, Message } from '@/types'
import { cn } from '@/lib/utils'
import { API_BASE_URL, toAbsoluteBackendUrl } from '@/lib/env'
import { getAccessToken, getTenantId } from '@/lib/auth-storage'

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
  p: ({ children }: { children?: ReactNode }) => <p className="mb-2 last:mb-0">{children}</p>,
  ul: ({ children }: { children?: ReactNode }) => (
    <ul className="list-disc pl-4 mb-2 space-y-1 marker:text-slate-400">{children}</ul>
  ),
  ol: ({ children }: { children?: ReactNode }) => (
    <ol className="list-decimal pl-4 mb-2 space-y-1 marker:text-slate-400">{children}</ol>
  ),
  li: ({ children }: { children?: ReactNode }) => <li className="mb-0.5">{children}</li>,
  a: ({ href, children }: { href?: string; children?: ReactNode }) => (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className="text-sky-600 dark:text-sky-400 font-medium hover:underline decoration-sky-300 underline-offset-2"
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
        className="my-2 w-full h-auto max-h-96 object-contain rounded-lg border border-slate-200/70 dark:border-slate-700 bg-white dark:bg-slate-900"
      />
    )
  },
  blockquote: ({ children }: { children?: React.ReactNode }) => (
    <blockquote className="border-l-4 border-sky-200 dark:border-sky-800 pl-4 italic text-slate-500 dark:text-slate-400 my-2 bg-slate-50 dark:bg-slate-800/50 py-2 rounded-r-lg">
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
          'bg-slate-100 dark:bg-slate-800 px-1.5 py-0.5 rounded-md text-sm text-pink-500 dark:text-pink-400 font-mono',
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
        'flex gap-4 px-4 group animate-in fade-in slide-in-from-bottom-2 duration-500',
        isUser ? 'justify-end' : 'justify-start'
      )}
    >
      {!isUser && (
        <div className="flex-shrink-0 w-8 h-8 rounded-lg bg-sky-50 dark:bg-sky-900/30 border border-sky-100 dark:border-sky-800 flex items-center justify-center shadow-sm mt-1">
          <Sparkles className="h-4 w-4 text-sky-600 dark:text-sky-400" />
        </div>
      )}

      <div
        className={cn(
          'max-w-2xl px-6 py-4 shadow-sm relative text-[15px]',
          isUser
            ? 'bg-slate-900 dark:bg-sky-600 text-white rounded-2xl rounded-tr-sm shadow-md'
            : 'bg-white dark:bg-slate-900 text-slate-800 dark:text-slate-200 border border-slate-100 dark:border-slate-800 rounded-2xl rounded-tl-sm'
          )}
      >
        <button
          type="button"
          onClick={handleCopy}
          aria-label={copied ? 'Copied' : 'Copy message'}
          title={copied ? 'Copied' : 'Copy'}
          className={cn(
            'absolute bottom-2 right-2 z-10 rounded-md p-1.5 transition',
            'opacity-70 hover:opacity-100 group-hover:opacity-100',
            'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-500/60 focus-visible:ring-offset-2 focus-visible:ring-offset-transparent',
            isUser
              ? 'text-white/70 hover:text-white hover:bg-white/10'
              : 'text-slate-500 hover:text-slate-900 dark:text-slate-400 dark:hover:text-slate-100 hover:bg-slate-100/70 dark:hover:bg-slate-800/70'
          )}
        >
          {copied ? (
            <Check className="h-4 w-4" />
          ) : (
            <Copy className="h-4 w-4" />
          )}
        </button>

        <div
          className={cn(
            'prose max-w-none break-words leading-relaxed dark:prose-invert',
            isUser ? 'prose-invert' : 'prose-slate',
            'prose-p:my-1.5 prose-p:leading-7',
            'prose-pre:bg-slate-900 dark:prose-pre:bg-slate-950 prose-pre:border prose-pre:border-slate-800 dark:prose-pre:border-slate-800 prose-pre:text-slate-50 prose-pre:rounded-xl prose-pre:p-4 prose-pre:my-2',
            'prose-code:bg-slate-100 dark:prose-code:bg-slate-800 prose-code:px-1.5 prose-code:py-0.5 prose-code:rounded-md prose-code:text-sm prose-code:font-mono prose-code:text-pink-600 dark:prose-code:text-pink-400 prose-code:before:content-none prose-code:after:content-none',
            isUser && 'prose-code:bg-slate-800 prose-code:text-slate-200'
          )}
        >
          {isUser ? (
            <div className="whitespace-pre-wrap font-normal">{message.content}</div>
          ) : isStreaming ? (
            <div className="whitespace-pre-wrap font-normal">
              {message.content}
              <span className="inline-block w-2 animate-pulse">▍</span>
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
          <div className="mt-4 pt-3 border-t border-slate-100 dark:border-slate-800 space-y-2">
            <div className="flex items-center gap-2 text-[10px] font-bold text-slate-400 uppercase tracking-wider">
              <Database className="w-3 h-3" />
              参考来源
            </div>
            <div className="grid grid-cols-1 gap-2">
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
        <div className="flex-shrink-0 w-8 h-8 rounded-full bg-slate-100 dark:bg-slate-800 flex items-center justify-center text-[10px] font-bold text-slate-500 dark:text-slate-400 mt-1 border border-slate-200 dark:border-slate-700">
          U
        </div>
      )}
    </div>
  )
})

const CitationCard = memo(function CitationCard({ citation, index }: { citation: Citation; index: number }) {
  const [hideImage, setHideImage] = useState(false)
  const imgUrl = (() => {
    if (!citation.img_url) return null
    const raw = citation.img_url
    const resolved = /^https?:\/\//i.test(raw) || /^data:/i.test(raw) || /^blob:/i.test(raw) ? raw : toAbsoluteBackendUrl(raw)
    return maybeAttachImageAuthToken(resolved)
  })()

  return (
    <div className="text-xs bg-slate-50 dark:bg-slate-800/50 hover:bg-white dark:hover:bg-slate-800 rounded-lg p-2.5 border border-slate-100 dark:border-slate-700 hover:border-sky-200 dark:hover:border-sky-700 transition-all cursor-pointer group shadow-sm hover:shadow-md">
      <div className="flex items-start gap-2.5">
        <span className="flex-shrink-0 w-4 h-4 bg-white dark:bg-slate-900 text-sky-600 dark:text-sky-400 border border-sky-100 dark:border-sky-800 rounded flex items-center justify-center text-[10px] font-bold shadow-sm group-hover:bg-sky-50 dark:group-hover:bg-sky-900/50 group-hover:border-sky-200 transition-colors">
          {index + 1}
        </span>
        <div className="flex-1 min-w-0">
          <p className="font-semibold text-slate-700 dark:text-slate-300 truncate group-hover:text-sky-700 dark:group-hover:text-sky-400 transition-colors">
            {citation.document_name}
            {citation.page_number && ` · P.${citation.page_number}`}
          </p>
          <p className="text-slate-500 dark:text-slate-400 mt-1 line-clamp-2 leading-relaxed group-hover:text-slate-600 dark:group-hover:text-slate-300">
            &quot;{citation.chunk_content}&quot;
          </p>
          <div className="flex items-center gap-2 mt-2">
            <span className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 text-slate-400 dark:text-slate-500 px-1.5 py-0.5 rounded text-[10px] group-hover:border-sky-100 dark:group-hover:border-sky-800 group-hover:text-sky-400 transition-colors">
              相似度 {Math.round(citation.relevance_score * 100)}%
            </span>
          </div>

          {citation.has_image && imgUrl && !hideImage && (
            <div className="mt-2">
              <a href={imgUrl} target="_blank" rel="noopener noreferrer" className="block">
                <Image
                  src={imgUrl}
                  alt="引用图片"
                  width={800}
                  height={600}
                  unoptimized
                  sizes="(max-width: 768px) 100vw, 640px"
                  loading="lazy"
                  className="w-full h-auto max-h-48 object-contain rounded-md border border-slate-200/70 dark:border-slate-700 bg-white dark:bg-slate-900"
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
