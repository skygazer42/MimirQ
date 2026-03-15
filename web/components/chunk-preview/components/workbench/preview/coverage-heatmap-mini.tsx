/**
 * CoverageHeatmapMini - tiny, PII-safe visual for chunk coverage continuity.
 *
 * Renders a fixed number of bins across the document length:
 * - empty bins => gaps (red tint)
 * - non-empty bins => coverage intensity (primary tint)
 */
'use client'

import { useMemo } from 'react'

import type { ChunkPreviewItem } from '@/types'
import { cn } from '@/lib/utils'
import { computeCoverageHeatmapBins } from '@/components/chunk-preview/utils/coverage-heatmap'

function clampInt(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, Math.trunc(value)))
}

export function CoverageHeatmapMini(props: Readonly<{
  chunks: ChunkPreviewItem[]
  totalChars: number
  strategy?: string
  bins?: number
  className?: string
}>) {
  const { chunks, totalChars, strategy, bins, className } = props

  const model = useMemo(() => {
    const out = computeCoverageHeatmapBins(chunks || [], totalChars, { bins: bins ?? 72, strategy })
    const gapBins = out.counts.reduce((acc, c) => acc + (c <= 0 ? 1 : 0), 0)
    const max = Math.max(0, out.max || 0)
    return {
      ...out,
      max,
      gapBins,
      gapPct: out.bins > 0 ? Math.round((gapBins / out.bins) * 100) : 0,
    }
  }, [bins, chunks, strategy, totalChars])

  const keyedCounts = useMemo(
    () => model.counts.map((count, index) => ({ count, key: `bin-${index + 1}` })),
    [model.counts]
  )

  if (!model.bins) return null

  const title = `coverage bins: ${model.bins - model.gapBins}/${model.bins} · gaps ~${model.gapPct}% · max overlap ${model.max}`
  const aria = `Coverage heatmap: ${model.bins - model.gapBins} of ${model.bins} bins covered; max overlap ${model.max}`

  return (
    <div
      className={cn('flex items-center gap-[1px] rounded bg-muted/30 border border-border/60 px-1 py-0.5', className)}
      role="img"
      aria-label={aria}
      title={title}
    >
      {keyedCounts.map(({ count, key }) => {
        const c = clampInt(count, 0, 999)
        const alpha =
          c <= 0
            ? 0.18
            : Math.min(0.9, 0.15 + 0.75 * (model.max > 0 ? c / model.max : 1))
        const bg =
          c <= 0 ? `hsl(var(--destructive) / ${alpha})` : `hsl(var(--primary) / ${alpha})`
        return (
          <span
            key={key}
            className="h-3 w-[2px] rounded-[1px]"
            style={{ backgroundColor: bg }}
          />
        )
      })}
    </div>
  )
}
