/**
 * CoverageHeatmapMini - tiny, PII-safe visual for chunk coverage continuity.
 *
 * All visible metrics and bars are derived from backend stats only. The UI does
 * not recompute coverage quality from chunk ranges.
 */
'use client'

import { useMemo } from 'react'

import type { ChunkPreviewStats } from '@/types'
import { cn } from '@/lib/utils'

function ratioToPct(value: unknown): number | null {
  if (typeof value !== 'number' || !Number.isFinite(value)) return null
  return Math.max(0, Math.min(100, Math.round(value * 100)))
}

function statInt(value: unknown): number | null {
  if (typeof value !== 'number' || !Number.isFinite(value)) return null
  return Math.max(0, Math.trunc(value))
}

export function CoverageHeatmapMini(props: Readonly<{
  stats?: ChunkPreviewStats
  className?: string
}>) {
  const { stats, className } = props

  const backendStats = useMemo(() => {
    const coveragePct = ratioToPct(stats?.coverage_ratio)
    const overlapWastePct = ratioToPct(stats?.overlap_waste_ratio)
    const gapCount = statInt(stats?.gap_count)
    const largestGap = statInt(stats?.largest_gap)
    return {
      coveragePct,
      overlapWastePct,
      gapCount,
      largestGap,
      hasAny: coveragePct != null || overlapWastePct != null || gapCount != null || largestGap != null,
    }
  }, [stats?.coverage_ratio, stats?.overlap_waste_ratio, stats?.gap_count, stats?.largest_gap])

  const backendBars = useMemo(() => {
    const total = 18
    const covered = Math.max(0, Math.min(total, Math.round(((backendStats.coveragePct ?? 0) / 100) * total)))
    const hasRisk = (backendStats.gapCount ?? 0) > 0 || (backendStats.overlapWastePct ?? 0) > 8
    return Array.from({ length: total }, (_, index) => ({
      key: `backend-bin-${index + 1}`,
      active: index < covered,
      height: `${Math.max(6, Math.round(6 + (index / Math.max(1, total - 1)) * 8))}px`,
      tone: hasRisk ? 'risk' : 'healthy',
    }))
  }, [backendStats.coveragePct, backendStats.gapCount, backendStats.overlapWastePct])

  if (!backendStats.hasAny) return null

  const coverageLabel = backendStats.coveragePct == null ? '--' : `${backendStats.coveragePct}%`
  const overlapLabel = backendStats.overlapWastePct == null ? '--' : `${backendStats.overlapWastePct}%`
  const gapLabel = backendStats.gapCount == null ? '--' : String(backendStats.gapCount)
  const largestGapLabel = backendStats.largestGap == null ? '--' : String(backendStats.largestGap)
  const overlapDisplayLabel = backendStats.overlapWastePct === 0 ? '无重叠' : `重叠 ${overlapLabel}`
  const gapDisplayLabel = backendStats.gapCount === 0 ? '无缺口' : `缺口 ${gapLabel}`
  const title = `后端统计：覆盖 ${coverageLabel} · 重叠浪费 ${overlapLabel} · 缺口 ${gapLabel} · 最大缺口 ${largestGapLabel}`
  const aria = `后端切片统计：覆盖率 ${coverageLabel}，重叠浪费 ${overlapLabel}，缺口 ${gapLabel}，最大缺口 ${largestGapLabel}`
  const statusTone =
    (backendStats.gapCount ?? 0) <= 0 && (backendStats.overlapWastePct ?? 0) <= 8
      ? 'text-emerald-700 dark:text-emerald-300'
      : (backendStats.gapCount ?? 0) <= 2
        ? 'text-amber-700 dark:text-amber-300'
        : 'text-destructive'
  const pulseTone =
    (backendStats.gapCount ?? 0) <= 0 && (backendStats.overlapWastePct ?? 0) <= 8
      ? 'bg-emerald-500/80'
      : (backendStats.gapCount ?? 0) <= 2
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
      <span className={cn('hidden h-1.5 w-1.5 rounded-full motion-safe:animate-pulse xl:inline-flex', pulseTone)} />

      <div className="flex items-end gap-[2px] rounded-md border border-border/40 bg-[linear-gradient(180deg,hsl(var(--background)/0.84),hsl(var(--muted)/0.32))] px-1.5 py-1">
        {backendBars.map(({ active, height, key, tone }) => {
          const bg = active
            ? tone === 'risk'
              ? 'hsl(35 92% 52% / 0.78)'
              : 'hsl(160 84% 38% / 0.72)'
            : 'hsl(var(--muted-foreground) / 0.16)'
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
          覆盖 {coverageLabel}
        </span>
        <span className={cn('tabular-nums transition-colors duration-300 motion-reduce:transition-none', (backendStats.overlapWastePct ?? 0) > 8 ? 'text-amber-700 dark:text-amber-300' : 'text-muted-foreground')}>
          {overlapDisplayLabel}
        </span>
        <span className={cn('tabular-nums transition-colors duration-300 motion-reduce:transition-none', (backendStats.gapCount ?? 0) > 0 ? 'text-amber-700 dark:text-amber-300' : 'text-muted-foreground')}>
          {gapDisplayLabel}
        </span>
      </div>
    </div>
  )
}
