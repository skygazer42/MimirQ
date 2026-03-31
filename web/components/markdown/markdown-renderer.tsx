'use client'

import { Component, memo, useEffect, useMemo, useRef } from 'react'
import type * as React from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import rehypeRaw from 'rehype-raw'
import rehypeSanitize, { defaultSchema } from 'rehype-sanitize'
import type { Options as RehypeSanitizeOptions } from 'rehype-sanitize'

import { AuthImage } from '@/components/auth-image'
import { cn } from '@/lib/utils'
import { extractMarkdownHeadings, flashElementId, scrollToElementId } from '@/lib/markdown'
import { resolveMarkdownImageSrc, sanitizeMarkdownHref } from './markdown-safety'

const FLASH_CLASS = 'bg-primary/10 ring-1 ring-primary/25 rounded-md transition-colors'

const MARKDOWN_SANITIZE_SCHEMA: RehypeSanitizeOptions = {
  ...defaultSchema,
  tagNames: [
    ...(defaultSchema.tagNames || []),
    'table',
    'thead',
    'tbody',
    'tfoot',
    'tr',
    'th',
    'td',
    'caption',
    'colgroup',
    'col',
  ],
  attributes: {
    ...defaultSchema.attributes,
    table: [...((defaultSchema.attributes?.table as string[] | undefined) || [])],
    thead: [...((defaultSchema.attributes?.thead as string[] | undefined) || [])],
    tbody: [...((defaultSchema.attributes?.tbody as string[] | undefined) || [])],
    tfoot: [...((defaultSchema.attributes?.tfoot as string[] | undefined) || [])],
    tr: [...((defaultSchema.attributes?.tr as string[] | undefined) || [])],
    th: [...((defaultSchema.attributes?.th as string[] | undefined) || []), 'colspan', 'rowspan'],
    td: [...((defaultSchema.attributes?.td as string[] | undefined) || []), 'colspan', 'rowspan'],
    caption: [...((defaultSchema.attributes?.caption as string[] | undefined) || [])],
    colgroup: [...((defaultSchema.attributes?.colgroup as string[] | undefined) || [])],
    col: [...((defaultSchema.attributes?.col as string[] | undefined) || []), 'span'],
  },
  protocols: {
    ...(defaultSchema.protocols || {}),
    href: ['http', 'https', 'mailto', 'tel'],
    src: ['http', 'https', 'blob', 'data'],
  },
}

type MarkdownRendererProps = Readonly<{
  markdown: string
  className?: string
  enableTocAnchors?: boolean
  autoScrollToHash?: boolean
}>

type MarkdownRenderBoundaryProps = Readonly<{
  className?: string
  resetKey: string
  children: React.ReactNode
}>

type MarkdownRenderBoundaryState = Readonly<{
  hasError: boolean
}>

function MarkdownRenderFallback({ className }: Readonly<{ className?: string }>) {
  return (
    <div
      role="status"
      className={cn(
        'rounded-lg border border-amber-500/30 bg-amber-500/8 px-4 py-3 text-sm text-amber-900 dark:text-amber-100',
        className
      )}
    >
      Markdown 内容渲染失败，请尝试刷新或查看原始文本。
    </div>
  )
}

class MarkdownRenderBoundary extends Component<MarkdownRenderBoundaryProps, MarkdownRenderBoundaryState> {
  state: MarkdownRenderBoundaryState = { hasError: false }

  static getDerivedStateFromError(): MarkdownRenderBoundaryState {
    return { hasError: true }
  }

  componentDidCatch(error: unknown) {
    console.error('Markdown rendering failed:', error)
  }

  componentDidUpdate(previousProps: MarkdownRenderBoundaryProps) {
    if (this.state.hasError && previousProps.resetKey !== this.props.resetKey) {
      this.setState({ hasError: false })
    }
  }

  render() {
    if (this.state.hasError) {
      return <MarkdownRenderFallback className={this.props.className} />
    }

    return this.props.children
  }
}

