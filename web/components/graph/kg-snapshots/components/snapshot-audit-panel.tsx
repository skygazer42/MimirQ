'use client'

import { BarChart3, Layers, ShieldAlert } from '@/components/icons'
import type { ReactNode } from 'react'
import { Bar, BarChart, CartesianGrid, Tooltip, XAxis, YAxis } from 'recharts'

import { Badge } from '@/components/ui/badge'
import { SafeResponsiveChart } from '@/components/ui/safe-responsive-chart'
import { Switch } from '@/components/ui/switch'
import { cn } from '@/lib/utils'

import {
  DELTA_BADGE_VARIANTS,
  DELTA_LABELS,
  DELTA_TEXT_CLASSES,
  DELTA_TINT_CLASSES,
  SNAPSHOT_COUNT_LABELS,
} from '../constants'
import type { AuditSeverity, SnapshotChartTooltipProps, SnapshotDeltaRow, SnapshotDiffEntityRow } from '../types'
import { deltaDirection, deltaFill, deltaSign, driftScoreToneForSeverity, toneClassForDelta } from '../utils'
import { SectionHeading, SnapshotInlineStat } from './shared'

function auditSeverityMeta(severity: AuditSeverity): {
  label: string
  icon: ReactNode
} {
  if (severity === 'warning') {
    return {
      label: '数量变化较大',
      icon: <ShieldAlert className="h-3.5 w-3.5" aria-hidden="true" />,
    }
  }
  if (severity === 'notice') {
    return {
      label: '数量有变化',
      icon: <BarChart3 className="h-3.5 w-3.5" aria-hidden="true" />,
    }
  }
  return {
    label: '数量变化较小',
    icon: <BarChart3 className="h-3.5 w-3.5" aria-hidden="true" />,
  }
}

function SnapshotChartTooltip({ active, payload }: Readonly<SnapshotChartTooltipProps>) {
  const row = payload?.[0]?.payload
  if (!active || !row) return null
  const sign = row.delta > 0 ? '+' : ''
  return (
    <div className="rounded-lg border border-border/70 bg-card px-3 py-2 shadow-sm">
      <div className="text-xs text-muted-foreground">{SNAPSHOT_COUNT_LABELS[row.key]}</div>
      <div className="mt-1 flex items-center gap-2 text-[13px]">
        <span className="font-mono text-muted-foreground">A {row.a}</span>
        <span className="font-mono text-muted-foreground">B {row.b}</span>
        <span
          className={cn(
            'font-mono font-semibold',
            deltaDirection(row.delta) === 'flat' ? 'text-foreground' : toneClassForDelta(row.delta),
          )}
        >
          Δ {sign}
          {row.delta}
        </span>
      </div>
    </div>
  )
}

