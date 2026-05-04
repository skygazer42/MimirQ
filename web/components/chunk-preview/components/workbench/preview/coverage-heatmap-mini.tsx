/**
 * CoverageHeatmapMini - tiny, PII-safe visual for chunk coverage continuity.
 *
 * Previous versions rendered only a dense strip of bins, which was compact
 * but hard to interpret. This version keeps the sparkline while surfacing
 * the key summary signals explicitly:
 * - coverage percentage
 * - gap percentage
 * - max overlap
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
    const out = computeCoverageHeatmapBins(chunks || [], totalChars, { bins: bins ?? 24, strategy })
    const gapBins = out.counts.reduce((acc, c) => acc + (c <= 0 ? 1 : 0), 0)
    const max = Math.max(0, out.max || 0)
    const coveredBins = Math.max(0, out.bins - gapBins)
    return {
      ...out,
      max,
      coveredBins,
      gapBins,
      coveragePct: out.bins > 0 ? Math.round((coveredBins / out.bins) * 100) : 0,
      gapPct: out.bins > 0 ? Math.round((gapBins / out.bins) * 100) : 0,
    }
  }, [bins, chunks, strategy, totalChars])

  const keyedCounts = useMemo(
    () => model.counts.map((count, index) => ({ count, key: `bin-${index + 1}` })),
    [model.counts]
  )

  if (!model.bins) return null

  const title = `coverage ${model.coveragePct}% · gaps ${model.gapPct}% · max overlap ${model.max}`
  const aria = `Coverage summary: ${model.coveragePct} percent covered, ${model.gapPct} percent gaps, max overlap ${model.max}`
  const statusTone =
    model.gapPct <= 2 && model.max <= 1
      ? 'text-emerald-700 dark:text-emerald-300'
      : model.gapPct <= 8
        ? 'text-amber-700 dark:text-amber-300'
        : 'text-destructive'
  const pulseTone =
    model.gapPct <= 2 && model.max <= 1
      ? 'bg-emerald-500/80'
      : model.gapPct <= 8
        ? 'bg-amber-500/80'
        : 'bg-rose-500/80'

  return (
    <div
      className={cn(
        'flex items-center gap-2 rounded-md border border-border/60 bg-[linear-gradient(180deg,hsl(var(--background)),hsl(var(--muted)/0.22))] px-2 py-1 shadow-[inset_0_1px_0_rgba(255,255,255,0.55)]',
        className
      )}
      role="img"
      aria-label={aria}
      title={title}
    >
      <div className="hidden xl:flex min-w-0 flex-col leading-none">
        <div className="flex items-center gap-1">
          <span className={cn('h-1.5 w-1.5 rounded-full motion-safe:animate-pulse', pulseTone)} />
          <span className="text-[8px] font-semibold uppercase tracking-[0.16em] text-muted-foreground/75">
            Coverage
          </span>
        </div>
        <span className={cn('mt-1 text-[10px] font-semibold tabular-nums transition-colors duration-300 motion-reduce:transition-none', statusTone)}>
          {model.coveragePct}%
        </span>
      </div>

      <div className="flex items-end gap-[2px] rounded-md border border-border/40 bg-[linear-gradient(180deg,hsl(var(--background)/0.84),hsl(var(--muted)/0.32))] px-1.5 py-1">
        {keyedCounts.map(({ count, key }) => {
          const c = clampInt(count, 0, 999)
          const ratio = model.max > 0 ? c / model.max : 0
          const alpha =
            c <= 0
              ? 0.22
              : Math.min(0.92, 0.2 + 0.72 * ratio)
          const bg =
            c <= 0
              ? `hsl(var(--destructive) / ${alpha})`
              : c === 1
                ? `hsl(160 84% 38% / ${alpha})`
                : c === 2
                  ? `hsl(192 88% 42% / ${alpha})`
                  : `hsl(35 92% 52% / ${alpha})`
          const height =
            c <= 0
              ? '0.375rem'
              : `${Math.max(6, Math.round(6 + ratio * 8))}px`
          return (
            <span
              key={key}
              className="w-[3px] rounded-[2px] transition-[height,background-color,transform] duration-500 ease-out motion-reduce:transition-none"
              style={{ backgroundColor: bg, height }}
            />
          )
        })}
      </div>

      <div className="flex items-center gap-1.5 text-[9px] font-mono text-muted-foreground">
        <span className={cn('tabular-nums transition-colors duration-300 motion-reduce:transition-none', statusTone)}>
          {model.coveragePct}%
        </span>
        <span className={cn('tabular-nums transition-colors duration-300 motion-reduce:transition-none', model.gapPct > 0 ? 'text-amber-700 dark:text-amber-300' : 'text-muted-foreground')}>
          gap {model.gapPct}%
        </span>
        <span className={cn('tabular-nums transition-colors duration-300 motion-reduce:transition-none', model.max > 2 ? 'text-amber-700 dark:text-amber-300' : model.max > 1 ? 'text-sky-700 dark:text-sky-300' : 'text-muted-foreground')}>
          x{model.max}
        </span>
      </div>
    </div>
  )
}
