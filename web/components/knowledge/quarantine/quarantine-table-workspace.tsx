'use client'

import { useState } from 'react'
import {
  AlertCircle,
  Calendar,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Dataset,
  Filter,
  Layers,
  Loader2,
  MoreHorizontal,
  PanelRightClose,
  PanelRightOpen,
  Quarantine,
  ShieldAlert,
  ShieldCheck,
  Trash2,
} from '@/components/icons'
import { getFileTypeMeta } from '@/components/knowledge/file-type'
import { Button } from '@/components/ui/button'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { IconButton } from '@/components/ui/icon-button'
import { Input } from '@/components/ui/input'
import { WorkspaceNotice } from '@/components/ui/operational-workspace'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { SearchInput } from '@/components/ui/search-input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle, SheetTrigger } from '@/components/ui/sheet'
import { useMediaQuery } from '@/hooks/use-media-query'
import type { DomainTone } from '@/lib/dataset-domain-tone'
import { cn } from '@/lib/utils'
import type { Document } from '@/types'
import { QUARANTINE_PAGE_SIZE } from '@/app/knowledge/quarantine/constants'
import {
  getDropReasons,
  getQuarantineSeverity,
  getQuarantineSource,
  getReasonTone,
  isReviewed,
  reasonLabel,
} from '@/app/knowledge/quarantine/quarantine-signals'
import type { ActingState, QuarantineSeverity } from '@/app/knowledge/quarantine/types'
import styles from '@/app/knowledge/quarantine/quarantine.module.css'
import { QuarantineInlineReview, type QuarantineReviewActions } from './quarantine-inline-review'

type Props = Omit<QuarantineReviewActions, 'acting'> & {
  actingByDocumentId: ReadonlyMap<string, NonNullable<ActingState>>
  demoMode: boolean
  documentViewerOpen: boolean
  reviewRailOpen: boolean
  reviewSheetOpen: boolean
  dateFrom: string
  dateTo: string
  datasetLabelById: Record<string, string>
  datasetToneById: Record<string, DomainTone>
  datasetOptions: { id: string; label: string }[]
  datasetsLoading: boolean
  documentsCount: number
  filteredCount: number
  hasActiveFilters: boolean
  paginated: Document[]
  queueFetching: boolean
  initialLoading: boolean
  queueError: string | null
  countsReady: boolean
  reviewCounts: { total: number; unreviewed: number; reviewed: number }
  severityCounts: Record<QuarantineSeverity, number>
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
  onSelectDocument: (docId: string | null) => void
  onReviewRailOpenChange: (open: boolean) => void
  onReviewSheetOpenChange: (open: boolean) => void
  onPageChange: (page: number) => void
  onReasonChange: (value: string) => void
  onRefresh: () => void
  onResetFilters: () => void
  onSearchChange: (value: string) => void
  onSeverityChange: (value: string) => void
  onSourceChange: (value: string) => void
}

function processingTime(value: string, full = false): string {
  const date = new Date(value)
  if (!Number.isFinite(date.getTime())) return '—'
  return date.toLocaleString('zh-CN', {
    ...(full ? { year: 'numeric' as const } : {}),
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  })
}

function ReviewStateLabel({ doc }: Readonly<{ doc: Document }>) {
  const reviewed = isReviewed(doc)
  return (
    <span className={styles.reviewState} data-reviewed={reviewed}>
      {reviewed ? '已复核' : '待复核'}
    </span>
  )
}

