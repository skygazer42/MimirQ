'use client'

import { memo, useState, useEffect, useRef } from 'react'

import { cn } from '@/lib/utils'
import { flashElementId, scrollToElementId, type MarkdownHeading } from '@/lib/markdown'

const FLASH_CLASS = 'bg-primary/10 ring-1 ring-primary/25 rounded-md transition-colors'

function useScrollSpy(headings: readonly MarkdownHeading[]): string | null {
  const [activeId, setActiveId] = useState<string | null>(null)

  useEffect(() => {
    if (typeof IntersectionObserver === 'undefined') return

    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((entry) => entry.isIntersecting)
          .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)

        if (visible.length > 0) {
          setActiveId(visible[0].target.id)
        }
      },
      { rootMargin: '-10% 0px -70% 0px' },
    )

    for (const { id } of headings) {
      const headingElement = document.getElementById(id)
      if (headingElement !== null) observer.observe(headingElement)
    }

    return () => observer.disconnect()
  }, [headings])

  return activeId
}

export const MarkdownToc = memo(function MarkdownToc({ headings }: Readonly<{ headings: readonly MarkdownHeading[] }>) {
  const activeId = useScrollSpy(headings)
  const activeItemRef = useRef<HTMLLIElement | null>(null)

  useEffect(() => {
    activeItemRef.current?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
  }, [activeId])

  function navigateToHeading(headingId: string) {
    window.history.replaceState(null, '', `#${encodeURIComponent(headingId)}`)
    scrollToElementId(headingId)
    flashElementId(headingId, FLASH_CLASS)
  }

  return (
    <nav className="text-sm" aria-label="Table of contents">
      <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-muted-foreground/70">目录</div>
      <ul className="mt-2 space-y-0.5">
        {headings.map((heading) => {
          const isActive = activeId === heading.id
          return (
            <li key={heading.id} ref={isActive ? activeItemRef : undefined}>
              <button
                type="button"
                onClick={() => navigateToHeading(heading.id)}
                className={cn(
                  'w-full text-left text-[13px] leading-5 truncate rounded-md px-1.5 py-0.5 transition-colors',
                  isActive
                    ? 'font-medium text-foreground'
                    : 'text-muted-foreground hover:text-foreground hover:bg-muted/35',
                )}
                style={{ paddingLeft: `${(heading.level - 1) * 12 + 6}px` }}
                title={heading.text}
              >
                {heading.text}
              </button>
            </li>
          )
        })}
      </ul>
    </nav>
  )
})
