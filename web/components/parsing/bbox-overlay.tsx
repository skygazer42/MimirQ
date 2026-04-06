/**
 * BboxOverlay - lightweight bounding-box overlay for PDF pages.
 *
 * Rendering is "best-effort": callers provide a scale factor that matches the rendered PDF canvas.
 */
'use client'

import { getParsingLayoutMeta, type ParsingLayoutKind } from '@/lib/parsing-layout'
import { computePdfOverlayRect, detectPdfBboxCoordinateSpace } from '@/lib/pdf-bbox'
import { cn } from '@/lib/utils'
import type { ParsingPosition } from '@/lib/parsing-positions'

export type BboxOverlayItem = {
  id: string
  kind?: ParsingLayoutKind
  position: ParsingPosition
}

export function BboxOverlay(props: Readonly<{
  items: BboxOverlayItem[]
  scale: number
  pageBaseWidth?: number | null
  pageBaseHeight?: number | null
  showAll: boolean
  activeIds: Set<string>
  hoveredIds: Set<string>
  onHoverId?: (id: string | null) => void
  onClickId?: (id: string) => void
}>) {
  const { items, scale, pageBaseWidth, pageBaseHeight, showAll, activeIds, hoveredIds, onHoverId, onClickId } = props
  const coordinateSpace = detectPdfBboxCoordinateSpace({
    items,
    pageBaseWidth,
    pageBaseHeight,
  })

  return (
    <div className="pointer-events-none absolute inset-0">
      {(items || []).map((item, idx) => {
        if (!showAll && !activeIds.has(item.id) && !hoveredIds.has(item.id)) {
          return null
        }

        const rect = computePdfOverlayRect({
          position: item.position,
          scale,
          pageBaseWidth,
          pageBaseHeight,
          coordinateSpace,
        })
        const isActive = activeIds.has(item.id)
        const isHovered = hoveredIds.has(item.id)
        const layoutMeta = getParsingLayoutMeta(item.kind || 'paragraph')

        return (
          <button
            key={item.id}
            type="button"
            title={layoutMeta.label}
            className={cn(
              'pointer-events-auto absolute rounded border transition-[box-shadow,transform,border-color,background-color] duration-150 ease-out',
              layoutMeta.overlayClassName,
              isHovered && 'z-10 ring-2 ring-primary/20',
              isActive && 'z-20 ring-2 ring-primary/35 shadow-[0_0_0_1px_hsl(var(--background))]'
            )}
            style={{ left: rect.left, top: rect.top, width: rect.width, height: rect.height }}
            onMouseEnter={() => onHoverId?.(item.id)}
            onMouseLeave={() => onHoverId?.(null)}
            onClick={() => onClickId?.(item.id)}
          />
        )
      })}
    </div>
  )
}
