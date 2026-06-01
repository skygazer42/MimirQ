'use client'

import dynamic from 'next/dynamic'
import { Component, useRef, useEffect, useState, forwardRef, useImperativeHandle, useCallback, useMemo } from 'react'
import type { ForceGraphMethods } from 'react-force-graph-2d'
import { useTheme } from 'next-themes'
import type { GraphEndpointRef, GraphLinkLike, GraphNodeLike } from '@/app/graph/graph-page-utils'
import { useResizeObserver } from '@/hooks/use-resize-observer'
import { getCssHslColor, getCssHslaColor } from '@/lib/css-vars'
import { decorateLinksForDisplay } from '@/lib/graph-edge-display'
import { buildGraphLinkProvenanceTooltipHtml } from '@/lib/graph-provenance'
import { buildGraphViewportLod, type GraphViewportLod, type GraphViewportRect } from '@/lib/graph-viewport-lod'
import { GraphMinimap } from './graph-minimap'
import { Loader2 } from 'lucide-react'

export const NODE_COLOR_PALETTE = [
  '#ccfeff', '#8ed8ff', '#6fb7ff', '#79c7c5', '#8fd3a8',
  '#b8df8a', '#f2d27b', '#f5b97a', '#c6c9ff', '#9bb5ff',
  '#a6e7ff', '#7fd9f3', '#5cc7de', '#6ebfd1', '#82cfff',
  '#b6e4ff', '#c7f1e0', '#def5c8', '#ffe6b6', '#e2dcff',
  '#c2d8ff', '#9bd1ff', '#8adfd8', '#a7c4ff',
]
export const EVENT_COLOR = '#8ea2ff'

export const EDGE_KIND_COLORS: Record<string, string> = {
  entity_relation: '#3b82f6', // blue
  event_entity: '#a855f7', // purple
  entity_entity: '#22d3ee', // cyan
}

function clamp01(value: number): number {
  if (!Number.isFinite(value)) return 0
  return Math.min(1, Math.max(0, value))
}

type GraphNodeDatum = GraphNodeLike & {
  id: string
  label: string
  color?: string
  group?: number
  x?: number
  y?: number
  z?: number
  fx?: number | null
  fy?: number | null
  fz?: number | null
}

type GraphLinkDatum = GraphLinkLike & {
  source: GraphEndpointRef | GraphNodeDatum
  target: GraphEndpointRef | GraphNodeDatum
  color?: string
  curvature?: number
  curveRotation?: number
  isSelfLoop?: boolean
}

type GraphRenderData = Readonly<{
  nodes: GraphNodeDatum[]
  links: GraphLinkDatum[]
}>

type GraphEndpointObject = {
  id?: string | number | null
  x?: number
  y?: number
  z?: number
}

type GraphCanvasPalette = {
  edgeLabelBg: string
  edgeLabelHoverText: string
  edgeLabelText: string
  labelDim: string
  labelFill: string
}

type LinkLabelRenderState = {
  startNode: GraphEndpointObject
  endNode: GraphEndpointObject
  label: string
  isPathLink: boolean
  isHoveredLink: boolean
  isAccent: boolean
}

type LinkLabelLayout = {
  textPos: { x: number; y: number }
  textAngle: number
  textWidth: number
  fontSize: number
}

type GraphNodeRenderState = {
  node: GraphNodeDatum
  label: string
  fontSize: number
  color: string
  degree: number
  coreRadius: number
  shellRadius: number
  nx: number
  ny: number
  labelDirection: number
  isHighlighted: boolean
  isPathNode: boolean
  isSelected: boolean
  isHovered: boolean
  isDimmed: boolean
  emphasis: boolean
  isDark: boolean
  globalScale: number
}

function graphDisplayString(value: unknown): string {
  if (typeof value === 'string') return value.trim()
  if (
    typeof value === 'number' ||
    typeof value === 'boolean' ||
    typeof value === 'bigint'
  ) {
    return String(value)
  }
  return ''
}

function firstGraphDisplayString(...values: unknown[]): string {
  for (const value of values) {
    const label = graphDisplayString(value)
    if (label) return label
  }
  return ''
}

function graphEndpointId(endpoint: unknown): string {
  if (endpoint && typeof endpoint === 'object' && 'id' in endpoint) {
    return firstGraphDisplayString((endpoint as GraphEndpointObject).id)
  }
  return firstGraphDisplayString(endpoint)
}

function isGraphEndpointObject(value: unknown): value is GraphEndpointObject {
  return Boolean(value) && typeof value === 'object'
}

function getLinkKind(link: GraphLinkDatum): string {
  return firstGraphDisplayString(link?.meta?.kind, link?.kind)
}

function getLinkConfidence(link: GraphLinkDatum): number | null {
  const raw = link?.meta?.confidence ?? link?.confidence ?? link?.weight
  const num = Number(raw)
  return Number.isFinite(num) ? num : null
}

function getStableLinkId(link: GraphLinkDatum | null | undefined, index?: number): string {
  if (typeof link?.id === 'string' && link.id.trim()) return link.id
  if (typeof link?.id === 'number') return String(link.id)
  if (typeof link?.index === 'number' && Number.isFinite(link.index)) return `link-${link.index}`
  if (typeof index === 'number' && Number.isFinite(index)) return `link-${index}`
  return ''
}

function areStringSetsEqual(left: ReadonlySet<string>, right: ReadonlySet<string>): boolean {
  if (left.size !== right.size) return false
  for (const value of left) {
    if (!right.has(value)) return false
  }
  return true
}

function areViewportLodsEqual(left: GraphViewportLod | null, right: GraphViewportLod | null): boolean {
  if (left === right) return true
  if (!left || !right) return false
  return (
    left.tier === right.tier &&
    left.hiddenNodeCount === right.hiddenNodeCount &&
    left.hiddenLinkCount === right.hiddenLinkCount &&
    areStringSetsEqual(left.visibleNodeIds, right.visibleNodeIds) &&
    areStringSetsEqual(left.visibleLinkIds, right.visibleLinkIds)
  )
}

function confidenceToWidth(confidence: number | null, opts: { isLargeGraph: boolean }): number {
  // Map [0..1] -> stroke width. Keep this bounded so large graphs remain readable.
  const isLargeGraph = Boolean(opts?.isLargeGraph)
  const c = confidence == null ? 0.55 : clamp01(confidence)
  const base = isLargeGraph ? 0.45 : 0.75
  const span = isLargeGraph ? 1.35 : 2.25
  return base + c * span
}

type RgbColor = { r: number; g: number; b: number }

function parseColorToRgb(color: string): RgbColor | null {
  const value = String(color || '').trim()
  if (!value) return null

  const hex = value.replace('#', '')
  if (/^[\da-fA-F]{3}$/.test(hex)) {
    return {
      r: Number.parseInt(hex[0] + hex[0], 16),
      g: Number.parseInt(hex[1] + hex[1], 16),
      b: Number.parseInt(hex[2] + hex[2], 16),
    }
  }

  if (/^[\da-fA-F]{6}$/.test(hex)) {
    return {
      r: Number.parseInt(hex.slice(0, 2), 16),
      g: Number.parseInt(hex.slice(2, 4), 16),
      b: Number.parseInt(hex.slice(4, 6), 16),
    }
  }

  const rgbMatch = /rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)/i.exec(value)
  if (!rgbMatch) return null

  return {
    r: Number(rgbMatch[1]),
    g: Number(rgbMatch[2]),
    b: Number(rgbMatch[3]),
  }
}

