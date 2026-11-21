'use client'

import { RefreshCw } from '@/components/icons'
import type { EvidenceSuite } from '@/types'
import type { CoverageHeatmap, SuiteDashboard, SuiteDashboardSnapshot } from '@/lib/evidence-dashboard'
import { cn } from '@/lib/utils'
import { Badge } from '@/components/ui/badge'
import { Checkbox } from '@/components/ui/checkbox'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { LoadingButton } from '@/components/ui/loading-button'
import { Panel } from '@/components/ui/panel'
import { Separator } from '@/components/ui/separator'
import { Skeleton } from '@/components/ui/skeleton'
import { WorkspaceNotice, workspaceStyles as ws } from '@/components/ui/operational-workspace'

type SuiteDashboardDialogProps = {
  open: boolean
  selectedSuite: EvidenceSuite | null
  selectedSuiteId: string
  includeArchived: boolean
  loading: boolean
  error: string | null
  snapshot: SuiteDashboardSnapshot | null
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

function LanguageFileTypeHeatmap({ heatmap }: { heatmap: CoverageHeatmap }) {
  if (heatmap.x.length === 0 || heatmap.y.length === 0) {
    return <p className={ws.muted}>暂无语言与文件类型交叉统计。</p>
  }
  let maximum = 0
  for (const row of heatmap.z) {
    for (const value of row) {
      if (value > maximum) maximum = value
    }
  }
  return (
    <div className="overflow-x-auto" tabIndex={0} role="region" aria-label="语言与文件类型热图">
      <table className="w-full border-collapse text-xs font-mono" aria-label="语言与文件类型覆盖">
        <caption className="sr-only">language × file_type · {heatmap.metric}</caption>
        <thead>
          <tr>
            <th scope="col" className="min-w-[120px] border border-border/60 bg-muted/40 px-2 py-1 text-left">
              language / file_type
            </th>
            {heatmap.x.map((fileType) => (
              <th key={fileType} scope="col" className="min-w-[72px] border border-border/60 bg-muted/40 px-2 py-1">
                {fileType}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {heatmap.z.map((row, rowIndex) => (
            <tr key={heatmap.y[rowIndex]}>
              <th
                scope="row"
                className="border border-border/60 bg-muted/30 px-2 py-1 text-left font-normal text-muted-foreground"
              >
                {heatmap.y[rowIndex]}
              </th>
              {row.map((value, columnIndex) => (
                <td
                  key={heatmap.x[columnIndex]}
                  className={cn(
                    'border border-border/60 px-2 py-1 text-center tabular-nums',
                    heatmapCellBg(value, maximum === 0 ? 0 : value / maximum),
                  )}
                >
                  {value}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function formatDurationSec(value: number | null | undefined): string {
  if (value === undefined || value === null) return '未提供'
  if (value < 60) return `${value}s`
  const minutes = value / 60
  if (minutes < 60) return `${Math.round(minutes)}m`
  const hours = minutes / 60
  if (hours < 48) return `${hours.toFixed(1)}h`
  return `${(hours / 24).toFixed(1)}d`
}

function LeadTimePanel({ title, stats }: { title: string; stats: SuiteDashboard['throughput']['draft_to_reviewed'] }) {
  return (
    <Panel className="p-3">
      <h3 className="mb-1 text-xs font-medium text-muted-foreground">{title}</h3>
      <div className="text-xs text-muted-foreground font-mono tabular-nums">n {stats.count}</div>
      <div className="mt-1 text-xs font-mono tabular-nums">
        p50 {formatDurationSec(stats.p50_sec)} · p90 {formatDurationSec(stats.p90_sec)} · mean{' '}
        {formatDurationSec(stats.mean_sec)}
      </div>
    </Panel>
  )
}

function CoveragePanel({ title, buckets }: { title: string; buckets: SuiteDashboard['coverage']['language'] }) {
  return (
    <Panel className="p-3">
      <h3 className="mb-2 text-xs font-medium text-muted-foreground">{title}</h3>
      <div className="space-y-1">
        {buckets.length === 0 ? (
          <p className={ws.muted}>暂无覆盖记录。</p>
        ) : (
          buckets.map((bucket) => (
            <div key={bucket.key} className="flex items-center justify-between gap-3 text-xs">
              <div className="min-w-0 truncate font-mono">{bucket.key}</div>
              <div className="flex items-center gap-3 font-mono tabular-nums text-muted-foreground">
                <span>refs {bucket.references}</span>
                <span>items {bucket.items}</span>
              </div>
            </div>
          ))
        )}
      </div>
    </Panel>
  )
}

function DashboardContent({ snapshot }: { snapshot: SuiteDashboardSnapshot }) {
  const { throughput, coverage } = snapshot.data
  const heatmap = coverage.heatmaps.language_x_file_type
  return (
    <div className="space-y-4">
      <p className={ws.muted}>当前统计：{snapshot.includeArchived ? '包含已归档条目' : '不含已归档条目'}</p>
      <section className="space-y-3" aria-label="条目流转统计">
        <h2 className="text-xs font-medium text-muted-foreground">Throughput (last {throughput.window_days}d)</h2>
        <div className="flex flex-wrap gap-2 text-xs">
          <Badge variant="outline" className="font-mono tabular-nums">
            created {throughput.last_window.created}
          </Badge>
          <Badge variant="secondary" className="font-mono tabular-nums">
            reviewed {throughput.last_window.reviewed}
          </Badge>
          <Badge variant="soft" className="font-mono tabular-nums">
            approved {throughput.last_window.approved}
          </Badge>
        </div>
        <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
          <LeadTimePanel title="draft → reviewed" stats={throughput.draft_to_reviewed} />
          <LeadTimePanel title="reviewed → approved" stats={throughput.reviewed_to_approved} />
          <LeadTimePanel title="draft → approved" stats={throughput.draft_to_approved} />
        </div>
      </section>
      <Separator />
      <section className="grid grid-cols-1 gap-3 md:grid-cols-2" aria-label="引用覆盖统计">
        <CoveragePanel title="Language coverage" buckets={coverage.language} />
        <CoveragePanel title="File type coverage" buckets={coverage.file_type} />
        <CoveragePanel title="Quality bucket coverage" buckets={coverage.quality_bucket} />
        <CoveragePanel title="Channel (hit_type) coverage" buckets={coverage.channel} />
      </section>
      <Panel className="p-3">
        <h2 className="mb-2 text-xs font-medium text-muted-foreground">Heatmap: language × file_type</h2>
        {heatmap === undefined ? (
          <p className={ws.muted}>暂无交叉统计。</p>
        ) : (
          <LanguageFileTypeHeatmap heatmap={heatmap} />
        )}
      </Panel>
    </div>
  )
}

export function SuiteDashboardDialog({
  open,
  selectedSuite,
  selectedSuiteId,
  includeArchived,
  loading,
  error,
  snapshot,
  onOpenChange,
  onIncludeArchivedChange,
  onRefresh,
}: Readonly<SuiteDashboardDialogProps>) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className={`${ws.dialog} ${ws.wideDialog}`}>
        <DialogHeader className={ws.dialogHeader}>
          <DialogTitle>Suite Dashboard</DialogTitle>
          <DialogDescription className="text-pretty">
            {selectedSuite === null ? (
              '请选择一个 Suite'
            ) : (
              <>
                Suite <span className="font-mono">{selectedSuite.id.slice(0, 8)}</span> · {selectedSuite.name}
              </>
            )}{' '}
            统计最近更新的最多 10,000 个条目。
          </DialogDescription>
        </DialogHeader>
        <div className={ws.dialogBody}>
          <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center">
            <label className="inline-flex items-center gap-2 text-xs text-muted-foreground">
              <Checkbox
                checked={includeArchived}
                onCheckedChange={(value) => onIncludeArchivedChange(value === true)}
                aria-label="Include archived items"
              />
              include archived items
            </label>
            <div className="flex flex-wrap items-center gap-2 sm:ml-auto">
              {snapshot !== null ? (
                <span className="text-xs font-mono tabular-nums text-muted-foreground">
                  generated {snapshot.data.generated_at.slice(0, 19).replaceAll('T', ' ')}
                </span>
              ) : null}
              <LoadingButton
                loading={loading}
                variant="outline"
                size="sm"
                onClick={onRefresh}
                disabled={!selectedSuiteId}
              >
                <RefreshCw className="size-4" aria-hidden="true" />
                refresh
              </LoadingButton>
            </div>
          </div>
          {error !== null ? (
            <WorkspaceNotice retry={onRefresh} pending={loading}>
              {error}
            </WorkspaceNotice>
          ) : null}
          <div aria-busy={loading}>
            {snapshot !== null ? (
              <DashboardContent snapshot={snapshot} />
            ) : loading ? (
              <div className="space-y-3" role="status" aria-label="正在读取统计">
                <Skeleton className="h-6 w-40" />
                <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
                  <Skeleton className="h-20" />
                  <Skeleton className="h-20" />
                  <Skeleton className="h-20" />
                </div>
                <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                  <Skeleton className="h-24" />
                  <Skeleton className="h-24" />
                </div>
              </div>
            ) : error === null ? (
              <p className={ws.muted}>点击 refresh 加载统计。</p>
            ) : null}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}
