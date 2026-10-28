'use client'

import { Fragment } from 'react'
import { AlertCircle, Calendar, ChevronLeft, ChevronRight, Dataset, Loader2, Quarantine, ShieldAlert, ShieldCheck } from '@/components/icons'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { FileTypeIcon } from '@/components/ui/file-type-icon'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { SearchInput } from '@/components/ui/search-input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import type { Document } from '@/types'
import { QUARANTINE_PAGE_SIZE } from '@/app/knowledge/quarantine/constants'
import { getDropReasons, getQuarantineSeverity, getQuarantineSource, isReviewed, reasonLabel } from '@/app/knowledge/quarantine/quarantine-signals'
import type { QuarantineSeverity, ReviewState } from '@/app/knowledge/quarantine/types'
import styles from '@/app/knowledge/quarantine/quarantine.module.css'
import { QuarantineInlineReview, type QuarantineReviewActions } from './quarantine-inline-review'

type Props = QuarantineReviewActions & {
  demoMode: boolean
  dateFrom: string
  dateTo: string
  datasetLabelById: Record<string, string>
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
  onOpenReview: (docId: string) => void
  onPageChange: (page: number) => void
  onReasonChange: (value: string) => void
  onRefresh: () => void
  onResetFilters: () => void
  onReviewStateChange: (value: ReviewState) => void
  onSearchChange: (value: string) => void
  onSeverityChange: (value: string) => void
  onSourceChange: (value: string) => void
}

function processingTime(value: string, full = false): string {
  const date = new Date(value)
  if (!Number.isFinite(date.getTime())) return '—'
  return date.toLocaleString('zh-CN', {
    ...(full ? { year: 'numeric' as const } : {}),
    month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false,
  })
}

function ReviewStateLabel({ doc }: Readonly<{ doc: Document }>) {
  const reviewed = isReviewed(doc)
  return <span className={styles.reviewState} data-reviewed={reviewed}>{reviewed ? '已复核' : '待复核'}</span>
}

