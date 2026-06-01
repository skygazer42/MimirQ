'use client'

import { Component, createContext, memo, useContext, useEffect, useMemo } from 'react'
import type * as React from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import rehypeRaw from 'rehype-raw'
import rehypeSanitize, { defaultSchema } from 'rehype-sanitize'
import type { Options as RehypeSanitizeOptions } from 'rehype-sanitize'

import { AuthImage } from '@/components/auth-image'
import { cn } from '@/lib/utils'
import { extractMarkdownHeadings, flashElementId, scrollToElementId } from '@/lib/markdown'
import { reportClientError } from '@/lib/client-logging'
import type { MarkdownHeading } from '@/lib/markdown'
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
    ...defaultSchema.protocols,
    href: ['http', 'https', 'mailto', 'tel'],
    src: ['http', 'https', 'blob', 'data'],
  },
}

type MarkdownRendererProps = Readonly<{
  markdown: string
  className?: string
  enableTocAnchors?: boolean
  autoScrollToHash?: boolean
  scrollContainerSelector?: string
}>

type MarkdownRenderBoundaryProps = Readonly<{
  className?: string
  resetKey: string
  children: React.ReactNode
}>

type MarkdownRenderBoundaryState = Readonly<{
  hasError: boolean
}>

type MarkdownRendererRuntime = Readonly<{
  enableTocAnchors: boolean
  headings: MarkdownHeading[]
  scrollContainerSelector?: string
}>
type MarkdownAstNode = {
  position?: {
    start?: {
      line?: number
    }
  }
}
type MarkdownHeadingLevel = 1 | 2 | 3 | 4 | 5 | 6
type MarkdownHeadingProps = React.HTMLAttributes<HTMLHeadingElement> & {
  level: MarkdownHeadingLevel
  node?: MarkdownAstNode
}
type MarkdownAnchorProps = React.AnchorHTMLAttributes<HTMLAnchorElement>
type MarkdownImageProps = React.ImgHTMLAttributes<HTMLImageElement>
type MarkdownTableProps = React.TableHTMLAttributes<HTMLTableElement> & {
  node?: unknown
}

const MarkdownRendererRuntimeContext = createContext<MarkdownRendererRuntime>({
  enableTocAnchors: true,
  headings: [],
})

function useMarkdownRendererRuntime() {
  return useContext(MarkdownRendererRuntimeContext)
}

function renderHeadingByLevel(
  level: MarkdownHeadingLevel,
  props: React.HTMLAttributes<HTMLHeadingElement>
) {
  switch (level) {
    case 1:
      return <h1 {...props} />
    case 2:
      return <h2 {...props} />
    case 3:
      return <h3 {...props} />
    case 4:
      return <h4 {...props} />
    case 5:
      return <h5 {...props} />
    case 6:
      return <h6 {...props} />
  }
}

function MarkdownHeadingComponent({
  children,
  className,
  level,
  node,
  ...props
}: MarkdownHeadingProps) {
  const { enableTocAnchors, headings, scrollContainerSelector } = useMarkdownRendererRuntime()
  const line = Number(node?.position?.start?.line || 0)
  const heading = line
    ? headings.find((item) => item.line === line && item.level === level)
    : undefined
  const id = heading?.id
  const headingChildren = (
    <>
      {children}
      {enableTocAnchors && id && (
        <a
          href={`#${encodeURIComponent(id)}`}
          onClick={(event) => {
            event.preventDefault()
            if (globalThis.window !== undefined) {
              globalThis.window.history.replaceState(null, '', `#${encodeURIComponent(id)}`)
            }
            scrollToElementId(id, { scrollContainerSelector })
            flashElementId(id, FLASH_CLASS)
          }}
          className="ml-2 no-underline text-muted-foreground/60 hover:text-primary opacity-0 group-hover:opacity-100"
          aria-label="Jump to section"
        >
          #
        </a>
      )}
    </>
  )

  return renderHeadingByLevel(level, {
    id,
    className: cn('group scroll-mt-32', className),
    ...props,
    children: headingChildren,
  })
}

function MarkdownH1(props: Omit<MarkdownHeadingProps, 'level'>) {
  return <MarkdownHeadingComponent level={1} {...props} />
}

function MarkdownH2(props: Omit<MarkdownHeadingProps, 'level'>) {
  return <MarkdownHeadingComponent level={2} {...props} />
}