export function withAlpha(color: string, alpha: number): string {
  const rgb = parseColorToRgb(color)
  if (!rgb) return color
  return `rgba(${rgb.r}, ${rgb.g}, ${rgb.b}, ${clamp01(alpha)})`
}

export function mixHexColors(color: string, target: string, amount: number): string {
  const from = parseColorToRgb(color)
  const to = parseColorToRgb(target)
  if (!from || !to) return color

  const t = clamp01(amount)
  const mix = (start: number, end: number) => Math.round(start + (end - start) * t)
  return `rgb(${mix(from.r, to.r)}, ${mix(from.g, to.g)}, ${mix(from.b, to.b)})`
}

export function truncateGraphLabel(value: unknown, maxLength = 22): string {
  const text = graphDisplayString(value)
  if (!text) return ''
  if (text.length <= maxLength) return text
  return `${text.slice(0, Math.max(1, maxLength - 1))}\u2026`
}

function traceRoundRect(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  width: number,
  height: number,
  radius: number
): void {
  const r = Math.max(0, Math.min(radius, width / 2, height / 2))
  ctx.beginPath()
  ctx.moveTo(x + r, y)
  ctx.lineTo(x + width - r, y)
  ctx.quadraticCurveTo(x + width, y, x + width, y + r)
  ctx.lineTo(x + width, y + height - r)
  ctx.quadraticCurveTo(x + width, y + height, x + width - r, y + height)
  ctx.lineTo(x + r, y + height)
  ctx.quadraticCurveTo(x, y + height, x, y + height - r)
  ctx.lineTo(x, y + r)
  ctx.quadraticCurveTo(x, y, x + r, y)
  ctx.closePath()
}

function hashTypeToIndex(type: string): number {
  let hash = 0
  for (let i = 0; i < type.length; i++) {
    hash = Math.trunc((hash * 31 + (type.codePointAt(i) ?? 0)) % 0x7fffffff)
  }
  return Math.abs(hash) % NODE_COLOR_PALETTE.length
}

function graphNodeRecord(node: unknown): { meta?: Record<string, unknown> | null; type?: unknown } {
  return node && typeof node === 'object' ? (node as { meta?: Record<string, unknown> | null; type?: unknown }) : {}
}

export function buildTypeColorMap(nodes: readonly unknown[]): Map<string, string> {
  const map = new Map<string, string>()
  for (const node of nodes) {
    const record = graphNodeRecord(node)
    const meta = record.meta && typeof record.meta === 'object' ? record.meta : {}
    const kind = graphDisplayString(meta.kind)
    if (kind === 'event') continue
    const type = firstGraphDisplayString(meta.type, record.type) || 'unknown'
    if (!map.has(type)) {
      map.set(type, NODE_COLOR_PALETTE[hashTypeToIndex(type)])
    }
  }
  return map
}

function graphCursorStyle(
  isPanning: boolean,
  hoveredNodeId: string | null,
  hoveredLinkId: string | null
) {
  if (isPanning) return 'grabbing'
  if (hoveredNodeId || hoveredLinkId) return 'pointer'
  return 'grab'
}

function graphNodeKind(node: GraphNodeDatum): string {
  return graphDisplayString(node?.meta?.kind)
}

function graphNodeType(node: GraphNodeDatum): string {
  return firstGraphDisplayString(node?.meta?.type, node?.type)
}

function linkEndpointIds(link: GraphLinkDatum) {
  return {
    sourceId: graphEndpointId(link.source),
    targetId: graphEndpointId(link.target),
  }
}

function endpointMatchesSelected(link: GraphLinkDatum, selectedNodeId: string) {
  const { sourceId, targetId } = linkEndpointIds(link)
  return sourceId === selectedNodeId || targetId === selectedNodeId
}

function endpointsAreHighlighted(
  link: GraphLinkDatum,
  highlightedNodeIds: ReadonlySet<string>
) {
  const { sourceId, targetId } = linkEndpointIds(link)
  return highlightedNodeIds.has(sourceId) && highlightedNodeIds.has(targetId)
}

function nodeShellAlpha(isSelected: boolean, isHovered: boolean) {
  if (isSelected) return 0.22
  if (isHovered) return 0.16
  return 0.1
}

function nodeHighlightFontSize(
  isHighlighted: boolean,
  isSelected: boolean,
  isHovered: boolean,
  globalScale: number
) {
  if (isHighlighted || isSelected || isHovered) return 11.5 / globalScale
  return 10.5 / globalScale
}

function nodeDegreeBonus(degree: number, isLargeGraph: boolean) {
  if (isLargeGraph) return Math.min(degree * 0.08, 0.7)
  return Math.min(degree * 0.18, 1.8)
}

function nodeRadii({
  degree,
  isLargeGraph,
  isHighlighted,
  isSelected,
  isHovered,
}: {
  degree: number
  isLargeGraph: boolean
  isHighlighted: boolean
  isSelected: boolean
  isHovered: boolean
}) {
  const baseRadius = isLargeGraph ? 2.7 : 3.2
  let coreRadius = baseRadius + nodeDegreeBonus(degree, isLargeGraph)
  if (isHighlighted || isSelected) coreRadius += 0.9
  if (isHovered) coreRadius += 0.45
  return {
    coreRadius,
    shellRadius: coreRadius + (isLargeGraph ? 1.05 : 1.55),
  }
}

function shouldDimNode({
  hasHighlightedNodes,
  hasHighlightedLinks,
  isHighlighted,
  selectedNodeId,
  isLargeGraph,
  isSelected,
  isNeighbor,
}: {
  hasHighlightedNodes: boolean
  hasHighlightedLinks: boolean
  isHighlighted: boolean
  selectedNodeId: string | null
  isLargeGraph: boolean
  isSelected: boolean
  isNeighbor: boolean
}) {
  const dimmedByPath = (hasHighlightedNodes || hasHighlightedLinks) && !isHighlighted
  const dimmedBySelection = Boolean(
    selectedNodeId && !isLargeGraph && !isSelected && !isNeighbor
  )
  return dimmedByPath || dimmedBySelection
}