export function QuarantineTableWorkspace(props: Readonly<Props>) {
  const { dateFrom, dateTo, datasetLabelById, datasetOptions, datasetsLoading, documentsCount, filteredCount, hasActiveFilters, paginated, queueFetching, initialLoading, queueError, countsReady, reviewCounts, severityCounts, reviewState, safePage, search, selectedDataset, selectedId, selectedReason, selectedSeverity, selectedSource, sortedReasons, sourceOptions, totalPages, reasonCounts, onDateFromChange, onDateToChange, onDatasetChange, onOpenReview, onPageChange, onReasonChange, onRefresh, onResetFilters, onReviewStateChange, onSearchChange, onSeverityChange, onSourceChange } = props
  const views: { id: ReviewState; label: string; count: number }[] = [
    { id: 'all', label: '全部', count: reviewCounts.total },
    { id: 'pending', label: '待复核', count: reviewCounts.unreviewed },
    { id: 'reviewed', label: '已复核', count: reviewCounts.reviewed },
  ]
  const dateLabel = dateFrom && dateTo ? `${dateFrom.slice(5)} – ${dateTo.slice(5)}` : dateFrom ? `${dateFrom.slice(5)} 起` : dateTo ? `截至 ${dateTo.slice(5)}` : '全部日期'
  return (
    <div className={styles.workspace}>
      <div className={styles.filters}>
        <div className={styles.viewbar}>
          <div className={styles.tabs} role="group" aria-label="复核状态">{views.map(view => <button key={view.id} type="button" className={styles.tab} aria-pressed={reviewState === view.id} onClick={() => onReviewStateChange(view.id)}>{view.label}{countsReady && <span className={styles.tabCount}>{view.count}</span>}</button>)}</div>
          {countsReady && <div className={styles.riskSummary} aria-label="风险分布">风险分布{(['高', '中', '低'] as const).map(level => <span key={level}>{level}<strong>{severityCounts[level]}</strong></span>)}</div>}
        </div>
        <div className={styles.filterRow}>
          <Select value={selectedDataset} onValueChange={onDatasetChange} disabled={datasetsLoading}><SelectTrigger className={styles.filterControl} aria-label="筛选数据集"><Dataset aria-hidden="true" /><SelectValue placeholder="全部数据集" /></SelectTrigger><SelectContent><SelectItem value="all">全部数据集</SelectItem>{datasetOptions.map(option => <SelectItem key={option.id} value={option.id}>{option.label}</SelectItem>)}</SelectContent></Select>
          <Select value={selectedReason} onValueChange={onReasonChange}><SelectTrigger className={styles.filterControl} aria-label="筛选隔离原因"><SelectValue placeholder="所有原因" /></SelectTrigger><SelectContent><SelectItem value="all">所有原因</SelectItem>{sortedReasons.map(reason => <SelectItem key={reason} value={reason}>{reasonLabel(reason)} · {reasonCounts[reason]}</SelectItem>)}</SelectContent></Select>
          <Select value={selectedSource} onValueChange={onSourceChange}><SelectTrigger className={styles.filterControl} aria-label="筛选来源"><SelectValue placeholder="全部来源" /></SelectTrigger><SelectContent><SelectItem value="all">全部来源</SelectItem>{sourceOptions.map(source => <SelectItem key={source} value={source}>{source}</SelectItem>)}</SelectContent></Select>
          <Select value={selectedSeverity} onValueChange={onSeverityChange}><SelectTrigger className={styles.filterControl} aria-label="筛选风险"><SelectValue placeholder="全部风险" /></SelectTrigger><SelectContent><SelectItem value="all">全部风险</SelectItem>{['高', '中', '低'].map(level => <SelectItem key={level} value={level}>{level}风险</SelectItem>)}</SelectContent></Select>
          <Popover><PopoverTrigger asChild><Button variant="outline" className={`${styles.filterControl} ${styles.dateControl}`} data-active={Boolean(dateFrom || dateTo)} aria-label={`筛选处理日期：${dateLabel}`}><Calendar aria-hidden="true" />{dateLabel}</Button></PopoverTrigger><PopoverContent align="start" className="w-72"><div className={styles.dateFields}><label>开始日期<Input type="date" value={dateFrom} max={dateTo || undefined} onChange={event => onDateFromChange(event.target.value)} /></label><label>结束日期<Input type="date" value={dateTo} min={dateFrom || undefined} onChange={event => onDateToChange(event.target.value)} /></label><Button size="sm" variant="ghost" disabled={!dateFrom && !dateTo} onClick={() => { onDateFromChange(''); onDateToChange('') }}>清除日期</Button></div></PopoverContent></Popover>
          <SearchInput value={search} onValueChange={onSearchChange} placeholder="搜索文档、规则或原因" aria-label="搜索隔离文档" containerClassName={styles.search} inputClassName={styles.searchInput} />
          {hasActiveFilters && <Button variant="ghost" className={styles.clearFilters} onClick={onResetFilters}>清除筛选</Button>}
        </div>
      </div>
      {queueError && paginated.length > 0 && <div className={styles.queueError} role="alert"><AlertCircle aria-hidden="true" /><span>{queueError}，当前显示已加载记录。</span><Button variant="ghost" disabled={queueFetching} onClick={onRefresh}>重新加载</Button></div>}
      <div className={styles.tableArea}>
        <div className={styles.tableScroll} data-page-scroll-container data-empty={!paginated.length} role="region" aria-label="隔离文档列表" tabIndex={0} aria-busy={queueFetching}>
          <table className={styles.table}>
            <caption className="sr-only">隔离与失败文档，可展开记录核对原因和原文</caption>
            <colgroup><col className={styles.nameColumn} /><col className={styles.reasonColumn} /><col className={styles.datasetColumn} /><col className={styles.sourceColumn} /><col className={styles.riskColumn} /><col className={styles.reviewColumn} /><col className={styles.dateColumn} /><col className={styles.actionColumn} /></colgroup>
            <thead><tr><th scope="col">文档</th><th scope="col" className={styles.reasonCell}>隔离原因</th><th scope="col" className={styles.datasetCell}>数据集</th><th scope="col" className={styles.sourceCell}>来源</th><th scope="col" className={styles.riskCell}>风险</th><th scope="col" className={styles.reviewCell}>复核状态</th><th scope="col" className={styles.dateCell}>处理时间</th><th scope="col">操作</th></tr></thead>
            <tbody>{paginated.map(doc => {
              const expanded = selectedId === doc.id
              const reasons = getDropReasons(doc).map(reasonLabel).join('、') || '待确认原因'
              const severity = getQuarantineSeverity(doc)
              const datasetLabel = doc.dataset_id ? datasetLabelById[doc.dataset_id] || doc.dataset_id : '未指定数据集'
              const regionId = `quarantine-review-${doc.id}`
              const RiskIcon = severity === '高' ? ShieldAlert : ShieldCheck
              return <Fragment key={doc.id}>
                <tr className={styles.record} data-quarantine-row={doc.id} data-expanded={expanded}>
                  <td><button type="button" className={styles.fileButton} aria-label={`复核 ${doc.filename}`} aria-expanded={expanded} aria-controls={expanded ? regionId : undefined} title={doc.filename} onClick={() => onOpenReview(doc.id)}><FileTypeIcon type={doc.file_type} filename={doc.filename} /><span>{doc.filename}</span></button><div className={styles.mobileMeta}><span>{reasons}</span><ReviewStateLabel doc={doc} /></div></td>
                  <td className={styles.reasonCell} title={reasons}>{reasons}</td><td className={styles.datasetCell} title={datasetLabel}>{datasetLabel}</td><td className={styles.sourceCell}>{getQuarantineSource(doc)}</td>
                  <td className={styles.riskCell}><span className={styles.risk} data-severity={severity}><RiskIcon aria-hidden="true" />{severity}</span></td><td className={styles.reviewCell}><ReviewStateLabel doc={doc} /></td>
                  <td className={styles.dateCell} title={processingTime(doc.updated_at || doc.created_at, true)}>{processingTime(doc.updated_at || doc.created_at)}</td>
                  <td><button type="button" className={styles.rowAction} aria-label={`${expanded ? '收起' : '展开'} ${doc.filename}复核`} aria-expanded={expanded} aria-controls={expanded ? regionId : undefined} onClick={() => onOpenReview(doc.id)}>复核<ChevronRight aria-hidden="true" /></button></td>
                </tr>
                {expanded && <tr><td colSpan={8} className={styles.expandedCell} id={regionId}><QuarantineInlineReview {...props} document={doc} datasetLabel={datasetLabel} /></td></tr>}
              </Fragment>
            })}</tbody>
          </table>
          {!paginated.length && <div className={styles.state}>{initialLoading ? <><Loader2 className="animate-spin motion-reduce:animate-none" aria-hidden="true" /><h2 role="status">正在加载隔离队列…</h2></>
            : queueError ? <><AlertCircle aria-hidden="true" /><h2>隔离队列加载失败</h2><p role="alert">{queueError}</p><Button variant="outline" disabled={queueFetching} onClick={onRefresh}>重新加载</Button></>
            : hasActiveFilters ? <><Quarantine aria-hidden="true" /><h2>没有符合条件的文档</h2><p>调整搜索词或筛选条件，查看其他隔离记录。</p><Button variant="outline" onClick={onResetFilters}>清除筛选</Button></>
            : <><ShieldCheck aria-hidden="true" /><h2>当前没有待复核文档</h2><p>文档被隔离或入库失败后，会出现在这里。</p></>}</div>}
        </div>
      </div>
      <footer className={styles.footer} data-task-center-dock="true"><span role="status">{queueFetching ? '正在同步…' : countsReady ? hasActiveFilters ? `筛出 ${filteredCount} / ${documentsCount} 份文档` : `共 ${documentsCount} 份文档 · ${reviewCounts.unreviewed} 份待复核` : '队列尚未加载'}</span><div className={styles.pagination}><span className={styles.pageSizeLabel}>每页 {QUARANTINE_PAGE_SIZE} 条</span><Button variant="ghost" aria-label="上一页" disabled={safePage <= 1} onClick={() => onPageChange(safePage - 1)}><ChevronLeft aria-hidden="true" /></Button><span className={styles.pageNumber} aria-label={`第 ${safePage} 页，共 ${totalPages} 页`}>{safePage} / {totalPages}</span><Button variant="ghost" aria-label="下一页" disabled={safePage >= totalPages} onClick={() => onPageChange(safePage + 1)}><ChevronRight aria-hidden="true" /></Button></div></footer>
    </div>
  )
}
