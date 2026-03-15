'use client'

import { memo, useEffect, useMemo, useRef } from 'react'
import type * as React from 'react'
import Image from 'next/image'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import rehypeRaw from 'rehype-raw'
import rehypeSanitize, { defaultSchema } from 'rehype-sanitize'
import type { Options as RehypeSanitizeOptions } from 'rehype-sanitize'

import { cn } from '@/lib/utils'
import { API_BASE_URL, toAbsoluteBackendUrl } from '@/lib/env'
import { extractMarkdownHeadings, flashElementId, scrollToElementId } from '@/lib/markdown'
import { getAccessToken, getTenantId } from '@/lib/auth-storage'

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
}

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

export const MarkdownRenderer = memo(function MarkdownRenderer({
  markdown,
  className,
  enableTocAnchors = true,
  autoScrollToHash = false,
}: Readonly<{
  markdown: string
  className?: string
  enableTocAnchors?: boolean
  autoScrollToHash?: boolean
}>) {
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
    if (typeof globalThis.window === 'undefined') return

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
          className={cn('group scroll-mt-24', props.className)}
          {...props}
        >
          {children}
          {enableTocAnchors && id && (
            <a
              href={`#${encodeURIComponent(id)}`}
              onClick={(e) => {
                e.preventDefault()
                if (typeof globalThis.window !== 'undefined') {
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
            if (rawHref.startsWith('#')) {
              const id = rawHref.slice(1)
              return (
                <a
                  href={rawHref}
                  onClick={(e) => {
                    e.preventDefault()
                    const decoded = id ? decodeURIComponent(id) : ''
                    if (!decoded) return
                    if (typeof globalThis.window !== 'undefined') {
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
                href={rawHref}
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
                className="my-2 w-full h-auto max-h-96 object-contain rounded-lg border border-border/70 bg-card shadow-sm"
              />
            )
          },
          table: ({ node, className, children, ...props }) => (
            <div className="my-4 overflow-x-auto">
              <table className={cn('w-full', className)} {...props}>
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
})
