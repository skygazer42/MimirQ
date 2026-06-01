"use client"

import { AnimatePresence, motion, useReducedMotion } from 'framer-motion'
import dynamic from 'next/dynamic'
import { startTransition, useEffect, useMemo, useRef, useState, type ComponentPropsWithoutRef } from "react"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import { AuthImage } from '@/components/auth-image'
import { resolveMarkdownImageSrc, sanitizeMarkdownHref } from '@/components/markdown/markdown-safety'
import { randomIntInclusive } from '@/lib/secure-random'
import { cn } from "@/lib/utils"

const CinematicCodeBlock = dynamic(
  () => import('./cinematic-code-block').then((mod) => mod.CinematicCodeBlock),
  { ssr: false }
)

// Typing configuration (ms).
// Keep it deterministic and relatively low-frequency to reduce layout jitter while streaming.
const MIN_UNIT_DELAY_MS = 12
const MAX_UNIT_DELAY_MS = 22
const STREAM_WAIT_MS = 50
const NEWLINE_DELAY_MS = 60
const PUNCTUATION_DELAY_MS = 140

interface CinematicTypewriterProps {
  readonly content: string
  readonly onComplete?: () => void
  readonly isStreaming?: boolean
  readonly className?: string
}

type MarkdownChildrenProps = Readonly<{ children?: React.ReactNode }>
type MarkdownLinkProps = Readonly<{ href?: string; children?: React.ReactNode }>
type MarkdownImageProps = Readonly<{ src?: string | Blob; alt?: string }>

function CinematicMarkdownParagraph({ children }: MarkdownChildrenProps) {
  return (
    <p className="mb-3 last:mb-0 leading-relaxed motion-safe:animate-fade-in">
      {children}
    </p>
  )
}

function CinematicMarkdownList({ children }: MarkdownChildrenProps) {
  return (
    <ul className="list-disc pl-5 mb-3 space-y-1.5 marker:text-muted-foreground/60 motion-safe:animate-fade-in">
      {children}
    </ul>
  )
}

function CinematicMarkdownOrderedList({ children }: MarkdownChildrenProps) {
  return (
    <ol className="list-decimal pl-5 mb-3 space-y-1.5 marker:text-muted-foreground/60 motion-safe:animate-fade-in">
      {children}
    </ol>
  )
}