function createNodeRenderState({
  node,
  globalScale,
  highlightedNodeIds,
  highlightedLinkIds,
  selectedNodeId,
  neighborSet,
  hoveredNodeId,
  isLargeGraph,
  isDark,
  color,
  degree,
}: {
  node: GraphNodeDatum
  globalScale: number
  highlightedNodeIds: ReadonlySet<string>
  highlightedLinkIds: ReadonlySet<string>
  selectedNodeId: string | null
  neighborSet: ReadonlySet<string> | null
  hoveredNodeId: string | null
  isLargeGraph: boolean
  isDark: boolean
  color: string
  degree: number
}): GraphNodeRenderState {
  const isHighlighted = highlightedNodeIds.size > 0 && highlightedNodeIds.has(node.id)
  const isPathNode = highlightedLinkIds.size > 0 && highlightedNodeIds.has(node.id)
  const isSelected = selectedNodeId === node.id
  const isNeighbor = Boolean(neighborSet?.has(node.id))
  const isHovered = hoveredNodeId === node.id && !isLargeGraph
  const { coreRadius, shellRadius } = nodeRadii({
    degree,
    isLargeGraph,
    isHighlighted,
    isSelected,
    isHovered,
  })
  const nx = node.x || 0
  const ny = node.y || 0

  return {
    node,
    label: truncateGraphLabel(node.label || node.id, 24),
    fontSize: nodeHighlightFontSize(
      isHighlighted,
      isSelected,
      isHovered,
      globalScale
    ),
    color,
    degree,
    coreRadius,
    shellRadius,
    nx,
    ny,
    labelDirection: nx >= 0 ? 1 : -1,
    isHighlighted,
    isPathNode,
    isSelected,
    isHovered,
    isDimmed: shouldDimNode({
      hasHighlightedNodes: highlightedNodeIds.size > 0,
      hasHighlightedLinks: highlightedLinkIds.size > 0,
      isHighlighted,
      selectedNodeId,
      isLargeGraph,
      isSelected,
      isNeighbor,
    }),
    emphasis: isSelected || isHighlighted || isHovered,
    isDark,
    globalScale,
  }
}

function nodeStrokeAlpha(
  isHighlighted: boolean,
  isHovered: boolean,
  isDark: boolean
) {
  if (isHighlighted || isHovered) return 0.7
  return isDark ? 0.42 : 0.32
}

function nodeStrokeStyle({
  isPathNode,
  color,
  isSelected,
  isHighlighted,
  isHovered,
  isDark,
}: {
  isPathNode: boolean
  color: string
  isSelected: boolean
  isHighlighted: boolean
  isHovered: boolean
  isDark: boolean
}) {
  if (isPathNode) return '#f59e0b'
  const alpha = isSelected ? 0.88 : nodeStrokeAlpha(isHighlighted, isHovered, isDark)
  return withAlpha(color, alpha)
}

function nodeStrokeWidth(
  isSelected: boolean,
  isHighlighted: boolean,
  isHovered: boolean,
  globalScale: number
) {
  if (isSelected) return 1.9 / globalScale
  if (isHighlighted || isHovered) return 1.45 / globalScale
  return 1.1 / globalScale
}

function nodeLabelCardFill(
  emphasis: boolean,
  color: string,
  isDark: boolean
) {
  if (!emphasis) {
    return isDark ? 'rgba(2, 6, 23, 0.78)' : 'rgba(255, 254, 249, 0.86)'
  }
  return withAlpha(
    mixHexColors(color, isDark ? '#0f172a' : '#fffef9', isDark ? 0.74 : 0.84),
    isDark ? 0.92 : 0.9
  )
}

function drawNodeGlow(ctx: CanvasRenderingContext2D, state: GraphNodeRenderState) {
  if (!state.emphasis) return
  if (!state.isHovered && !state.isSelected) return

  ctx.save()
  const glowRadius = state.shellRadius + (state.isSelected ? 7 : 5.5)
  const glow = ctx.createRadialGradient(
    state.nx,
    state.ny,
    state.coreRadius * 0.5,
    state.nx,
    state.ny,
    glowRadius
  )
  glow.addColorStop(0, withAlpha(state.color, state.isSelected ? 0.22 : 0.16))
  glow.addColorStop(1, withAlpha(state.color, 0))
  ctx.beginPath()
  ctx.arc(state.nx, state.ny, glowRadius, 0, 2 * Math.PI)
  ctx.fillStyle = glow
  ctx.globalAlpha = state.isSelected ? 0.7 : 0.5
  ctx.fill()
  ctx.restore()
  ctx.globalAlpha = state.isDimmed ? 0.36 : 1
}

function drawNodeShell(ctx: CanvasRenderingContext2D, state: GraphNodeRenderState) {
  ctx.beginPath()
  ctx.arc(state.nx, state.ny, state.shellRadius, 0, 2 * Math.PI, false)
  ctx.fillStyle = withAlpha(
    mixHexColors(
      state.color,
      state.isDark ? '#0f172a' : '#fffef9',
      state.isDark ? 0.45 : 0.22
    ),
    nodeShellAlpha(state.isSelected, state.isHovered)
  )
  ctx.fill()

  ctx.beginPath()
  ctx.arc(state.nx, state.ny, state.shellRadius, 0, 2 * Math.PI, false)
  ctx.strokeStyle = nodeStrokeStyle({
    isPathNode: state.isPathNode,
    color: state.color,
    isSelected: state.isSelected,
    isHighlighted: state.isHighlighted,
    isHovered: state.isHovered,
    isDark: state.isDark,
  })
  ctx.lineWidth = nodeStrokeWidth(
    state.isSelected,
    state.isHighlighted,
    state.isHovered,
    state.globalScale
  )
  ctx.stroke()
}

function drawNodeCore(ctx: CanvasRenderingContext2D, state: GraphNodeRenderState) {
  const coreGradient = ctx.createRadialGradient(
    state.nx - state.coreRadius * 0.45,
    state.ny - state.coreRadius * 0.55,
    Math.max(0.25, state.coreRadius * 0.15),
    state.nx,
    state.ny,
    state.coreRadius
  )
  coreGradient.addColorStop(
    0,
    mixHexColors(state.color, '#ffffff', state.isDark ? 0.1 : 0.42)
  )
  coreGradient.addColorStop(
    0.5,
    mixHexColors(state.color, '#ffffff', state.isDark ? 0.03 : 0.2)
  )
  coreGradient.addColorStop(
    1,
    mixHexColors(
      state.color,
      state.isDark ? '#020617' : '#dbeafe',
      state.isDark ? 0.18 : 0.08
    )
  )

  ctx.beginPath()
  ctx.arc(state.nx, state.ny, state.coreRadius, 0, 2 * Math.PI, false)
  ctx.fillStyle = coreGradient
  ctx.fill()

  ctx.beginPath()
  ctx.arc(state.nx, state.ny, state.coreRadius, 0, 2 * Math.PI, false)
  ctx.strokeStyle = withAlpha('#ffffff', state.isDark ? 0.16 : 0.72)
  ctx.lineWidth = 0.9 / state.globalScale
  ctx.stroke()

  ctx.beginPath()
  ctx.arc(
    state.nx - state.coreRadius * 0.34,
    state.ny - state.coreRadius * 0.4,
    Math.max(0.42 / state.globalScale, state.coreRadius * 0.2),
    0,
    2 * Math.PI,
    false
  )
  ctx.fillStyle = withAlpha('#ffffff', state.isDark ? 0.18 : 0.58)
  ctx.fill()
}

function shouldShowNodeLabel(
  state: GraphNodeRenderState,
  viewportLodTier: GraphViewportLod['tier'] | 'detail',
  isLargeGraph: boolean
) {
  if (state.emphasis) return true
  if (viewportLodTier !== 'detail' && isLargeGraph) return false
  if (state.globalScale > 1.7) return true
  if (state.degree >= 4 && state.globalScale > 1.2) return true
  return state.degree >= 7 && state.globalScale > 1.02
}

