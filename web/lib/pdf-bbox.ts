import type { ParsingPosition } from '@/lib/parsing-positions'

export type PdfBboxCoordinateSpace = 'absolute' | 'normalized-1000'

export interface PdfOverlayRect {
  left: number
  top: number
  width: number
  height: number
}

function isFinitePositive(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value) && value > 0
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value)
}

export function detectPdfBboxCoordinateSpace(params: {
  items: Array<{ position: ParsingPosition }>
  pageBaseWidth?: number | null
  pageBaseHeight?: number | null
}): PdfBboxCoordinateSpace {
  const { items, pageBaseWidth, pageBaseHeight } = params
  if (!isFinitePositive(pageBaseWidth) || !isFinitePositive(pageBaseHeight)) {
    return 'absolute'
  }

  for (const item of items || []) {
    const position = item?.position
    if (!position) continue

    const maxX = Math.max(position.left, position.right)
    const maxY = Math.max(position.top, position.bottom)
    if (maxX > pageBaseWidth + 1 || maxY > pageBaseHeight + 1) {
      return 'normalized-1000'
    }
  }

  return 'absolute'
}

export function computePdfOverlayRect(params: {
  position: ParsingPosition
  scale: number
  pageBaseWidth?: number | null
  pageBaseHeight?: number | null
  coordinateSpace?: PdfBboxCoordinateSpace
}): PdfOverlayRect {
  const { position, scale, pageBaseWidth, pageBaseHeight } = params
  const coordinateSpace = params.coordinateSpace || 'absolute'

  const left = Math.min(position.left, position.right)
  const right = Math.max(position.left, position.right)
  const top = Math.min(position.top, position.bottom)
  const bottom = Math.max(position.top, position.bottom)

  if (
    coordinateSpace === 'normalized-1000' &&
    isFinitePositive(pageBaseWidth) &&
    isFinitePositive(pageBaseHeight) &&
    isFinitePositive(scale)
  ) {
    const renderedWidth = pageBaseWidth * scale
    const renderedHeight = pageBaseHeight * scale
    return {
      left: (left / 1000) * renderedWidth,
      top: (top / 1000) * renderedHeight,
      width: ((right - left) / 1000) * renderedWidth,
      height: ((bottom - top) / 1000) * renderedHeight,
    }
  }

  const resolvedScale = isFinitePositive(scale) ? scale : 1
  return {
    left: left * resolvedScale,
    top: top * resolvedScale,
    width: (right - left) * resolvedScale,
    height: (bottom - top) * resolvedScale,
  }
}

export function computePdfOverlayScrollTop(params: {
  containerHeight: number
  containerScrollTop: number
  containerTop: number
  overlayHeight: number
  overlayTop: number
  pageTop: number
}): number {
  const {
    containerHeight,
    containerScrollTop,
    containerTop,
    overlayHeight,
    overlayTop,
    pageTop,
  } = params

  if (
    !isFiniteNumber(containerHeight) ||
    !isFiniteNumber(containerScrollTop) ||
    !isFiniteNumber(containerTop) ||
    !isFiniteNumber(overlayHeight) ||
    !isFiniteNumber(overlayTop) ||
    !isFiniteNumber(pageTop)
  ) {
    return 0
  }

  const pageTopInContainer = containerScrollTop + (pageTop - containerTop)
  const overlayCenter = pageTopInContainer + overlayTop + overlayHeight / 2
  return Math.max(0, Math.round(overlayCenter - containerHeight / 2))
}
