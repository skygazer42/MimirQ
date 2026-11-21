'use client'

import { useState, useEffect, useRef, type RefObject } from 'react'

export function useResizeObserver<T extends HTMLElement>(ref: RefObject<T | null>) {
  const [dimensions, setDimensions] = useState({ width: 0, height: 0 })
  const observationRef = useRef<{ target: T; cleanup: () => void } | null>(null)

  // A stable ref can point to a new element after a conditional render.
  useEffect(() => {
    const observeTarget = ref.current
    if (observationRef.current?.target === observeTarget) return
    observationRef.current?.cleanup()
    observationRef.current = null
    if (!observeTarget) return

    let rafId: number | null = null
    const rect = observeTarget.getBoundingClientRect()
    let pending: { width: number; height: number } = rect

    const commit = (width: number, height: number) => {
      if (width <= 0 || height <= 0) return
      setDimensions((prev) => (prev.width === width && prev.height === height ? prev : { width, height }))
    }

    const scheduleCommit = (width: number, height: number) => {
      pending = { width, height }
      if (rafId != null) return
      rafId = requestAnimationFrame(() => {
        rafId = null
        commit(pending.width, pending.height)
      })
    }

    // Initial measure (if still 0, ResizeObserver will update later).
    commit(rect.width, rect.height)

    const resizeObserver = new ResizeObserver((entries) => {
      const entry = entries.at(-1)
      if (!entry) return
      const { width, height } = entry.contentRect
      scheduleCommit(width, height)
    })

    resizeObserver.observe(observeTarget)

    observationRef.current = {
      target: observeTarget,
      cleanup: () => {
        resizeObserver.disconnect()
        if (rafId != null) cancelAnimationFrame(rafId)
        rafId = null
      },
    }
  })

  useEffect(() => {
    return () => {
      observationRef.current?.cleanup()
      observationRef.current = null
    }
  }, [])

  return dimensions
}
