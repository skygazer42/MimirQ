'use client'

import { Activity } from 'lucide-react'

import { cn } from '@/lib/utils'

import type { VelocityUnit } from './monitor-utils'

export const VELOCITY_STORAGE_KEY = 'mimirq.ingestion.velocityUnit'

export function readStoredVelocityUnit(): VelocityUnit {
  if (typeof window === 'undefined') return 'docs'
  const value = window.localStorage.getItem(VELOCITY_STORAGE_KEY)
  return value === 'bytes' ? 'bytes' : 'docs'
}

export function persistVelocityUnit(unit: VelocityUnit) {
  if (typeof window === 'undefined') return
  window.localStorage.setItem(VELOCITY_STORAGE_KEY, unit)
}

function formatValue(value: number | null, unit: VelocityUnit): string {
  if (value == null) return '--'
  return unit === 'docs' ? `${value.toFixed(1)} docs/min` : `${value.toFixed(2)} MB/s`
}

export function LiveVelocity({
  unit,
  docsPerMinute,
  megabytesPerSecond,
  onToggle,
}: Readonly<{
  unit: VelocityUnit
  docsPerMinute: number | null
  megabytesPerSecond: number | null
  onToggle: () => void
}>) {
  const displayValue = unit === 'docs' ? docsPerMinute : megabytesPerSecond

  return (
    <button
      type="button"
      aria-pressed={unit === 'bytes'}
      onClick={onToggle}
      className={cn(
        'inline-flex items-center gap-2 rounded-lg border border-sky-500/20 bg-sky-500/5 px-2 py-1 text-[11px] font-bold uppercase  text-sky-600 transition-colors hover:bg-sky-500/10 motion-reduce:transition-none',
        'dark:text-sky-400'
      )}
      title="点击切换 docs/min 与 MB/s"
    >
      <Activity className="h-3.5 w-3.5" />
      <span className="text-[10px] font-semibold text-sky-700/80 dark:text-sky-300/80">处理效率</span>
      <span className="tabular-nums">{formatValue(displayValue, unit)}</span>
      <span className="text-[10px] font-medium opacity-60">近 5 min 均值</span>
    </button>
  )
}
