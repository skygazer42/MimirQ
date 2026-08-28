'use client'

import { ChevronLeft, ChevronRight, Download, Eye, RefreshCw, RotateCcw } from 'lucide-react'

import { getDocumentKind } from '@/components/ingestion/monitor-utils'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { SearchInput } from '@/components/ui/search-input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { cn, detachPromise, formatDate, formatFileSize } from '@/lib/utils'
import type { Document } from '@/types'

import { FileKindGlyph } from '@/app/knowledge/quarantine/components/file-kind-glyph'
import { QuarantineEmptyState } from '@/app/knowledge/quarantine/components/quarantine-empty-state'
import { StatusPill } from '@/app/knowledge/quarantine/components/status-pill'
import { QUARANTINE_PAGE_SIZE } from '@/app/knowledge/quarantine/constants'
import {
  getDropReasons,
  getQuarantineSeverity,
  getQuarantineSource,
  getSeverityBarClassName,
  getSeverityClassName,
  isReviewed,
  reasonLabel,
} from '@/app/knowledge/quarantine/quarantine-signals'
import type { ReviewState } from '@/app/knowledge/quarantine/types'

type DatasetOption = {
  id: string
  label: string
}

type QuarantineAuditCanvasProps = {
  className?: string
  autoRefresh: boolean
  dateFrom: string
  dateTo: string
  datasetLabelById: Record<string, string>
  datasetOptions: DatasetOption[]
  datasets: DatasetOption[]
  datasetsLoading: boolean
  documentsCount: number
  filtered: Document[]
  footerMessage: string
  hasActiveFilters: boolean
  listSummary: string | null
  paginated: Document[]
  queueFetching: boolean
  reviewState: ReviewState
  safePage: number
  search: string
  selectedDataset: string
  selectedId: string | null
  selectedReason: string
  selectedSeverity: string
  selectedSource: string
  sortedReasons: string[]
  sourceOptions: string[]
  totalPages: number
  reasonCounts: Record<string, number>
  onDateFromChange: (value: string) => void
  onDateToChange: (value: string) => void
  onDatasetChange: (value: string) => void
  onOpenDocument: (docId: string) => void
  onOpenReview: (docId: string) => void
  onPageChange: (page: number) => void
  onReasonChange: (value: string) => void
  onRefresh: () => Promise<boolean> | void
  onResetFilters: () => void
  onReviewStateChange: (value: ReviewState) => void
  onSearchChange: (value: string) => void
  onSeverityChange: (value: string) => void
  onSourceChange: (value: string) => void
}

function triggerRefresh(action: () => Promise<boolean> | void) {
  const result = action()
  if (result && typeof (result as Promise<boolean>).then === 'function') {
    detachPromise(result)
  }
}

