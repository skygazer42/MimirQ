'use client'

import { useCallback, useEffect, useMemo, useRef, type MouseEvent } from 'react'

import { cn } from '@/lib/utils'

type GraphMinimapProps = {
  readonly graphRef: any
  readonly data: {
    nodes: any[]
    links: any[]
  }
  readonly graphWidth: number
  readonly graphHeight: number
  readonly isDark?: boolean
  readonly className?: string
  readonly width?: number
  readonly height?: number
}

function safeNumber(value: any, fallback: number): number {
  const n = Number(value)
  return Number.isFinite(n) ? n : fallback
}

export function GraphMinimap({
  graphRef,
  data,
  graphWidth,
  graphHeight,
  isDark = false,
  className,
  width = 140,
  height = 100,
}: GraphMinimapProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null)

  const nodePositions = useMemo(() => {
    const out: Array<{ x: number; y: number }> = []
    for (const n of data.nodes || []) {
      const x = safeNumber((n as any)?.x, Number.NaN)
      const y = safeNumber((n as any)?.y, Number.NaN)
      if (!Number.isFinite(x) || !Number.isFinite(y)) continue
      out.push({ x, y })
    }
    return out
  }, [data.nodes])

  const draw = useCallback(() => {
    const canvas = canvasRef.current
    const g = graphRef?.current
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

    // BBox (prefer force-graph API when available)
    let xmin = Infinity
    let xmax = -Infinity
    let ymin = Infinity
    let ymax = -Infinity
    try {
      const bbox = g.getGraphBbox?.()
      if (bbox?.x && bbox?.y) {
        xmin = safeNumber(bbox.x[0], xmin)
        xmax = safeNumber(bbox.x[1], xmax)
        ymin = safeNumber(bbox.y[0], ymin)
        ymax = safeNumber(bbox.y[1], ymax)
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

    const sx = (x: number) => ((x - xmin) / (xmax - xmin)) * w
    const sy = (y: number) => ((y - ymin) / (ymax - ymin)) * h

    // Nodes
    ctx.fillStyle = isDark ? 'rgba(148, 163, 184, 0.65)' : 'rgba(71, 85, 105, 0.55)'
    for (const p of nodePositions) {
      ctx.fillRect(sx(p.x), sy(p.y), 1.5, 1.5)
    }

    // Viewport rectangle
    let center = { x: 0, y: 0 }
    let zoom = 1
    try {
      center = g.centerAt?.() || center
      zoom = safeNumber(g.zoom?.(), 1)
    } catch {}
    zoom = Math.max(0.1, zoom)

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
  }, [graphRef, graphWidth, graphHeight, isDark, nodePositions])

  useEffect(() => {
    let raf = 0
    let last = 0

    const tick = (t: number) => {
      if (t - last > 140) {
        last = t
        draw()
      }
      raf = requestAnimationFrame(tick)
    }

    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [draw])

  const handleClick = useCallback(
    (evt: MouseEvent<HTMLCanvasElement>) => {
      const canvas = canvasRef.current
      const g = graphRef?.current
      if (!canvas || !g) return

      const rect = canvas.getBoundingClientRect()
      const cx = evt.clientX - rect.left
      const cy = evt.clientY - rect.top

      // Recompute bbox quickly (same as draw; keep it simple).
      let xmin = Infinity
      let xmax = -Infinity
      let ymin = Infinity
      let ymax = -Infinity
      for (const p of nodePositions) {
        xmin = Math.min(xmin, p.x)
        xmax = Math.max(xmax, p.x)
        ymin = Math.min(ymin, p.y)
        ymax = Math.max(ymax, p.y)
      }
      if (!Number.isFinite(xmin) || !Number.isFinite(xmax) || xmax - xmin <= 0) return
      if (!Number.isFinite(ymin) || !Number.isFinite(ymax) || ymax - ymin <= 0) return

      const tx = xmin + (cx / canvas.width) * (xmax - xmin)
      const ty = ymin + (cy / canvas.height) * (ymax - ymin)

      try {
        g.centerAt?.(tx, ty, 400)
      } catch {}
    },
    [graphRef, nodePositions]
  )

  return (
    <div
      className={cn(
        'rounded-xl border border-border/50 bg-card/60 shadow-sm backdrop-blur-sm',
        className
      )}
    >
      <canvas
        ref={canvasRef}
        width={width}
        height={height}
        className="block cursor-pointer rounded-xl"
        onClick={handleClick}
        aria-label="Graph minimap"
      />
    </div>
  )
}