function drawNodeLabel({
  ctx,
  state,
  canvasColors,
}: {
  ctx: CanvasRenderingContext2D
  state: GraphNodeRenderState
  canvasColors: GraphCanvasPalette
}) {
  const padX = 6 / state.globalScale
  const padY = 3 / state.globalScale
  const leaderGap = 5 / state.globalScale
  const cardRadius = 5 / state.globalScale
  const cardFill = nodeLabelCardFill(
    state.emphasis,
    state.color,
    state.isDark
  )

  ctx.font = `${state.emphasis ? '600 ' : ''}${state.fontSize}px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif`
  ctx.textAlign = state.labelDirection === 1 ? 'left' : 'right'
  ctx.textBaseline = 'middle'

  const labelWidth = ctx.measureText(state.label).width
  const cardWidth = labelWidth + padX * 2
  const cardHeight = state.fontSize + padY * 2
  const anchorX = state.nx + state.labelDirection * (state.shellRadius + leaderGap)
  const cardX =
    state.labelDirection === 1 ? anchorX : anchorX - cardWidth
  const cardY = state.ny - cardHeight / 2
  const leaderEndX = labelLeaderEndX(
    state.labelDirection,
    cardX,
    cardWidth,
    state.globalScale
  )

  ctx.beginPath()
  ctx.moveTo(
    state.nx + state.labelDirection * (state.shellRadius - 0.3 / state.globalScale),
    state.ny
  )
  ctx.lineTo(leaderEndX, state.ny)
  ctx.strokeStyle = pathAwareStroke(
    state.isPathNode,
    '#f59e0b',
    withAlpha(state.color, state.emphasis ? 0.56 : 0.28)
  )
  ctx.lineWidth = 1 / state.globalScale
  ctx.stroke()

  traceRoundRect(ctx, cardX, cardY, cardWidth, cardHeight, cardRadius)
  ctx.fillStyle = cardFill
  ctx.fill()
  ctx.strokeStyle = pathAwareStroke(
    state.isPathNode,
    withAlpha('#f59e0b', 0.72),
    withAlpha(state.color, state.emphasis ? 0.42 : 0.22)
  )
  ctx.lineWidth = 1 / state.globalScale
  ctx.stroke()

  ctx.fillStyle = state.isDimmed ? canvasColors.labelDim : canvasColors.labelFill
  const textX =
    state.labelDirection === 1 ? cardX + padX : cardX + cardWidth - padX
  ctx.fillText(state.label, textX, state.ny)
}

function drawGraphNode({
  ctx,
  state,
  canvasColors,
  viewportLodTier,
  isLargeGraph,
}: {
  ctx: CanvasRenderingContext2D
  state: GraphNodeRenderState
  canvasColors: GraphCanvasPalette
  viewportLodTier: GraphViewportLod['tier'] | 'detail'
  isLargeGraph: boolean
}) {
  ctx.globalAlpha = state.isDimmed ? 0.36 : 1
  drawNodeGlow(ctx, state)
  drawNodeShell(ctx, state)
  drawNodeCore(ctx, state)
  if (shouldShowNodeLabel(state, viewportLodTier, isLargeGraph)) {
    drawNodeLabel({ ctx, state, canvasColors })
  }
  ctx.globalAlpha = 1
}

function labelLeaderEndX(
  labelDirection: number,
  cardX: number,
  cardWidth: number,
  globalScale: number
) {
  if (labelDirection === 1) return cardX - 2 / globalScale
  return cardX + cardWidth + 2 / globalScale
}

function pathAwareStroke(
  isPathNode: boolean,
  pathColor: string,
  fallbackColor: string
) {
  return isPathNode ? pathColor : fallbackColor
}

function edgeLabelFillStyle(
  isPathLink: boolean,
  isHoveredLink: boolean,
  fallback: string
) {
  if (isPathLink) return '#f59e0b'
  if (isHoveredLink) return 'rgba(56, 189, 248, 0.15)'
  return fallback
}

function edgeLabelTextStyle(
  isPathLink: boolean,
  isHoveredLink: boolean,
  hoverText: string,
  text: string
) {
  if (isPathLink) return '#ffffff'
  if (isHoveredLink) return hoverText
  return text
}

function normalizeReadableTextAngle(angle: number) {
  if (angle > Math.PI / 2) return -(Math.PI - angle)
  if (angle < -Math.PI / 2) return -(-Math.PI - angle)
  return angle
}

function getLinkLabelRenderState({
  link,
  highlightedLinkIds,
  hoveredLinkId,
  allowEdgeLabels,
  globalScale,
  edgeLabelScale,
}: {
  link: GraphLinkDatum
  highlightedLinkIds: ReadonlySet<string>
  hoveredLinkId: string | null
  allowEdgeLabels: boolean
  globalScale: number
  edgeLabelScale: number
}): LinkLabelRenderState | null {
  if (!isGraphEndpointObject(link.source) || !isGraphEndpointObject(link.target)) {
    return null
  }

  const linkId = getStableLinkId(link)
  const isPathLink = Boolean(
    highlightedLinkIds.size > 0 && linkId && highlightedLinkIds.has(linkId)
  )
  const isHoveredLink = hoveredLinkId !== null && linkId === hoveredLinkId
  const isAccent = isPathLink || isHoveredLink
  if (!allowEdgeLabels && !isAccent) return null
  if (globalScale < edgeLabelScale && !isAccent) return null

  const label = graphDisplayString(link.label)
  if (!label) return null

  return {
    startNode: link.source,
    endNode: link.target,
    label,
    isPathLink,
    isHoveredLink,
    isAccent,
  }
}

function getLinkLabelLayout(
  ctx: CanvasRenderingContext2D,
  state: LinkLabelRenderState,
  globalScale: number
): LinkLabelLayout | null {
  const x1 = state.startNode.x || 0
  const y1 = state.startNode.y || 0
  const x2 = state.endNode.x || 0
  const y2 = state.endNode.y || 0
  const relLink = { x: x2 - x1, y: y2 - y1 }
  const maxTextLength = Math.hypot(relLink.x, relLink.y) - 8
  const fontSize = state.isAccent ? 12 / globalScale : 11 / globalScale

  ctx.font = `${state.isAccent ? 'bold ' : ''}${fontSize}px Sans-Serif`
  const textWidth = ctx.measureText(state.label).width
  if (textWidth > maxTextLength) return null

  return {
    textPos: { x: x1 + relLink.x / 2, y: y1 + relLink.y / 2 },
    textAngle: normalizeReadableTextAngle(Math.atan2(relLink.y, relLink.x)),
    textWidth,
    fontSize,
  }
}

