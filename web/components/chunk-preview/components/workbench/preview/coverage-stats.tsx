'use client'

import { AlertCircle, ChevronDown } from '@/components/icons'
import { Button } from '@/components/ui/button'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import type { ChunkPreviewResponse } from '@/types'
import styles from '../compare.module.css'

function ratioToPercent(ratio: number | undefined): number | null {
  if (typeof ratio === 'number' && ratio >= 0 && ratio <= 1) return Math.round(ratio * 100)
  return null
}

function readGapMetric(value: number | undefined): number | null {
  if (typeof value === 'number' && Number.isInteger(value) && value >= 0) return value
  return null
}

export function CoverageStats({ stats }: Readonly<{ stats: ChunkPreviewResponse['stats'] }>) {
  const coverage = ratioToPercent(stats?.coverage_ratio)
  const overlap = ratioToPercent(stats?.overlap_waste_ratio)
  const gaps = readGapMetric(stats?.gap_count)
  const largestGap = readGapMetric(stats?.largest_gap)
  if (coverage === null && overlap === null && gaps === null && largestGap === null) return null

  const hasGaps = gaps !== null && gaps > 0

  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button variant="ghost" className={styles.coverageTrigger}>
          覆盖统计
          <ChevronDown />
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" sideOffset={8} className={styles.coveragePanel} aria-label="原文覆盖统计">
        <h3>原文覆盖统计</h3>
        <dl className={styles.coverageMetrics}>
          <div>
            <dt>覆盖率</dt>
            <dd>{coverage === null ? '—' : `${coverage}%`}</dd>
          </div>
          <div>
            <dt>重叠浪费</dt>
            <dd className={overlap !== null && overlap > 8 ? styles.coverageWarning : undefined}>
              {overlap === null ? '—' : `${overlap}%`}
            </dd>
          </div>
          <div>
            <dt>缺口</dt>
            <dd className={hasGaps ? styles.coverageWarning : undefined}>
              {hasGaps && <AlertCircle aria-hidden="true" />}
              {gaps ?? '—'}
            </dd>
          </div>
        </dl>
        {coverage !== null ? (
          <div
            className={styles.coverageTrack}
            role="progressbar"
            aria-label="原文覆盖率"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={coverage}
          >
            <span style={{ width: `${coverage}%` }} />
          </div>
        ) : null}
        {largestGap !== null ? (
          <p className={styles.coverageFootnote}>
            最大缺口 <span>{largestGap}</span> 字符
          </p>
        ) : null}
      </PopoverContent>
    </Popover>
  )
}