export function QuarantineTableWorkspace(props: Readonly<Props>) {
  const [mobileFiltersOpen, setMobileFiltersOpen] = useState(false)
  const isBelowRailBreakpoint = useMediaQuery('(max-width: 1279px)')
  const isCompactWithRail = useMediaQuery('(max-width: 1559px)')
  const isCompactDesktop = useMediaQuery('(max-width: 1279px)')
  const isCompactDate = useMediaQuery('(max-width: 1080px)')
  const isMobile = useMediaQuery('(max-width: 767px)')

  const {
    actingByDocumentId,
    demoMode,
    documentViewerOpen,
    reviewRailOpen,
    reviewSheetOpen,
    dateFrom,
    dateTo,
    datasetLabelById,
    datasetToneById,
    datasetOptions,
    datasetsLoading,
    documentsCount,
    filteredCount,
    hasActiveFilters,
    paginated,
    queueFetching,
    initialLoading,
    queueError,
    countsReady,
    reviewCounts,
    severityCounts,
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
    onSelectDocument,
    onReviewRailOpenChange,
    onReviewSheetOpenChange,
    onPageChange,
    onReasonChange,
    onRefresh,
    onResetFilters,
    onSearchChange,
    onSeverityChange,
    onSourceChange,
    onRelease,
    onRetry,
    onTune,
    onMarkReviewed,
    onDelete,
    onOpenDocument,
    onShowDetails,
    actionError,
  } = props

  const hasRailSpace = !isBelowRailBreakpoint
  const reviewRailVisible = hasRailSpace && !documentViewerOpen && paginated.length > 0 && reviewRailOpen
  const rightReviewVisible = reviewRailVisible || (!hasRailSpace && reviewSheetOpen)
  const inspectedDoc = paginated.find((doc) => doc.id === selectedId) ?? paginated[0] ?? null
  const inspectedDatasetLabel = inspectedDoc?.dataset_id
    ? (datasetLabelById[inspectedDoc.dataset_id] ?? inspectedDoc.dataset_id)
    : '未指定数据集'
  const inspectedDatasetTone = inspectedDoc?.dataset_id ? datasetToneById[inspectedDoc.dataset_id] : undefined
  const inspectedActing = inspectedDoc ? (actingByDocumentId.get(inspectedDoc.id) ?? null) : null
  const inspectedBusy = Boolean(inspectedActing)

  const showDetailColumns = !isMobile
  const showSourceColumn = showDetailColumns && !isCompactDesktop && !(reviewRailVisible && isCompactWithRail)
  const showDateColumn = showDetailColumns && !isCompactDate && !(reviewRailVisible && isCompactWithRail)

  const selectForReview = (doc: Document) => {
    onSelectDocument(doc.id)
    if (hasRailSpace) {
      if (!reviewRailOpen) onReviewRailOpenChange(true)
    } else {
      onReviewSheetOpenChange(true)
    }
  }

  const dateLabel =
    dateFrom && dateTo
      ? `${dateFrom.slice(5)} – ${dateTo.slice(5)}`
      : dateFrom
        ? `${dateFrom.slice(5)} 起`
        : dateTo
          ? `截至 ${dateTo.slice(5)}`
          : '全部日期'

  const activeFilterLabels = [
    selectedReason !== 'all' ? reasonLabel(selectedReason) : null,
    selectedSource !== 'all' ? selectedSource : null,
    selectedSeverity !== 'all' ? `${selectedSeverity}风险` : null,
    dateFrom ? `起始 ${dateFrom}` : null,
    dateTo ? `截至 ${dateTo}` : null,
  ].filter(Boolean)

  const reasonFilter = (
    <Select value={selectedReason} onValueChange={onReasonChange}>
      <SelectTrigger className={styles.filterControl} aria-label="筛选隔离原因">
        <SelectValue placeholder="所有原因" />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value="all">所有原因</SelectItem>
        {sortedReasons.map((reason) => (
          <SelectItem key={reason} value={reason}>
            {reasonLabel(reason)} · {reasonCounts[reason]}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )

  const sourceFilter = (
    <Select value={selectedSource} onValueChange={onSourceChange}>
      <SelectTrigger className={styles.filterControl} aria-label="筛选来源">
        <SelectValue placeholder="全部来源" />
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
  )

  const severityFilter = (
    <Select value={selectedSeverity} onValueChange={onSeverityChange}>
      <SelectTrigger className={styles.filterControl} aria-label="筛选风险">
        <SelectValue placeholder="全部风险" />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value="all">全部风险</SelectItem>
        {['高', '中', '低'].map((level) => (
          <SelectItem key={level} value={level}>
            {level}风险
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )

  const dateFields = (
    <div className={styles.dateFields}>
      <label>
        开始日期
        <Input type="date" value={dateFrom} max={dateTo} onChange={(event) => onDateFromChange(event.target.value)} />
      </label>
      <label>
        结束日期
        <Input type="date" value={dateTo} min={dateFrom} onChange={(event) => onDateToChange(event.target.value)} />
      </label>
      <Button
        size="sm"
        variant="ghost"
        disabled={!dateFrom && !dateTo}
        onClick={() => {
          onDateFromChange('')
          onDateToChange('')
        }}
      >
        清除日期
      </Button>
    </div>
  )

  const dateFilter = (
    <Popover>
      <PopoverTrigger asChild>
        <Button
          variant="outline"
          className={`${styles.filterControl} ${styles.dateControl}`}
          data-active={Boolean(dateFrom || dateTo)}
          aria-label={`筛选处理日期：${dateLabel}`}
        >
          <Calendar aria-hidden="true" />
          {dateLabel}
        </Button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-72">
        {dateFields}
      </PopoverContent>
    </Popover>
  )

  const reviewOverflowMenu = inspectedDoc ? (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <IconButton
          label={`${inspectedDoc.filename}的更多操作`}
          variant="ghost"
          className={styles.toolIcon}
          disabled={inspectedBusy}
        >
          <MoreHorizontal className="size-4" aria-hidden="true" />
        </IconButton>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuItem onSelect={() => onShowDetails(inspectedDoc.id)}>
          <Layers className="mr-2 size-4" aria-hidden="true" />
          入库详情
        </DropdownMenuItem>
        {!isReviewed(inspectedDoc) && (
          <DropdownMenuItem onSelect={() => onMarkReviewed(inspectedDoc)}>
            <CheckCircle2 className="mr-2 size-4" aria-hidden="true" />
            标记已复核
          </DropdownMenuItem>
        )}
        <DropdownMenuSeparator />
        <ConfirmDialog
          title={`删除「${inspectedDoc.filename}」？`}
          description="文档及相关入库记录将被删除，此操作无法撤销。"
          confirmLabel="删除文档"
          onConfirm={() => onDelete(inspectedDoc)}
          confirmDisabled={inspectedBusy}
        >
          <DropdownMenuItem
            onSelect={(event) => event.preventDefault()}
            className="text-destructive focus:text-destructive"
          >
            <Trash2 className="mr-2 size-4" aria-hidden="true" />
            删除文档
          </DropdownMenuItem>
        </ConfirmDialog>
      </DropdownMenuContent>
    </DropdownMenu>
  ) : null

  const reviewPanel = (
    <QuarantineInlineReview
      key={inspectedDoc?.id ?? 'none'}
      document={inspectedDoc}
      datasetLabel={inspectedDatasetLabel}
      datasetTone={inspectedDatasetTone}
      demoMode={demoMode}
      acting={inspectedActing}
      actionError={actionError}
      onRelease={onRelease}
      onRetry={onRetry}
      onTune={onTune}
      onOpenDocument={(docId) => {
        onReviewSheetOpenChange(false)
        onOpenDocument(docId)
      }}
    />
  )

  return (
    <div className={styles.workspace}>
      <div className={styles.toolbar} data-filtered={hasActiveFilters} aria-label="隔离队列筛选">
        <Select value={selectedDataset} onValueChange={onDatasetChange} disabled={datasetsLoading}>
          <SelectTrigger className={styles.filterControl} aria-label="筛选数据集">
            <Dataset aria-hidden="true" />
            <SelectValue placeholder="全部数据集" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">全部数据集</SelectItem>
            {selectedDataset !== 'all' && !datasetOptions.some((option) => option.id === selectedDataset) ? (
              <SelectItem value={selectedDataset} disabled>
                已选数据集：{selectedDataset}
              </SelectItem>
            ) : null}
            {datasetOptions.map((option) => (
              <SelectItem key={option.id} value={option.id}>
                {option.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <div className={styles.desktopFilters}>
          {reasonFilter}
          {sourceFilter}
          {severityFilter}
          {dateFilter}
        </div>
        <Sheet open={mobileFiltersOpen} onOpenChange={setMobileFiltersOpen}>
          <SheetTrigger asChild>
            <Button
              variant="outline"
              className={styles.mobileFiltersTrigger}
              aria-label="更多隔离筛选"
              data-active={activeFilterLabels.length > 0}
            >
              <Filter aria-hidden="true" />
              更多筛选
            </Button>
          </SheetTrigger>
          <SheetContent className={styles.filterSheet}>
            <SheetHeader className={styles.filterSheetHeader}>
              <SheetTitle>更多筛选</SheetTitle>
              <SheetDescription className="sr-only">
                按隔离原因、来源、风险和处理日期筛选当前范围内的文档
              </SheetDescription>
            </SheetHeader>
            <div className={styles.filterSheetBody}>
              <div className={styles.filterSheetField}>
                <p>隔离原因</p>
                {reasonFilter}
              </div>
              <div className={styles.filterSheetField}>
                <p>来源</p>
                {sourceFilter}
              </div>
              <div className={styles.filterSheetField}>
                <p>风险</p>
                {severityFilter}
              </div>
              <div className={styles.filterSheetDateFields}>{dateFields}</div>
            </div>
            <div className={styles.filterSheetFooter}>
              <Button variant="ghost" disabled={!hasActiveFilters} onClick={onResetFilters}>
                清除筛选
              </Button>
              <Button variant="outline" onClick={() => setMobileFiltersOpen(false)}>
                查看结果
              </Button>
            </div>
          </SheetContent>
        </Sheet>
        <div className={styles.toolbarEnd}>
          {countsReady && (
            <div className={styles.riskSummary} role="group" aria-label="风险分布">
              {(['高', '中', '低'] as const).map((level) => {
                const active = selectedSeverity === level
                return (
                  <button
                    key={level}
                    type="button"
                    className={styles.riskChip}
                    data-severity={level}
                    aria-pressed={active}
                    onClick={() => onSeverityChange(active ? 'all' : level)}
                  >
                    <span className={styles.riskDot} aria-hidden="true" />
                    <span>{level}</span>
                    <strong>{severityCounts[level]}</strong>
                  </button>
                )
              })}
            </div>
          )}
          <SearchInput
            value={search}
            onValueChange={onSearchChange}
            placeholder="搜索文档、规则或原因"
            aria-label="搜索隔离文档"
            containerClassName={styles.search}
            inputClassName={styles.searchInput}
          />
          {hasActiveFilters && (
            <Button variant="ghost" className={styles.clearFilters} onClick={onResetFilters}>
              清除筛选
            </Button>
          )}
          {paginated.length > 0 && !documentViewerOpen ? (
            <IconButton
              label={rightReviewVisible ? '收起复核详情' : '展开复核详情'}
              title={rightReviewVisible ? '收起复核详情' : '展开复核详情'}
              variant="ghost"
              className={styles.toolIcon}
              aria-pressed={rightReviewVisible}
              onClick={() =>
                hasRailSpace ? onReviewRailOpenChange(!reviewRailOpen) : onReviewSheetOpenChange(!reviewSheetOpen)
              }
            >
              {rightReviewVisible ? <PanelRightClose className="size-4" /> : <PanelRightOpen className="size-4" />}
            </IconButton>
          ) : null}
        </div>
        {activeFilterLabels.length > 0 && (
          <p className={styles.activeFilterSummary} role="status" aria-label="当前筛选条件">
            当前：{activeFilterLabels.join(' · ')}
          </p>
        )}
      </div>

      {queueError && paginated.length > 0 && (
        <WorkspaceNotice
          placement="floating"
          tone="warning"
          pending={queueFetching}
          retry={onRefresh}
          retryLabel="重新加载"
        >
          {queueError}，当前显示已加载记录。
        </WorkspaceNotice>
      )}

      <div className={styles.workspaceBody}>
        <div className={styles.tablePane} data-review-open={reviewRailVisible}>
          <div className={styles.tableArea}>
            <div
              className={styles.tableScroll}
              data-page-scroll-container
              data-empty={!paginated.length}
              role="region"
              aria-label="隔离文档列表"
              tabIndex={0}
              aria-busy={queueFetching}
            >
              <table className={styles.table}>
                <caption className="sr-only">隔离与失败文档，点击记录在右侧复核详情核对原因与原文</caption>
                <colgroup>
                  <col className={styles.nameColumn} />
                  {showDetailColumns ? <col className={styles.reasonColumn} /> : null}
                  {showDetailColumns ? <col className={styles.datasetColumn} /> : null}
                  {showSourceColumn ? <col className={styles.sourceColumn} /> : null}
                  {showDetailColumns ? <col className={styles.riskColumn} /> : null}
                  {showDetailColumns ? <col className={styles.reviewColumn} /> : null}
                  {showDateColumn ? <col className={styles.dateColumn} /> : null}
                </colgroup>
                <thead>
                  <tr>
                    <th scope="col">文档</th>
                    {showDetailColumns ? (
                      <th scope="col" className={styles.reasonCell}>
                        隔离原因
                      </th>
                    ) : null}
                    {showDetailColumns ? (
                      <th scope="col" className={styles.datasetCell}>
                        数据集
                      </th>
                    ) : null}
                    {showSourceColumn ? (
                      <th scope="col" className={styles.sourceCell}>
                        来源
                      </th>
                    ) : null}
                    {showDetailColumns ? (
                      <th scope="col" className={styles.riskCell}>
                        风险
                      </th>
                    ) : null}
                    {showDetailColumns ? (
                      <th scope="col" className={styles.reviewCell}>
                        复核状态
                      </th>
                    ) : null}
                    {showDateColumn ? (
                      <th scope="col" className={styles.dateCell}>
                        处理时间
                      </th>
                    ) : null}
                  </tr>
                </thead>
                <tbody>
                  {paginated.map((doc) => {
                    const inspected = inspectedDoc?.id === doc.id && rightReviewVisible
                    const dropReasons = getDropReasons(doc)
                    const reasonsText = dropReasons.map(reasonLabel).join('、') || '待确认原因'
                    const severity = getQuarantineSeverity(doc)
                    const datasetLabel = doc.dataset_id
                      ? (datasetLabelById[doc.dataset_id] ?? doc.dataset_id)
                      : '未指定数据集'
                    const datasetTone = doc.dataset_id ? datasetToneById[doc.dataset_id] : undefined
                    const processedAt = doc.updated_at
                    const RiskIcon = severity === '高' ? ShieldAlert : ShieldCheck
                    const fileType = getFileTypeMeta(doc)
                    const TypeIcon = fileType.icon
                    return (
                      <tr
                        key={doc.id}
                        className={styles.record}
                        data-quarantine-row={doc.id}
                        data-inspected={inspected}
                        onClick={(event) => {
                          if (!(event.target as HTMLElement).closest('button, a')) selectForReview(doc)
                        }}
                      >
                        <td>
                          <button
                            type="button"
                            className={styles.fileButton}
                            aria-label={`复核 ${doc.filename}`}
                            aria-current={inspected ? 'true' : undefined}
                            title={doc.filename}
                            onClick={() => selectForReview(doc)}
                          >
                            <span className={cn(styles.fileBadge, fileType.bg)}>
                              <TypeIcon appearance="color" aria-hidden="true" className={styles.fileIcon} />
                            </span>
                            <span className={styles.fileName}>{doc.filename}</span>
                          </button>
                          <div className={styles.mobileMeta}>
                            <span>{reasonsText}</span>
                            <ReviewStateLabel doc={doc} />
                          </div>
                        </td>
                        {showDetailColumns ? (
                          <td className={styles.reasonCell} title={reasonsText}>
                            {dropReasons.length > 0 ? (
                              <div className={styles.reasonPills}>
                                {dropReasons.slice(0, 2).map((reason) => (
                                  <span key={reason} className={styles.reasonPill} data-tone={getReasonTone(reason)}>
                                    {reasonLabel(reason)}
                                  </span>
                                ))}
                                {dropReasons.length > 2 ? (
                                  <span className={styles.reasonMore}>+{dropReasons.length - 2}</span>
                                ) : null}
                              </div>
                            ) : (
                              <span className={styles.reasonMuted}>待确认原因</span>
                            )}
                          </td>
                        ) : null}
                        {showDetailColumns ? (
                          <td className={styles.datasetCell} title={datasetLabel}>
                            <span className={styles.datasetPill} data-tone={datasetTone}>
                              {datasetLabel}
                            </span>
                          </td>
                        ) : null}
                        {showSourceColumn ? <td className={styles.sourceCell}>{getQuarantineSource(doc)}</td> : null}
                        {showDetailColumns ? (
                          <td className={styles.riskCell}>
                            <span className={styles.risk} data-severity={severity}>
                              <RiskIcon aria-hidden="true" />
                              {severity}
                            </span>
                          </td>
                        ) : null}
                        {showDetailColumns ? (
                          <td className={styles.reviewCell}>
                            <ReviewStateLabel doc={doc} />
                          </td>
                        ) : null}
                        {showDateColumn ? (
                          <td className={styles.dateCell} title={processingTime(processedAt, true)}>
                            {processingTime(processedAt)}
                          </td>
                        ) : null}
                      </tr>
                    )
                  })}
                </tbody>
              </table>
              {!paginated.length && (
                <div className={styles.state}>
                  {initialLoading ? (
                    <>
                      <Loader2 className="animate-spin motion-reduce:animate-none" aria-hidden="true" />
                      <h2 role="status">正在加载隔离队列…</h2>
                    </>
                  ) : queueError ? (
                    <>
                      <AlertCircle aria-hidden="true" />
                      <h2>隔离队列加载失败</h2>
                      <p role="alert">{queueError}</p>
                      <Button variant="outline" disabled={queueFetching} onClick={onRefresh}>
                        重新加载
                      </Button>
                    </>
                  ) : hasActiveFilters ? (
                    <>
                      <Quarantine aria-hidden="true" />
                      <h2>没有符合条件的文档</h2>
                      <p>调整搜索词或筛选条件，查看其他隔离记录。</p>
                      <Button variant="outline" onClick={onResetFilters}>
                        清除筛选
                      </Button>
                    </>
                  ) : (
                    <>
                      <ShieldCheck aria-hidden="true" />
                      <h2>当前没有待复核文档</h2>
                      <p>文档被隔离或入库失败后，会出现在这里。</p>
                    </>
                  )}
                </div>
              )}
            </div>
          </div>

          <footer className={styles.footer} data-task-center-dock="true">
            <span role="status" className={styles.totals}>
              {queueFetching
                ? '正在同步…'
                : countsReady
                  ? hasActiveFilters
                    ? `筛出 ${filteredCount} / ${documentsCount} 份文档`
                    : `已加载 ${documentsCount} 份文档 · ${reviewCounts.unreviewed} 份待复核`
                  : '队列尚未加载'}
            </span>
            <div className={styles.pagination}>
              <span className={styles.pageSizeLabel}>每页 {QUARANTINE_PAGE_SIZE} 条</span>
              <Button
                variant="ghost"
                aria-label="上一页"
                disabled={safePage <= 1}
                onClick={() => onPageChange(safePage - 1)}
              >
                <ChevronLeft aria-hidden="true" />
              </Button>
              <span className={styles.pageNumber} aria-label={`第 ${safePage} 页，共 ${totalPages} 页`}>
                {safePage} / {totalPages}
              </span>
              <Button
                variant="ghost"
                aria-label="下一页"
                disabled={safePage >= totalPages}
                onClick={() => onPageChange(safePage + 1)}
              >
                <ChevronRight aria-hidden="true" />
              </Button>
            </div>
          </footer>
        </div>

        {reviewRailVisible ? (
          <aside className={styles.reviewRail} aria-label="复核详情" data-quarantine-review-rail="true">
            <header className={styles.reviewRailHeader}>
              <h2>复核详情</h2>
              {reviewOverflowMenu}
            </header>
            <div className={styles.reviewRailBody}>{reviewPanel}</div>
          </aside>
        ) : null}
      </div>

      <Sheet open={!reviewRailVisible && reviewSheetOpen} onOpenChange={onReviewSheetOpenChange}>
        <SheetContent className={styles.reviewSheet}>
          <SheetHeader className={styles.reviewSheetHeader}>
            <div className={styles.reviewSheetTitleRow}>
              <SheetTitle>复核详情</SheetTitle>
              {reviewOverflowMenu}
            </div>
            <SheetDescription className="sr-only">{inspectedDoc?.filename}</SheetDescription>
          </SheetHeader>
          <div className={styles.reviewRailBody}>{!reviewRailVisible ? reviewPanel : null}</div>
        </SheetContent>
      </Sheet>
    </div>
  )
}
