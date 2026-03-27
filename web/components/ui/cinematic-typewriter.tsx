"use client"

import dynamic from 'next/dynamic'
import { useEffect, useState, useRef, useMemo } from "react"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import { AuthImage } from '@/components/auth-image'
import { resolveMarkdownImageSrc, sanitizeMarkdownHref } from '@/components/markdown/markdown-safety'
import { cn } from "@/lib/utils"

const CinematicCodeBlock = dynamic(
  () => import('./cinematic-code-block').then((mod) => mod.CinematicCodeBlock),
  { ssr: false }
)

// 调整打字速度配置 (ms)
const MIN_TYPE_SPEED = 5
const MAX_TYPE_SPEED = 15
const PUNCTUATION_DELAY = 150 // 遇到标点符号时的额外停顿

interface CinematicTypewriterProps {
  readonly content: string
  readonly onComplete?: () => void
  readonly isStreaming?: boolean
  readonly className?: string
}

type MarkdownChildrenProps = Readonly<{ children?: React.ReactNode }>
type MarkdownLinkProps = Readonly<{ href?: string; children?: React.ReactNode }>
type MarkdownImageProps = Readonly<{ src?: string | Blob; alt?: string }>

export function CinematicTypewriter({
  content,
  onComplete,
  isStreaming = false,
  className,
}: Readonly<CinematicTypewriterProps>) {
  const [reduceMotion, setReduceMotion] = useState(false)
  const [displayedContent, setDisplayedContent] = useState("")
  const [isTyping, setIsTyping] = useState(false)
  const indexRef = useRef(0)
  const timeoutRef = useRef<NodeJS.Timeout | null>(null)

  // Markdown 组件配置
  const markdownComponents = useMemo(() => ({
    p: ({ children }: MarkdownChildrenProps) => <p className="mb-3 last:mb-0 leading-relaxed motion-safe:animate-fade-in">{children}</p>,
    ul: ({ children }: MarkdownChildrenProps) => (
      <ul className="list-disc pl-5 mb-3 space-y-1.5 marker:text-muted-foreground/60 motion-safe:animate-fade-in">{children}</ul>
    ),
    ol: ({ children }: MarkdownChildrenProps) => (
      <ol className="list-decimal pl-5 mb-3 space-y-1.5 marker:text-muted-foreground/60 motion-safe:animate-fade-in">{children}</ol>
    ),
    a: ({ href, children }: MarkdownLinkProps) => {
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
    },
    img: ({ src, alt }: MarkdownImageProps) => {
      const resolved = resolveMarkdownImageSrc(typeof src === 'string' ? src : '')
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
          className="my-3 w-full h-auto max-h-96 rounded-xl border border-border/50 bg-background/50 object-contain shadow-sm motion-safe:animate-fade-in"
        />
      )
    },
    code: ({ className, children, ...props }: any) => {
      const match = /language-(\w+)/.exec(className || '')
      return match ? (
        <CinematicCodeBlock
          language={match[1]}
          code={String(children).replace(/\n$/, '')}
        />
      ) : (
        <code className="bg-secondary/50 px-1.5 py-0.5 rounded-md text-sm font-mono text-primary" {...props}>
          {children}
        </code>
      )
    },
  }), [])

  useEffect(() => {
    if (globalThis.window === undefined) return
    const media = globalThis.window.matchMedia('(prefers-reduced-motion: reduce)')
    const update = () => setReduceMotion(Boolean(media.matches))
    update()
    if (typeof media.addEventListener === 'function') {
      media.addEventListener('change', update)
      return () => media.removeEventListener('change', update)
    }
    // Safari < 14
    media.addListener(update)
    return () => media.removeListener(update)
  }, [])

  useEffect(() => {
    if (reduceMotion) {
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current)
        timeoutRef.current = null
      }
      indexRef.current = content.length
      if (displayedContent !== content) {
        setDisplayedContent(content)
      }
      setIsTyping(false)
      if (!isStreaming) onComplete?.()
      return
    }

    // If the parent swapped in a new message (not an append), reset typing state.
    if (displayedContent && !content.startsWith(displayedContent)) {
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current)
        timeoutRef.current = null
      }
      indexRef.current = 0
      setDisplayedContent("")
      setIsTyping(false)
      return
    }

    // 如果已经不再 streaming 且显示内容已追上，直接完成
    if (!isStreaming && indexRef.current >= content.length) {
      if (displayedContent !== content) {
        setDisplayedContent(content)
      }
      setIsTyping(false)
      timeoutRef.current = null
      onComplete?.()
      return
    }

    setIsTyping(true)

    const typeNextChar = () => {
      if (indexRef.current >= content.length) {
        if (isStreaming) {
          // Wait for more content from stream
          timeoutRef.current = setTimeout(typeNextChar, 50)
        } else {
          setIsTyping(false)
          timeoutRef.current = null
          onComplete?.()
        }
        return
      }

      const char = content[indexRef.current]
      indexRef.current++
      setDisplayedContent((prev) => prev + char)

      let delay = Math.random() * (MAX_TYPE_SPEED - MIN_TYPE_SPEED) + MIN_TYPE_SPEED

      // 模拟思考停顿
      if (['.', '!', '?', '。', '！', '？'].includes(char)) {
        delay += PUNCTUATION_DELAY
      } else if (char === '\n') {
        delay += 20
      }

      timeoutRef.current = setTimeout(typeNextChar, delay)
    }

    // 只有当有新内容未显示时才启动打字循环，避免重复重置
    if (timeoutRef.current === null && indexRef.current < content.length) {
      typeNextChar()
    }

    return () => {
      // Cleanup is tricky with self-scheduling loop, usually handled by ref check
    }
  }, [content, isStreaming, onComplete, displayedContent, reduceMotion])

  // 组件卸载时清理
  useEffect(() => {
    return () => {
      if (timeoutRef.current) clearTimeout(timeoutRef.current)
    }
  }, [])

  return (
    <div className={cn("relative leading-relaxed", className)}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        skipHtml
        components={markdownComponents}
      >
        {displayedContent}
      </ReactMarkdown>

      {/* 电影感光标 */}
      {isTyping && !reduceMotion && (
        <span className="inline-block w-1.5 h-5 ml-0.5 align-middle bg-primary motion-safe:animate-blink rounded-full" />
      )}
    </div>
  )
}