function MarkdownRendererContent({
  markdown,
  className,
  enableTocAnchors = true,
  autoScrollToHash = false,
}: MarkdownRendererProps) {
  const text = markdown || ''

  const headings = useMemo(
    () => (enableTocAnchors ? extractMarkdownHeadings(text) : []),
    [text, enableTocAnchors]
  )

  const headingCursorRef = useRef(0)
  useEffect(() => {
    headingCursorRef.current = 0
  }, [text, enableTocAnchors])

  useEffect(() => {
    if (!autoScrollToHash) return
    if (globalThis.window === undefined) return

    const scrollNow = (behavior: ScrollBehavior) => {
      const raw = globalThis.window.location.hash || ''
      const id = raw.startsWith('#') ? raw.slice(1) : raw
      const decoded = id ? decodeURIComponent(id) : ''
      if (!decoded) return
      globalThis.window.requestAnimationFrame(() => {
        const ok = scrollToElementId(decoded, { behavior })
        if (ok) flashElementId(decoded, FLASH_CLASS)
      })
    }

    const onHashChange = () => scrollNow('smooth')

    scrollNow('auto')
    globalThis.window.addEventListener('hashchange', onHashChange)
    return () => globalThis.window.removeEventListener('hashchange', onHashChange)
  }, [autoScrollToHash, text])

  const headingComponent = (level: 1 | 2 | 3 | 4 | 5 | 6) => {
    const Tag = `h${level}` as keyof React.JSX.IntrinsicElements
    return function Heading({ children, ...props }: any) {
      const idx = headingCursorRef.current
      const heading = headings[idx]
      headingCursorRef.current += 1
      const id = heading?.id

      return (
        <Tag
          id={id}
          className={cn('group scroll-mt-32', props.className)}
          {...props}
        >
          {children}
          {enableTocAnchors && id && (
            <a
              href={`#${encodeURIComponent(id)}`}
              onClick={(e) => {
                e.preventDefault()
                if (globalThis.window !== undefined) {
                  globalThis.window.history.replaceState(null, '', `#${encodeURIComponent(id)}`)
                }
                scrollToElementId(id)
                flashElementId(id, FLASH_CLASS)
              }}
              className="ml-2 no-underline text-muted-foreground/60 hover:text-primary opacity-0 group-hover:opacity-100"
              aria-label="Jump to section"
            >
              #
            </a>
          )}
        </Tag>
      )
    }
  }

  return (
    <div className={className}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeRaw, [rehypeSanitize, MARKDOWN_SANITIZE_SCHEMA]]}
        components={{
          h1: headingComponent(1),
          h2: headingComponent(2),
          h3: headingComponent(3),
          h4: headingComponent(4),
          h5: headingComponent(5),
          h6: headingComponent(6),
          a: ({ href, children }) => {
            const rawHref = typeof href === 'string' ? href : ''
            const safeHref = sanitizeMarkdownHref(rawHref)
            if (!safeHref) {
              return <span className="text-muted-foreground">{children}</span>
            }

            if (safeHref.startsWith('#')) {
              const id = safeHref.slice(1)
              return (
                <a
                  href={safeHref}
                  onClick={(e) => {
                    e.preventDefault()
                    const decoded = id ? decodeURIComponent(id) : ''
                    if (!decoded) return
                    if (globalThis.window !== undefined) {
                      globalThis.window.history.replaceState(null, '', `#${encodeURIComponent(decoded)}`)
                    }
                    scrollToElementId(decoded)
                    flashElementId(decoded, FLASH_CLASS)
                  }}
                  className="underline decoration-border/70 underline-offset-2 hover:decoration-border"
                >
                  {children}
                </a>
              )
            }

            return (
              <a
                href={safeHref}
                target="_blank"
                rel="noopener noreferrer"
                className="underline decoration-border/70 underline-offset-2 hover:decoration-border"
              >
                {children}
              </a>
            )
          },
          img: ({ src, alt }) => {
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
                className="my-2 w-full h-auto max-h-96 object-contain rounded-lg border border-border/70 bg-card shadow-sm"
              />
            )
          },
          table: ({ node, className, children, ...props }) => (
            <div className="my-4 overflow-x-auto">
              <table aria-label="Markdown 表格" className={cn('w-full', className)} {...props}>
                {children}
              </table>
            </div>
          ),
        }}
      >
        {text}
      </ReactMarkdown>
    </div>
  )
}

export const MarkdownRenderer = memo(function MarkdownRenderer(props: MarkdownRendererProps) {
  const text = props.markdown || ''

  return (
    <MarkdownRenderBoundary className={props.className} resetKey={text}>
      <MarkdownRendererContent {...props} markdown={text} />
    </MarkdownRenderBoundary>
  )
})
