'use client'

import { useCallback, useEffect, useRef, type KeyboardEvent, type MouseEvent } from 'react'
import type { ForceGraphMethods } from 'react-force-graph-2d'

import { cn } from '@/lib/utils'

type GraphMinimapProps = {
  readonly graphRef: Readonly<{ current?: GraphMinimapHandle | null }>
  readonly nodes: readonly GraphMinimapNode[]
  readonly graphWidth: number
  readonly graphHeight: number
  readonly isDark?: boolean
  readonly className?: string
  readonly width?: number
  readonly height?: number
}

type GraphMinimapNode = {
  readonly x?: unknown
  readonly y?: unknown
}

type GraphMinimapHandle = Partial<Pick<ForceGraphMethods, 'getGraphBbox' | 'centerAt' | 'zoom'>>

type RenderedBounds = { xmin: number; xmax: number; ymin: number; ymax: number }

const PAN_DIRECTIONS = new Map<string, readonly [number, number]>([
  ['ArrowLeft', [-1, 0]],
  ['ArrowRight', [1, 0]],
  ['ArrowUp', [0, -1]],
  ['ArrowDown', [0, 1]],
])

function safeNumber(value: unknown, fallback: number): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback
}

export function GraphMinimap({
  graphRef,
  nodes,
  graphWidth,
  graphHeight,
  isDark = false,
  className,
  width = 140,
  height = 100,
}: GraphMinimapProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const renderedBounds = useRef<RenderedBounds | null>(null)

  const draw = useCallback(() => {
    renderedBounds.current = null
    const canvas = canvasRef.current
    const g = graphRef.current
    if (!canvas || !g) return
    if (!graphWidth || !graphHeight) return

    const ctx = canvas.getContext('2d')
    if (!ctx) return

    const w = canvas.width
    const h = canvas.height
    ctx.clearRect(0, 0, w, h)

    // Background
    ctx.fillStyle = isDark ? 'rgba(2, 6, 23, 0.6)' : 'rgba(255, 255, 255, 0.8)'
    ctx.fillRect(0, 0, w, h)

    // The force simulation updates coordinates on the existing nodes.
    const nodePositions: Array<{ x: number; y: number }> = []
    for (const node of nodes) {
      const x = safeNumber(node.x, Number.NaN)
      const y = safeNumber(node.y, Number.NaN)
      if (Number.isFinite(x) && Number.isFinite(y)) nodePositions.push({ x, y })
    }

    // BBox (prefer force-graph API when available)
    let xmin = Infinity
    let xmax = -Infinity
    let ymin = Infinity
    let ymax = -Infinity
    try {
      const bbox = g.getGraphBbox?.()
      const xRange = Array.isArray(bbox?.x) ? bbox.x : null
      const yRange = Array.isArray(bbox?.y) ? bbox.y : null
      if (xRange && yRange) {
        xmin = safeNumber(xRange[0], xmin)
        xmax = safeNumber(xRange[1], xmax)
        ymin = safeNumber(yRange[0], ymin)
        ymax = safeNumber(yRange[1], ymax)
      }
    } catch {}

    if (!Number.isFinite(xmin) || !Number.isFinite(xmax) || !Number.isFinite(ymin) || !Number.isFinite(ymax)) {
      for (const p of nodePositions) {
        xmin = Math.min(xmin, p.x)
        xmax = Math.max(xmax, p.x)
        ymin = Math.min(ymin, p.y)
        ymax = Math.max(ymax, p.y)
      }
    }

    if (!Number.isFinite(xmin) || !Number.isFinite(xmax) || xmax - xmin <= 0) return
    if (!Number.isFinite(ymin) || !Number.isFinite(ymax) || ymax - ymin <= 0) return

    const padX = (xmax - xmin) * 0.08
    const padY = (ymax - ymin) * 0.08
    xmin -= padX
    xmax += padX
    ymin -= padY
    ymax += padY
    renderedBounds.current = { xmin, xmax, ymin, ymax }

    const sx = (x: number) => ((x - xmin) / (xmax - xmin)) * w
    const sy = (y: number) => ((y - ymin) / (ymax - ymin)) * h

    // Nodes
    ctx.fillStyle = isDark ? 'rgba(148, 163, 184, 0.65)' : 'rgba(71, 85, 105, 0.55)'
    for (const p of nodePositions) {
      ctx.fillRect(sx(p.x), sy(p.y), 1.5, 1.5)
    }

    // Viewport rectangle
    let center = { x: 0, y: 0 }
    let zoom = Number.NaN
    try {
      const currentCenter = g.centerAt?.()
      if (currentCenter && typeof currentCenter === 'object' && 'x' in currentCenter && 'y' in currentCenter) {
        center = {
          x: safeNumber(currentCenter.x, center.x),
          y: safeNumber(currentCenter.y, center.y),
        }
      }
      zoom = safeNumber(g.zoom?.(), Number.NaN)
    } catch {}
    if (!Number.isFinite(zoom) || zoom <= 0) return

    const halfW = graphWidth / (2 * zoom)
    const halfH = graphHeight / (2 * zoom)
    const left = center.x - halfW
    const right = center.x + halfW
    const top = center.y - halfH
    const bottom = center.y + halfH

    const vx = Math.min(w, Math.max(0, sx(left)))
    const vy = Math.min(h, Math.max(0, sy(top)))
    const vw = Math.min(w, Math.max(0, sx(right))) - vx
    const vh = Math.min(h, Math.max(0, sy(bottom))) - vy

    ctx.strokeStyle = isDark ? 'rgba(56, 189, 248, 0.9)' : 'rgba(2, 132, 199, 0.9)'
    ctx.lineWidth = 1
    ctx.strokeRect(vx, vy, Math.max(0, vw), Math.max(0, vh))
  }, [graphRef, graphWidth, graphHeight, isDark, nodes])

  useEffect(() => {
    let frameId: number
    let lastDrawTime = 0

    const tick = (time: number) => {
      if (time - lastDrawTime > 140) {
        lastDrawTime = time
        draw()
      }
      frameId = requestAnimationFrame(tick)
    }

    frameId = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frameId)
  }, [draw])

  function handleClick(event: MouseEvent<HTMLButtonElement>) {
    const graph = graphRef.current
    const bounds = renderedBounds.current
    const rect = canvasRef.current?.getBoundingClientRect()
    if (graph === undefined || graph === null || bounds === null || rect === undefined) return
    if (rect.width === 0 || rect.height === 0) return

    const { xmin, xmax, ymin, ymax } = bounds
    const horizontal = event.detail === 0 ? 0.5 : (event.clientX - rect.left) / rect.width
    const vertical = event.detail === 0 ? 0.5 : (event.clientY - rect.top) / rect.height
    graph.centerAt?.(xmin + horizontal * (xmax - xmin), ymin + vertical * (ymax - ymin), 400)
  }

  function handleKeyDown(event: KeyboardEvent<HTMLButtonElement>) {
    const direction = PAN_DIRECTIONS.get(event.key)
    if (direction === undefined) return
    const graph = graphRef.current
    const center = graph?.centerAt?.()
    const zoom = graph?.zoom?.()
    if (center === undefined || zoom === undefined || !Number.isFinite(zoom) || zoom <= 0) return
    event.preventDefault()
    const [horizontal, vertical] = direction
    graph?.centerAt?.(
      center.x + (horizontal * graphWidth) / (4 * zoom),
      center.y + (vertical * graphHeight) / (4 * zoom),
      400,
    )
  }

  return (
    <button
      type="button"
      className={cn(
        'block cursor-pointer rounded-xl border border-border/50 bg-card/60 shadow-sm backdrop-blur-sm focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring',
        className,
      )}
      onClick={handleClick}
      onKeyDown={handleKeyDown}
      aria-label="图谱小地图，按 Enter 居中，方向键平移"
    >
      <canvas ref={canvasRef} width={width} height={height} className="block rounded-xl" aria-hidden="true" />
    </button>
  )
}
