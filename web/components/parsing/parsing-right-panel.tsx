'use client'

import { useCallback, useRef, useState } from 'react'
import type { AriaAttributes, ReactNode, PointerEvent as ReactPointerEvent, MouseEvent as ReactMouseEvent } from 'react'

import { cn } from '@/lib/utils'

type ParsingRightPanelProps = Pick<AriaAttributes, 'aria-busy' | 'aria-label'> & {
  children: ReactNode
  className?: string
  dragScroll?: boolean
}

type DragState = {
  pointerId: number
  startX: number
  startY: number
  startScrollLeft: number
  startScrollTop: number
  moved: boolean
}

export function ParsingRightPanel({
  children,
  className,
  dragScroll = false,
  ...props
}: Readonly<ParsingRightPanelProps>) {
  const dragStateRef = useRef<DragState | null>(null)
  const suppressClickRef = useRef(false)
  const [isDragging, setIsDragging] = useState(false)

  const clearDragState = useCallback(() => {
    dragStateRef.current = null
    setIsDragging(false)
  }, [])

  const handlePointerDown = useCallback(
    (event: ReactPointerEvent<HTMLDivElement>) => {
      if (!dragScroll || event.pointerType !== 'mouse' || event.button !== 0) return
      suppressClickRef.current = false

      const { target, currentTarget: container } = event
      if (
        target instanceof Element &&
        target.closest('button, a, input, textarea, select, label, [role="button"], [data-no-drag-scroll="true"]')
      ) {
        return
      }

      dragStateRef.current = {
        pointerId: event.pointerId,
        startX: event.clientX,
        startY: event.clientY,
        startScrollLeft: container.scrollLeft,
        startScrollTop: container.scrollTop,
        moved: false,
      }

      container.setPointerCapture?.(event.pointerId)
    },
    [dragScroll],
  )

  const handlePointerMove = useCallback((event: ReactPointerEvent<HTMLDivElement>) => {
    const container = event.currentTarget
    const dragState = dragStateRef.current
    if (dragState?.pointerId !== event.pointerId) return

    const deltaX = event.clientX - dragState.startX
    const deltaY = event.clientY - dragState.startY

    if (!dragState.moved && Math.abs(deltaX) + Math.abs(deltaY) < 4) {
      return
    }

    if (!dragState.moved) {
      dragState.moved = true
      suppressClickRef.current = true
      setIsDragging(true)
    }

    container.scrollLeft = dragState.startScrollLeft - deltaX
    container.scrollTop = dragState.startScrollTop - deltaY
    event.preventDefault()
  }, [])

  const handlePointerUp = useCallback(
    (event: ReactPointerEvent<HTMLDivElement>) => {
      const dragState = dragStateRef.current
      if (dragState?.pointerId !== event.pointerId) return
      clearDragState()
    },
    [clearDragState],
  )

  const handleClickCapture = useCallback((event: ReactMouseEvent<HTMLDivElement>) => {
    if (event.detail === 0 || !suppressClickRef.current) return
    suppressClickRef.current = false
    event.preventDefault()
    event.stopPropagation()
  }, [])

  return (
    <div
      {...props}
      data-page-scroll-container="true"
      data-drag-scroll={dragScroll ? 'enabled' : 'disabled'}
      className={cn(
        'min-h-0 min-w-0 overflow-y-auto overscroll-contain',
        dragScroll && 'cursor-grab',
        dragScroll && isDragging && 'cursor-grabbing select-none',
        className,
      )}
      onPointerDown={handlePointerDown}
      onPointerMove={handlePointerMove}
      onPointerUp={handlePointerUp}
      onPointerCancel={() => {
        suppressClickRef.current = false
        clearDragState()
      }}
      onLostPointerCapture={clearDragState}
      onClickCapture={handleClickCapture}
    >
      {children}
    </div>
  )
}
