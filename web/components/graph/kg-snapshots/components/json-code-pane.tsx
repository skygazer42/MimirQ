'use client'

import { Copy, Download, FileJson } from '@/components/icons'
import { useMemo, type ReactNode } from 'react'

import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

import {
  cellSurfaceClass,
  lineNumberClassForStatus,
  splitCodeLines,
  tokenClassName,
  tokenizeJsonLine,
} from '../json-diff'
import type { DiffCell } from '../types'

function JsonLine({ lineNumber, text }: Readonly<{ lineNumber: number; text: string }>) {
  const tokens = useMemo(() => tokenizeJsonLine(text), [text])

  return (
    <div className="grid min-w-0 grid-cols-[52px_minmax(0,1fr)] border-b border-border/60 text-[12px] leading-6">
      <div className="select-none border-r border-border/70 px-3 text-right font-mono tabular-nums text-muted-foreground">
        {lineNumber}
      </div>
      <div className="px-3 font-mono">
        <span className="inline-block min-w-full whitespace-pre">
          {tokens.map((token, index) => (
            <span key={`${index}:${token.kind}`} className={tokenClassName(token.kind)}>
              {token.text}
            </span>
          ))}
        </span>
      </div>
    </div>
  )
}

export function JsonDiffCell({
  cell,
  side,
}: Readonly<{
  cell: DiffCell
  side: 'left' | 'right'
}>) {
  const tokens = useMemo(() => tokenizeJsonLine(cell.text), [cell.text])
  const lineNumberClass = lineNumberClassForStatus(cell.status)

  return (
    <>
      <div
        className={cn(
          'select-none border-r border-border/70 px-3 py-0.5 text-right font-mono text-[12px] leading-6 tabular-nums',
          cellSurfaceClass(cell.status, side),
          lineNumberClass,
        )}
      >
        {cell.lineNumber}
      </div>
      <div className={cn('px-3 py-0.5 font-mono text-[12px] leading-6', cellSurfaceClass(cell.status, side))}>
        <span className="inline-block min-w-full whitespace-pre">
          {tokens.map((token, index) => (
            <span key={`${cell.lineNumber ?? side}:${index}:${token.kind}`} className={tokenClassName(token.kind)}>
              {token.text}
            </span>
          ))}
        </span>
      </div>
    </>
  )
}

export function JsonCodePane({
  label,
  title,
  subtitle,
  code,
  isEmpty,
  emptyState,
  onCopy,
  onDownload,
}: Readonly<{
  label: string
  title: string
  subtitle?: string
  code: string
  isEmpty?: boolean
  emptyState?: ReactNode
  onCopy: () => void
  onDownload: () => void
}>) {
  const lines = useMemo(() => splitCodeLines(code), [code])

  return (
    <div className="flex h-full min-h-0 flex-col bg-card">
      <div className="flex shrink-0 items-center justify-between border-b border-border px-4 py-3 md:px-6">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-sm font-medium text-foreground">
            <FileJson className="size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
            <span className="truncate">{title}</span>
            <span className="shrink-0 text-xs font-normal text-muted-foreground">{label}</span>
          </div>
          {subtitle ? (
            <div title={subtitle} className="mt-0.5 truncate text-xs text-muted-foreground">
              {subtitle}
            </div>
          ) : null}
        </div>
        <div className="ml-4 flex shrink-0 items-center gap-1">
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="size-11 rounded-md sm:size-9"
            title="复制 JSON"
            aria-label="复制 JSON"
            onClick={onCopy}
            disabled={isEmpty}
          >
            <Copy className="h-4 w-4" aria-hidden="true" />
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="size-11 rounded-md sm:size-9"
            title="导出 JSON"
            aria-label="导出 JSON"
            onClick={onDownload}
            disabled={isEmpty}
          >
            <Download className="h-4 w-4" aria-hidden="true" />
          </Button>
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-auto bg-card">
        {isEmpty && emptyState ? (
          emptyState
        ) : (
          <div className="min-w-max">
            {lines.map((line, index) => (
              <JsonLine key={`${title}:${index + 1}`} lineNumber={index + 1} text={line} />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
