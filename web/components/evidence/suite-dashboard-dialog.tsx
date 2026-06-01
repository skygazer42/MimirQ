'use client'

import type { ReactNode } from 'react'
import { Loader2, RefreshCw } from 'lucide-react'

import type { EvidenceCoverageHeatmap, EvidenceSuite, EvidenceSuiteDashboard } from '@/types'
import { cn } from '@/lib/utils'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Panel } from '@/components/ui/panel'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Separator } from '@/components/ui/separator'

type SuiteDashboardDialogProps = {
  open: boolean
  selectedSuite: EvidenceSuite | null
  selectedSuiteId: string
  includeArchived: boolean
  loading: boolean
  error: string | null
  dashboard: EvidenceSuiteDashboard | null
  onOpenChange: (open: boolean) => void
  onIncludeArchivedChange: (value: boolean) => void
  onRefresh: () => void
}

function heatmapCellBg(value: number, ratio: number): string {
  if (value === 0) return 'bg-muted/20'
  if (ratio >= 0.75) return 'bg-primary/30'
  if (ratio >= 0.5) return 'bg-primary/20'
  if (ratio >= 0.25) return 'bg-primary/10'
  return 'bg-primary/5'
}

function renderLanguageXFileTypeHeatmap(heatmap: EvidenceCoverageHeatmap | null | undefined): ReactNode {
  const x = Array.isArray(heatmap?.x) ? heatmap.x : []
  const y = Array.isArray(heatmap?.y) ? heatmap.y : []
  const z = Array.isArray(heatmap?.z) ? heatmap.z : []

  let max = 0
  for (const row of z) {
    if (!Array.isArray(row)) continue
    for (const value of row) {
      const next = Number(value) || 0
      if (next > max) max = next
    }
  }

  const xNodes: ReactNode[] = []
  for (const fileType of x) {
    const label = String(fileType ?? '')
    xNodes.push(
      <div key={`hm-x:${label}`} className="bg-muted/40 px-2 py-1 text-[11px] font-mono truncate">
        {label}
      </div>,
    )
  }

  const rowNodes: ReactNode[] = []
  for (let rowIndex = 0; rowIndex < y.length; rowIndex++) {
    const languageLabel = String(y[rowIndex] ?? '')
    const row = Array.isArray(z[rowIndex]) ? z[rowIndex] : []
    const cellNodes: ReactNode[] = []
    for (let colIndex = 0; colIndex < x.length; colIndex++) {
      const fileTypeLabel = String(x[colIndex] ?? '')
      const value = Number(row?.[colIndex] ?? 0) || 0
      const ratio = max > 0 ? value / max : 0
      const cellBg = heatmapCellBg(value, ratio)
      cellNodes.push(
        <div
          key={`hm-cell:${languageLabel}:${fileTypeLabel}`}
          className={cn('px-2 py-1 text-[11px] font-mono tabular-nums text-center', cellBg)}
        >
          {value}
        </div>,
      )
    }

    rowNodes.push(
      <div key={`hm-row:${languageLabel}`} className="contents">
        <div className="bg-muted/30 px-2 py-1 text-[11px] font-mono text-muted-foreground truncate">{languageLabel}</div>
        {cellNodes}
      </div>,
    )
  }

  return (
    <div
      className="grid gap-px rounded-lg overflow-hidden border border-border/60 bg-border/60"
      style={{ gridTemplateColumns: `120px repeat(${x.length}, minmax(72px, 1fr))` }}
    >
      <div className="bg-muted/40 px-2 py-1 text-[11px] font-mono text-muted-foreground">lang \\ ft</div>
      {xNodes}
      {rowNodes}
    </div>
  )
}

function formatDurationSec(value: unknown): string {
  const seconds = Number(value)
  if (!Number.isFinite(seconds) || seconds <= 0) return '-'
  const mins = seconds / 60
  if (mins < 60) return `${Math.round(mins)}m`
  const hours = mins / 60
  if (hours < 48) return `${hours.toFixed(1)}h`
  const days = hours / 24
  return `${days.toFixed(1)}d`
}

