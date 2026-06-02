'use client'

import { useState, useEffect, RefObject } from 'react'

export function useResizeObserver<T extends HTMLElement>(ref: RefObject<T | null>) {
  const [dimensions, setDimensions] = useState({ width: 0, height: 0 })

  useEffect(() => {
    const observeTarget = ref.current
    if (!observeTarget) return

    let rafId: number | null = null
    let pending: { width: number; height: number } | null = null

    const commit = (width: number, height: number) => {
      if (width <= 0 || height <= 0) return
      setDimensions((prev) =>
        prev.width === width && prev.height === height ? prev : { width, height }
      )
    }

    const scheduleCommit = (width: number, height: number) => {
      pending = { width, height }
      if (rafId != null) return
      rafId = requestAnimationFrame(() => {
        rafId = null
        if (!pending) return
        commit(pending.width, pending.height)
        pending = null
      })
    }

    // Initial measure (if still 0, ResizeObserver will update later).
    const rect = observeTarget.getBoundingClientRect()
    commit(rect.width, rect.height)

    const resizeObserver = new ResizeObserver((entries) => {
      const entry = entries.at(-1)
      if (!entry) return
      const { width, height } = entry.contentRect
      scheduleCommit(width, height)
    })

    resizeObserver.observe(observeTarget)

    return () => {
      resizeObserver.disconnect()
      if (rafId != null) cancelAnimationFrame(rafId)
      rafId = null
      pending = null
    }
  }, [ref])

  return dimensions
}
