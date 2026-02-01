/**
 * BboxOverlay - lightweight bounding-box overlay for PDF pages.
 *
 * Rendering is "best-effort": callers provide a scale factor that matches the rendered PDF canvas.
 */
'use client'

import type { ParsingPosition } from '@/lib/parsing-positions'

export type BboxOverlayItem = {
  id: string
  position: ParsingPosition
}

export function BboxOverlay(props: {
  items: BboxOverlayItem[]
  scale: number
  showAll: boolean
  activeIds: Set<string>
  hoveredIds: Set<string>
  onHoverId?: (id: string | null) => void
  onClickId?: (id: string) => void
}) {
  const { items, scale, showAll, activeIds, hoveredIds, onHoverId, onClickId } = props

  return (
    <div className="pointer-events-none absolute inset-0">
      {(items || []).map((item, idx) => {
        if (!showAll && !activeIds.has(item.id) && !hoveredIds.has(item.id)) {
          return null
        }

        const { left, right, top, bottom } = item.position
        const x = Math.min(left, right) * scale
        const y = Math.min(top, bottom) * scale
        const width = Math.abs(right - left) * scale
        const height = Math.abs(bottom - top) * scale
        const isActive = activeIds.has(item.id)
        const isHovered = hoveredIds.has(item.id)

        const baseColor = isActive ? 'border-warning bg-warning/10' : 'border-primary/60'
        const hoverColor = isHovered ? 'border-primary bg-primary/10' : ''

        return (
          <button
            key={`${item.id}-${idx}`}
            type="button"
            className={`pointer-events-auto absolute rounded border ${baseColor} ${hoverColor}`}
            style={{ left: x, top: y, width, height }}
            onMouseEnter={() => onHoverId?.(item.id)}
            onMouseLeave={() => onHoverId?.(null)}
            onClick={() => onClickId?.(item.id)}
          />
        )
      })}
    </div>
  )
}

