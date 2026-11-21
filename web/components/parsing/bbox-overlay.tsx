/** Physical PDF annotations retain their identity independently of logical selection. */
'use client'

import { getParsingLayoutMeta, type ParsingLayoutKind } from '@/lib/parsing-layout'
import type { ParsingEditFocusHint } from '@/lib/parsing-edit-focus'
import { computePdfOverlayRect, detectPdfBboxCoordinateSpace } from '@/lib/pdf-bbox'
import { cn } from '@/lib/utils'
import type { ParsingPosition } from '@/lib/parsing-positions'

export type BboxOverlayItem = {
  id: string
  kind?: ParsingLayoutKind
  position: ParsingPosition
}

type BboxOverlayProps = {
  items: readonly BboxOverlayItem[]
  scale: number
  pageBaseWidth: number
  pageBaseHeight: number
  showAll: boolean
  activeIds: ReadonlySet<string>
  hoveredIds: ReadonlySet<string>
  onHoverId?: (id: string | null) => void
  onClickId?: (id: string, hint?: ParsingEditFocusHint) => void
}

export function BboxOverlay({
  items,
  scale,
  pageBaseWidth,
  pageBaseHeight,
  showAll,
  activeIds,
  hoveredIds,
  onHoverId,
  onClickId,
}: Readonly<BboxOverlayProps>) {
  const coordinateSpace = detectPdfBboxCoordinateSpace({ items, pageBaseWidth, pageBaseHeight })
  const seen = new Set<string>()

  return (
    <div className="pointer-events-none absolute inset-0">
      {items.map((item) => {
        if (!showAll && !activeIds.has(item.id) && !hoveredIds.has(item.id)) return null
        const position = item.position
        const key = JSON.stringify([
          item.id,
          Math.min(position.left, position.right),
          Math.max(position.left, position.right),
          Math.min(position.top, position.bottom),
          Math.max(position.top, position.bottom),
        ])
        if (seen.has(key)) return null
        seen.add(key)
        const rect = computePdfOverlayRect({ position, scale, pageBaseWidth, pageBaseHeight, coordinateSpace })
        const isActive = activeIds.has(item.id)
        const isHovered = hoveredIds.has(item.id)
        const layoutMeta = item.kind === undefined ? null : getParsingLayoutMeta(item.kind)
        const attributes = {
          'data-bbox-overlay-id': item.id,
          'data-bbox-overlay-active': isActive ? 'true' : undefined,
          title: layoutMeta === null ? '文档区域' : layoutMeta.label,
          className: cn(
            'absolute rounded border transition-[box-shadow,transform,border-color,background-color] duration-150 ease-out',
            onHoverId === undefined && onClickId === undefined ? 'pointer-events-none' : 'pointer-events-auto',
            layoutMeta === null ? 'border-border bg-muted/10' : layoutMeta.overlayClassName,
            isHovered && 'z-10 ring-2 ring-primary/20',
            isActive &&
              'z-20 border-primary bg-primary/15 ring-4 ring-primary/40 shadow-[0_0_0_2px_hsl(var(--background))]',
          ),
          style: { left: rect.left, top: rect.top, width: rect.width, height: rect.height },
          onMouseEnter: onHoverId === undefined ? undefined : () => onHoverId(item.id),
          onMouseLeave: onHoverId === undefined ? undefined : () => onHoverId(null),
        }
        if (onClickId === undefined) return <span key={key} {...attributes} />
        return (
          <button
            key={key}
            type="button"
            {...attributes}
            onClick={(event) => {
              if (event.detail === 0) {
                onClickId(item.id)
                return
              }
              const bounds = event.currentTarget.getBoundingClientRect()
              onClickId(item.id, {
                xRatio: Math.max(0, Math.min(1, (event.clientX - bounds.left) / bounds.width)),
                yRatio: Math.max(0, Math.min(1, (event.clientY - bounds.top) / bounds.height)),
              })
            }}
          />
        )
      })}
    </div>
  )
}
