'use client'

import { useEffect, useMemo, useRef } from 'react'
import Image from 'next/image'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

import { cn } from '@/lib/utils'
import { toAbsoluteBackendUrl } from '@/lib/env'
import { extractMarkdownHeadings, flashElementId, scrollToElementId } from '@/lib/markdown'

const FLASH_CLASS =
  'bg-indigo-50 dark:bg-indigo-900/20 ring-1 ring-indigo-200 dark:ring-indigo-700 rounded-md transition-colors'

export function MarkdownRenderer({
  markdown,
  className,
  enableTocAnchors = true,
  autoScrollToHash = false,
}: {
  markdown: string
  className?: string
  enableTocAnchors?: boolean
  autoScrollToHash?: boolean
}) {
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
    if (typeof window === 'undefined') return

    const scrollNow = (behavior: ScrollBehavior) => {
      const raw = window.location.hash || ''
      const id = raw.startsWith('#') ? raw.slice(1) : raw
      const decoded = id ? decodeURIComponent(id) : ''
      if (!decoded) return
      window.requestAnimationFrame(() => {
        const ok = scrollToElementId(decoded, { behavior })
        if (ok) flashElementId(decoded, FLASH_CLASS)
      })
    }

    const onHashChange = () => scrollNow('smooth')

    scrollNow('auto')
    window.addEventListener('hashchange', onHashChange)
    return () => window.removeEventListener('hashchange', onHashChange)
  }, [autoScrollToHash, text])

  const headingComponent = (level: 1 | 2 | 3 | 4 | 5 | 6) => {
    const Tag = (`h${level}` as unknown) as keyof JSX.IntrinsicElements
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
                if (typeof window !== 'undefined') {
                  window.history.replaceState(null, '', `#${encodeURIComponent(id)}`)
                }
                scrollToElementId(id)
                flashElementId(id, FLASH_CLASS)
              }}
              className="ml-2 no-underline text-slate-400 hover:text-slate-600 opacity-0 group-hover:opacity-100"
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
                    if (typeof window !== 'undefined') {
                      window.history.replaceState(null, '', `#${encodeURIComponent(decoded)}`)
                    }
                    scrollToElementId(decoded)
                    flashElementId(decoded, FLASH_CLASS)
                  }}
                  className="underline decoration-slate-300 underline-offset-2 hover:decoration-slate-500"
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
                className="underline decoration-slate-300 underline-offset-2 hover:decoration-slate-500"
              >
                {children}
              </a>
            )
          },
          img: ({ src, alt }) => {
            const raw = typeof src === 'string' ? src : ''
            const resolved = raw
              ? raw.startsWith('http')
                ? raw
                : toAbsoluteBackendUrl(raw)
              : ''
            if (!resolved) return null
            return (
              <Image
                src={resolved}
                alt={alt || 'image'}
                width={1200}
                height={800}
                unoptimized
                className="my-2 w-full h-auto max-h-96 object-contain rounded-lg border border-slate-200/70 dark:border-slate-700 bg-white dark:bg-slate-900"
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
}