export function SuiteDashboardDialog({
  open,
  selectedSuite,
  selectedSuiteId,
  includeArchived,
  loading,
  error,
  dashboard,
  onOpenChange,
  onIncludeArchivedChange,
  onRefresh,
}: Readonly<SuiteDashboardDialogProps>) {
  const throughput = dashboard?.throughput
  const coverage = dashboard?.coverage
  const suiteDescription = selectedSuite ? (
    <>
      Suite <span className="font-mono">{String(selectedSuite.id).slice(0, 8)}</span> 路{' '}
      <span className="font-medium">{selectedSuite.name}</span>
    </>
  ) : (
    '请选择一个 Suite'
  )
  const generatedSummary = dashboard ? (
    <div className="text-xs text-muted-foreground font-mono tabular-nums">
      generated {String(dashboard.generated_at || '').slice(0, 19).replaceAll('T', ' ')}
    </div>
  ) : null

  let throughputSection: ReactNode
  if (throughput) {
    throughputSection = (
      <div>
        <div className="mb-2 text-xs font-medium text-muted-foreground">Throughput (last {throughput.window_days}d)</div>
        <div className="flex flex-wrap gap-2 text-xs">
          <Badge variant="outline" className="font-mono tabular-nums">
            created {throughput.last_window?.created ?? 0}
          </Badge>
          <Badge variant="secondary" className="font-mono tabular-nums">
            reviewed {throughput.last_window?.reviewed ?? 0}
          </Badge>
          <Badge variant="soft" className="font-mono tabular-nums">
            approved {throughput.last_window?.approved ?? 0}
          </Badge>
        </div>

        <div className="mt-3 grid grid-cols-1 gap-3 md:grid-cols-3">
          <Panel className="p-3">
            <div className="mb-1 text-xs font-medium text-muted-foreground">draft → reviewed</div>
            <div className="text-xs text-muted-foreground font-mono tabular-nums">
              n {throughput.draft_to_reviewed?.count ?? 0}
            </div>
            <div className="mt-1 text-xs font-mono tabular-nums">
              p50 {formatDurationSec(throughput.draft_to_reviewed?.p50_sec ?? 0)} · p90{' '}
              {formatDurationSec(throughput.draft_to_reviewed?.p90_sec ?? 0)} · mean{' '}
              {formatDurationSec(throughput.draft_to_reviewed?.mean_sec ?? 0)}
            </div>
          </Panel>

          <Panel className="p-3">
            <div className="mb-1 text-xs font-medium text-muted-foreground">reviewed → approved</div>
            <div className="text-xs text-muted-foreground font-mono tabular-nums">
              n {throughput.reviewed_to_approved?.count ?? 0}
            </div>
            <div className="mt-1 text-xs font-mono tabular-nums">
              p50 {formatDurationSec(throughput.reviewed_to_approved?.p50_sec ?? 0)} · p90{' '}
              {formatDurationSec(throughput.reviewed_to_approved?.p90_sec ?? 0)} · mean{' '}
              {formatDurationSec(throughput.reviewed_to_approved?.mean_sec ?? 0)}
            </div>
          </Panel>

          <Panel className="p-3">
            <div className="mb-1 text-xs font-medium text-muted-foreground">draft → approved</div>
            <div className="text-xs text-muted-foreground font-mono tabular-nums">
              n {throughput.draft_to_approved?.count ?? 0}
            </div>
            <div className="mt-1 text-xs font-mono tabular-nums">
              p50 {formatDurationSec(throughput.draft_to_approved?.p50_sec ?? 0)} · p90{' '}
              {formatDurationSec(throughput.draft_to_approved?.p90_sec ?? 0)} · mean{' '}
              {formatDurationSec(throughput.draft_to_approved?.mean_sec ?? 0)}
            </div>
          </Panel>
        </div>
      </div>
    )
  } else {
    throughputSection = <div className="text-sm text-muted-foreground text-pretty">No throughput data.</div>
  }

  let coverageSection: ReactNode
  if (coverage) {
    coverageSection = (
      <>
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          <Panel className="p-3">
            <div className="mb-2 text-xs font-medium text-muted-foreground">Language coverage</div>
            <div className="space-y-1">
              {(coverage.language || []).map((bucket) => (
                <div key={`lang:${bucket.key}`} className="flex items-center justify-between gap-3 text-xs">
                  <div className="min-w-0 truncate font-mono">{bucket.key}</div>
                  <div className="flex items-center gap-3 font-mono tabular-nums text-muted-foreground">
                    <span>refs {bucket.references}</span>
                    <span>items {bucket.items}</span>
                  </div>
                </div>
              ))}
            </div>
          </Panel>

          <Panel className="p-3">
            <div className="mb-2 text-xs font-medium text-muted-foreground">File type coverage</div>
            <div className="space-y-1">
              {(coverage.file_type || []).map((bucket) => (
                <div key={`ft:${bucket.key}`} className="flex items-center justify-between gap-3 text-xs">
                  <div className="min-w-0 truncate font-mono">{bucket.key}</div>
                  <div className="flex items-center gap-3 font-mono tabular-nums text-muted-foreground">
                    <span>refs {bucket.references}</span>
                    <span>items {bucket.items}</span>
                  </div>
                </div>
              ))}
            </div>
          </Panel>

          <Panel className="p-3">
            <div className="mb-2 text-xs font-medium text-muted-foreground">Quality bucket coverage</div>
            <div className="space-y-1">
              {(coverage.quality_bucket || []).map((bucket) => (
                <div key={`qb:${bucket.key}`} className="flex items-center justify-between gap-3 text-xs">
                  <div className="min-w-0 truncate font-mono">{bucket.key}</div>
                  <div className="flex items-center gap-3 font-mono tabular-nums text-muted-foreground">
                    <span>refs {bucket.references}</span>
                    <span>items {bucket.items}</span>
                  </div>
                </div>
              ))}
            </div>
          </Panel>

          <Panel className="p-3">
            <div className="mb-2 text-xs font-medium text-muted-foreground">Channel (hit_type) coverage</div>
            <div className="space-y-1">
              {(coverage.channel || []).map((bucket) => (
                <div key={`ch:${bucket.key}`} className="flex items-center justify-between gap-3 text-xs">
                  <div className="min-w-0 truncate font-mono">{bucket.key}</div>
                  <div className="flex items-center gap-3 font-mono tabular-nums text-muted-foreground">
                    <span>refs {bucket.references}</span>
                    <span>items {bucket.items}</span>
                  </div>
                </div>
              ))}
            </div>
          </Panel>
        </div>

        <Panel className="p-3">
          <div className="mb-2 text-xs font-medium text-muted-foreground">Heatmap: language × file_type (unique items)</div>
          {coverage.heatmaps?.language_x_file_type ? (
            <div className="overflow-x-auto">{renderLanguageXFileTypeHeatmap(coverage.heatmaps.language_x_file_type)}</div>
          ) : (
            <div className="text-xs text-muted-foreground">No heatmap data.</div>
          )}
        </Panel>
      </>
    )
  } else {
    coverageSection = <div className="text-sm text-muted-foreground text-pretty">No coverage data.</div>
  }

  let dashboardContent: ReactNode
  if (loading) {
    dashboardContent = (
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="size-4 animate-spin motion-reduce:animate-none" aria-hidden="true" />
        loading…
      </div>
    )
  } else if (dashboard) {
    dashboardContent = (
      <>
        {throughputSection}
        <Separator />
        {coverageSection}
      </>
    )
  } else {
    dashboardContent = <div className="text-sm text-muted-foreground text-pretty">No dashboard data.</div>
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-4xl overflow-hidden">
        <DialogHeader>
          <DialogTitle>Suite Dashboard</DialogTitle>
          <DialogDescription className="text-pretty">
            {suiteDescription}
          </DialogDescription>
        </DialogHeader>

        <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
          <div className="inline-flex items-center gap-2 select-none text-xs text-muted-foreground">
            <Checkbox
              checked={includeArchived}
              onCheckedChange={(value) => onIncludeArchivedChange(Boolean(value))}
              aria-label="Include archived items"
            />
            include archived items
          </div>

          <div className="flex items-center gap-2 sm:ml-auto">
            {generatedSummary}
            <Button variant="outline" size="sm" className="gap-2" onClick={onRefresh} disabled={!selectedSuiteId || loading}>
              <RefreshCw className={cn('size-4', loading ? 'animate-spin motion-reduce:animate-none' : '')} aria-hidden="true" />
              refresh
            </Button>
          </div>
        </div>

        {error ? <div className="text-xs text-destructive text-pretty">{error}</div> : null}

        <ScrollArea className="max-h-[70vh] pr-3">
          <div className="space-y-4">
            {dashboardContent}
          </div>
        </ScrollArea>
      </DialogContent>
    </Dialog>
  )
}
