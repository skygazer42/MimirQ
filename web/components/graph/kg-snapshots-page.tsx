'use client'

import { diffLines } from 'diff'
import {
  AlertCircle,
  ArrowRightLeft,
  BarChart3,
  CheckCircle2,
  CircleDashed,
  Copy,
  Database,
  Download,
  FileJson,
  GitCompare,
  Hash,
  Layers,
  Link2,
  PanelLeftClose,
  PanelLeftOpen,
  RefreshCcw,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  Trash2,
} from 'lucide-react'
import { startTransition, useDeferredValue, useMemo, useState, type ReactNode } from 'react'
import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { toast } from 'sonner'

import { AppFrame } from '@/components/app-frame'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Textarea } from '@/components/ui/textarea'
import { formatApiError } from '@/lib/api-errors'
import { kgApi } from '@/lib/api/graph'
import { sanitizeFilename } from '@/lib/sanitize'
import { cn, detachPromise } from '@/lib/utils'

type SnapshotPayload = Record<string, unknown>

type SnapshotDiffEntityRow = {
  type?: string
  delta?: number | null
  [key: string]: unknown
}

type SnapshotDiffPayload = {
  delta?: SnapshotPayload | null
  entity_types_delta?: SnapshotDiffEntityRow[] | null
  node_diff?: SnapshotExactDiffSummary | null
  edge_diff?: SnapshotExactDiffSummary | null
  [key: string]: unknown
}

type SnapshotExactDiffSummary = {
  added_count?: number | null
  removed_count?: number | null
  changed_count?: number | null
  sample_limit?: number | null
}

type SnapshotView = 'diff' | 'a' | 'b'
type WorkspaceTab = 'studio' | 'audit'
type DiffCellStatus = 'same' | 'added' | 'removed' | 'empty'
type JsonTokenKind = 'plain' | 'key' | 'string' | 'number' | 'boolean' | 'null' | 'punctuation'
type AuditSeverity = 'healthy' | 'notice' | 'warning'

type DiffCell = {
  lineNumber: number | null
  text: string
  status: DiffCellStatus
}

type SideBySideDiffRow = {
  left: DiffCell
  right: DiffCell
}

type SnapshotDeltaRow = {
  key: string
  a: number
  b: number
  delta: number
}

type SnapshotChartTooltipProps = {
  active?: boolean
  payload?: Array<{ payload?: SnapshotDeltaRow }>
}

const DIFF_KEYS = ['docs', 'events', 'entities', 'links', 'relations'] as const

