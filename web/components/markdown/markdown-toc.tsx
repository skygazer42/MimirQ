'use client'

import { memo, useMemo } from 'react'

import { cn } from '@/lib/utils'
import { extractMarkdownHeadings, flashElementId, scrollToElementId } from '@/lib/markdown'

const FLASH_CLASS = 'bg-primary/10 ring-1 ring-primary/25 rounded-md transition-colors'

export const MarkdownToc = memo(function MarkdownToc({
  markdown,
  className,
  title = '目录',
  maxDepth = 4,
  onNavigate,
}: {
  markdown: string
  className?: string
  title?: string
  maxDepth?: number
  onNavigate?: (id: string) => void
}) {
  const headings = useMemo(
    () => extractMarkdownHeadings(markdown || '', { maxDepth }),
    [markdown, maxDepth]
  )

  if (!headings.length) return null

  const navigate = (id: string) => {
    if (!id) return
    if (onNavigate) {
      onNavigate(id)
      return
    }
    if (typeof window !== 'undefined') {
      window.history.replaceState(null, '', `#${encodeURIComponent(id)}`)
    }
    scrollToElementId(id)
    flashElementId(id, FLASH_CLASS)
  }

  return (
    <nav className={cn('text-sm', className)} aria-label="Table of contents">
      <div className="text-xs font-semibold text-muted-foreground  uppercase">
        {title}
      </div>
      <ul className="mt-2 space-y-1">
        {headings.map((h) => (
          <li key={h.id}>
            <button
              type="button"
              onClick={() => navigate(h.id)}
              className={cn(
                'w-full text-left text-[13px] leading-5 truncate',
                'text-muted-foreground hover:text-primary'
              )}
              style={{ paddingLeft: `${Math.max(0, h.level - 1) * 12}px` }}
              title={h.text}
            >
              {h.text}
            </button>
          </li>
        ))}
      </ul>
    </nav>
  )
})
