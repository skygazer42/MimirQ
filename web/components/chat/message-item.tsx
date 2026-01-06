/**
 * Shared chat message item (ChatArea + History).
 */
'use client'

import { memo, useState } from 'react'
import Image from 'next/image'
import { Database, Sparkles } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

import type { Citation, Message } from '@/types'
import { cn } from '@/lib/utils'
import { toAbsoluteBackendUrl } from '@/lib/env'

const markdownPlugins = [remarkGfm]
const markdownComponents = {
  p: ({ children }: { children?: React.ReactNode }) => <p className="mb-2 last:mb-0">{children}</p>,
  ul: ({ children }: { children?: React.ReactNode }) => (
    <ul className="list-disc pl-4 mb-2 space-y-1 marker:text-slate-400">{children}</ul>
  ),
  ol: ({ children }: { children?: React.ReactNode }) => (
    <ol className="list-decimal pl-4 mb-2 space-y-1 marker:text-slate-400">{children}</ol>
  ),
  li: ({ children }: { children?: React.ReactNode }) => <li className="mb-0.5">{children}</li>,
  a: ({ href, children }: { href?: string; children?: React.ReactNode }) => (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className="text-indigo-600 dark:text-indigo-400 font-medium hover:underline decoration-indigo-300 underline-offset-2"
    >
      {children}
    </a>
  ),
  img: ({ src, alt }: { src?: string; alt?: string }) => {
    const raw = typeof src === 'string' ? src : ''
    const resolved = raw ? (raw.startsWith('http') ? raw : toAbsoluteBackendUrl(raw)) : ''
    if (!resolved) return null
    return (
      <Image
        src={resolved}
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
    <blockquote className="border-l-4 border-indigo-200 dark:border-indigo-800 pl-4 italic text-slate-500 dark:text-slate-400 my-2 bg-slate-50 dark:bg-slate-800/50 py-2 rounded-r-lg">
      {children}
    </blockquote>
  ),
  code: ({ className, children, ...props }: { className?: string; children?: React.ReactNode }) => {
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

  return (
    <div
      className={cn(
        'flex gap-4 px-4 group animate-in fade-in slide-in-from-bottom-2 duration-500',
        isUser ? 'justify-end' : 'justify-start'
      )}
    >
      {!isUser && (
        <div className="flex-shrink-0 w-8 h-8 rounded-lg bg-indigo-50 dark:bg-indigo-900/30 border border-indigo-100 dark:border-indigo-800 flex items-center justify-center shadow-sm mt-1">
          <Sparkles className="h-4 w-4 text-indigo-600 dark:text-indigo-400" />
        </div>
      )}

      <div
        className={cn(
          'max-w-2xl px-6 py-4 shadow-sm relative text-[15px]',
          isUser
            ? 'bg-slate-900 dark:bg-indigo-600 text-white rounded-2xl rounded-tr-sm shadow-md'
            : 'bg-white dark:bg-slate-900 text-slate-800 dark:text-slate-200 border border-slate-100 dark:border-slate-800 rounded-2xl rounded-tl-sm'
        )}
      >
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
  const imgUrl = citation.img_url
    ? citation.img_url.startsWith('http')
      ? citation.img_url
      : toAbsoluteBackendUrl(citation.img_url)
    : null

  return (
    <div className="text-xs bg-slate-50 dark:bg-slate-800/50 hover:bg-white dark:hover:bg-slate-800 rounded-lg p-2.5 border border-slate-100 dark:border-slate-700 hover:border-indigo-200 dark:hover:border-indigo-700 transition-all cursor-pointer group shadow-sm hover:shadow-md">
      <div className="flex items-start gap-2.5">
        <span className="flex-shrink-0 w-4 h-4 bg-white dark:bg-slate-900 text-indigo-600 dark:text-indigo-400 border border-indigo-100 dark:border-indigo-800 rounded flex items-center justify-center text-[10px] font-bold shadow-sm group-hover:bg-indigo-50 dark:group-hover:bg-indigo-900/50 group-hover:border-indigo-200 transition-colors">
          {index + 1}
        </span>
        <div className="flex-1 min-w-0">
          <p className="font-semibold text-slate-700 dark:text-slate-300 truncate group-hover:text-indigo-700 dark:group-hover:text-indigo-400 transition-colors">
            {citation.document_name}
            {citation.page_number && ` · P.${citation.page_number}`}
          </p>
          <p className="text-slate-500 dark:text-slate-400 mt-1 line-clamp-2 leading-relaxed group-hover:text-slate-600 dark:group-hover:text-slate-300">
            &quot;{citation.chunk_content}&quot;
          </p>
          <div className="flex items-center gap-2 mt-2">
            <span className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 text-slate-400 dark:text-slate-500 px-1.5 py-0.5 rounded text-[10px] group-hover:border-indigo-100 dark:group-hover:border-indigo-800 group-hover:text-indigo-400 transition-colors">
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