export function SnapshotAuditPanel({
  deltaRows,
  typeDriftRows,
  severity,
  driftScore,
  includeZeroDeltas,
  compactRows,
  onIncludeZeroDeltasChange,
  onCompactRowsChange,
}: Readonly<{
  deltaRows: SnapshotDeltaRow[]
  typeDriftRows: SnapshotDiffEntityRow[]
  severity: AuditSeverity
  driftScore: number
  includeZeroDeltas: boolean
  compactRows: boolean
  onIncludeZeroDeltasChange: (value: boolean) => void
  onCompactRowsChange: (value: boolean) => void
}>) {
  const severityMeta = auditSeverityMeta(severity)
  const changedRows = deltaRows.filter((row) => row.delta !== 0)
  const chartRows = includeZeroDeltas ? deltaRows : changedRows
  const chartRowsWithFill = chartRows.map((row) => ({
    ...row,
    label: SNAPSHOT_COUNT_LABELS[row.key],
    fill: deltaFill(row.delta),
  }))
  const shownDriftRows = compactRows ? typeDriftRows.slice(0, 14) : typeDriftRows
  const driftScoreTone = driftScoreToneForSeverity(severity)

  return (
    <div className="flex min-w-0 flex-col">
      <div className="shrink-0 px-1 pb-5">
        <SectionHeading
          title="数量变化统计"
          description="比较两版文档及图谱结构的数量。"
          icon={<BarChart3 className="h-5 w-5" aria-hidden="true" />}
          extra={
            <span className="inline-flex items-center gap-1.5 text-xs text-muted-foreground">
              {severityMeta.icon}
              {severityMeta.label}
            </span>
          }
        />
        <div className="mt-4 flex flex-wrap items-center gap-x-6 gap-y-2">
          <SnapshotInlineStat label="数量差异比" value={driftScore.toFixed(2)} tone={driftScoreTone} />
          <SnapshotInlineStat
            label="类型变化"
            value={typeDriftRows.length}
            tone={typeDriftRows.length > 0 ? 'positive' : 'muted'}
          />
          <SnapshotInlineStat label="变化项" value={changedRows.length} tone="neutral" />
        </div>
      </div>

      <div className="grid min-w-0 xl:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)]">
        <div className="min-h-0 border-b border-border/70 xl:border-b-0 xl:border-r">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border/70 px-4 py-2.5">
            <div className="inline-flex items-center gap-2 text-[13px] font-medium text-foreground">
              <BarChart3 className="h-3.5 w-3.5 text-primary/70" aria-hidden="true" />
              数量差异分布
            </div>
            <div className="flex items-center gap-4">
              <label className="inline-flex items-center gap-2 text-xs text-muted-foreground">
                <Switch checked={includeZeroDeltas} onCheckedChange={onIncludeZeroDeltasChange} />
                显示 0 值
              </label>
            </div>
          </div>

          <div className="px-3 py-2">
            <SafeResponsiveChart className="h-[280px]" minHeight={280}>
              <BarChart data={chartRowsWithFill} margin={{ top: 8, right: 10, left: -16, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="hsl(var(--border))" />
                <XAxis
                  dataKey="label"
                  tick={{ fontSize: 12, fill: 'hsl(var(--muted-foreground))' }}
                  axisLine={false}
                  tickLine={false}
                />
                <YAxis
                  tick={{ fontSize: 12, fill: 'hsl(var(--muted-foreground))' }}
                  axisLine={false}
                  tickLine={false}
                  allowDecimals={false}
                />
                <Tooltip cursor={{ fill: 'rgba(148, 163, 184, 0.08)' }} content={<SnapshotChartTooltip />} />
                <Bar dataKey="delta" radius={[3, 3, 0, 0]} isAnimationActive={false} />
              </BarChart>
            </SafeResponsiveChart>
          </div>
        </div>

        <div className="min-h-0 flex flex-col">
          <div className="flex items-center justify-between gap-2 border-b border-border/70 px-4 py-2.5">
            <div className="inline-flex items-center gap-2 text-[13px] font-medium text-foreground">
              <Layers className="h-3.5 w-3.5 text-primary/70" aria-hidden="true" />
              实体类型变化
            </div>
            <label className="inline-flex items-center gap-2 text-xs text-muted-foreground">
              <Switch checked={compactRows} onCheckedChange={onCompactRowsChange} />
              紧凑模式
            </label>
          </div>

          <div className="min-h-0 flex-1 overflow-auto">
            {shownDriftRows.length ? (
              shownDriftRows.map((row, index) => {
                const type = row.type || '未返回类型名'
                const delta = row.delta
                const direction = typeof delta === 'number' ? deltaDirection(delta) : null
                const deltaLabel = typeof delta === 'number' ? `Δ ${deltaSign(delta)}${delta}` : '未取得'
                return (
                  <div
                    key={`drift:${type}:${index}`}
                    className="grid w-full grid-cols-[minmax(0,1fr)_auto_auto] items-center gap-2 border-b border-border/60 px-4 py-2 text-left"
                    title={`${type} ${deltaLabel}`}
                  >
                    <span className="truncate text-[13px] text-foreground">{type}</span>
                    <span
                      className={cn(
                        'inline-flex min-w-[52px] items-center justify-center rounded-md px-2 py-0.5 text-[13px] font-semibold tabular-nums ring-1',
                        direction === null ? 'text-muted-foreground' : DELTA_TINT_CLASSES[direction],
                        direction !== null && DELTA_TEXT_CLASSES[direction],
                      )}
                    >
                      {deltaLabel}
                    </span>
                    {direction !== null && (
                      <Badge variant={DELTA_BADGE_VARIANTS[direction]} className="text-xs">
                        {DELTA_LABELS[direction]}
                      </Badge>
                    )}
                  </div>
                )
              })
            ) : (
              <div className="flex h-full items-center justify-center px-4 py-12">
                <div className="flex max-w-[320px] flex-col items-center text-center">
                  <div className="flex size-8 items-center justify-center text-muted-foreground">
                    <Layers className="h-5 w-5" aria-hidden="true" />
                  </div>
                  <div className="mt-3 text-[13px] font-semibold text-foreground">未返回类型变化</div>
                  <div className="mt-1 text-[13px] leading-6 text-muted-foreground">当前结果没有实体类型变化明细。</div>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
