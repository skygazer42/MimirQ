'use client'

import { Copy, Download, Layers } from 'lucide-react'
import { useMemo, type ReactNode } from 'react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'

import { buildSideBySideDiffRows } from '../json-diff'
import type { SnapshotDiffEntityRow, SnapshotDiffPayload } from '../types'
import { toneClassForDelta } from '../utils'
import { JsonDiffCell } from './json-code-pane'
import { SnapshotExactDriftPanel } from './snapshot-exact-drift-panel'

export function SnapshotDiffView({
  titleA,
  titleB,
  subtitleA,
  subtitleB,
  leftCode,
  rightCode,
  diff,
  typeDrift,
  isEmpty,
  emptyState,
  onCopy,
  onDownload,
}: Readonly<{
  titleA: string
  titleB: string
  subtitleA?: string
  subtitleB?: string
  leftCode: string
  rightCode: string
  diff: SnapshotDiffPayload | null
  typeDrift: SnapshotDiffEntityRow[]
  isEmpty?: boolean
  emptyState?: ReactNode
  onCopy: () => void
  onDownload: () => void
}>) {
  const rows = useMemo(
    () => buildSideBySideDiffRows(leftCode, rightCode),
    [leftCode, rightCode]
  )

  return (
    <div className="flex h-full min-h-0 flex-col bg-card">
      <div className="flex shrink-0 items-center justify-between gap-3 border-b border-border/70 bg-background px-4 py-2">
        <div className="min-w-0 flex-1">
          {typeDrift.length > 0 ? (
            <div className="flex flex-wrap items-center gap-2">
              <span className="inline-flex items-center gap-1.5 text-[10.5px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
                <Layers
                  className="h-3.5 w-3.5 text-primary/70"
                  aria-hidden="true"
                />
                Type Drift
              </span>
              {typeDrift.slice(0, 8).map((row) => {
                const type = String(row.type || 'unknown')
                const delta = Number(row.delta ?? 0)
                const sign = delta > 0 ? '+' : ''
                return (
                  <Badge
                    key={`${type}:${delta}`}
                    variant="outline"
                    className="inline-flex items-center gap-1 font-mono text-[11px]"
                  >
                    <span className="text-muted-foreground">{type}</span>
                    <span className={toneClassForDelta(delta)}>
                      {sign + delta}
                    </span>
                  </Badge>
                )
              })}
            </div>
          ) : (
            <span className="inline-flex items-center gap-1.5 text-[10.5px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
              <Layers
                className="h-3.5 w-3.5 text-muted-foreground/60"
                aria-hidden="true"
              />
              Type Drift · 暂无
            </span>
          )}
        </div>
        <div className="flex shrink-0 items-center gap-1">
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8 rounded-lg"
            title="复制 Diff JSON"
            onClick={onCopy}
            disabled={isEmpty}
          >
            <Copy className="h-4 w-4" aria-hidden="true" />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8 rounded-lg"
            title="导出 Diff JSON"
            onClick={onDownload}
            disabled={isEmpty}
          >
            <Download className="h-4 w-4" aria-hidden="true" />
          </Button>
        </div>
      </div>

      <SnapshotExactDriftPanel diff={diff} />

      <div className="min-h-0 flex-1 overflow-auto bg-card">
        {isEmpty && emptyState ? (
          emptyState
        ) : (
          <div className="min-w-[980px]">
            <div className="sticky top-0 z-10 grid grid-cols-[52px_minmax(0,1fr)_52px_minmax(0,1fr)] border-b border-border/70 bg-[linear-gradient(180deg,hsl(var(--background)),hsl(var(--muted)/0.10))] text-[12px] backdrop-blur">
              <div className="border-r border-border/70 px-3 py-2 text-right font-mono text-muted-foreground">
                #
              </div>
              <div className="border-r border-border/70 px-3 py-2">
                <div className="text-[12px] font-semibold tracking-[-0.01em] text-foreground">
                  {titleA}
                </div>
                {subtitleA ? (
                  <div className="truncate text-[11px] text-muted-foreground">
                    {subtitleA}
                  </div>
                ) : null}
              </div>
              <div className="border-r border-border/70 px-3 py-2 text-right font-mono text-muted-foreground">
                #
              </div>
              <div className="px-3 py-2">
                <div className="text-[12px] font-semibold tracking-[-0.01em] text-foreground">
                  {titleB}
                </div>
                {subtitleB ? (
                  <div className="truncate text-[11px] text-muted-foreground">
                    {subtitleB}
                  </div>
                ) : null}
              </div>
            </div>

            {rows.map((row) => (
              <div
                key={`${row.left.lineNumber ?? 'x'}:${row.right.lineNumber ?? 'x'}:${row.left.status}:${row.right.status}:${row.left.text}:${row.right.text}`}
                className="grid grid-cols-[52px_minmax(0,1fr)_52px_minmax(0,1fr)]"
              >
                <JsonDiffCell cell={row.left} side="left" />
                <JsonDiffCell cell={row.right} side="right" />
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
