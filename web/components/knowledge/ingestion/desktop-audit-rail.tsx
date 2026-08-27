'use client'

import { motion } from 'framer-motion'
import { Check, ChevronLeft } from 'lucide-react'

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { cn, formatFileSize } from '@/lib/utils'
import type { Dataset, Document } from '@/types'
import { getDocumentKind, getDocumentKindAccent } from '@/components/ingestion/monitor-utils'
import { getAuditRailStatusTone, getProgressTone } from '@/app/knowledge/ingestion/presentation'
import type { SampleDisposition } from '@/app/knowledge/ingestion/types'

export type AuditDispositionFilter = 'all' | 'pending' | 'manual' | 'approved'

type AuditRailCounts = {
  all: number
  pending: number
  manual: number
  approved: number
}

type DesktopAuditRailProps = {
  auditDispositionFilter: AuditDispositionFilter
  auditRailCounts: AuditRailCounts
  datasetScope: string
  datasets: Dataset[]
  selectedAuditIds: string[]
  selectedReason: string | null
  scopeLabel: string
  showDesktopAuditRail: boolean
  visibleAuditSamples: Document[]
  onClearSelectedReason: () => void
  onDatasetScopeChange: (value: string) => void
  onOpenAuditSnapshot: (documentId: string) => void
  resolvedSampleDispositions: Record<string, SampleDisposition>
  onSampleDisposition: (
    documentId: string,
    disposition: SampleDisposition
  ) => void
  onSelectAudit: (documentId: string) => void
  onSetAuditDispositionFilter: (value: AuditDispositionFilter) => void
  onSetDesktopScopeCollapsed: (value: boolean) => void
}