function MarkdownH3(props: Omit<MarkdownHeadingProps, 'level'>) {
  return <MarkdownHeadingComponent level={3} {...props} />
}

function MarkdownH4(props: Omit<MarkdownHeadingProps, 'level'>) {
  return <MarkdownHeadingComponent level={4} {...props} />
}

function MarkdownH5(props: Omit<MarkdownHeadingProps, 'level'>) {
  return <MarkdownHeadingComponent level={5} {...props} />
}

function MarkdownH6(props: Omit<MarkdownHeadingProps, 'level'>) {
  return <MarkdownHeadingComponent level={6} {...props} />
}

function MarkdownAnchor({ href, children }: MarkdownAnchorProps) {
  const { scrollContainerSelector } = useMarkdownRendererRuntime()
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
        onClick={(event) => {
          event.preventDefault()
          const decoded = id ? decodeURIComponent(id) : ''
          if (!decoded) return
          if (globalThis.window !== undefined) {
            globalThis.window.history.replaceState(null, '', `#${encodeURIComponent(decoded)}`)
          }
          scrollToElementId(decoded, { scrollContainerSelector })
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
}

function MarkdownImage({ src, alt }: MarkdownImageProps) {
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
}

function MarkdownTable({ className, children, node: _node, ...props }: MarkdownTableProps) {
  return (
    <div className="my-4 overflow-x-auto">
      <table aria-label="Markdown 表格" className={cn('w-full', className)} {...props}>
        {children}
      </table>
    </div>
  )
}

const MARKDOWN_RENDERER_COMPONENTS = {
  a: MarkdownAnchor,
  h1: MarkdownH1,
  h2: MarkdownH2,
  h3: MarkdownH3,
  h4: MarkdownH4,
  h5: MarkdownH5,
  h6: MarkdownH6,
  img: MarkdownImage,
  table: MarkdownTable,
}

function MarkdownRenderFallback({ className }: Readonly<{ className?: string }>) {
  return (
    <output
      className={cn(
        'rounded-lg border border-amber-500/30 bg-amber-500/8 px-4 py-3 text-sm text-amber-900 dark:text-amber-100',
        className
      )}
    >
      Markdown 内容渲染失败，请尝试刷新或查看原始文本。
    </output>
  )
}

class MarkdownRenderBoundary extends Component<MarkdownRenderBoundaryProps, MarkdownRenderBoundaryState> {
  state: MarkdownRenderBoundaryState = { hasError: false }

  static getDerivedStateFromError(): MarkdownRenderBoundaryState {
    return { hasError: true }
  }

  componentDidCatch(error: unknown) {
    reportClientError('Markdown rendering failed', error)
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
  scrollContainerSelector,
}: MarkdownRendererProps) {
  const text = markdown || ''

  const headings = useMemo(
    () => (enableTocAnchors ? extractMarkdownHeadings(text) : []),
    [text, enableTocAnchors]
  )

  useEffect(() => {
    if (!autoScrollToHash) return
    if (globalThis.window === undefined) return

    const scrollNow = (behavior: ScrollBehavior) => {
      const raw = globalThis.window.location.hash || ''
      const id = raw.startsWith('#') ? raw.slice(1) : raw
      const decoded = id ? decodeURIComponent(id) : ''
      if (!decoded) return
      globalThis.window.requestAnimationFrame(() => {
        const ok = scrollToElementId(decoded, { behavior, scrollContainerSelector })
        if (ok) flashElementId(decoded, FLASH_CLASS)
      })
    }

    const onHashChange = () => scrollNow('smooth')

    scrollNow('auto')
    globalThis.window.addEventListener('hashchange', onHashChange)
    return () => globalThis.window.removeEventListener('hashchange', onHashChange)
  }, [autoScrollToHash, scrollContainerSelector, text])

  const runtime = useMemo<MarkdownRendererRuntime>(
    () => ({
      enableTocAnchors,
      headings,
      scrollContainerSelector,
    }),
    [enableTocAnchors, headings, scrollContainerSelector]
  )

  return (
    <div className={className}>
      <MarkdownRendererRuntimeContext.Provider value={runtime}>
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          rehypePlugins={[rehypeRaw, [rehypeSanitize, MARKDOWN_SANITIZE_SCHEMA]]}
          components={MARKDOWN_RENDERER_COMPONENTS}
        >
          {text}
        </ReactMarkdown>
      </MarkdownRendererRuntimeContext.Provider>
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