function prettyJson(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

function downloadJson(value: unknown, filename: string): void {
  const content = JSON.stringify(value ?? {}, null, 2)
  const blob = new Blob([content], { type: 'application/json;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  globalThis.window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}

async function copyToClipboard(text: string, label: string): Promise<void> {
  const v = String(text || '')
  if (!v.trim()) {
    toast.error('无可复制内容')
    return
  }
  try {
    await navigator.clipboard.writeText(v)
    toast.success(`已复制 ${label}`)
  } catch (err) {
    console.error('clipboard.writeText failed:', err)
    toast.error('复制失败（浏览器权限限制）')
  }
}

function parseDocumentIds(raw: string): string[] {
  const input = String(raw || '').trim()
  if (!input) return []
  return input
    .split(/[,\n]/g)
    .map((s) => s.trim())
    .filter(Boolean)
}

function splitCodeLines(value: string): string[] {
  const normalized = String(value ?? '').replace(/\r/g, '')
  const lines = normalized.split('\n')
  if (lines.length > 1 && lines[lines.length - 1] === '') lines.pop()
  return lines.length ? lines : ['']
}

function buildPairedRows(
  leftLines: string[],
  rightLines: string[],
  leftStatus: DiffCellStatus,
  rightStatus: DiffCellStatus,
  leftCounter: { value: number },
  rightCounter: { value: number }
): SideBySideDiffRow[] {
  const maxLength = Math.max(leftLines.length, rightLines.length)
  return Array.from({ length: maxLength }, (_, index) => {
    const leftText = leftLines[index]
    const rightText = rightLines[index]

    const leftCell: DiffCell = {
      lineNumber: typeof leftText === 'string' ? leftCounter.value++ : null,
      text: leftText ?? '',
      status: typeof leftText === 'string' ? leftStatus : 'empty',
    }
    const rightCell: DiffCell = {
      lineNumber: typeof rightText === 'string' ? rightCounter.value++ : null,
      text: rightText ?? '',
      status: typeof rightText === 'string' ? rightStatus : 'empty',
    }
    return { left: leftCell, right: rightCell }
  })
}

function buildSideBySideDiffRows(aText: string, bText: string): SideBySideDiffRow[] {
  const changes = diffLines(aText, bText)
  const leftCounter = { value: 1 }
  const rightCounter = { value: 1 }
  const rows: SideBySideDiffRow[] = []

  for (let index = 0; index < changes.length; index += 1) {
    const change = changes[index]
    if (!change) continue

    if (!change.added && !change.removed) {
      const lines = splitCodeLines(change.value)
      rows.push(...buildPairedRows(lines, lines, 'same', 'same', leftCounter, rightCounter))
      continue
    }

    const next = changes[index + 1]
    if (change.removed && next?.added) {
      rows.push(
        ...buildPairedRows(
          splitCodeLines(change.value),
          splitCodeLines(next.value),
          'removed',
          'added',
          leftCounter,
          rightCounter
        )
      )
      index += 1
      continue
    }

    if (change.added && next?.removed) {
      rows.push(
        ...buildPairedRows(
          splitCodeLines(next.value),
          splitCodeLines(change.value),
          'removed',
          'added',
          leftCounter,
          rightCounter
        )
      )
      index += 1
      continue
    }

    if (change.removed) {
      rows.push(...buildPairedRows(splitCodeLines(change.value), [], 'removed', 'empty', leftCounter, rightCounter))
      continue
    }

    if (change.added) {
      rows.push(...buildPairedRows([], splitCodeLines(change.value), 'empty', 'added', leftCounter, rightCounter))
    }
  }

  return rows
}

function tokenizeJsonLine(line: string): Array<{ text: string; kind: JsonTokenKind }> {
  const tokens: Array<{ text: string; kind: JsonTokenKind }> = []
  const pattern =
    /("(?:\\.|[^"\\])*")(\s*:)?|\b-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?\b|\btrue\b|\bfalse\b|\bnull\b|[{}\[\],:]/g

  let lastIndex = 0
  let match: RegExpExecArray | null = pattern.exec(line)
  while (match) {
    if (match.index > lastIndex) {
      tokens.push({ text: line.slice(lastIndex, match.index), kind: 'plain' })
    }

    const raw = match[0] ?? ''
    if (match[1]) {
      const suffix = match[2] ?? ''
      tokens.push({ text: match[1], kind: suffix ? 'key' : 'string' })
      if (suffix) tokens.push({ text: suffix, kind: 'punctuation' })
    } else if (raw === 'true' || raw === 'false') {
      tokens.push({ text: raw, kind: 'boolean' })
    } else if (raw === 'null') {
      tokens.push({ text: raw, kind: 'null' })
    } else if (/^-?\d/.test(raw)) {
      tokens.push({ text: raw, kind: 'number' })
    } else {
      tokens.push({ text: raw, kind: 'punctuation' })
    }

    lastIndex = pattern.lastIndex
    match = pattern.exec(line)
  }

  if (lastIndex < line.length) {
    tokens.push({ text: line.slice(lastIndex), kind: 'plain' })
  }

  if (tokens.length === 0) return [{ text: line, kind: 'plain' }]
  return tokens
}

function toneClassForDelta(value: number) {
  if (value > 0) return 'text-emerald-700'
  if (value < 0) return 'text-rose-700'
  return 'text-muted-foreground'
}

function tabLabelForView(view: SnapshotView) {
  if (view === 'diff') return 'Diff 对比'
  if (view === 'a') return '视图 A'
  return '视图 B'
}

function cellSurfaceClass(status: DiffCellStatus, side: 'left' | 'right') {
  if (status === 'removed') return 'bg-rose-50/90'
  if (status === 'added') return 'bg-emerald-50/90'
  if (status === 'empty') return side === 'left' ? 'bg-rose-50/35' : 'bg-emerald-50/35'
  return 'bg-card'
}

function tokenClassName(kind: JsonTokenKind) {
  if (kind === 'key') return 'text-sky-700'
  if (kind === 'string') return 'text-emerald-700'
  if (kind === 'number') return 'text-amber-700'
  if (kind === 'boolean') return 'text-violet-700'
  if (kind === 'null') return 'text-rose-600'
  if (kind === 'punctuation') return 'text-slate-500'
  return 'text-foreground/90'
}

function SnapshotInlineStat({
  icon,
  label,
  value,
  tone = 'muted',
  valueTitle,
  valueClassName,
}: Readonly<{
  icon?: ReactNode
  label: string
  value: ReactNode
  tone?: 'muted' | 'neutral' | 'positive' | 'negative' | 'warning'
  valueTitle?: string
  valueClassName?: string
}>) {
  const toneClasses =
    tone === 'positive'
      ? 'border-emerald-200/70 bg-emerald-50/70 text-emerald-700'
      : tone === 'negative'
        ? 'border-rose-200/70 bg-rose-50/70 text-rose-700'
        : tone === 'warning'
          ? 'border-amber-200/70 bg-amber-50/70 text-amber-700'
          : tone === 'neutral'
            ? 'border-border/70 bg-card text-foreground'
            : 'border-border/70 bg-card text-muted-foreground'
  const valueTone =
    tone === 'positive'
      ? 'text-emerald-700'
      : tone === 'negative'
        ? 'text-rose-700'
        : tone === 'warning'
          ? 'text-amber-700'
          : tone === 'neutral'
            ? 'text-foreground'
            : 'text-muted-foreground'

  return (
    <div className={cn('inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1', toneClasses)}>
      {icon ? <span className="flex h-3.5 w-3.5 items-center justify-center opacity-80">{icon}</span> : null}
      <span className="text-[10.5px] font-medium uppercase tracking-[0.1em] opacity-80">{label}</span>
      <span title={valueTitle} className={cn('font-mono text-[11px] font-semibold tabular-nums', valueTone, valueClassName)}>
        {value}
      </span>
    </div>
  )
}

function WorkspaceSection({
  icon,
  label,
  hint,
  children,
}: Readonly<{
  icon?: ReactNode
  label: string
  hint?: string
  children: ReactNode
}>) {
  return (
    <section className="space-y-2.5 rounded-xl border border-border/70 bg-[linear-gradient(180deg,hsl(var(--background)),hsl(var(--muted)/0.18))] p-3 shadow-sm">
      <div className="flex items-center justify-between gap-2">
        <div className="inline-flex items-center gap-1.5 text-[10.5px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
          {icon ? <span className="flex h-3.5 w-3.5 items-center justify-center text-primary/70">{icon}</span> : null}
          {label}
        </div>
        {hint ? <span className="text-[10px] text-muted-foreground/70">{hint}</span> : null}
      </div>
      {children}
    </section>
  )
}

function SectionHeading({
  eyebrow,
  title,
  description,
  icon,
  extra,
}: Readonly<{
  eyebrow: string
  title: string
  description?: string
  icon?: ReactNode
  extra?: ReactNode
}>) {
  return (
    <div className="flex items-start justify-between gap-3">
      <div className="flex min-w-0 items-start gap-3">
        {icon ? (
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-border/60 bg-[linear-gradient(180deg,hsl(var(--card)),hsl(var(--muted)/0.30))] text-primary shadow-sm">
            {icon}
          </div>
        ) : null}
        <div className="min-w-0">
          <div className="text-[10.5px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">{eyebrow}</div>
          <div className="mt-0.5 text-[15px] font-semibold tracking-[-0.01em] text-foreground md:text-base">{title}</div>
          {description ? <div className="mt-1 max-w-[640px] text-[12px] leading-5 text-muted-foreground">{description}</div> : null}
        </div>
      </div>
      {extra ? <div className="shrink-0">{extra}</div> : null}
    </div>
  )
}

function DiffEmptyState({
  title,
  description,
  hint,
}: Readonly<{
  title: string
  description: string
  hint?: string
}>) {
  return (
    <div className="flex h-full min-h-[280px] items-center justify-center px-6 py-10">
      <div className="flex max-w-[440px] flex-col items-center text-center">
        <div className="relative">
          <div className="absolute inset-0 -z-0 rounded-full bg-[radial-gradient(circle,hsl(var(--primary)/0.18),transparent_60%)] blur-xl" aria-hidden />
          <div className="relative flex h-16 w-16 items-center justify-center rounded-2xl border border-border/60 bg-[linear-gradient(180deg,hsl(var(--card)),hsl(var(--muted)/0.30))] text-primary shadow-sm">
            <ArrowRightLeft className="h-7 w-7" strokeWidth={1.5} aria-hidden="true" />
          </div>
        </div>
        <h3 className="mt-4 text-[15px] font-semibold tracking-tight text-foreground">{title}</h3>
        <p className="mt-1.5 text-[12px] leading-5 text-muted-foreground">{description}</p>
        {hint ? (
          <div className="mt-3 inline-flex items-center gap-1.5 rounded-full border border-border/60 bg-card px-3 py-1 text-[11px] text-muted-foreground">
            <CircleDashed className="h-3.5 w-3.5 text-primary/60" aria-hidden="true" />
            {hint}
          </div>
        ) : null}
      </div>
    </div>
  )
}

function auditSeverityMeta(severity: AuditSeverity): {
  label: string
  variant: 'soft' | 'outline' | 'destructive'
  icon: ReactNode
} {
  if (severity === 'warning') {
    return {
      label: '高波动',
      variant: 'destructive',
      icon: <ShieldAlert className="h-3.5 w-3.5" aria-hidden="true" />,
    }
  }
  if (severity === 'notice') {
    return {
      label: '关注',
      variant: 'outline',
      icon: <BarChart3 className="h-3.5 w-3.5" aria-hidden="true" />,
    }
  }
  return {
    label: '稳定',
    variant: 'soft',
    icon: <ShieldCheck className="h-3.5 w-3.5" aria-hidden="true" />,
  }
}

function SnapshotChartTooltip({ active, payload }: Readonly<SnapshotChartTooltipProps>) {
  const row = payload?.[0]?.payload
  if (!active || !row) return null
  const sign = row.delta > 0 ? '+' : ''
  return (
    <div className="rounded-lg border border-border/70 bg-card px-3 py-2 shadow-sm">
      <div className="font-mono text-[11px] text-muted-foreground">{row.key}</div>
      <div className="mt-1 flex items-center gap-2 text-[11px]">
        <span className="font-mono text-muted-foreground">A {row.a}</span>
        <span className="font-mono text-muted-foreground">B {row.b}</span>
        <span className={cn('font-mono font-semibold', row.delta > 0 ? 'text-emerald-700' : row.delta < 0 ? 'text-rose-700' : 'text-foreground')}>
          Δ {sign}
          {row.delta}
        </span>
      </div>
    </div>
  )
}

function exactDiffCount(summary: SnapshotExactDiffSummary | null | undefined, key: keyof SnapshotExactDiffSummary): number {
  const value = Number(summary?.[key] ?? 0)
  return Number.isFinite(value) ? value : 0
}

function exactDiffSample(diff: SnapshotDiffPayload | null, key: string): Array<Record<string, unknown>> {
  const value = diff?.[key]
  return Array.isArray(value) ? value.filter((item): item is Record<string, unknown> => Boolean(item && typeof item === 'object')) : []
}

function DriftCounterCluster({
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
          <span className="inline-flex min-w-[40px] items-center justify-center gap-0.5 rounded-md bg-emerald-50 px-1.5 py-1 font-mono text-[11px] font-semibold tabular-nums text-emerald-700 ring-1 ring-emerald-200/60">
            <span aria-hidden className="opacity-70">+</span>
            {added}
          </span>
          <span className="inline-flex min-w-[40px] items-center justify-center gap-0.5 rounded-md bg-rose-50 px-1.5 py-1 font-mono text-[11px] font-semibold tabular-nums text-rose-700 ring-1 ring-rose-200/60">
            <span aria-hidden className="opacity-70">−</span>
            {removed}
          </span>
          <span className="inline-flex min-w-[40px] items-center justify-center gap-0.5 rounded-md bg-amber-50 px-1.5 py-1 font-mono text-[11px] font-semibold tabular-nums text-amber-700 ring-1 ring-amber-200/60">
            <span aria-hidden className="opacity-70">Δ</span>
            {changed}
          </span>
        </div>
      </div>
    </div>
  )
}

function SnapshotExactDriftPanel({ diff }: Readonly<{ diff: SnapshotDiffPayload | null }>) {
  const nodeSummary = diff?.node_diff
  const edgeSummary = diff?.edge_diff
  const hasExactDiff = Boolean(nodeSummary || edgeSummary)
  const sampleRows = [
    { label: '新增节点', key: 'nodes_added', icon: <Database className="h-3.5 w-3.5" />, tone: 'text-emerald-700', tint: 'bg-emerald-50' },
    { label: '移除节点', key: 'nodes_removed', icon: <Database className="h-3.5 w-3.5" />, tone: 'text-rose-700', tint: 'bg-rose-50' },
    { label: '变更节点', key: 'nodes_changed', icon: <Database className="h-3.5 w-3.5" />, tone: 'text-amber-700', tint: 'bg-amber-50' },
    { label: '新增边', key: 'edges_added', icon: <Link2 className="h-3.5 w-3.5" />, tone: 'text-emerald-700', tint: 'bg-emerald-50' },
    { label: '移除边', key: 'edges_removed', icon: <Link2 className="h-3.5 w-3.5" />, tone: 'text-rose-700', tint: 'bg-rose-50' },
    { label: '变更边', key: 'edges_changed', icon: <Link2 className="h-3.5 w-3.5" />, tone: 'text-amber-700', tint: 'bg-amber-50' },
  ]

  return (
    <div className="border-b border-border/70 bg-[linear-gradient(180deg,hsl(var(--background)),hsl(var(--muted)/0.10))] px-4 py-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="inline-flex items-center gap-1.5 text-[10.5px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
            <Sparkles className="h-3.5 w-3.5 text-primary/70" aria-hidden="true" />
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
              .map((item) => String(item.name || item.id || 'unknown'))
              .join(' / ')
            return (
              <div key={row.key} className="rounded-lg border border-border/70 bg-card px-3 py-2 transition-shadow hover:shadow-sm">
                <div className="flex items-center justify-between gap-2">
                  <span className="inline-flex items-center gap-1.5 text-[11px] font-medium text-muted-foreground">
                    <span className={cn('flex h-5 w-5 items-center justify-center rounded-md', row.tint, row.tone)}>
                      {row.icon}
                    </span>
                    {row.label}
                  </span>
                  <span className={cn('font-mono text-[11px] font-semibold tabular-nums', row.tone)}>{items.length}</span>
                </div>
                <div className="mt-1 truncate font-mono text-[11px] text-muted-foreground" title={preview || '暂无样本'}>
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

function JsonLine({
  lineNumber,
  text,
  status,
  side = 'single',
}: Readonly<{
  lineNumber: number | null
  text: string
  status: DiffCellStatus | 'single'
  side?: 'left' | 'right' | 'single'
}>) {
  const tokens = useMemo(() => tokenizeJsonLine(text), [text])
  const lineNumberClass =
    status === 'added'
      ? 'text-emerald-700'
      : status === 'removed'
        ? 'text-rose-700'
        : 'text-muted-foreground'

  return (
    <div
      className={cn(
        'grid min-w-0 grid-cols-[52px_minmax(0,1fr)] border-b border-border/60 text-[12px] leading-6',
        status === 'single' ? 'bg-transparent' : cellSurfaceClass(status, side === 'single' ? 'left' : side)
      )}
    >
      <div className={cn('select-none border-r border-border/70 px-3 text-right font-mono tabular-nums', lineNumberClass)}>
        {lineNumber ?? ''}
      </div>
      <div className="px-3 font-mono">
        <span className="inline-block min-w-full whitespace-pre">
          {tokens.map((token, index) => (
            <span key={`${lineNumber ?? 'x'}:${index}:${token.kind}`} className={tokenClassName(token.kind)}>
              {token.text}
            </span>
          ))}
        </span>
      </div>
    </div>
  )
}

function JsonDiffCell({
  cell,
  side,
}: Readonly<{
  cell: DiffCell
  side: 'left' | 'right'
}>) {
  const tokens = useMemo(() => tokenizeJsonLine(cell.text), [cell.text])
  const lineNumberClass =
    cell.status === 'added'
      ? 'text-emerald-700'
      : cell.status === 'removed'
        ? 'text-rose-700'
        : 'text-muted-foreground'

  return (
    <>
      <div
        className={cn(
          'select-none border-r border-border/70 px-3 py-0.5 text-right font-mono text-[12px] leading-6 tabular-nums',
          cellSurfaceClass(cell.status, side),
          lineNumberClass
        )}
      >
        {cell.lineNumber ?? ''}
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

function JsonCodePane({
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
        <div className="flex shrink-0 items-center justify-between border-b border-border/70 bg-[linear-gradient(180deg,hsl(var(--background)),hsl(var(--muted)/0.15))] px-4 py-2.5">
        <div className="min-w-0">
          <div className="inline-flex items-center gap-1.5 rounded-md border border-border/70 bg-card px-2 py-0.5 text-[10.5px] font-semibold tracking-[0.08em] text-muted-foreground">
            <FileJson className="h-3 w-3 text-primary/70" aria-hidden="true" />
            {label}
          </div>
          <div className="mt-1 truncate text-[13px] font-semibold text-foreground">{title}</div>
          {subtitle ? <div className="mt-0.5 truncate text-[11px] text-muted-foreground">{subtitle}</div> : null}
        </div>
        <div className="ml-4 flex shrink-0 items-center gap-1 rounded-md border border-border/70 bg-card p-0.5">
          <Button variant="ghost" size="icon" className="h-8 w-8 rounded-lg" title="复制 JSON" onClick={onCopy} disabled={isEmpty}>
            <Copy className="h-4 w-4" aria-hidden="true" />
          </Button>
          <Button variant="ghost" size="icon" className="h-8 w-8 rounded-lg" title="导出 JSON" onClick={onDownload} disabled={isEmpty}>
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
              <JsonLine key={`${title}:${index + 1}`} lineNumber={index + 1} text={line} status="single" />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

function SnapshotDiffView({
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
  const rows = useMemo(() => buildSideBySideDiffRows(leftCode, rightCode), [leftCode, rightCode])

  return (
      <div className="flex h-full min-h-0 flex-col bg-card">
        <div className="flex shrink-0 items-center justify-between gap-3 border-b border-border/70 bg-background px-4 py-2">
        <div className="min-w-0 flex-1">
          {typeDrift.length > 0 ? (
            <div className="flex flex-wrap items-center gap-2">
              <span className="inline-flex items-center gap-1.5 text-[10.5px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
                <Layers className="h-3.5 w-3.5 text-primary/70" aria-hidden="true" />
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
                    <span className={toneClassForDelta(delta)}>{sign + delta}</span>
                  </Badge>
                )
              })}
            </div>
          ) : (
            <span className="inline-flex items-center gap-1.5 text-[10.5px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
              <Layers className="h-3.5 w-3.5 text-muted-foreground/60" aria-hidden="true" />
              Type Drift · 暂无
            </span>
          )}
        </div>
        <div className="flex shrink-0 items-center gap-1">
          <Button variant="ghost" size="icon" className="h-8 w-8 rounded-lg" title="复制 Diff JSON" onClick={onCopy} disabled={isEmpty}>
            <Copy className="h-4 w-4" aria-hidden="true" />
          </Button>
          <Button variant="ghost" size="icon" className="h-8 w-8 rounded-lg" title="导出 Diff JSON" onClick={onDownload} disabled={isEmpty}>
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
              <div className="border-r border-border/70 px-3 py-2 text-right font-mono text-muted-foreground">#</div>
              <div className="border-r border-border/70 px-3 py-2">
                <div className="text-[12px] font-semibold tracking-[-0.01em] text-foreground">{titleA}</div>
                {subtitleA ? <div className="truncate text-[11px] text-muted-foreground">{subtitleA}</div> : null}
              </div>
              <div className="border-r border-border/70 px-3 py-2 text-right font-mono text-muted-foreground">#</div>
              <div className="px-3 py-2">
                <div className="text-[12px] font-semibold tracking-[-0.01em] text-foreground">{titleB}</div>
                {subtitleB ? <div className="truncate text-[11px] text-muted-foreground">{subtitleB}</div> : null}
              </div>
            </div>

            {rows.map((row, index) => (
              <div key={`diff-row:${index}`} className="grid grid-cols-[52px_minmax(0,1fr)_52px_minmax(0,1fr)]">
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

function SnapshotAuditPanel({
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
  const chartRows = includeZeroDeltas ? deltaRows : deltaRows.filter((row) => row.delta !== 0)
  const shownDriftRows = compactRows ? typeDriftRows.slice(0, 14) : typeDriftRows
  const driftScoreTone: 'positive' | 'warning' | 'negative' = severity === 'healthy' ? 'positive' : severity === 'notice' ? 'warning' : 'negative'

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="shrink-0 border-b border-border/70 bg-[linear-gradient(180deg,hsl(var(--background)),hsl(var(--muted)/0.20))] px-4 py-3">
        <SectionHeading
          eyebrow="Audit"
          title="效果面板"
          description="快速查看快照差异强度、类型漂移与整体风险等级。"
          icon={<BarChart3 className="h-5 w-5" aria-hidden="true" />}
          extra={
            <Badge variant={severityMeta.variant} className="inline-flex items-center gap-1.5 font-mono text-[11px]">
              {severityMeta.icon}
              {severityMeta.label}
            </Badge>
          }
        />
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <SnapshotInlineStat
            icon={<Sparkles className="h-3.5 w-3.5" />}
            label="Drift Score"
            value={driftScore.toFixed(2)}
            tone={driftScoreTone}
          />
          <SnapshotInlineStat
            icon={<Layers className="h-3.5 w-3.5" />}
            label="Type Drift"
            value={typeDriftRows.length}
            tone={typeDriftRows.length > 0 ? 'positive' : 'muted'}
          />
          <SnapshotInlineStat
            icon={<ArrowRightLeft className="h-3.5 w-3.5" />}
            label="Delta Keys"
            value={deltaRows.filter((row) => row.delta !== 0).length}
            tone="neutral"
          />
        </div>
      </div>

      <div className="grid min-h-0 flex-1 xl:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)]">
        <div className="min-h-0 border-b border-border/70 xl:border-b-0 xl:border-r">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border/70 px-4 py-2.5">
            <div className="inline-flex items-center gap-1.5 text-[10.5px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
              <BarChart3 className="h-3.5 w-3.5 text-primary/70" aria-hidden="true" />
              Delta Distribution
            </div>
            <div className="flex items-center gap-4">
              <label className="inline-flex items-center gap-2 text-[11px] text-muted-foreground">
                <Switch checked={includeZeroDeltas} onCheckedChange={onIncludeZeroDeltasChange} />
                显示 0 值
              </label>
            </div>
          </div>

          <div className="h-[280px] px-3 py-2">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={chartRows} margin={{ top: 8, right: 10, left: -16, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e2e8f0" />
                <XAxis dataKey="key" tick={{ fontSize: 11, fill: '#64748b' }} axisLine={false} tickLine={false} />
                <YAxis tick={{ fontSize: 11, fill: '#64748b' }} axisLine={false} tickLine={false} allowDecimals={false} />
                <Tooltip cursor={{ fill: 'rgba(148, 163, 184, 0.08)' }} content={<SnapshotChartTooltip />} />
                <Bar dataKey="delta" radius={[6, 6, 0, 0]}>
                  {chartRows.map((row) => (
                    <Cell key={`delta:${row.key}`} fill={row.delta > 0 ? '#10b981' : row.delta < 0 ? '#f43f5e' : '#94a3b8'} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="min-h-0 flex flex-col">
          <div className="flex items-center justify-between gap-2 border-b border-border/70 px-4 py-2.5">
            <div className="inline-flex items-center gap-1.5 text-[10.5px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
              <Layers className="h-3.5 w-3.5 text-primary/70" aria-hidden="true" />
              Type Drift Rows
            </div>
            <label className="inline-flex items-center gap-2 text-[11px] text-muted-foreground">
              <Switch checked={compactRows} onCheckedChange={onCompactRowsChange} />
              紧凑模式
            </label>
          </div>

          <div className="min-h-0 flex-1 overflow-auto">
            {shownDriftRows.length ? (
              shownDriftRows.map((row, index) => {
                const type = String(row.type || 'unknown')
                const delta = Number(row.delta ?? 0)
                const sign = delta > 0 ? '+' : ''
                const tone = delta > 0 ? 'text-emerald-700' : delta < 0 ? 'text-rose-700' : 'text-muted-foreground'
                const tint = delta > 0 ? 'bg-emerald-50 ring-emerald-200/60' : delta < 0 ? 'bg-rose-50 ring-rose-200/60' : 'bg-muted/40 ring-border'
                return (
                  <button
                    key={`drift:${type}:${index}`}
                    type="button"
                    className="grid w-full grid-cols-[minmax(0,1fr)_auto_auto] items-center gap-2 border-b border-border/60 px-4 py-2 text-left transition-colors hover:bg-muted/30"
                    title={`${type} Δ ${sign}${delta}`}
                  >
                    <span className="truncate font-mono text-[12px] text-foreground">{type}</span>
                    <span className={cn('inline-flex min-w-[52px] items-center justify-center rounded-md px-2 py-0.5 font-mono text-[11px] font-semibold tabular-nums ring-1', tint, tone)}>
                      Δ {sign}
                      {delta}
                    </span>
                    <Badge variant={delta > 0 ? 'soft' : delta < 0 ? 'destructive' : 'outline'} className="font-mono text-[10.5px]">
                      {delta > 0 ? 'increase' : delta < 0 ? 'decrease' : 'flat'}
                    </Badge>
                  </button>
                )
              })
            ) : (
              <div className="flex h-full items-center justify-center px-4 py-12">
                <div className="flex max-w-[320px] flex-col items-center text-center">
                  <div className="flex h-12 w-12 items-center justify-center rounded-2xl border border-border/60 bg-card text-muted-foreground/70 shadow-sm">
                    <Layers className="h-5 w-5" aria-hidden="true" />
                  </div>
                  <div className="mt-3 text-[13px] font-semibold text-foreground">暂无类型漂移</div>
                  <div className="mt-1 text-[11px] leading-5 text-muted-foreground">
                    entity_types_delta 为空：A / B 之间的实体类型构成保持一致。
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

export function KGSnapshotsPage() {
  const [pipelineHashA, setPipelineHashA] = useState('')
  const [pipelineHashB, setPipelineHashB] = useState('')
  const [documentIdsRaw, setDocumentIdsRaw] = useState('')
  const [workspaceTab, setWorkspaceTab] = useState<WorkspaceTab>('studio')
  const [activeView, setActiveView] = useState<SnapshotView>('diff')
  const [leftSidebarCollapsed, setLeftSidebarCollapsed] = useState(false)
  const [includeZeroDeltas, setIncludeZeroDeltas] = useState(true)
  const [compactAuditRows, setCompactAuditRows] = useState(true)

  const [snapA, setSnapA] = useState<SnapshotPayload | null>(null)
  const [snapB, setSnapB] = useState<SnapshotPayload | null>(null)
  const [diff, setDiff] = useState<SnapshotDiffPayload | null>(null)
  const [latencyMs, setLatencyMs] = useState<number | null>(null)
  const [isRunning, setIsRunning] = useState(false)

  const documentIds = useMemo(() => parseDocumentIds(documentIdsRaw), [documentIdsRaw])

  const snapAJson = useMemo(() => prettyJson(snapA ?? { hint: '点击左侧“导出 A”生成快照。' }), [snapA])
  const snapBJson = useMemo(() => prettyJson(snapB ?? { hint: '点击左侧“导出 B”生成快照。' }), [snapB])
  const diffJson = useMemo(() => prettyJson(diff ?? { hint: '点击左侧“开始对比”生成 diff。' }), [diff])

  const diffDelta = useMemo(() => {
    const delta = diff?.delta && typeof diff.delta === 'object' ? diff.delta : null
    const entityTypesDelta = Array.isArray(diff?.entity_types_delta) ? diff.entity_types_delta : []
    return { delta, entityTypesDelta }
  }, [diff])
  const deferredEntityTypesDelta = useDeferredValue(diffDelta.entityTypesDelta)

  async function runExport(which: 'a' | 'b'): Promise<void> {
    const pipelineHash = (which === 'a' ? pipelineHashA : pipelineHashB).trim()
    if (!pipelineHash) {
      toast.error(which === 'a' ? '请输入 pipeline_hash A' : '请输入 pipeline_hash B')
      return
    }

    setIsRunning(true)
    try {
      const snapshot = await kgApi.exportSnapshot({
        pipeline_hash: pipelineHash,
        document_ids: documentIds.length ? documentIds : undefined,
        include_details: true,
      })
      if (which === 'a') {
        setSnapA(snapshot)
        setActiveView('a')
      } else {
        setSnapB(snapshot)
        setActiveView('b')
      }
      toast.success(`已导出 ${which.toUpperCase()} 快照`)
    } catch (err) {
      toast.error(formatApiError(err, '导出 KG snapshot 失败'))
    } finally {
      setIsRunning(false)
    }
  }

  async function runCompare(): Promise<void> {
    const a = pipelineHashA.trim()
    const b = pipelineHashB.trim()
    if (!a || !b) {
      toast.error('请输入 pipeline_hash A / B')
      return
    }
    if (a === b) {
      toast.error('A / B pipeline_hash 不能相同')
      return
    }

    setIsRunning(true)
    setLatencyMs(null)
    try {
      const start = Date.now()
      const [snapshotA, snapshotB] = await Promise.all([
        kgApi.exportSnapshot({
          pipeline_hash: a,
          document_ids: documentIds.length ? documentIds : undefined,
          include_details: true,
        }),
        kgApi.exportSnapshot({
          pipeline_hash: b,
          document_ids: documentIds.length ? documentIds : undefined,
          include_details: true,
        }),
      ])
      const result = await kgApi.diffSnapshots({ snapshot_a: snapshotA, snapshot_b: snapshotB })
      setLatencyMs(Math.max(0, Date.now() - start))
      setSnapA(snapshotA)
      setSnapB(snapshotB)
      setDiff(result)
      setActiveView('diff')
      toast.success('已生成 diff')
    } catch (err) {
      toast.error(formatApiError(err, 'KG snapshot compare 失败'))
    } finally {
      setIsRunning(false)
    }
  }

  async function runBackendCompare(): Promise<void> {
    const a = pipelineHashA.trim()
    const b = pipelineHashB.trim()
    if (!a || !b) {
      toast.error('请输入 pipeline_hash A / B')
      return
    }
    if (a === b) {
      toast.error('A / B pipeline_hash 不能相同')
      return
    }

    setIsRunning(true)
    setLatencyMs(null)
    try {
      const start = Date.now()
      const result = await kgApi.compareSnapshots({
        pipeline_hash_a: a,
        pipeline_hash_b: b,
        document_ids: documentIds.length ? documentIds : undefined,
      })
      setLatencyMs(Math.max(0, Date.now() - start))
      setDiff(result)
      setActiveView('diff')
      toast.success('后端对比完成')
    } catch (err) {
      toast.error(formatApiError(err, 'KG snapshot 后端对比失败'))
    } finally {
      setIsRunning(false)
    }
  }

  const hashAValue = pipelineHashA.trim()
  const hashBValue = pipelineHashB.trim()
  const hasHashA = Boolean(hashAValue)
  const hasHashB = Boolean(hashBValue)
  const hashATitle = hashAValue || '未设置'
  const hashBTitle = hashBValue || '未设置'
  const hashPairStatus = hasHashA && hasHashB ? '已就绪' : hasHashA || hasHashB ? '待补全' : '未设置'
  const hashPairTitle = `A: ${hashAValue || '未填写'}\nB: ${hashBValue || '未填写'}`
  const diffBaseName = sanitizeFilename(`kg_snapshot_${hashAValue || 'A'}_vs_${hashBValue || 'B'}`) || 'kg_snapshot'
  const snapshotAFileName = sanitizeFilename(`kg_snapshot_${hashAValue || 'A'}`) || 'kg_snapshot_A'
  const snapshotBFileName = sanitizeFilename(`kg_snapshot_${hashBValue || 'B'}`) || 'kg_snapshot_B'
  const deltaRows = useMemo<SnapshotDeltaRow[]>(() => {
    return DIFF_KEYS.map((key) => {
      const a = Number(snapA?.[key] ?? 0)
      const b = Number(snapB?.[key] ?? 0)
      const d = Number(diffDelta.delta?.[key] ?? b - a)
      return {
        key,
        a: Number.isFinite(a) ? a : 0,
        b: Number.isFinite(b) ? b : 0,
        delta: Number.isFinite(d) ? d : 0,
      }
    })
  }, [diffDelta.delta, snapA, snapB])
  const driftScore = useMemo(() => {
    const denominator = deltaRows.reduce((acc, row) => acc + Math.max(Math.max(row.a, row.b), 1), 0)
    if (denominator <= 0) return 0
    const totalDelta = deltaRows.reduce((acc, row) => acc + Math.abs(row.delta), 0)
    return totalDelta / denominator
  }, [deltaRows])
  const auditSeverity: AuditSeverity = driftScore >= 0.35 ? 'warning' : driftScore >= 0.12 ? 'notice' : 'healthy'
  const auditDriftRows = useMemo(() => {
    return [...deferredEntityTypesDelta].sort((a, b) => Math.abs(Number(b.delta ?? 0)) - Math.abs(Number(a.delta ?? 0)))
  }, [deferredEntityTypesDelta])
  const formInputClassName = 'h-10 rounded-lg border-border/70 bg-card font-mono text-xs shadow-none'
  const formTextareaClassName = 'min-h-[108px] resize-none rounded-lg border-border/70 bg-card font-mono text-xs shadow-none'

  return (
    <AppFrame showBackground={false}>
      <div className="flex h-full min-h-0 flex-col bg-[radial-gradient(1200px_460px_at_12%_-18%,rgba(37,99,235,0.08),transparent_58%),radial-gradient(960px_420px_at_88%_-24%,rgba(14,165,233,0.06),transparent_56%)] bg-background">
        <header className="shrink-0 border-b border-border/70 bg-background/80 backdrop-blur">
          <div className="px-4 py-3 md:px-6">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <SectionHeading
                eyebrow="Graph"
                title="KG Snapshots"
                description="对比 pipeline hash 生成的轻量 KG 快照，并在 Audit 面板快速判断波动强度。"
                icon={<GitCompare className="h-5 w-5" aria-hidden="true" />}
                extra={
                  <div className="flex items-center gap-2">
                    {hasHashA && hasHashB ? (
                      <SnapshotInlineStat
                        icon={<CheckCircle2 className="h-3.5 w-3.5" />}
                        label="A/B"
                        value={hashPairStatus}
                        valueTitle={hashPairTitle}
                        tone="positive"
                      />
                    ) : hasHashA || hasHashB ? (
                      <SnapshotInlineStat
                        icon={<AlertCircle className="h-3.5 w-3.5" />}
                        label="A/B"
                        value={hashPairStatus}
                        valueTitle={hashPairTitle}
                        tone="warning"
                      />
                    ) : (
                      <SnapshotInlineStat
                        icon={<CircleDashed className="h-3.5 w-3.5" />}
                        label="A/B"
                        value={hashPairStatus}
                        valueTitle={hashPairTitle}
                        tone="muted"
                      />
                    )}
                    {typeof latencyMs === 'number' ? (
                      <SnapshotInlineStat
                        icon={<Sparkles className="h-3.5 w-3.5" />}
                        label="Latency"
                        value={`${latencyMs} ms`}
                        tone="neutral"
                      />
                    ) : null}
                  </div>
                }
              />

              <div className="flex shrink-0 items-center gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  className="h-9 gap-2 rounded-lg border-border/70 bg-card text-xs font-medium"
                  title={hashAValue && hashBValue ? '重新导出并刷新 A/B 对比结果' : '先填写 Hash A / Hash B'}
                  disabled={isRunning || !hashAValue || !hashBValue}
                  onClick={() => detachPromise(runCompare())}
                >
                  <RefreshCcw className={cn('h-3.5 w-3.5', isRunning && 'animate-spin')} aria-hidden="true" />
                  刷新对比
                </Button>

                <Button
                  variant="ghost"
                  size="icon"
                  className="h-9 w-9 rounded-lg text-muted-foreground hover:text-foreground"
                  title="清空"
                  onClick={() => {
                    setSnapA(null)
                    setSnapB(null)
                    setDiff(null)
                    setLatencyMs(null)
                    startTransition(() => {
                      setWorkspaceTab('studio')
                      setActiveView('diff')
                    })
                    toast.message('已清空')
                  }}
                >
                  <Trash2 className="h-4 w-4" aria-hidden="true" />
                </Button>

                <div className="mx-1 h-5 w-px bg-border/70" aria-hidden />

                <Button
                  variant="outline"
                  size="icon"
                  className="h-9 w-9 rounded-lg border-border/70 bg-card"
                  onClick={() => setLeftSidebarCollapsed((prev) => !prev)}
                  aria-label={leftSidebarCollapsed ? '展开参数栏' : '折叠参数栏'}
                  title={leftSidebarCollapsed ? '展开参数栏' : '折叠参数栏'}
                >
                  {leftSidebarCollapsed ? <PanelLeftOpen className="h-4 w-4" /> : <PanelLeftClose className="h-4 w-4" />}
                </Button>
              </div>
            </div>
          </div>
        </header>

        <div className="flex min-h-0 flex-1">
          <aside
            className={cn(
              'shrink-0 border-r border-border/70 bg-background transition-[width,opacity] duration-200',
              leftSidebarCollapsed ? 'w-0 overflow-hidden border-r-0 opacity-0' : 'w-[304px] opacity-100',
              'flex min-h-0 flex-col'
            )}
          >
            <div className="flex h-full min-h-0 flex-col">
              <div className="shrink-0 border-b border-border/70 bg-[linear-gradient(180deg,hsl(var(--background)),hsl(var(--muted)/0.20))] px-4 py-3">
                <div className="grid grid-cols-2 gap-1 rounded-xl border border-border/70 bg-card p-1 shadow-sm">
                  <button
                    type="button"
                    className={cn(
                      'inline-flex h-8 items-center justify-center gap-1.5 rounded-lg text-[12px] font-medium transition-colors',
                      workspaceTab === 'studio'
                        ? 'bg-primary text-primary-foreground shadow-sm'
                        : 'text-muted-foreground hover:bg-muted/40 hover:text-foreground'
                    )}
                    onClick={() => {
                      startTransition(() => setWorkspaceTab('studio'))
                    }}
                  >
                    <FileJson className="h-3.5 w-3.5" aria-hidden="true" />
                    Studio
                  </button>
                  <button
                    type="button"
                    className={cn(
                      'inline-flex h-8 items-center justify-center gap-1.5 rounded-lg text-[12px] font-medium transition-colors',
                      workspaceTab === 'audit'
                        ? 'bg-primary text-primary-foreground shadow-sm'
                        : 'text-muted-foreground hover:bg-muted/40 hover:text-foreground'
                    )}
                    onClick={() => {
                      startTransition(() => setWorkspaceTab('audit'))
                    }}
                  >
                    <BarChart3 className="h-3.5 w-3.5" aria-hidden="true" />
                    Audit
                  </button>
                </div>
                <div className="mt-2.5 flex flex-wrap items-center gap-2">
                  {hasHashA && hasHashB ? (
                    <SnapshotInlineStat
                      icon={<CheckCircle2 className="h-3.5 w-3.5" />}
                      label="A/B"
                      value={hashPairStatus}
                      valueTitle={hashPairTitle}
                      tone="positive"
                    />
                  ) : hasHashA || hasHashB ? (
                    <SnapshotInlineStat
                      icon={<AlertCircle className="h-3.5 w-3.5" />}
                      label="A/B"
                      value={hashPairStatus}
                      valueTitle={hashPairTitle}
                      tone="warning"
                    />
                  ) : (
                    <SnapshotInlineStat
                      icon={<CircleDashed className="h-3.5 w-3.5" />}
                      label="A/B"
                      value={hashPairStatus}
                      valueTitle={hashPairTitle}
                      tone="muted"
                    />
                  )}
                  {typeof latencyMs === 'number' ? (
                    <SnapshotInlineStat
                      icon={<Sparkles className="h-3.5 w-3.5" />}
                      label="Latency"
                      value={`${latencyMs} ms`}
                      tone="neutral"
                    />
                  ) : null}
                </div>
              </div>

              <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4">
                <div className="space-y-3">
                  <WorkspaceSection icon={<Hash className="h-3.5 w-3.5" />} label="对比参数" hint="pipeline hash">
                    <div className="space-y-3">
                      <div className="space-y-1.5">
                        <Label htmlFor="pipeline-hash-a" className="flex items-center gap-1.5 text-[10.5px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
                          <span className="inline-flex h-4 w-4 items-center justify-center rounded-md bg-emerald-50 text-[10px] font-bold text-emerald-700 ring-1 ring-emerald-200/60">A</span>
                          Hash A
                        </Label>
                        <Input
                          id="pipeline-hash-a"
                          placeholder="ph_a..."
                          value={pipelineHashA}
                          onChange={(e) => setPipelineHashA(e.target.value)}
                          className={formInputClassName}
                        />
                      </div>

                      <div className="space-y-1.5">
                        <Label htmlFor="pipeline-hash-b" className="flex items-center gap-1.5 text-[10.5px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
                          <span className="inline-flex h-4 w-4 items-center justify-center rounded-md bg-sky-50 text-[10px] font-bold text-sky-700 ring-1 ring-sky-200/60">B</span>
                          Hash B
                        </Label>
                        <Input
                          id="pipeline-hash-b"
                          placeholder="ph_b..."
                          value={pipelineHashB}
                          onChange={(e) => setPipelineHashB(e.target.value)}
                          className={formInputClassName}
                        />
                      </div>
                    </div>
                  </WorkspaceSection>

                  <WorkspaceSection icon={<Layers className="h-3.5 w-3.5" />} label="作用范围" hint="document_ids">
                    <div className="space-y-1.5">
                      <Label htmlFor="document-ids" className="text-[10.5px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
                        document_ids
                      </Label>
                      <Textarea
                        id="document-ids"
                        placeholder="按逗号或换行填写。留空表示使用默认可访问文档集合。"
                        value={documentIdsRaw}
                        onChange={(e) => setDocumentIdsRaw(e.target.value)}
                        rows={5}
                        className={formTextareaClassName}
                      />
                    </div>

                    <div className="flex flex-wrap items-center gap-2">
                      <SnapshotInlineStat
                        icon={<Database className="h-3.5 w-3.5" />}
                        label="Docs"
                        value={documentIds.length || 'All'}
                        tone={documentIds.length ? 'neutral' : 'muted'}
                      />
                      <SnapshotInlineStat
                        icon={<ShieldCheck className="h-3.5 w-3.5" />}
                        label="Mode"
                        value="PII-safe"
                        tone="muted"
                      />
                    </div>
                  </WorkspaceSection>
                </div>
              </div>

              <div className="shrink-0 border-t border-border/70 bg-background/95 px-4 py-4 backdrop-blur">
                <div className="grid grid-cols-2 gap-2">
                  <Button
                    variant="outline"
                    className="h-10 gap-1.5 rounded-lg border-border/70 bg-card text-xs font-medium"
                    onClick={() => detachPromise(runExport('a'))}
                    disabled={isRunning}
                  >
                    <Download className="h-3.5 w-3.5" aria-hidden="true" />
                    导出 A
                  </Button>
                  <Button
                    variant="outline"
                    className="h-10 gap-1.5 rounded-lg border-border/70 bg-card text-xs font-medium"
                    onClick={() => detachPromise(runExport('b'))}
                    disabled={isRunning}
                  >
                    <Download className="h-3.5 w-3.5" aria-hidden="true" />
                    导出 B
                  </Button>
                </div>

                <Button
                  className="mt-2.5 h-11 w-full gap-2 rounded-xl bg-[linear-gradient(90deg,hsl(var(--primary)),hsl(var(--info)))] text-sm font-semibold text-primary-foreground shadow-md transition-shadow hover:shadow-lg"
                  onClick={() => detachPromise(runCompare())}
                  disabled={isRunning}
                >
                  {isRunning ? (
                    <RefreshCcw className="h-4 w-4 animate-spin" aria-hidden="true" />
                  ) : (
                    <GitCompare className="h-4 w-4" aria-hidden="true" />
                  )}
                  {isRunning ? '对比中…' : '开始对比'}
                </Button>

                <Button
                  variant="outline"
                  className="mt-2 h-10 w-full gap-1.5 rounded-xl border-border/70 bg-card text-xs font-medium"
                  onClick={() => detachPromise(runBackendCompare())}
                  disabled={isRunning}
                >
                  <ArrowRightLeft className="h-3.5 w-3.5" aria-hidden="true" />
                  后端对比
                </Button>

                <p className="mt-3 text-[11px] leading-5 text-muted-foreground/85">
                  默认请求 bounded 明细：节点、边、属性 hash 都会参与 diff；完整溯源仍可结合 KG diagnostics 或 traces 排查。
                </p>
              </div>
            </div>
          </aside>

          <section className="min-w-0 flex-1 bg-card">
            {workspaceTab === 'studio' ? (
              <Tabs
                value={activeView}
                onValueChange={(value) => {
                  startTransition(() => setActiveView(value as SnapshotView))
                }}
                className="flex h-full min-h-0 flex-col"
              >
                <div className="shrink-0 border-b border-border/70 bg-[linear-gradient(180deg,hsl(var(--background)),hsl(var(--muted)/0.15))]">
                  <div className="px-4 py-3">
                    <div className="flex flex-wrap items-center justify-between gap-3">
                      <div className="min-w-0">
                        <div className="inline-flex items-center gap-1.5 text-[10.5px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
                          <FileJson className="h-3.5 w-3.5 text-primary/70" aria-hidden="true" />
                          Snapshot Studio
                        </div>
                        <div className="mt-0.5 truncate text-[15px] font-semibold text-foreground">
                          {tabLabelForView(activeView)}
                        </div>
                      </div>

                      <TabsList className="h-9 gap-1 rounded-xl border border-border/70 bg-card p-1 shadow-sm">
                        <TabsTrigger
                          value="diff"
                          className="inline-flex h-7 items-center gap-1.5 rounded-lg px-3 text-[12px] font-medium text-muted-foreground transition-colors data-[state=active]:bg-primary data-[state=active]:text-primary-foreground data-[state=active]:shadow-sm hover:text-foreground"
                        >
                          <ArrowRightLeft className="h-3.5 w-3.5" aria-hidden="true" />
                          Diff 对比
                        </TabsTrigger>
                        <TabsTrigger
                          value="a"
                          className="inline-flex h-7 items-center gap-1.5 rounded-lg px-3 text-[12px] font-medium text-muted-foreground transition-colors data-[state=active]:bg-emerald-500 data-[state=active]:text-white data-[state=active]:shadow-sm hover:text-foreground"
                        >
                          <span className="inline-flex h-4 w-4 items-center justify-center rounded-md bg-emerald-50 text-[10px] font-bold text-emerald-700 ring-1 ring-emerald-200/60 data-[state=active]:bg-emerald-700 data-[state=active]:text-white data-[state=active]:ring-0">A</span>
                          视图 A
                        </TabsTrigger>
                        <TabsTrigger
                          value="b"
                          className="inline-flex h-7 items-center gap-1.5 rounded-lg px-3 text-[12px] font-medium text-muted-foreground transition-colors data-[state=active]:bg-sky-500 data-[state=active]:text-white data-[state=active]:shadow-sm hover:text-foreground"
                        >
                          <span className="inline-flex h-4 w-4 items-center justify-center rounded-md bg-sky-50 text-[10px] font-bold text-sky-700 ring-1 ring-sky-200/60 data-[state=active]:bg-sky-700 data-[state=active]:text-white data-[state=active]:ring-0">B</span>
                          视图 B
                        </TabsTrigger>
                      </TabsList>
                    </div>

                    <div className="mt-2.5 flex flex-wrap items-center gap-2">
                      {diffDelta.delta ? (
                        deltaRows.map((row) => {
                          const sign = row.delta > 0 ? '+' : ''
                          return (
                            <SnapshotInlineStat
                              key={row.key}
                              label={row.key}
                              value={`${row.a} → ${row.b} (${sign}${row.delta})`}
                              tone={row.delta > 0 ? 'positive' : row.delta < 0 ? 'negative' : 'muted'}
                            />
                          )
                        })
                      ) : (
                        <span className="inline-flex items-center gap-1.5 rounded-full border border-dashed border-border/70 bg-card/60 px-2.5 py-1 text-[11px] text-muted-foreground">
                          <CircleDashed className="h-3.5 w-3.5 text-primary/60" aria-hidden="true" />
                          填写 A / B Hash 后点击「开始对比」即可查看 docs / events / entities / links / relations 增量
                        </span>
                      )}
                    </div>
                  </div>
                </div>

                <TabsContent value="diff" className="mt-0 min-h-0 flex-1">
                  <SnapshotDiffView
                    titleA={`Snapshot A · ${hashATitle}`}
                    titleB={`Snapshot B · ${hashBTitle}`}
                    subtitleA={documentIds.length ? `${documentIds.length} 个 document_ids` : '默认可访问范围'}
                    subtitleB={documentIds.length ? `${documentIds.length} 个 document_ids` : '默认可访问范围'}
                    leftCode={snapAJson}
                    rightCode={snapBJson}
                    diff={diff}
                    typeDrift={auditDriftRows}
                    isEmpty={!diff}
                    emptyState={
                      <DiffEmptyState
                        title="还没有对比结果"
                        description="填写左侧的 Hash A / Hash B，可以选择 document_ids 圈定范围，然后点击「开始对比」生成 side-by-side diff 与节点/边精确变更。"
                        hint={hasHashA && hasHashB ? '已就绪：直接点击「开始对比」' : '提示：A / B Hash 二者皆需填写'}
                      />
                    }
                    onCopy={() => detachPromise(copyToClipboard(diffJson, 'diff JSON'))}
                    onDownload={() => {
                      downloadJson(diff ?? {}, `${diffBaseName}.diff.json`)
                      toast.success('已导出 diff.json')
                    }}
                  />
                </TabsContent>

                <TabsContent value="a" className="mt-0 min-h-0 flex-1">
                  <JsonCodePane
                    label="A 视图"
                    title="快照内容"
                    subtitle={hashAValue ? `Hash · ${hashAValue}` : '尚未导出'}
                    code={snapAJson}
                    isEmpty={!snapA}
                    emptyState={
                      <DiffEmptyState
                        title="A 视图为空"
                        description="先在左侧填写 Hash A，然后点击「导出 A」即可在此查看 bounded 快照 JSON。"
                        hint={hasHashA ? '已填写 Hash A，可点击「导出 A」' : '请先填写 Hash A'}
                      />
                    }
                    onCopy={() => detachPromise(copyToClipboard(snapAJson, 'snapshot A JSON'))}
                    onDownload={() => {
                      downloadJson(snapA ?? {}, `${snapshotAFileName}.json`)
                      toast.success('已导出 snapshot A')
                    }}
                  />
                </TabsContent>

                <TabsContent value="b" className="mt-0 min-h-0 flex-1">
                  <JsonCodePane
                    label="B 视图"
                    title="快照内容"
                    subtitle={hashBValue ? `Hash · ${hashBValue}` : '尚未导出'}
                    code={snapBJson}
                    isEmpty={!snapB}
                    emptyState={
                      <DiffEmptyState
                        title="B 视图为空"
                        description="先在左侧填写 Hash B，然后点击「导出 B」即可在此查看 bounded 快照 JSON。"
                        hint={hasHashB ? '已填写 Hash B，可点击「导出 B」' : '请先填写 Hash B'}
                      />
                    }
                    onCopy={() => detachPromise(copyToClipboard(snapBJson, 'snapshot B JSON'))}
                    onDownload={() => {
                      downloadJson(snapB ?? {}, `${snapshotBFileName}.json`)
                      toast.success('已导出 snapshot B')
                    }}
                  />
                </TabsContent>
              </Tabs>
            ) : (
              <SnapshotAuditPanel
                deltaRows={deltaRows}
                typeDriftRows={auditDriftRows}
                severity={auditSeverity}
                driftScore={driftScore}
                includeZeroDeltas={includeZeroDeltas}
                compactRows={compactAuditRows}
                onIncludeZeroDeltasChange={setIncludeZeroDeltas}
                onCompactRowsChange={setCompactAuditRows}
              />
            )}
          </section>
        </div>
      </div>
    </AppFrame>
  )
}