export function DesktopAuditRail({
  auditDispositionFilter,
  auditRailCounts,
  datasetScope,
  datasets,
  scopeLabel,
  selectedAuditIds,
  selectedReason,
  showDesktopAuditRail,
  visibleAuditSamples,
  onClearSelectedReason,
  onDatasetScopeChange,
  onOpenAuditSnapshot,
  resolvedSampleDispositions,
  onSampleDisposition,
  onSelectAudit,
  onSetAuditDispositionFilter,
  onSetDesktopScopeCollapsed,
}: Readonly<DesktopAuditRailProps>) {
  return (
    <aside
        className={cn(
          'hidden shrink-0 overflow-hidden pr-3 transition-all duration-300 ease-out lg:block',
          showDesktopAuditRail
            ? 'w-[15.5rem] opacity-100'
            : 'w-0 opacity-0 -translate-x-4 pointer-events-none'
        )}
      >
        <div className="sticky top-4">
          <div className="overflow-hidden rounded-[0.95rem] border border-border/38 bg-background/64 p-1.5 shadow-none backdrop-blur-xl">
            <div className="flex items-center justify-between gap-2 px-1 pb-1.5">
              <div className="flex min-w-0 items-center gap-2">
                <span className="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-[0.65rem] border border-border/45 bg-muted/20 text-muted-foreground">
                  <Check className="h-3.5 w-3.5" />
                </span>
                <div className="min-w-0">
                  <div className="text-[10px] font-semibold text-foreground">
                    运行范围
                  </div>
                  <div className="mt-0.5 truncate text-[8px] text-muted-foreground">
                    轻量筛选数据集与线索
                  </div>
                </div>
              </div>
              <button
                type="button"
                className="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-full border border-border/45 bg-background/60 text-muted-foreground transition-colors hover:border-info/25 hover:text-foreground"
                onClick={() => onSetDesktopScopeCollapsed(true)}
              >
                <ChevronLeft className="h-3.5 w-3.5" />
              </button>
            </div>

            <div className="mb-1.5 rounded-[0.68rem] border border-border/35 bg-background/45 p-1.5">
              <div className="mb-1 flex items-center justify-between gap-2 px-1">
                <span className="text-[8px] font-medium text-muted-foreground">
                  数据集
                </span>
                <span className="font-mono text-[7px] text-muted-foreground">
                  {scopeLabel}
                </span>
              </div>
              <Select value={datasetScope} onValueChange={onDatasetScopeChange}>
                <SelectTrigger className="h-7 rounded-[0.6rem] border-border/45 bg-background/70 px-2 text-[9px] font-medium shadow-none">
                  <SelectValue placeholder="全部项目" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="__all__">全部项目</SelectItem>
                  {datasets.map((dataset) => (
                    <SelectItem key={dataset.id} value={dataset.id}>
                      {dataset.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="mb-1.5 grid grid-cols-2 gap-1">
              {([
                ['pending', '待确认', auditRailCounts.pending],
                ['manual', '人工处理', auditRailCounts.manual],
                ['approved', '已确认', auditRailCounts.approved],
              ] as const).map(([value, label, count]) => (
                <button
                  key={value}
                  type="button"
                  aria-pressed={auditDispositionFilter === value}
                  onClick={() => onSetAuditDispositionFilter(value)}
                  className={cn(
                    'rounded-[0.56rem] border px-1.5 py-1 text-left text-[8px] transition-colors',
                    auditDispositionFilter === value
                      ? 'border-info/25 bg-info/10 text-info'
                      : 'border-border/35 bg-background/50 text-muted-foreground hover:text-foreground'
                  )}
                >
                  <span className="block font-medium">{label}</span>
                  <span className="font-mono tabular-nums">{count}</span>
                </button>
              ))}
              <button
                type="button"
                aria-pressed={auditDispositionFilter === 'all'}
                onClick={() => onSetAuditDispositionFilter('all')}
                className={cn(
                  'rounded-[0.56rem] border px-1.5 py-1 text-left text-[8px] transition-colors',
                  auditDispositionFilter === 'all'
                    ? 'border-info/25 bg-info/10 text-info'
                    : 'border-border/35 bg-background/50 text-muted-foreground hover:text-foreground'
                )}
              >
                <span className="block font-medium">全部</span>
                <span className="font-mono tabular-nums">
                  {auditRailCounts.all}
                </span>
              </button>
            </div>

            <div className="space-y-1.5">
              {visibleAuditSamples.map((document) => {
                const kind = getDocumentKind(document.filename)
                const disposition = resolvedSampleDispositions[document.id]
                const status = String(document.status || '').toLowerCase()
                const progress = Math.max(
                  0,
                  Math.min(100, Number(document.processing_progress || 0))
                )
                const statusPresentation = getAuditRailStatusTone({
                  disposition,
                  status,
                })
                const stageLabel =
                  document.current_stage ||
                  (status === 'completed' ? 'completed' : status)

                return (
                  <motion.article
                    key={document.id}
                    drag="x"
                    dragConstraints={{ left: 0, right: 0 }}
                    dragElastic={0.16}
                    onDragEnd={(_, info) => {
                      if (info.offset.x > 100) {
                        onSampleDisposition(document.id, 'approved')
                      }
                      if (info.offset.x < -100) {
                        onSampleDisposition(document.id, 'manual')
                      }
                    }}
                    className="group relative overflow-hidden rounded-[0.74rem] border border-border/38 bg-background/62 px-1.5 py-1.5 shadow-none transition-colors hover:border-info/25 hover:bg-background/82"
                  >
                    <div className="flex items-start gap-2">
                      <input
                        checked={selectedAuditIds.includes(document.id)}
                        onChange={() => onSelectAudit(document.id)}
                        className="mt-1 h-2.5 w-2.5 rounded border-border/60 text-foreground"
                        type="checkbox"
                        aria-label={`选择 ${document.filename}`}
                      />
                      <span
                        className={cn(
                          'mt-0.5 inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-[0.65rem] border text-[7px] font-semibold uppercase',
                          getDocumentKindAccent(kind)
                        )}
                      >
                        {String(document.file_type || kind).toUpperCase()}
                      </span>
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center justify-between gap-2">
                          <div className="min-w-0">
                            <div className="truncate text-[10.5px] font-semibold leading-4 text-foreground">
                              {document.filename}
                            </div>
                          </div>
                          <span
                            className={cn(
                              'shrink-0 rounded-full border px-1.5 py-0.5 text-[8px] font-medium',
                              statusPresentation.tone
                            )}
                          >
                            {statusPresentation.label}
                          </span>
                        </div>

                        <div className="mt-0.5 flex flex-wrap items-center gap-x-1.5 gap-y-0.5 text-[8px] text-muted-foreground">
                          <span className="max-w-[6.5rem] truncate">
                            {stageLabel}
                          </span>
                          <span className="font-mono tabular-nums">
                            {formatFileSize(document.file_size || 0)}
                          </span>
                          <span className="font-mono tabular-nums">
                            {Number(document.chunk_count || 0)} 块
                          </span>
                          <span className="font-mono tabular-nums">
                            {progress}%
                          </span>
                        </div>

                        {document.error_message ? (
                          <div className="mt-1 line-clamp-1 rounded-[0.6rem] border border-destructive/15 bg-destructive/6 px-2 py-1 text-[8px] leading-3 text-destructive">
                            {document.error_message}
                          </div>
                        ) : null}

                        <div className="mt-1 h-0.5 overflow-hidden rounded-full bg-muted/45">
                          <div
                            className={cn(
                              'h-full rounded-full transition-all',
                              getProgressTone(status)
                            )}
                            style={{ width: `${progress}%` }}
                          />
                        </div>
                      </div>
                    </div>
                    <div className="mt-1.5 grid grid-cols-3 gap-1">
                      <button
                        type="button"
                        className="inline-flex h-5 items-center justify-center rounded-[0.45rem] border border-success/20 bg-success/8 px-1.5 text-[7.5px] font-medium text-success transition-colors hover:border-success/35 hover:bg-success/12"
                        onClick={() =>
                          onSampleDisposition(document.id, 'approved')
                        }
                      >
                        确认
                      </button>
                      <button
                        type="button"
                        className="inline-flex h-5 items-center justify-center rounded-[0.45rem] border border-warning/20 bg-warning/8 px-1.5 text-[7.5px] font-medium text-warning transition-colors hover:border-warning/35 hover:bg-warning/12"
                        onClick={() => onSampleDisposition(document.id, 'manual')}
                      >
                        转人工
                      </button>
                      <button
                        type="button"
                        className="inline-flex h-5 items-center justify-center rounded-[0.45rem] border border-border/55 bg-background/70 px-1.5 text-[7.5px] font-medium text-foreground transition-colors hover:border-info/25 hover:text-info"
                        onClick={() => onOpenAuditSnapshot(document.id)}
                      >
                        快照
                      </button>
                    </div>
                  </motion.article>
                )
              })}
              {visibleAuditSamples.length === 0 ? (
                <div className="rounded-[0.78rem] border border-dashed border-border/55 bg-background/48 px-3 py-4 text-center text-[10px] text-muted-foreground">
                  暂无可见资产
                </div>
              ) : null}
              <div className="flex items-center justify-between border-t border-border/45 px-1 pt-2 text-[9px] font-medium text-muted-foreground">
                <span>共 {visibleAuditSamples.length} 项线索</span>
                {selectedReason ? (
                  <button
                    type="button"
                    className="text-info transition-colors hover:text-info"
                    onClick={onClearSelectedReason}
                  >
                    清除聚焦
                  </button>
                ) : (
                  <span>范围筛选</span>
                )}
              </div>
            </div>
          </div>
        </div>
    </aside>
  )
}
