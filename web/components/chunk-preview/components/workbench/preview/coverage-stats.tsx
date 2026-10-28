'use client'

import { AlertCircle, ChevronDown } from '@/components/icons'
import { Button } from '@/components/ui/button'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import type { ChunkPreviewStats } from '@/types'
import { cn } from '@/lib/utils'
import styles from '../compare.module.css'

function percentage(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value)
    ? Math.max(0, Math.min(100, Math.round(value * 100)))
    : null
}

function integer(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? Math.max(0, Math.trunc(value)) : null
}

/** Display API coverage statistics without inventing a spatial distribution. */
export function CoverageStats({ stats, className }: Readonly<{ stats?: ChunkPreviewStats; className?: string }>) {
  const coverage = percentage(stats?.coverage_ratio)
  const overlap = percentage(stats?.overlap_waste_ratio)
  const gaps = integer(stats?.gap_count)
  const largestGap = integer(stats?.largest_gap)
  if (coverage === null && overlap === null && gaps === null && largestGap === null) return null

  return <Popover>
    <PopoverTrigger asChild>
      <Button variant="ghost" className={styles.coverageTrigger}>覆盖统计<ChevronDown /></Button>
    </PopoverTrigger>
    <PopoverContent align="end" sideOffset={8} className={cn(styles.coveragePanel, className)} aria-label="原文覆盖统计">
      <h3>原文覆盖统计</h3>
      <dl className={styles.coverageMetrics}>
        <div><dt>覆盖率</dt><dd>{coverage === null ? '—' : `${coverage}%`}</dd></div>
        <div><dt>重叠浪费</dt><dd className={overlap !== null && overlap > 8 ? styles.coverageWarning : undefined}>{overlap === null ? '—' : `${overlap}%`}</dd></div>
        <div><dt>缺口</dt><dd className={gaps !== null && gaps > 0 ? styles.coverageWarning : undefined}>{gaps !== null && gaps > 0 ? <AlertCircle aria-hidden="true" /> : null}{gaps ?? '—'}</dd></div>
      </dl>
      {coverage !== null ? <div className={styles.coverageTrack} role="progressbar" aria-label="原文覆盖率" aria-valuemin={0} aria-valuemax={100} aria-valuenow={coverage}><span style={{ width: `${coverage}%` }} /></div> : null}
      {largestGap !== null ? <p className={styles.coverageFootnote}>最大缺口 <span>{largestGap}</span> 字符</p> : null}
    </PopoverContent>
  </Popover>
}
