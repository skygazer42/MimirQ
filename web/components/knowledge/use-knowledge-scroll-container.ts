'use client'

import { useEffect, useRef, useState } from 'react'

type KnowledgeScrollContainer = {
  /**
   * Mount this sentinel inside the main pane subtree so we can resolve the
   * correct internal scroll container via `.closest(...)`.
   */
  sentinelRef: React.RefObject<HTMLDivElement | null>
  scrollEl: HTMLElement | null
}

export function useKnowledgeScrollContainer(): KnowledgeScrollContainer {
  const sentinelRef = useRef<HTMLDivElement | null>(null)
  const [scrollEl, setScrollEl] = useState<HTMLElement | null>(null)

  useEffect(() => {
    const node = sentinelRef.current
    if (!node) return
    const el = node.closest<HTMLElement>('[data-page-scroll-container="true"]')
    if (!el) return
    setScrollEl(el)
  }, [])

  return { sentinelRef, scrollEl }
}

