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
import { extractMarkdownHeadings, flashElementId, scrollToElementId, type MarkdownHeading } from '@/lib/markdown'
import { reportClientError } from '@/lib/client-logging'
import { resolveMarkdownImageSrc, sanitizeMarkdownHref } from './markdown-safety'
import { rehypeSourceRange, type MarkdownSourceRange } from './markdown-source-range'

const FLASH_CLASS = 'bg-primary/10 ring-1 ring-primary/25 rounded-md transition-colors'

const MARKDOWN_SANITIZE_SCHEMA: RehypeSanitizeOptions = {
  ...defaultSchema,
  tagNames: [...(defaultSchema.tagNames ?? []), 'caption', 'colgroup', 'col'],
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
  sourceRange?: MarkdownSourceRange | null
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
  headingsByLine: ReadonlyMap<number, MarkdownHeading>
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
  headingsByLine: new Map(),
})

function useMarkdownRendererRuntime() {
  return useContext(MarkdownRendererRuntimeContext)
}

function decodeHeadingId(hash: string): string | null {
  const encodedId = hash.slice(1)
  if (encodedId === '') return null
  try {
    return decodeURIComponent(encodedId)
  } catch {
    return null
  }
}

function renderHeadingByLevel(
  level: MarkdownHeadingLevel,
  { children, ...props }: React.HTMLAttributes<HTMLHeadingElement>,
) {
  switch (level) {
    case 1:
      return <h1 {...props}>{children}</h1>
    case 2:
      return <h2 {...props}>{children}</h2>
    case 3:
      return <h3 {...props}>{children}</h3>
    case 4:
      return <h4 {...props}>{children}</h4>
    case 5:
      return <h5 {...props}>{children}</h5>
    case 6:
      return <h6 {...props}>{children}</h6>
  }
}

function MarkdownHeadingComponent({ children, className, level, node, ...props }: MarkdownHeadingProps) {
  const { headingsByLine, scrollContainerSelector } = useMarkdownRendererRuntime()
  const line = node?.position?.start?.line
  const heading = line === undefined ? undefined : headingsByLine.get(line)
  const id = heading?.level === level ? heading.id : undefined
  const headingChildren = (
    <>
      {children}
      {id !== undefined && (
        <a
          href={`#${encodeURIComponent(id)}`}
          onClick={(event) => {
            event.preventDefault()
            window.history.replaceState(null, '', `#${encodeURIComponent(id)}`)
            scrollToElementId(id, { scrollContainerSelector })
            flashElementId(id, FLASH_CLASS)
          }}
          className="ml-2 no-underline text-muted-foreground/60 hover:text-primary opacity-0 group-hover:opacity-100 focus-visible:opacity-100"
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
  const safeHref = sanitizeMarkdownHref(href)
  const isHeadingLink = safeHref !== null && safeHref.startsWith('#')
  const headingId = isHeadingLink ? decodeHeadingId(safeHref) : null
  if (safeHref === null || (isHeadingLink && headingId === null)) {
    return <span className="text-muted-foreground">{children}</span>
  }

  if (headingId !== null) {
    return (
      <a
        href={safeHref}
        onClick={(event) => {
          event.preventDefault()
          window.history.replaceState(null, '', `#${encodeURIComponent(headingId)}`)
          scrollToElementId(headingId, { scrollContainerSelector })
          flashElementId(headingId, FLASH_CLASS)
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
  const resolved = resolveMarkdownImageSrc(src)
  if (resolved === null) return null
  return (
    <AuthImage
      src={resolved}
      alt={alt ?? ''}
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
      <table className={cn('w-full', className)} {...props}>
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
      className={cn('rounded-lg border border-warning/30 bg-warning/8 px-4 py-3 text-sm text-warning', className)}
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
  sourceRange,
}: MarkdownRendererProps) {
  const rehypePlugins = useMemo<React.ComponentProps<typeof ReactMarkdown>['rehypePlugins']>(
    () => [rehypeRaw, [rehypeSanitize, MARKDOWN_SANITIZE_SCHEMA], [rehypeSourceRange, { range: sourceRange }]],
    [sourceRange],
  )

  const headingsByLine = useMemo(() => {
    const byLine = new Map<number, MarkdownHeading>()
    if (enableTocAnchors) {
      for (const heading of extractMarkdownHeadings(markdown)) {
        byLine.set(heading.line, heading)
      }
    }
    return byLine
  }, [markdown, enableTocAnchors])

  useEffect(() => {
    if (!autoScrollToHash) return
    let scrollFrame: number | null = null

    function cancelHashScroll() {
      if (scrollFrame === null) return
      window.cancelAnimationFrame(scrollFrame)
      scrollFrame = null
    }

    function scheduleHashScroll(behavior: ScrollBehavior) {
      cancelHashScroll()
      const headingId = decodeHeadingId(window.location.hash)
      if (headingId === null) return
      scrollFrame = window.requestAnimationFrame(() => {
        scrollFrame = null
        if (scrollToElementId(headingId, { behavior, scrollContainerSelector })) {
          flashElementId(headingId, FLASH_CLASS)
        }
      })
    }

    const onHashChange = () => scheduleHashScroll('smooth')
    scheduleHashScroll('auto')
    window.addEventListener('hashchange', onHashChange)
    return () => {
      window.removeEventListener('hashchange', onHashChange)
      cancelHashScroll()
    }
  }, [autoScrollToHash, scrollContainerSelector, markdown])

  const runtime = useMemo<MarkdownRendererRuntime>(
    () => ({ headingsByLine, scrollContainerSelector }),
    [headingsByLine, scrollContainerSelector],
  )

  return (
    <div className={className}>
      <MarkdownRendererRuntimeContext.Provider value={runtime}>
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          rehypePlugins={rehypePlugins}
          components={MARKDOWN_RENDERER_COMPONENTS}
        >
          {markdown}
        </ReactMarkdown>
      </MarkdownRendererRuntimeContext.Provider>
    </div>
  )
}

export const MarkdownRenderer = memo(function MarkdownRenderer(props: MarkdownRendererProps) {
  return (
    <MarkdownRenderBoundary className={props.className} resetKey={props.markdown}>
      <MarkdownRendererContent {...props} />
    </MarkdownRenderBoundary>
  )
})