function CinematicMarkdownLink({ href, children }: MarkdownLinkProps) {
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

function CinematicMarkdownImage({ src, alt }: MarkdownImageProps) {
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
}

function CinematicMarkdownCode({ className, children, ...props }: ComponentPropsWithoutRef<'code'>) {
  const match = /language-(\w+)/.exec(className || '')
  if (match) {
    return (
      <CinematicCodeBlock
        language={match[1]}
        code={String(children).replace(/\n$/, '')}
      />
    )
  }

  return (
    <code className="bg-secondary/50 px-1.5 py-0.5 rounded-md text-sm font-mono text-primary" {...props}>
      {children}
    </code>
  )
}

const CINEMATIC_MARKDOWN_COMPONENTS = {
  a: CinematicMarkdownLink,
  code: CinematicMarkdownCode,
  img: CinematicMarkdownImage,
  ol: CinematicMarkdownOrderedList,
  p: CinematicMarkdownParagraph,
  ul: CinematicMarkdownList,
}

function randomDelay(minMs: number, maxMs: number) {
  return randomIntInclusive(minMs, maxMs)
}

function isAsciiWordChar(char: string) {
  return /\w/.test(char)
}

function isWhitespace(char: string) {
  return char === ' ' || char === '\t'
}

function readCodePointAt(text: string, index: number): { char: string; nextIndex: number } {
  const cp = text.codePointAt(index)
  if (cp == null) return { char: '', nextIndex: index }
  const char = String.fromCodePoint(cp)
  const nextIndex = index + (cp > 0xffff ? 2 : 1)
  return { char, nextIndex }
}

function computeNextTypingStep(text: string, startIndex: number): { nextIndex: number; delayMs: number } {
  if (startIndex >= text.length) return { nextIndex: startIndex, delayMs: STREAM_WAIT_MS }

  // Group ASCII words to reduce re-render frequency while keeping a "token-ish" feel.
  const head = text[startIndex]
  if (isAsciiWordChar(head)) {
    let idx = startIndex + 1
    while (idx < text.length && isAsciiWordChar(text[idx])) idx += 1
    return { nextIndex: idx, delayMs: randomDelay(MIN_UNIT_DELAY_MS, MAX_UNIT_DELAY_MS) }
  }

  // Group consecutive spaces/tabs.
  if (isWhitespace(head)) {
    let idx = startIndex + 1
    while (idx < text.length && isWhitespace(text[idx])) idx += 1
    return { nextIndex: idx, delayMs: randomDelay(MIN_UNIT_DELAY_MS, MAX_UNIT_DELAY_MS) }
  }

  // Newline: a tiny pause so paragraph boundaries feel intentional.
  if (head === '\n') {
    return { nextIndex: startIndex + 1, delayMs: NEWLINE_DELAY_MS }
  }

  // Default: one code point (good for CJK + punctuation).
  const { char, nextIndex } = readCodePointAt(text, startIndex)
  let delayMs = randomDelay(MIN_UNIT_DELAY_MS, MAX_UNIT_DELAY_MS)
  if (['.', '!', '?', '。', '！', '？', ',', '，', '、', ':', '：', ';', '；'].includes(char)) {
    delayMs += PUNCTUATION_DELAY_MS
  }
  return { nextIndex, delayMs }
}

export function CinematicTypewriter({
  content,
  onComplete,
  isStreaming = false,
  className,
}: Readonly<CinematicTypewriterProps>) {
  const reduceMotion = useReducedMotion()
  const [displayedContent, setDisplayedContent] = useState("")
  const [pendingToken, setPendingToken] = useState("")
  const [pendingTokenKey, setPendingTokenKey] = useState(0)
  const [isTyping, setIsTyping] = useState(false)

  const contentRef = useRef(content)
  const streamingRef = useRef(isStreaming)
  const onCompleteRef = useRef(onComplete)
  const displayedRef = useRef(displayedContent)
  const pendingRef = useRef(pendingToken)
  const indexRef = useRef(0)
  const timeoutRef = useRef<number | null>(null)
  const completedRef = useRef(false)

  useEffect(() => {
    contentRef.current = content
  }, [content])

  useEffect(() => {
    streamingRef.current = isStreaming
    if (isStreaming) completedRef.current = false
  }, [isStreaming])

  useEffect(() => {
    onCompleteRef.current = onComplete
  }, [onComplete])

  useEffect(() => {
    displayedRef.current = displayedContent
  }, [displayedContent])

  useEffect(() => {
    pendingRef.current = pendingToken
  }, [pendingToken])

  useEffect(() => {
    if (reduceMotion) {
      if (timeoutRef.current != null) {
        globalThis.window.clearTimeout(timeoutRef.current)
        timeoutRef.current = null
      }

      const full = contentRef.current
      indexRef.current = full.length
      completedRef.current = !streamingRef.current
      displayedRef.current = full
      pendingRef.current = ''

      setDisplayedContent(full)
      setPendingToken('')
      setPendingTokenKey(0)
      setIsTyping(false)
      if (!streamingRef.current) onCompleteRef.current?.()
      return
    }

    // Streaming-safe typing loop: always reads latest content via refs, so appends keep flowing.
    function resetIfReplaced() {
      const full = contentRef.current
      const currentDisplayed = displayedRef.current + pendingRef.current
      if (currentDisplayed && !full.startsWith(currentDisplayed)) {
        indexRef.current = 0
        completedRef.current = false
        displayedRef.current = ''
        pendingRef.current = ''
        startTransition(() => setDisplayedContent(''))
        startTransition(() => setPendingToken(''))
      }
    }

    function schedule(delayMs: number) {
      if (timeoutRef.current != null) {
        globalThis.window.clearTimeout(timeoutRef.current)
      }
      timeoutRef.current = globalThis.window.setTimeout(tick, Math.max(0, delayMs))
    }

    function tick() {
      if (reduceMotion) return
      resetIfReplaced()

      const full = contentRef.current
      const buffered = pendingRef.current
      if (buffered) {
        const nextDisplayed = displayedRef.current + buffered
        displayedRef.current = nextDisplayed
        pendingRef.current = ''
        startTransition(() => setDisplayedContent(nextDisplayed))
        startTransition(() => setPendingToken(''))
      }

      const idx = indexRef.current

      if (idx >= full.length) {
        if (streamingRef.current) {
          setIsTyping(true)
          schedule(STREAM_WAIT_MS)
          return
        }

        setIsTyping(false)
        if (timeoutRef.current != null) {
          globalThis.window.clearTimeout(timeoutRef.current)
          timeoutRef.current = null
        }

        if (!completedRef.current) {
          completedRef.current = true
          onCompleteRef.current?.()
        }
        return
      }

      setIsTyping(true)
      const step = computeNextTypingStep(full, idx)
      const nextIndex = Math.min(full.length, Math.max(idx, step.nextIndex))
      const token = full.slice(idx, nextIndex)
      indexRef.current = nextIndex
      pendingRef.current = token

      startTransition(() => setPendingToken(token))
      startTransition(() => setPendingTokenKey((prev) => prev + 1))
      schedule(step.delayMs)
    }

    if (timeoutRef.current == null) {
      tick()
    }

    return () => {
      if (timeoutRef.current != null) {
        globalThis.window.clearTimeout(timeoutRef.current)
        timeoutRef.current = null
      }
    }
  }, [reduceMotion])

  const tokenRevealTransition = useMemo(
    () => ({
      duration: reduceMotion ? 0 : 0.18,
      ease: [0.16, 1, 0.3, 1] as const,
    }),
    [reduceMotion]
  )

  return (
    <div className={cn("relative leading-relaxed", className)}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        skipHtml
        components={CINEMATIC_MARKDOWN_COMPONENTS}
      >
        {displayedContent}
      </ReactMarkdown>
      <AnimatePresence initial={false} mode="popLayout">
        {!reduceMotion && pendingToken ? (
          <motion.span
            key={`pending:${pendingTokenKey}`}
            initial={{ opacity: 0, y: '0.35em', filter: 'blur(6px)' }}
            animate={{ opacity: 1, y: '0em', filter: 'blur(0px)' }}
            exit={{ opacity: 0, y: '-0.2em', filter: 'blur(4px)' }}
            transition={tokenRevealTransition}
            className="inline whitespace-pre-wrap align-baseline text-foreground/90 motion-safe:animate-fade-in"
          >
            {pendingToken}
          </motion.span>
        ) : null}
      </AnimatePresence>

      {/* 电影感光标 */}
      {isTyping && !reduceMotion && (
        <span className="inline-block w-1.5 h-5 ml-0.5 align-middle bg-primary motion-safe:animate-blink rounded-full" />
      )}
    </div>
  )
}