export function QuarantineAuditCanvas({
  className,
  autoRefresh,
  dateFrom,
  dateTo,
  datasetLabelById,
  datasetOptions,
  datasets,
  datasetsLoading,
  documentsCount,
  filtered,
  footerMessage,
  hasActiveFilters,
  listSummary,
  paginated,
  queueFetching,
  reviewState,
  safePage,
  search,
  selectedDataset,
  selectedId,
  selectedReason,
  selectedSeverity,
  selectedSource,
  sortedReasons,
  sourceOptions,
  totalPages,
  reasonCounts,
  onDateFromChange,
  onDateToChange,
  onDatasetChange,
  onOpenDocument,
  onOpenReview,
  onPageChange,
  onReasonChange,
  onRefresh,
  onResetFilters,
  onReviewStateChange,
  onSearchChange,
  onSeverityChange,
  onSourceChange,
}: Readonly<QuarantineAuditCanvasProps>) {
  return (
    <div
      aria-label="审计主画布"
      className={cn(
        'flex min-h-0 flex-col overflow-hidden rounded-[1.2rem] border border-border/60 bg-background/94 shadow-[0_20px_48px_-40px_rgba(15,23,42,0.18)] backdrop-blur-sm',
        className
      )}
    >
      <div className="border-b border-border/60 px-4.5 py-3.5">
        <div className="flex flex-col gap-2.5 xl:flex-row xl:items-start xl:justify-between">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-3">
              <div className="text-[0.98rem] font-semibold text-foreground">
                异常隔离审查表
              </div>
              <span className="rounded-full border border-border/60 bg-muted/35 px-2 py-0.5 text-[10px] font-medium text-muted-foreground tabular-nums">
                {listSummary || '当前空队列'}
              </span>
            </div>
            <p className="mt-0.5 text-[11px] leading-5 text-muted-foreground">
              治理规则命中统计与待裁决样本分布，支持按条件筛选后快速复核。
            </p>

            {hasActiveFilters ? (
              <div className="mt-3 flex flex-wrap gap-1.5">
                {reviewState === 'all' ? null : (
                  <Badge
                    variant="secondary"
                    className="rounded-full px-2.5 py-1 text-[11px] font-medium"
                  >
                    {reviewState === 'pending' ? '仅待审核' : '仅已处理'}
                  </Badge>
                )}
                {selectedReason === 'all' ? null : (
                  <Badge
                    variant="secondary"
                    className="rounded-full px-2.5 py-1 text-[11px] font-medium"
                  >
                    原因: {reasonLabel(selectedReason)}
                  </Badge>
                )}
                {selectedDataset === 'all' ? null : (
                  <Badge
                    variant="secondary"
                    className="rounded-full px-2.5 py-1 text-[11px] font-medium"
                  >
                    数据集: {datasetLabelById[selectedDataset] || selectedDataset}
                  </Badge>
                )}
                {selectedSource === 'all' ? null : (
                  <Badge
                    variant="secondary"
                    className="rounded-full px-2.5 py-1 text-[11px] font-medium"
                  >
                    来源: {selectedSource}
                  </Badge>
                )}
                {selectedSeverity === 'all' ? null : (
                  <Badge
                    variant="secondary"
                    className="rounded-full px-2.5 py-1 text-[11px] font-medium"
                  >
                    疑似度: {selectedSeverity}
                  </Badge>
                )}
                {search.trim() ? (
                  <Badge
                    variant="secondary"
                    className="rounded-full px-2.5 py-1 text-[11px] font-medium"
                  >
                    搜索: {search.trim()}
                  </Badge>
                ) : null}
                {dateFrom ? (
                  <Badge
                    variant="secondary"
                    className="rounded-full px-2.5 py-1 text-[11px] font-medium"
                  >
                    开始: {dateFrom}
                  </Badge>
                ) : null}
                {dateTo ? (
                  <Badge
                    variant="secondary"
                    className="rounded-full px-2.5 py-1 text-[11px] font-medium"
                  >
                    结束: {dateTo}
                  </Badge>
                ) : null}
              </div>
            ) : null}
          </div>

          <div className="w-full xl:w-[18rem]">
            <SearchInput
              value={search}
              onValueChange={onSearchChange}
              placeholder="搜索文件名 / ID / 规则 / 原因"
              containerClassName="w-full"
              inputClassName="h-9 rounded-xl border-border/60 bg-background text-[11px] shadow-none"
            />
          </div>
        </div>
      </div>

      <div className="border-b border-border/60 px-4.5 py-2">
        <div className="flex flex-col gap-2.5 xl:flex-row xl:items-center xl:justify-between">
          <div className="grid gap-2 md:grid-cols-3 xl:min-w-0 xl:flex-1 xl:grid-cols-7">
            <div className="min-w-0">
              <Select
                value={reviewState}
                onValueChange={(value) =>
                  onReviewStateChange(value as ReviewState)
                }
              >
                <SelectTrigger className="h-9 rounded-xl border-border/60 bg-background px-3 text-[11px] font-normal shadow-none">
                  <SelectValue placeholder="处理状态" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">全部状态</SelectItem>
                  <SelectItem value="pending">仅待审核</SelectItem>
                  <SelectItem value="reviewed">仅已处理</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div className="min-w-0">
              <Select value={selectedReason} onValueChange={onReasonChange}>
                <SelectTrigger className="h-9 rounded-xl border-border/60 bg-background px-3 text-[11px] font-normal shadow-none">
                  <SelectValue placeholder="隔离原因" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">所有原因</SelectItem>
                  {sortedReasons.map((reason) => (
                    <SelectItem key={reason} value={reason}>
                      {reasonLabel(reason)} ({reasonCounts[reason] || 0})
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="min-w-0">
              <Select value={selectedSource} onValueChange={onSourceChange}>
                <SelectTrigger className="h-9 rounded-xl border-border/60 bg-background px-3 text-[11px] font-normal shadow-none">
                  <SelectValue placeholder="来源" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">全部来源</SelectItem>
                  {sourceOptions.map((source) => (
                    <SelectItem key={source} value={source}>
                      {source}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="min-w-0">
              <Select value={selectedSeverity} onValueChange={onSeverityChange}>
                <SelectTrigger className="h-9 rounded-xl border-border/60 bg-background px-3 text-[11px] font-normal shadow-none">
                  <SelectValue placeholder="疑似度" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">全部疑似度</SelectItem>
                  <SelectItem value="高">高</SelectItem>
                  <SelectItem value="中">中</SelectItem>
                  <SelectItem value="低">低</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div className="min-w-0">
              <Select value={selectedDataset} onValueChange={onDatasetChange}>
                <SelectTrigger className="h-9 rounded-xl border-border/60 bg-background px-3 text-[11px] font-normal shadow-none">
                  <SelectValue placeholder="数据集" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">
                    {datasetsLoading ? '加载数据集…' : '全部数据集'}
                  </SelectItem>
                  {datasets.map((dataset) => (
                    <SelectItem key={dataset.id} value={dataset.id}>
                      {dataset.label}
                    </SelectItem>
                  ))}
                  {datasetOptions
                    .filter((option) => !datasetLabelById[option.id])
                    .map((option) => (
                      <SelectItem key={option.id} value={option.id}>
                        {option.label}
                      </SelectItem>
                    ))}
                </SelectContent>
              </Select>
            </div>

            <div className="min-w-0">
              <Input
                type="text"
                inputMode="numeric"
                placeholder="起始日期"
                aria-label="起始日期，格式 YYYY-MM-DD"
                value={dateFrom}
                onChange={(event) => onDateFromChange(event.target.value)}
                className="h-9 rounded-xl border-border/60 bg-background px-3 text-[11px] font-normal shadow-none placeholder:text-muted-foreground"
              />
            </div>

            <div className="min-w-0">
              <Input
                type="text"
                inputMode="numeric"
                placeholder="结束日期"
                aria-label="结束日期，格式 YYYY-MM-DD"
                value={dateTo}
                onChange={(event) => onDateToChange(event.target.value)}
                className="h-9 rounded-xl border-border/60 bg-background px-3 text-[11px] font-normal shadow-none placeholder:text-muted-foreground"
              />
            </div>
          </div>

          <div className="flex shrink-0 flex-nowrap items-center gap-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="h-9 rounded-xl border-border/60 bg-background px-3.5 text-[11px] font-medium"
              onClick={onResetFilters}
            >
              <RotateCcw className="size-3.5" />
              重置
            </Button>
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="h-9 rounded-xl border-info/25 bg-info/[0.06] px-3.5 text-[11px] font-medium text-info shadow-[0_12px_24px_-22px_hsl(var(--info)/0.5)] hover:border-info/40 hover:bg-info/[0.12] hover:text-info"
              onClick={() => triggerRefresh(onRefresh)}
            >
              <RefreshCw
                className={cn(
                  'size-3.5',
                  queueFetching ? 'animate-spin motion-reduce:animate-none' : ''
                )}
              />
              同步数据
            </Button>
          </div>
        </div>
      </div>

      <div className="min-h-[10.5rem] flex-1 overflow-x-auto">
        <table className="h-full w-full table-fixed border-collapse text-left">
          <colgroup>
            <col className="w-10" />
            <col className="w-[22%]" />
            <col className="w-[24%]" />
            <col className="w-[11%]" />
            <col className="w-[10%]" />
            <col className="w-[10%]" />
            <col className="w-[9%]" />
            <col className="w-[12%]" />
            <col className="w-[8%]" />
          </colgroup>
          <thead className="border-b border-border/60 bg-muted/40 text-[11px] font-medium text-muted-foreground">
            <tr>
              <th className="w-10 px-5 py-2.5">
                <input
                  type="checkbox"
                  className="h-3.5 w-3.5 rounded border-border/60"
                  aria-label="全选隔离记录"
                />
              </th>
              <th className="px-4 py-2.5 font-medium">文件 / ID</th>
              <th className="px-4 py-2.5 font-medium">命中规则 / 原因</th>
              <th className="px-4 py-2.5 font-medium">状态</th>
              <th className="px-4 py-2.5 font-medium">来源</th>
              <th className="px-4 py-2.5 font-medium">疑似度</th>
              <th className="px-4 py-2.5 font-medium text-right">大小</th>
              <th className="px-4 py-2.5 font-medium text-right">同步时间</th>
              <th className="w-12 px-4 py-2.5"></th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border/40">
            {filtered.length === 0 ? (
              <tr>
                <td colSpan={9} className="px-5 py-0">
                  <QuarantineEmptyState
                    hasActiveFilters={hasActiveFilters}
                    autoRefresh={autoRefresh}
                    isFetching={queueFetching}
                    onResetFilters={onResetFilters}
                    onRefresh={() => triggerRefresh(onRefresh)}
                  />
                </td>
              </tr>
            ) : (
              paginated.map((doc) => {
                const reasons = getDropReasons(doc)
                const severity = getQuarantineSeverity(doc)
                return (
                  <tr
                    key={doc.id}
                    className={cn(
                      'group transition-colors hover:bg-muted/30',
                      selectedId === doc.id && 'bg-primary/5 hover:bg-primary/5'
                    )}
                  >
                    <td className="px-5 py-2.5">
                      <input
                        type="checkbox"
                        className="h-3.5 w-3.5 rounded border-border/60"
                        aria-label={`选择 ${doc.filename}`}
                      />
                    </td>
                    <td className="px-4 py-2.5">
                      <button
                        type="button"
                        className="flex items-center gap-3 text-left"
                        onClick={() => onOpenReview(doc.id)}
                      >
                        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-[0.85rem] border border-primary/10 bg-primary/8 text-primary">
                          <FileKindGlyph
                            kind={getDocumentKind(doc.filename)}
                            className="h-4 w-4"
                          />
                        </div>
                        <div className="min-w-0">
                          <span className="block truncate text-[12px] font-medium text-foreground transition-colors group-hover:text-primary">
                            {doc.filename}
                          </span>
                          <span className="mt-0.5 block font-mono text-[9px] text-muted-foreground/70">
                            {doc.id.slice(0, 8)}
                          </span>
                        </div>
                      </button>
                    </td>
                    <td className="px-4 py-2.5">
                      <div className="flex flex-wrap gap-1.5">
                        {reasons.map((reason) => (
                          <span
                            key={reason}
                            className="rounded-full border border-warning/15 bg-warning/10 px-2 py-0.5 text-[10px] font-medium text-warning"
                          >
                            {reasonLabel(reason)}
                          </span>
                        ))}
                        {reasons.length === 0 ? (
                          <span className="text-xs text-muted-foreground/50">
                            人工触发
                          </span>
                        ) : null}
                      </div>
                    </td>
                    <td className="px-4 py-2.5">
                      <StatusPill
                        status={isReviewed(doc) ? 'completed' : 'quarantined'}
                      />
                    </td>
                    <td className="px-4 py-2.5 text-[11px] font-medium text-muted-foreground">
                      {getQuarantineSource(doc)}
                    </td>
                    <td className="px-4 py-2.5">
                      <div className="flex items-center gap-2">
                        <span
                          className={cn(
                            'min-w-[1rem] text-[11px] font-medium',
                            getSeverityClassName(severity)
                          )}
                        >
                          {severity}
                        </span>
                        <span className="h-1.5 w-10 overflow-hidden rounded-full bg-muted/50">
                          <span
                            className={cn(
                              'block h-full rounded-full',
                              getSeverityBarClassName(severity),
                              severity === '高' && 'w-8',
                              severity === '中' && 'w-5',
                              severity === '低' && 'w-3'
                            )}
                          />
                        </span>
                      </div>
                    </td>
                    <td className="px-4 py-2.5 text-right font-mono text-[10px] tabular-nums text-muted-foreground/85">
                      {formatFileSize(doc.file_size)}
                    </td>
                    <td className="px-4 py-2.5 text-right font-mono text-[9px] text-muted-foreground/70">
                      {formatDate(doc.updated_at)}
                    </td>
                    <td className="px-4 py-2.5">
                      <div className="flex items-center justify-end gap-1 opacity-60 transition-opacity group-hover:opacity-100">
                        <Button
                          size="icon"
                          variant="ghost"
                          aria-label="查看隔离详情"
                          title="查看隔离详情"
                          className="h-7 w-7 rounded-lg text-muted-foreground hover:bg-muted"
                          onClick={() => onOpenReview(doc.id)}
                        >
                          <Eye className="h-4 w-4" />
                        </Button>
                        <Button
                          size="icon"
                          variant="ghost"
                          aria-label="打开原文"
                          title="打开原文"
                          className="h-7 w-7 rounded-lg text-muted-foreground hover:bg-muted"
                          onClick={() => onOpenDocument(doc.id)}
                        >
                          <Download className="h-4 w-4" />
                        </Button>
                      </div>
                    </td>
                  </tr>
                )
              })
            )}
          </tbody>
        </table>
      </div>

      <div className="flex flex-col gap-2 border-t border-border/60 px-5 py-2.5 text-[11px] text-muted-foreground sm:flex-row sm:items-center sm:justify-between">
        <div>共 {filtered.length} 条记录</div>
        <div className="flex flex-wrap items-center gap-3">
          <div>{footerMessage}</div>
          {filtered.length > 0 ? (
            <div className="flex items-center gap-1">
              <button
                type="button"
                className="inline-flex h-8 w-8 items-center justify-center rounded-full border border-border/60 bg-background text-foreground disabled:opacity-40"
                disabled={safePage <= 1}
                onClick={() => onPageChange(Math.max(1, safePage - 1))}
              >
                <ChevronLeft className="h-3.5 w-3.5" />
              </button>
              {Array.from({ length: Math.min(totalPages, 5) }, (_, index) => {
                const pageNumber = index + 1
                return (
                  <button
                    key={pageNumber}
                    type="button"
                    onClick={() => onPageChange(pageNumber)}
                    className={cn(
                      'inline-flex h-8 min-w-8 items-center justify-center rounded-full px-2 text-[12px] font-medium tabular-nums',
                      safePage === pageNumber
                        ? 'bg-primary text-primary-foreground'
                        : 'text-muted-foreground hover:text-foreground'
                    )}
                  >
                    {pageNumber}
                  </button>
                )
              })}
              {totalPages > 5 ? (
                <span className="px-1 text-[11px]">…</span>
              ) : null}
              {totalPages > 5 ? (
                <button
                  type="button"
                  onClick={() => onPageChange(totalPages)}
                  className={cn(
                    'inline-flex h-8 min-w-8 items-center justify-center rounded-full px-2 text-[12px] font-medium tabular-nums',
                    safePage === totalPages
                      ? 'bg-primary text-primary-foreground'
                      : 'text-muted-foreground hover:text-foreground'
                  )}
                >
                  {totalPages}
                </button>
              ) : null}
              <button
                type="button"
                className="inline-flex h-8 w-8 items-center justify-center rounded-full border border-border/60 bg-background text-foreground disabled:opacity-40"
                disabled={safePage >= totalPages}
                onClick={() => onPageChange(Math.min(totalPages, safePage + 1))}
              >
                <ChevronRight className="h-3.5 w-3.5" />
              </button>
              <span className="ml-2 rounded-full border border-border/60 px-2.5 py-1 text-[12px]">
                {QUARANTINE_PAGE_SIZE} 条/页
              </span>
            </div>
          ) : null}
        </div>
      </div>
    </div>
  )
}