function drawLinkLabelBadge(
  ctx: CanvasRenderingContext2D,
  state: LinkLabelRenderState,
  layout: LinkLabelLayout,
  globalScale: number,
  canvasColors: GraphCanvasPalette
) {
  const padX = 4
  const padY = 2
  const rx = 3 / globalScale
  const bx = -layout.textWidth / 2 - padX
  const by = -layout.fontSize / 2 - padY
  const bw = layout.textWidth + padX * 2
  const bh = layout.fontSize + padY * 2

  traceRoundRect(ctx, bx, by, bw, bh, rx)
  ctx.fillStyle = edgeLabelFillStyle(
    state.isPathLink,
    state.isHoveredLink,
    canvasColors.edgeLabelBg
  )
  ctx.fill()

  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'
  ctx.fillStyle = edgeLabelTextStyle(
    state.isPathLink,
    state.isHoveredLink,
    canvasColors.edgeLabelHoverText,
    canvasColors.edgeLabelText
  )
  ctx.fillText(state.label, 0, 0)
}

function drawGraphLinkLabel({
  link,
  ctx,
  globalScale,
  allowEdgeLabels,
  edgeLabelScale,
  highlightedLinkIds,
  hoveredLinkId,
  canvasColors,
}: {
  link: GraphLinkDatum
  ctx: CanvasRenderingContext2D
  globalScale: number
  allowEdgeLabels: boolean
  edgeLabelScale: number
  highlightedLinkIds: ReadonlySet<string>
  hoveredLinkId: string | null
  canvasColors: GraphCanvasPalette
}) {
  const state = getLinkLabelRenderState({
    link,
    highlightedLinkIds,
    hoveredLinkId,
    allowEdgeLabels,
    globalScale,
    edgeLabelScale,
  })
  if (!state) return

  const layout = getLinkLabelLayout(ctx, state, globalScale)
  if (!layout) return

  ctx.save()
  ctx.translate(layout.textPos.x, layout.textPos.y)
  ctx.rotate(layout.textAngle)
  drawLinkLabelBadge(ctx, state, layout, globalScale, canvasColors)
  ctx.restore()
}

function getPrimaryCanvas(root: ParentNode | null): HTMLCanvasElement | null {
  if (!root) return null
  const canvases = Array.from(root.querySelectorAll('canvas')) as HTMLCanvasElement[]
  if (!canvases.length) return null
  return canvases
    .filter((canvas) => Number.isFinite(canvas.width) && Number.isFinite(canvas.height))
    .sort((a, b) => b.width * b.height - a.width * a.height)[0] ?? null
}

// Dynamically import ForceGraph2D via wrapper to handle Ref correctly
const ForceGraph2DNoSSR = dynamic(
  () => import('./force-graph-2d-wrapper'),
  { ssr: false }
)
const LARGE_GRAPH_NODE_THRESHOLD = 600
const LARGE_GRAPH_LINK_THRESHOLD = 1200

export interface GraphViewerRef {
  zoomIn: () => void
  zoomOut: () => void
  zoomToFit: () => void
  focusNode: (nodeId: string) => void
  exportPngDataUrl: () => string | null
  exportSvgString: () => string | null
}

export type LayoutMode = 'force' | 'tree' | 'radial'

interface GraphViewerProps {
  readonly data: GraphRenderData
  readonly onNodeClick?: (node: GraphNodeDatum) => void
  readonly onNodeRightClick?: (node: GraphNodeDatum, event: MouseEvent) => void
  readonly onLinkClick?: (link: GraphLinkDatum) => void
  readonly onLinkRightClick?: (link: GraphLinkDatum, event: MouseEvent) => void
  readonly onBackgroundClick?: () => void
  readonly onBackgroundRightClick?: (event: MouseEvent) => void
  readonly highlightedNodeIds?: Set<string>
  readonly highlightedLinkIds?: Set<string>
  readonly selectedNodeId?: string | null
  readonly showEdgeLabels?: boolean
  readonly layoutMode?: LayoutMode
  readonly showMinimap?: boolean
}

type GraphRenderBoundaryProps = Readonly<{
  resetKey: string
  children: React.ReactNode
}>

type GraphRenderBoundaryState = Readonly<{
  hasError: boolean
}>

function GraphRenderFallback() {
  return (
    <output
      className="absolute inset-0 flex items-center justify-center px-6 text-center text-sm text-muted-foreground"
    >
      图谱渲染失败，请尝试刷新当前视图。
    </output>
  )
}

class GraphRenderBoundary extends Component<GraphRenderBoundaryProps, GraphRenderBoundaryState> {
  state: GraphRenderBoundaryState = { hasError: false }

  static getDerivedStateFromError(): GraphRenderBoundaryState {
    return { hasError: true }
  }

  componentDidCatch(error: unknown) {
    console.error('Graph rendering failed:', error)
  }

  componentDidUpdate(previousProps: GraphRenderBoundaryProps) {
    if (this.state.hasError && previousProps.resetKey !== this.props.resetKey) {
      this.setState({ hasError: false })
    }
  }

  render() {
    if (this.state.hasError) {
      return <GraphRenderFallback />
    }

    return this.props.children
  }
}

