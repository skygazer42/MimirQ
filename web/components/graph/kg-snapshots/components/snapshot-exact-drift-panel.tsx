'use client'

import { Database, Link2, Sparkles } from 'lucide-react'
import type { ReactNode } from 'react'

import { cn } from '@/lib/utils'

import type { SnapshotDiffPayload } from '../types'
import { exactDiffCount, exactDiffSample, firstDisplayString } from '../utils'

export function DriftCounterCluster({
  groupIcon,
  groupLabel,
  added,
  removed,
  changed,
}: Readonly<{
  groupIcon: ReactNode
  groupLabel: string
  added: number
  removed: number
  changed: number
}>) {
  const total = added + removed + changed
  return (
    <div className="flex items-center gap-3 rounded-xl border border-border/70 bg-card px-3 py-2 shadow-sm">
      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
        {groupIcon}
      </div>
      <div className="flex min-w-0 flex-1 items-center justify-between gap-2">
        <div className="min-w-0">
          <div className="text-[10.5px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
            {groupLabel}
          </div>
          <div className="mt-0.5 text-[10px] text-muted-foreground/80">
            {total > 0 ? `共 ${total} 条变更` : '暂无变更'}
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          <span className="inline-flex min-w-[40px] items-center justify-center gap-0.5 rounded-md bg-success/10 px-1.5 py-1 font-mono text-[11px] font-semibold tabular-nums text-success ring-1 ring-success/30">
            <span aria-hidden className="opacity-70">
              +
            </span>
            {added}
          </span>
          <span className="inline-flex min-w-[40px] items-center justify-center gap-0.5 rounded-md bg-destructive/10 px-1.5 py-1 font-mono text-[11px] font-semibold tabular-nums text-destructive ring-1 ring-destructive/30">
            <span aria-hidden className="opacity-70">
              −
            </span>
            {removed}
          </span>
          <span className="inline-flex min-w-[40px] items-center justify-center gap-0.5 rounded-md bg-warning/10 px-1.5 py-1 font-mono text-[11px] font-semibold tabular-nums text-warning ring-1 ring-warning/30">
            <span aria-hidden className="opacity-70">
              Δ
            </span>
            {changed}
          </span>
        </div>
      </div>
    </div>
  )
}

export function SnapshotExactDriftPanel({
  diff,
}: Readonly<{ diff: SnapshotDiffPayload | null }>) {
  const nodeSummary = diff?.node_diff
  const edgeSummary = diff?.edge_diff
  const hasExactDiff = Boolean(nodeSummary || edgeSummary)
  const sampleRows = [
    {
      label: '新增节点',
      key: 'nodes_added',
      icon: <Database className="h-3.5 w-3.5" />,
      tone: 'text-success',
      tint: 'bg-success/10',
    },
    {
      label: '移除节点',
      key: 'nodes_removed',
      icon: <Database className="h-3.5 w-3.5" />,
      tone: 'text-destructive',
      tint: 'bg-destructive/10',
    },
    {
      label: '变更节点',
      key: 'nodes_changed',
      icon: <Database className="h-3.5 w-3.5" />,
      tone: 'text-warning',
      tint: 'bg-warning/10',
    },
    {
      label: '新增边',
      key: 'edges_added',
      icon: <Link2 className="h-3.5 w-3.5" />,
      tone: 'text-success',
      tint: 'bg-success/10',
    },
    {
      label: '移除边',
      key: 'edges_removed',
      icon: <Link2 className="h-3.5 w-3.5" />,
      tone: 'text-destructive',
      tint: 'bg-destructive/10',
    },
    {
      label: '变更边',
      key: 'edges_changed',
      icon: <Link2 className="h-3.5 w-3.5" />,
      tone: 'text-warning',
      tint: 'bg-warning/10',
    },
  ]

  return (
    <div className="border-b border-border/70 bg-[linear-gradient(180deg,hsl(var(--background)),hsl(var(--muted)/0.10))] px-4 py-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="inline-flex items-center gap-1.5 text-[10.5px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
            <Sparkles
              className="h-3.5 w-3.5 text-primary/70"
              aria-hidden="true"
            />
            精确节点/边 Diff
          </div>
          <div className="mt-1 max-w-[560px] text-[11px] leading-5 text-muted-foreground">
            {hasExactDiff
              ? '后端已返回 bounded nodes / edges 明细，可直接定位新增、移除和属性变化。'
              : '当前 diff 只有聚合计数；重新执行对比会请求 include_details=true。'}
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <DriftCounterCluster
            groupIcon={<Database className="h-4 w-4" />}
            groupLabel="Node"
            added={exactDiffCount(nodeSummary, 'added_count')}
            removed={exactDiffCount(nodeSummary, 'removed_count')}
            changed={exactDiffCount(nodeSummary, 'changed_count')}
          />
          <DriftCounterCluster
            groupIcon={<Link2 className="h-4 w-4" />}
            groupLabel="Edge"
            added={exactDiffCount(edgeSummary, 'added_count')}
            removed={exactDiffCount(edgeSummary, 'removed_count')}
            changed={exactDiffCount(edgeSummary, 'changed_count')}
          />
        </div>
      </div>

      {hasExactDiff ? (
        <div className="mt-3 grid gap-2 lg:grid-cols-3">
          {sampleRows.map((row) => {
            const items = exactDiffSample(diff, row.key)
            const preview = items
              .slice(0, 3)
              .map((item) => firstDisplayString(item.name, item.id) || 'unknown')
              .join(' / ')
            return (
              <div
                key={row.key}
                className="rounded-lg border border-border/70 bg-card px-3 py-2 transition-shadow hover:shadow-sm"
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="inline-flex items-center gap-1.5 text-[11px] font-medium text-muted-foreground">
                    <span
                      className={cn(
                        'flex h-5 w-5 items-center justify-center rounded-md',
                        row.tint,
                        row.tone
                      )}
                    >
                      {row.icon}
                    </span>
                    {row.label}
                  </span>
                  <span
                    className={cn(
                      'font-mono text-[11px] font-semibold tabular-nums',
                      row.tone
                    )}
                  >
                    {items.length}
                  </span>
                </div>
                <div
                  className="mt-1 truncate font-mono text-[11px] text-muted-foreground"
                  title={preview || '暂无样本'}
                >
                  {preview || '暂无样本'}
                </div>
              </div>
            )
          })}
        </div>
      ) : null}
    </div>
  )
}
