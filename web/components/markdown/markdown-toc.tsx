'use client'

import { memo, useMemo, useState, useEffect, useRef, useCallback } from 'react'

import { cn } from '@/lib/utils'
import { extractMarkdownHeadings, flashElementId, scrollToElementId } from '@/lib/markdown'

const FLASH_CLASS = 'bg-primary/10 ring-1 ring-primary/25 rounded-md transition-colors'

function useScrollSpy(
  headingIds: string[],
  scrollContainerSelector?: string
): string | null {
  const [activeId, setActiveId] = useState<string | null>(null)
  const skipNextScrollRef = useRef(false)

  const skipScrollSpy = useCallback(() => {
    skipNextScrollRef.current = true
    const timer = globalThis.window?.setTimeout(() => {
      skipNextScrollRef.current = false
    }, 600)
    return () => globalThis.window?.clearTimeout(timer)
  }, [])

  useEffect(() => {
    if (typeof IntersectionObserver === 'undefined' || headingIds.length === 0) return

    const root = scrollContainerSelector
      ? document.querySelector(scrollContainerSelector)
      : null

    const observer = new IntersectionObserver(
      (entries) => {
        if (skipNextScrollRef.current) return

        const visible = entries
          .filter((e) => e.isIntersecting)
          .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)

        if (visible.length > 0) {
          setActiveId(visible[0].target.id)
        }
      },
      {
        root: root ?? undefined,
        rootMargin: '-10% 0px -70% 0px',
        threshold: 0,
      }
    )

    const elements: Element[] = []
    for (const id of headingIds) {
      const el = document.getElementById(id)
      if (el) {
        observer.observe(el)
        elements.push(el)
      }
    }

    return () => {
      for (const el of elements) observer.unobserve(el)
      observer.disconnect()
    }
  }, [headingIds, scrollContainerSelector])

  return activeId
}

export const MarkdownToc = memo(function MarkdownToc({
  markdown,
  className,
  title = '目录',
  maxDepth = 4,
  onNavigate,
  scrollContainerSelector,
}: Readonly<{
  markdown: string
  className?: string
  title?: string
  maxDepth?: number
  onNavigate?: (id: string) => void
  scrollContainerSelector?: string
}>) {
  const headings = useMemo(
    () => extractMarkdownHeadings(markdown || '', { maxDepth }),
    [markdown, maxDepth]
  )

  const headingIds = useMemo(() => headings.map((h) => h.id), [headings])
  const activeId = useScrollSpy(headingIds, scrollContainerSelector)
  const activeItemRef = useRef<HTMLLIElement | null>(null)

  useEffect(() => {
    activeItemRef.current?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
  }, [activeId])

  if (!headings.length) return null

  const navigate = (id: string) => {
    if (!id) return
    if (onNavigate) {
      onNavigate(id)
      return
    }
    if (globalThis.window !== undefined) {
      globalThis.window.history.replaceState(null, '', `#${encodeURIComponent(id)}`)
    }
    scrollToElementId(id)
    flashElementId(id, FLASH_CLASS)
  }

  return (
    <nav className={cn('text-sm', className)} aria-label="Table of contents">
      <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
        {title}
      </div>
      <ul className="mt-2 space-y-0.5">
        {headings.map((h) => {
          const isActive = activeId === h.id
          return (
            <li key={h.id} ref={isActive ? activeItemRef : undefined}>
              <button
                type="button"
                onClick={() => navigate(h.id)}
                className={cn(
                  'w-full text-left text-[13px] leading-5 truncate rounded-md px-1.5 py-0.5 transition-colors',
                  isActive
                    ? 'text-primary font-medium bg-primary/5'
                    : 'text-muted-foreground hover:text-foreground hover:bg-muted/50'
                )}
                style={{ paddingLeft: `${Math.max(0, h.level - 1) * 12 + 6}px` }}
                title={h.text}
              >
                {h.text}
              </button>
            </li>
          )
        })}
      </ul>
    </nav>
  )
})