export const GraphViewer = forwardRef<GraphViewerRef, GraphViewerProps>(({ 
  data, 
  onNodeClick,
  onNodeRightClick,
  onLinkClick,
  onLinkRightClick,
  onBackgroundClick,
  onBackgroundRightClick,
  highlightedNodeIds = new Set(),
  highlightedLinkIds = new Set(),
  selectedNodeId = null,
  showEdgeLabels = true,
  layoutMode = 'force',
  showMinimap = true
}, ref) => {
  const containerRef = useRef<HTMLDivElement>(null)
  const fgRef = useRef<ForceGraphMethods | undefined>(undefined)
  const { width, height } = useResizeObserver(containerRef)
  const [mounted, setMounted] = useState(false)
  const [hoveredLinkId, setHoveredLinkId] = useState<string | null>(null)
  const [hoveredNodeId, setHoveredNodeId] = useState<string | null>(null)
  const [isCanvasPanning, setIsCanvasPanning] = useState(false)
  const [viewportLod, setViewportLod] = useState<GraphViewportLod | null>(null)
  const viewportLodFrameRef = useRef<number | null>(null)
  const viewportLodTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const pendingViewportLodRef = useRef<GraphViewportLod | null>(null)
  const { resolvedTheme } = useTheme()
  const isDark = resolvedTheme === 'dark'
  const canvasColors = useMemo(() => {
    const fg = getCssHslColor('--foreground', isDark ? '#e2e8f0' : '#1e293b')
    const muted = getCssHslColor('--muted-foreground', isDark ? '#94a3b8' : '#475569')
    const bgStroke = getCssHslaColor(
      '--background',
      isDark ? 0.86 : 0.94,
      isDark ? 'rgba(2, 6, 23, 0.86)' : 'rgba(255, 255, 255, 0.94)'
    )
    const edgeLabelBg = getCssHslaColor(
      '--background',
      isDark ? 0.82 : 0.95,
      isDark ? 'rgba(15, 23, 42, 0.86)' : 'rgba(255, 255, 255, 0.95)'
    )
    return {
      nodeDim: isDark ? '#334155' : '#cbd5e1',
      linkDim: isDark ? 'rgba(148, 163, 184, 0.18)' : '#e2e8f0',
      linkMid: isDark ? '#64748b' : '#94a3b8',
      labelStroke: bgStroke,
      labelFill: fg,
      labelDim: muted,
      edgeLabelBg,
      edgeLabelText: isDark ? fg : '#475569',
      edgeLabelHoverText: isDark ? fg : '#0c4a6e',
    }
  }, [isDark])

  const neighborSet = useMemo(() => {
    if (!selectedNodeId) return null
    const set = new Set<string>()
    set.add(selectedNodeId)
    for (const link of data.links) {
      const src = typeof link.source === 'object' ? link.source?.id : link.source
      const tgt = typeof link.target === 'object' ? link.target?.id : link.target
      if (src === selectedNodeId) set.add(String(tgt))
      if (tgt === selectedNodeId) set.add(String(src))
    }
    return set
  }, [selectedNodeId, data.links])

  const nodeDegreeMap = useMemo(() => {
    const map = new Map<string, number>()
    for (const link of data.links) {
      const src = typeof link.source === 'object' ? link.source?.id : link.source
      const tgt = typeof link.target === 'object' ? link.target?.id : link.target
      map.set(String(src), (map.get(String(src)) || 0) + 1)
      map.set(String(tgt), (map.get(String(tgt)) || 0) + 1)
    }
    return map
  }, [data.links])

  const typeColorMap = useMemo(() => buildTypeColorMap(data.nodes), [data.nodes])

  // Sanitize data to ensure fresh 2D simulation
  // 1. Clone nodes/links to break references (especially when switching from 3D)
  // 2. Convert link source/target objects back to IDs so d3 re-resolves them against the new node array
  // 3. Clear 3D-specific props or fixed positions
  const sanitizedData = useMemo(() => {
    const nodes = data.nodes.map(node => {
      // Destructure to remove 3D specific or fixed position props
      const { fx, fy, fz, vz, vy, vx, z, ...rest } = node
      return { ...rest }
    })

    const links = data.links.map((link, index) => ({
      ...link,
      id: link.id ?? getStableLinkId(link, index),
      // Reset source/target to IDs if they are objects (from previous d3 simulation)
      source: (typeof link.source === 'object' && link.source !== null && 'id' in link.source)
        ? (link.source).id
        : link.source,
      target: (typeof link.target === 'object' && link.target !== null && 'id' in link.target)
        ? (link.target).id
        : link.target
    }))

    // Spread parallel links and draw self-loops deterministically.
    decorateLinksForDisplay(links as Array<GraphLinkDatum & Record<string, unknown>>)

    return { nodes, links }
  }, [data])
  const isLargeGraph = useMemo(
    () =>
      sanitizedData.nodes.length > LARGE_GRAPH_NODE_THRESHOLD ||
      sanitizedData.links.length > LARGE_GRAPH_LINK_THRESHOLD,
    [sanitizedData.links.length, sanitizedData.nodes.length]
  )
  const allowEdgeLabels = showEdgeLabels && !isLargeGraph
  const edgeLabelScale = isLargeGraph ? 2.5 : 2
  const nodeRelSize = isLargeGraph ? 4 : 6
  const arrowLength = isLargeGraph ? 0 : 3.5
  const cooldownTicks = isLargeGraph ? 50 : 100
  const cooldownTime = isLargeGraph ? 4000 : 8000
  const graphRenderResetKey = `${sanitizedData.nodes.length}:${sanitizedData.links.length}:${layoutMode}`
  const graphCursor = graphCursorStyle(
    isCanvasPanning,
    hoveredNodeId,
    hoveredLinkId
  )
  const viewportPinnedNodeIds = useMemo(() => {
    const pinned = new Set<string>(highlightedNodeIds)
    if (selectedNodeId) pinned.add(selectedNodeId)
    return pinned
  }, [highlightedNodeIds, selectedNodeId])
  const viewportLodTier = viewportLod?.tier ?? 'detail'

  const flushViewportLodUpdate = useCallback(() => {
    viewportLodFrameRef.current = null
    viewportLodTimeoutRef.current = null
    const pending = pendingViewportLodRef.current
    setViewportLod((current) => (areViewportLodsEqual(current, pending) ? current : pending))
  }, [])

  const scheduleViewportLodUpdate = useCallback((next: GraphViewportLod | null) => {
    pendingViewportLodRef.current = next

    if (viewportLodFrameRef.current !== null || viewportLodTimeoutRef.current !== null) return

    if (
      globalThis.window !== undefined &&
      typeof globalThis.window.requestAnimationFrame === 'function'
    ) {
      viewportLodFrameRef.current = globalThis.window.requestAnimationFrame(() => {
        flushViewportLodUpdate()
      })
      return
    }

    viewportLodTimeoutRef.current = setTimeout(() => {
      flushViewportLodUpdate()
    }, 0)
  }, [flushViewportLodUpdate])

  const updateViewportLod = useCallback((transform?: { k?: number }) => {
    const graph = fgRef.current
    if (!isLargeGraph || !graph || width <= 0 || height <= 0) {
      scheduleViewportLodUpdate(null)
      return
    }

    const topLeft = graph.screen2GraphCoords?.(0, 0)
    const bottomRight = graph.screen2GraphCoords?.(width, height)
    if (!topLeft || !bottomRight) return

    const viewport: GraphViewportRect = {
      minX: Math.min(Number(topLeft.x), Number(bottomRight.x)),
      minY: Math.min(Number(topLeft.y), Number(bottomRight.y)),
      maxX: Math.max(Number(topLeft.x), Number(bottomRight.x)),
      maxY: Math.max(Number(topLeft.y), Number(bottomRight.y)),
    }
    if (!Object.values(viewport).every(Number.isFinite)) return

    const zoom = Number(transform?.k ?? graph.zoom?.() ?? 1)
    const next = buildGraphViewportLod({
      nodes: sanitizedData.nodes,
      links: sanitizedData.links,
      viewport,
      globalScale: Number.isFinite(zoom) ? zoom : 1,
      totalNodeCount: sanitizedData.nodes.length,
      selectedNodeIds: viewportPinnedNodeIds,
    })

    scheduleViewportLodUpdate(next)
  }, [height, isLargeGraph, sanitizedData.links, sanitizedData.nodes, scheduleViewportLodUpdate, viewportPinnedNodeIds, width])

  useEffect(() => {
    setMounted(true)
  }, [])

  useEffect(() => {
    return () => {
      if (viewportLodFrameRef.current !== null && globalThis.window !== undefined) {
        globalThis.window.cancelAnimationFrame(viewportLodFrameRef.current)
        viewportLodFrameRef.current = null
      }
      if (viewportLodTimeoutRef.current !== null) {
        clearTimeout(viewportLodTimeoutRef.current)
        viewportLodTimeoutRef.current = null
      }
    }
  }, [])

  useEffect(() => {
    if (typeof document === 'undefined') return

    const handleVisibility = () => {
      const isHidden = document.visibilityState === 'hidden'
      const graph = fgRef.current
      if (!graph) return
      if (isHidden) {
        graph.pauseAnimation?.()
      } else {
        graph.resumeAnimation?.()
      }
    }

    handleVisibility()
    document.addEventListener('visibilitychange', handleVisibility)
    return () => {
      document.removeEventListener('visibilitychange', handleVisibility)
    }
  }, [])

  useEffect(() => {
    if (!mounted) return

    const root = containerRef.current
    if (!root) return

    const resetPanning = () => setIsCanvasPanning(false)
    const handleMouseDown = (event: MouseEvent) => {
      if (!(event.target instanceof HTMLCanvasElement)) return
      if (event.button === 1 || event.button === 2) {
        setIsCanvasPanning(true)
      }
    }

    root.addEventListener('mousedown', handleMouseDown)
    globalThis.window.addEventListener('mouseup', resetPanning)
    globalThis.window.addEventListener('blur', resetPanning)
    globalThis.window.addEventListener('contextmenu', resetPanning)

    return () => {
      root.removeEventListener('mousedown', handleMouseDown)
      globalThis.window.removeEventListener('mouseup', resetPanning)
      globalThis.window.removeEventListener('blur', resetPanning)
      globalThis.window.removeEventListener('contextmenu', resetPanning)
    }
  }, [mounted])

  useEffect(() => {
    const root = containerRef.current
    const primaryCanvas = getPrimaryCanvas(root)
    if (root) {
      root.style.cursor = graphCursor
    }
    if (primaryCanvas) {
      primaryCanvas.style.cursor = graphCursor
    }
  }, [graphCursor, height, mounted, showMinimap, width, sanitizedData.links.length, sanitizedData.nodes.length])

  // Expose methods to parent
  useImperativeHandle(ref, () => ({
    zoomIn: () => {
      if (fgRef.current) {
        const currentZoom = fgRef.current.zoom()
        fgRef.current.zoom(currentZoom * 1.2, 400)
      }
    },
    zoomOut: () => {
      if (fgRef.current) {
        const currentZoom = fgRef.current.zoom()
        fgRef.current.zoom(currentZoom / 1.2, 400)
      }
    },
    zoomToFit: () => {
      if (fgRef.current) {
        fgRef.current.zoomToFit(400, 20)
      }
    },
    focusNode: (nodeId: string) => {
      // Use sanitizedData because that's what d3 is updating with x,y coords
      const node = sanitizedData.nodes.find(n => n.id === nodeId)
      if (node && fgRef.current) {
        fgRef.current.centerAt(node.x, node.y, 1000)
        fgRef.current.zoom(3, 1000)
      }
    },
    exportPngDataUrl: () => {
      const host = containerRef.current
      if (!host) return null
      const canvases = Array.from(host.querySelectorAll('canvas')) as HTMLCanvasElement[]
      if (!canvases.length) return null
      const main = canvases
        .filter((c) => c && Number.isFinite(c.width) && Number.isFinite(c.height))
        .sort((a, b) => (b.width * b.height) - (a.width * a.height))[0]
      if (!main) return null
      try {
        return main.toDataURL('image/png')
      } catch {
        return null
      }
    },
    exportSvgString: () => {
      const host = containerRef.current
      if (!host) return null
      const canvases = Array.from(host.querySelectorAll('canvas')) as HTMLCanvasElement[]
      if (!canvases.length) return null
      const main = canvases
        .filter((c) => c && Number.isFinite(c.width) && Number.isFinite(c.height))
        .sort((a, b) => (b.width * b.height) - (a.width * a.height))[0]
      if (!main) return null
      let pngDataUrl = ''
      try {
        pngDataUrl = main.toDataURL('image/png')
      } catch {
        return null
      }
      if (!pngDataUrl) return null
      const w = Math.max(1, main.width || 1)
      const h = Math.max(1, main.height || 1)
      return `<?xml version="1.0" encoding="UTF-8"?>\n<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}">\n  <image href="${pngDataUrl}" width="${w}" height="${h}" />\n</svg>\n`
    },
  }))

  // Auto zoom fit on data change
  useEffect(() => {
    let attempts = 0
    const maxAttempts = 10
    let timeoutId: number | null = null
    
    const tryZoom = () => {
      if (fgRef.current && sanitizedData.nodes.length > 0) {
        fgRef.current.zoomToFit(400, 20)
      } else if (attempts < maxAttempts) {
        attempts++
        timeoutId = globalThis.window.setTimeout(tryZoom, 200)
      }
    }
    
    // Initial delay to allow render
    timeoutId = globalThis.window.setTimeout(tryZoom, 300)
    return () => {
      if (timeoutId != null) {
        clearTimeout(timeoutId)
      }
    }
  }, [sanitizedData])

  // Layout transitions (U9): reheat the simulation so layout changes animate smoothly.
  useEffect(() => {
    if (fgRef.current) {
      fgRef.current.d3ReheatSimulation?.()
    }
  }, [layoutMode])

  useEffect(() => {
    if (!mounted) return
    updateViewportLod()
  }, [mounted, updateViewportLod])

  const handleNodeClick = useCallback((node: GraphNodeDatum) => {
    if (fgRef.current) {
      fgRef.current.centerAt(node.x, node.y, 400)
      fgRef.current.zoom(2.5, 400)
    }
    if (onNodeClick) {
      onNodeClick(node)
    }
  }, [onNodeClick])

  const getNodeColor = useCallback((node: GraphNodeDatum) => {
    const hasHighlights = highlightedNodeIds.size > 0
    if (hasHighlights && !highlightedNodeIds.has(node.id)) {
      return canvasColors.nodeDim
    }

    if (node.color) return node.color

    const kind = graphNodeKind(node)
    if (kind === 'event') return EVENT_COLOR

    const type = graphNodeType(node)
    if (type && typeColorMap.has(type)) return typeColorMap.get(type)!

    if (typeof node.group === 'number' && node.group > 0) {
      return NODE_COLOR_PALETTE[(node.group - 1) % NODE_COLOR_PALETTE.length]
    }

    return NODE_COLOR_PALETTE[hashTypeToIndex(node.id || '')]
  }, [highlightedNodeIds, typeColorMap, canvasColors.nodeDim])

  const isNodeVisibleForViewport = useCallback((node: GraphNodeDatum) => {
    if (!isLargeGraph || !viewportLod) return true
    const nodeId = String(node?.id ?? '')
    if (!nodeId) return false
    return viewportLod.visibleNodeIds.has(nodeId) || viewportPinnedNodeIds.has(nodeId)
  }, [isLargeGraph, viewportLod, viewportPinnedNodeIds])

  const isLinkVisibleForViewport = useCallback((link: GraphLinkDatum) => {
    if (!isLargeGraph || !viewportLod) return true
    const linkId = getStableLinkId(link)
    if (linkId && highlightedLinkIds.has(linkId)) return true
    return Boolean(linkId && viewportLod.visibleLinkIds.has(linkId))
  }, [highlightedLinkIds, isLargeGraph, viewportLod])

  // Determine DAG mode based on layoutMode
  const getDagMode = () => {
    switch (layoutMode) {
      case 'tree': return 'td' // Top-Down
      case 'radial': return 'radialout'
      default: return undefined // Force Directed
    }
  }

  return (
    <div ref={containerRef} className="relative h-full w-full bg-transparent">
      {(!mounted || width === 0 || height === 0) ? (
        <div className="absolute inset-0 flex items-center justify-center text-muted-foreground">
	           {mounted ? (
	              <div className="flex flex-col items-center gap-2">
	                 <Loader2 className="w-6 h-6 animate-spin motion-reduce:animate-none text-primary" />
	                 <span className="text-xs">Initializing Layout... ({Math.round(width)}x{Math.round(height)})</span>
	              </div>
	           ) : (
	              <Loader2 className="w-8 h-8 animate-spin motion-reduce:animate-none" />
	           )}
        </div>
      ) : (
        <GraphRenderBoundary resetKey={graphRenderResetKey}>
          <>
            <ForceGraph2DNoSSR
              graphRef={fgRef}
              width={width}
              height={height}
              graphData={sanitizedData}
              backgroundColor="rgba(0,0,0,0)"
              showPointerCursor={false}
              nodeLabel="label"
              nodeVisibility={isNodeVisibleForViewport}
              nodeColor={getNodeColor}
              nodeRelSize={nodeRelSize}
              // Layout Config
              dagMode={getDagMode()}
              dagLevelDistance={50}
              
              // Link styling
              linkCurvature={(link: GraphLinkDatum) => {
                const v = link?.curvature
                return typeof v === 'number' && Number.isFinite(v) ? v : 0
              }}
              linkCurveRotation={(link: GraphLinkDatum) => {
                const v = link?.curveRotation
                return typeof v === 'number' && Number.isFinite(v) ? v : 0
              }}
              linkColor={(link: GraphLinkDatum) => {
                 const linkId = getStableLinkId(link)
                 const linkKind = getLinkKind(link)
                 const baseColor = EDGE_KIND_COLORS[linkKind] || canvasColors.nodeDim
                 const baseLineColor = withAlpha(baseColor, isLargeGraph ? 0.22 : 0.32)
                 const activeLineColor = withAlpha(baseColor, isLargeGraph ? 0.44 : 0.58)
                  if (highlightedLinkIds.size > 0 && linkId && highlightedLinkIds.has(linkId)) {
                     return '#f59e0b'
                  }
                  if (hoveredLinkId && linkId && hoveredLinkId === linkId) {
                     return '#38bdf8'
                  }
                  if (highlightedNodeIds.size > 0) {
                    if (endpointsAreHighlighted(link, highlightedNodeIds)) {
                      return activeLineColor
                    }
                    return canvasColors.linkDim
                  }
                  if (selectedNodeId && !isLargeGraph) {
                    if (endpointMatchesSelected(link, selectedNodeId)) {
                      return activeLineColor
                    }
                    return canvasColors.linkDim
                  }

                  return baseLineColor
               }}
              linkWidth={(link: GraphLinkDatum) => {
                  const linkId = getStableLinkId(link)
                 const confidence = getLinkConfidence(link)
                 const baseWidth = confidenceToWidth(confidence, { isLargeGraph })
                  if (highlightedLinkIds.size > 0 && linkId && highlightedLinkIds.has(linkId)) {
                     return 4 
                  }
                  if (hoveredLinkId && linkId && hoveredLinkId === linkId) {
                     return 3
                  }
                  if (highlightedNodeIds.size > 0) return 1
                  if (selectedNodeId && !isLargeGraph) {
                    if (endpointMatchesSelected(link, selectedNodeId)) return Math.max(2.5, baseWidth + 0.6)
                    return 0.5
                  }
                  return Math.min(3.2, Math.max(isLargeGraph ? 0.45 : 0.8, baseWidth * 0.82))
               }}
              linkDirectionalArrowLength={(link: GraphLinkDatum) => (link?.isSelfLoop ? 0 : arrowLength)}
              linkDirectionalArrowRelPos={1}
              linkLabel={(link: GraphLinkDatum) => buildGraphLinkProvenanceTooltipHtml(link)}
              linkVisibility={isLinkVisibleForViewport}
              cooldownTicks={cooldownTicks}
              cooldownTime={cooldownTime}
              onZoomEnd={updateViewportLod}
              onEngineStop={updateViewportLod}
              onNodeClick={handleNodeClick}
              onNodeRightClick={(node: GraphNodeDatum, event: MouseEvent) => {
                onNodeRightClick?.(node, event)
              }}
              onLinkClick={(link: GraphLinkDatum) => { onLinkClick?.(link) }}
              onLinkRightClick={(link: GraphLinkDatum, event: MouseEvent) => {
                onLinkRightClick?.(link, event)
              }}
              onBackgroundClick={onBackgroundClick}
              onBackgroundRightClick={(event: MouseEvent) => {
                onBackgroundRightClick?.(event)
              }}
              onNodeHover={(node: GraphNodeDatum | null) => {
                if (isLargeGraph) return
                const id = node?.id ?? null
                setHoveredNodeId((prev) => (prev === id ? prev : id))
              }}
              onLinkHover={(link: GraphLinkDatum | null) => {
                const linkId = getStableLinkId(link)
                setHoveredLinkId((prev) => (prev === linkId ? prev : linkId))
              }}
              onNodeDragEnd={(node: GraphNodeDatum) => {
                node.fx = node.x;
                node.fy = node.y;
              }}
              
              // Custom Node Painting
              nodeCanvasObject={(node: GraphNodeDatum, ctx: CanvasRenderingContext2D, globalScale: number) => {
                const degree = nodeDegreeMap.get(String(node.id)) || 0
                const state = createNodeRenderState({
                  node,
                  globalScale,
                  highlightedNodeIds,
                  highlightedLinkIds,
                  selectedNodeId,
                  neighborSet,
                  hoveredNodeId,
                  isLargeGraph,
                  isDark,
                  color: getNodeColor(node),
                  degree,
                })
                drawGraphNode({
                  ctx,
                  state,
                  canvasColors,
                  viewportLodTier,
                  isLargeGraph,
                })
              }}

              // Custom Link Label Painting
              linkCanvasObjectMode={() => 'after'}
              linkCanvasObject={(link: GraphLinkDatum, ctx: CanvasRenderingContext2D, globalScale: number) => {
                drawGraphLinkLabel({
                  link,
                  ctx,
                  globalScale,
                  allowEdgeLabels,
                  edgeLabelScale,
                  highlightedLinkIds,
                  hoveredLinkId,
                  canvasColors,
                })
              }}
            />
            {isLargeGraph && viewportLod ? (
              <div className="pointer-events-none absolute left-5 top-5 z-10 rounded-full border border-border/70 bg-card/82 px-3 py-1 text-[11px] font-medium text-muted-foreground shadow-soft backdrop-blur-md">
                LOD {viewportLod.tier} · 隐藏 {viewportLod.hiddenNodeCount} 节点 / {viewportLod.hiddenLinkCount} 连线
              </div>
            ) : null}
            {showMinimap && !isLargeGraph && sanitizedData.nodes.length > 0 && (
              <div className="absolute bottom-24 right-6 z-10">
                <GraphMinimap
                  graphRef={fgRef}
                  data={sanitizedData}
                  graphWidth={width}
                  graphHeight={height}
                  isDark={isDark}
                />
              </div>
            )}
          </>
        </GraphRenderBoundary>
      )}
    </div>
  )
})

GraphViewer.displayName = 'GraphViewer'
