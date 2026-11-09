'use client'

import { useLayoutEffect, useState, type CSSProperties, type RefObject } from 'react'

export type DropdownSide = 'top' | 'bottom'

type DropdownPlacementOptions = {
  side: DropdownSide
  align?: 'start' | 'end'
  minWidth?: number
  maxHeight?: number
  onOpenChange: (open: boolean) => void
}

type DropdownPlacement = {
  side: DropdownSide
  maxHeight: number
  style: CSSProperties
}

export function useDropdownPlacement(
  open: boolean,
  triggerRef: RefObject<HTMLButtonElement | null>,
  { side, align = 'start', minWidth = 360, maxHeight = 420, onOpenChange }: DropdownPlacementOptions
) {
  const [placement, setPlacement] = useState<DropdownPlacement | null>(null)

  useLayoutEffect(() => {
    if (!open) return
    let frame = 0

    function updatePlacement() {
      const rect = triggerRef.current?.getBoundingClientRect()
      if (!rect) return
      const viewportWidth = document.documentElement.clientWidth
      const viewportHeight = window.innerHeight
      if (rect.bottom <= 0 || rect.top >= viewportHeight || rect.right <= 0 || rect.left >= viewportWidth) {
        onOpenChange(false)
        return
      }

      const padding = 12
      const gap = 8
      const above = Math.max(0, rect.top - padding - gap)
      const below = Math.max(0, viewportHeight - rect.bottom - padding - gap)
      // A preferred top menu may shrink to a useful scrollable height before flipping.
      const upward = side === 'top'
        ? above >= Math.min(160, maxHeight) || above > below
        : below < maxHeight && above > below
      const availableHeight = upward ? above : below
      const width = Math.min(Math.max(rect.width, minWidth), Math.max(0, viewportWidth - padding * 2))
      const alignedLeft = align === 'end' ? rect.right - width : rect.left
      const left = Math.max(padding, Math.min(alignedLeft, viewportWidth - padding - width))
      const height = Math.max(0, Math.min(maxHeight, Math.floor(availableHeight)))

      setPlacement({
        side: upward ? 'top' : 'bottom',
        maxHeight: height,
        style: {
          left,
          width,
          maxHeight: height,
          ...(upward
            ? { bottom: viewportHeight - rect.top + gap }
            : { top: rect.bottom + gap }),
        },
      })
    }

    function schedulePlacement() {
      cancelAnimationFrame(frame)
      frame = requestAnimationFrame(updatePlacement)
    }

    updatePlacement()
    window.addEventListener('resize', schedulePlacement)
    window.addEventListener('scroll', schedulePlacement, true)
    return () => {
      cancelAnimationFrame(frame)
      window.removeEventListener('resize', schedulePlacement)
      window.removeEventListener('scroll', schedulePlacement, true)
    }
  }, [open, triggerRef, side, align, minWidth, maxHeight, onOpenChange])

  return placement
}
