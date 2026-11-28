'use client'
import { useMemo, useState } from 'react'
import { ChevronLeft, ChevronRight, RefreshCcw, Search } from '@/components/icons'
import type { EChartsOption } from 'echarts'
import type { Document } from '@/types'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { FileTypeIcon } from '@/components/ui/file-type-icon'
import { Badge } from '@/components/ui/badge'
import { EChart } from '@/components/ui/echart'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '@/components/ui/dialog'
import { WorkspaceTableScroll, workspaceStyles as ws } from '@/components/ui/operational-workspace'
import { getDocumentStatusLabel, getDocumentStatusTone } from '@/app/knowledge/ingestion/presentation'
import { formatDurationClock } from '@/app/knowledge/ingestion/document-signals'
import { cn, formatFileSize } from '@/lib/utils'
import styles from './execution-monitor.module.css'
type ExecutionBatchAnalysis = {
  sourceLabel: string
  complexity: string
  pricingMode: string
  sampleTargetDetail: string
  totalSizeLabel: string
  samplePoolLabel: string
  pageCountNote?: string
}

type ExecutionRecentLog = {
  id: string
  time: string
  stage: string
  detail: string
}

type ExecutionPipelineCard = {
  key: 'parser' | 'chunker' | 'governance' | 'export'
  label: string
  metrics: string[][]
  statusLabel: string
}

type ExecutionMonitorPanelProps = {
  batchProfileBarOption: EChartsOption
  detail?: 'analysis' | 'logs' | null
  executionBatchAnalysis: ExecutionBatchAnalysis
  executionPipelineCards: ExecutionPipelineCard[]
  executionPipelineEstimateLabel: string
  executionPipelineWarning: string | null
  executionRecentLogs: ExecutionRecentLog[]
  executionTaskRows: Document[]
  isRefreshing?: boolean
  predictionOption: EChartsOption
  radarOption: EChartsOption
  selectedDatasetId: string | null
  onDetailChange?: (next: 'analysis' | 'logs' | null) => void
  onOpenAuditSnapshot: (documentId: string) => void
  onOpenIngestionOperation: () => void
  onRefresh?: () => void
  onScopeAllProjects: () => void
}

const stageLabels: Record<string, string> = {
  pending: '等待处理',
  preprocessing: '预处理',
  parsing: '解析正文',
  parser: '解析正文',
  governance: '数据治理',
  chunking: '文档切片',
  indexing: '建立索引',
  completed: '处理完成',
}
const statusViews = [
  ['all', '全部'],
  ['processing', '处理中'],
  ['pending', '等待中'],
  ['completed', '已完成'],
  ['failed', '失败'],
  ['quarantined', '已隔离'],
  ['cancelled', '已取消'],
] as const

export function ExecutionMonitorPanel(props: Readonly<ExecutionMonitorPanelProps>) {
  const [status, setStatus] = useState('all')
  const [query, setQuery] = useState('')
  const [page, setPage] = useState(1)
  const [localDetail, setLocalDetail] = useState<'analysis' | 'logs' | null>(null)
  const detail = props.detail !== undefined ? props.detail : localDetail
  const setDetail = props.onDetailChange ?? setLocalDetail
  const rows = useMemo(
    () =>
      props.executionTaskRows.filter(
        (doc) =>
          (status === 'all' || doc.status === status) &&
          doc.filename.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()),
      ),
    [props.executionTaskRows, status, query],
  )
  const pageCount = Math.max(1, Math.ceil(rows.length / 20))
  const currentPage = Math.min(page, pageCount)
  const visibleRows = rows.slice((currentPage - 1) * 20, currentPage * 20)
  const counts = (state: string) => props.executionTaskRows.filter((doc) => doc.status === state).length
  const isStandbyEmpty = props.executionTaskRows.length === 0
  return (
    <>
      {props.executionPipelineWarning ? (
        <p role="alert" className="px-5 pt-3 text-sm text-destructive">
          {props.executionPipelineWarning}
        </p>
      ) : null}
      {isStandbyEmpty ? (
        <div className={styles.standbySplit} data-execution-monitor-empty="true">
          <section className={styles.standbyLeft} aria-label="执行监控待命">
            <div className={styles.standbyIllust} aria-hidden="true">
              <svg viewBox="0 0 224 92" fill="none">
                <path
                  d="M24 52H72C80 52 84 46 88 46"
                  stroke="currentColor"
                  strokeOpacity="0.28"
                  strokeWidth="1.25"
                  strokeLinecap="round"
                />
                <path
                  d="M52 24H66C74 24 78 36 86 42"
                  stroke="currentColor"
                  strokeOpacity="0.28"
                  strokeWidth="1.25"
                  strokeLinecap="round"
                />
                <path
                  d="M138 44C148 44 156 18 170 18H186"
                  stroke="currentColor"
                  strokeOpacity="0.34"
                  strokeWidth="1.25"
                  strokeLinecap="round"
                />
                <path
                  d="M138 50C152 50 164 56 176 46H200"
                  stroke="currentColor"
                  strokeOpacity="0.28"
                  strokeWidth="1.25"
                  strokeLinecap="round"
                />
                <circle cx="20" cy="52" r="4" fill="hsl(var(--card))" stroke="currentColor" strokeOpacity="0.34" strokeWidth="1.25" />
                <circle cx="48" cy="24" r="4" fill="hsl(var(--card))" stroke="currentColor" strokeOpacity="0.34" strokeWidth="1.25" />
                <circle cx="204" cy="46" r="4" fill="hsl(var(--card))" stroke="currentColor" strokeOpacity="0.34" strokeWidth="1.25" />
                <circle cx="188" cy="18" r="4.5" fill="hsl(var(--accent))" />
                <rect
                  x="86"
                  y="20"
                  width="52"
                  height="52"
                  rx="12"
                  fill="hsl(var(--surface-2))"
                  stroke="currentColor"
                  strokeOpacity="0.32"
                  strokeWidth="1.25"
                />
                <path
                  d="M112 34L124 40.5L112 47L100 40.5L112 34Z"
                  stroke="currentColor"
                  strokeOpacity="0.55"
                  strokeWidth="1.35"
                  strokeLinejoin="round"
                />
                <path
                  d="M100 46.5L112 53L124 46.5"
                  stroke="currentColor"
                  strokeOpacity="0.45"
                  strokeWidth="1.35"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
                <path
                  d="M100 52.5L112 59L124 52.5"
                  stroke="currentColor"
                  strokeOpacity="0.38"
                  strokeWidth="1.35"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
            </div>
            <h2>当前范围暂无执行任务</h2>
            <p>提交入库任务后，这里将实时追踪解析、切块、治理与索引进度。</p>
            <div className={styles.standbyActions}>
              <Button className={styles.primaryAction} onClick={props.onOpenIngestionOperation}>
                前往入库操作
              </Button>
              {props.onRefresh ? (
                <Button
                  variant="outline"
                  className={styles.secondaryAction}
                  onClick={props.onRefresh}
                  disabled={props.isRefreshing}
                >
                  <RefreshCcw className="size-3.5" aria-hidden="true" />
                  重新读取
                </Button>
              ) : null}
              {props.selectedDatasetId ? (
                <Button variant="outline" className={styles.secondaryAction} onClick={props.onScopeAllProjects}>
                  查看全部数据集
                </Button>
              ) : null}
            </div>
          </section>
          <aside className={styles.standbyRight} aria-label="流水线阶段与运行概况">
            <div className={styles.standbyGroup}>
              <h3>流水线阶段待命</h3>
              <ul className={styles.stageList}>
                {props.executionPipelineCards.map((stage) => (
                  <li key={stage.key} className={styles.stageRow}>
                    <span className={styles.stageName}>{stage.label}</span>
                    <span className={styles.stageStatus}>{stage.statusLabel}</span>
                    <span className={styles.stageCount}>{stage.metrics[0]?.[1] ?? '0'}</span>
                  </li>
                ))}
              </ul>
            </div>
            <div className={styles.standbyGroup}>
              <h3>运行概况</h3>
              <div className={styles.summaryList}>
                <div className={styles.summaryRow}>
                  <span className={styles.stageName}>队列模式</span>
                  <span className={styles.summaryValue}>{props.executionPipelineEstimateLabel}</span>
                </div>
                <button
                  type="button"
                  className={styles.summaryRowButton}
                  onClick={() => setDetail('logs')}
                >
                  <span className={styles.stageName}>最近事件</span>
                  <span className={styles.summaryValue}>
                    {props.executionRecentLogs.length > 0 ? `${props.executionRecentLogs.length} 条记录` : '暂无记录'}
                    <ChevronRight className="size-3.5 shrink-0" aria-hidden="true" />
                  </span>
                </button>
              </div>
            </div>
          </aside>
        </div>
      ) : (
      <section className={cn(styles.activeBody, 'border-b border-border/70')}>
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <div className="flex min-w-0 items-baseline gap-3">
            <h2 className={ws.sectionTitle}>执行任务</h2>
            <span className="text-[13px] text-muted-foreground tabular-nums">
              已载入 {props.executionTaskRows.length} 条
            </span>
          </div>
        </div>
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2 sm:mb-4 sm:gap-3">
          <select
            aria-label="任务状态"
            value={status}
            className="h-11 rounded-md border border-border bg-background px-2 text-sm sm:hidden"
            onChange={(event) => {
              setStatus(event.target.value)
              setPage(1)
            }}
          >
            {statusViews.map(([value, label]) => (
              <option key={value} value={value}>
                {label}
                {value === 'all' ? '' : ` ${counts(value)}`}
              </option>
            ))}
          </select>
          <div role="group" aria-label="任务状态" className="hidden flex-wrap gap-1 sm:flex">
            {statusViews.map(([value, label]) => (
              <Button
                key={value}
                variant={status === value ? 'secondary' : 'ghost'}
                className="h-9 px-3 text-[13px] max-sm:h-11"
                aria-pressed={status === value}
                onClick={() => {
                  setStatus(value)
                  setPage(1)
                }}
              >
                {label}
                {value === 'all' ? '' : ` ${counts(value)}`}
              </Button>
            ))}
          </div>
          <div className="relative min-w-0 flex-1 sm:w-full sm:max-w-xs sm:flex-auto">
            <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              aria-label="搜索执行任务"
              placeholder="搜索文件名"
              className="pl-9"
              value={query}
              onChange={(e) => {
                setQuery(e.target.value)
                setPage(1)
              }}
            />
          </div>
        </div>
        <WorkspaceTableScroll label="执行任务表格" stickyActions>
          <table className={cn(ws.table, 'table-fixed sm:min-w-[880px] sm:table-auto')}>
            <thead>
              <tr>
                <th>文件</th>
                <th className="hidden sm:table-cell">当前阶段</th>
                <th className="hidden sm:table-cell">状态</th>
                <th className="hidden sm:table-cell">进度</th>
                <th className="hidden sm:table-cell">耗时</th>
                <th className="w-20 sm:w-auto">操作</th>
              </tr>
            </thead>
            <tbody>
              {visibleRows.map((doc) => {
                const progress =
                  typeof doc.processing_progress === 'number'
                    ? Math.round(doc.processing_progress)
                    : doc.status === 'completed'
                      ? 100
                      : null
                const duration = new Date(doc.updated_at).getTime() - new Date(doc.created_at).getTime()
                const stage = doc.current_stage
                  ? (stageLabels[doc.current_stage.toLowerCase()] ?? doc.current_stage)
                  : '—'
                return (
                  <tr key={doc.id}>
                    <td>
                      <div className="flex items-center gap-3">
                        <FileTypeIcon type={doc.file_type} filename={doc.filename} className="size-5 shrink-0" />
                        <div className="min-w-0">
                          <div className="max-w-[360px] truncate font-medium" title={doc.filename}>
                            {doc.filename}
                          </div>
                          <p className="hidden sm:block">
                            {(doc.file_type || '—').toUpperCase()} ·{' '}
                            {typeof doc.file_size === 'number' ? formatFileSize(doc.file_size) : '—'}
                          </p>
                          <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs sm:hidden">
                            <span className={getDocumentStatusTone(doc.status)}>
                              {getDocumentStatusLabel(doc.status)}
                            </span>
                            <span className="text-muted-foreground">{stage}</span>
                            <span className="tabular-nums text-muted-foreground">
                              {progress === null ? '—' : `${progress}%`}
                            </span>
                          </div>
                        </div>
                      </div>
                    </td>
                    <td className="hidden whitespace-nowrap sm:table-cell">{stage}</td>
                    <td className={cn(getDocumentStatusTone(doc.status), 'hidden whitespace-nowrap sm:table-cell')}>
                      {getDocumentStatusLabel(doc.status)}
                    </td>
                    <td className="hidden sm:table-cell">
                      <div className="flex items-center gap-2">
                        {progress !== null ? (
                          <>
                            <div
                              className={ws.progressTrack}
                              role="progressbar"
                              aria-valuenow={progress}
                              aria-valuemin={0}
                              aria-valuemax={100}
                              aria-label={`${doc.filename} 处理进度`}
                            >
                              <span data-state={doc.status} style={{ width: `${progress}%` }} />
                            </div>
                            <span className="tabular-nums">{progress}%</span>
                          </>
                        ) : (
                          <span className="text-muted-foreground">—</span>
                        )}
                      </div>
                    </td>
                    <td className="hidden tabular-nums sm:table-cell">
                      {Number.isFinite(duration) && duration > 0 ? formatDurationClock(duration / 1000) : '—'}
                    </td>
                    <td>
                      <Button
                        variant="ghost"
                        aria-label={`查看任务 ${doc.filename}`}
                        onClick={() => props.onOpenAuditSnapshot(doc.id)}
                      >
                        详情
                      </Button>
                    </td>
                  </tr>
                )
              })}
              {!visibleRows.length ? (
                <tr>
                  <td colSpan={6}>
                    <div className={ws.empty}>
                      <h2>{props.executionTaskRows.length ? '没有匹配的任务' : '当前范围暂无执行任务'}</h2>
                      {props.executionTaskRows.length ? (
                        <Button
                          variant="outline"
                          onClick={() => {
                            setStatus('all')
                            setQuery('')
                            setPage(1)
                          }}
                        >
                          清除筛选
                        </Button>
                      ) : (
                        <div className="flex flex-wrap gap-2">
                          <Button onClick={props.onOpenIngestionOperation}>去入库操作</Button>
                          {props.selectedDatasetId ? (
                            <Button variant="outline" onClick={props.onScopeAllProjects}>
                              查看全部数据集
                            </Button>
                          ) : null}
                        </div>
                      )}
                    </div>
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </WorkspaceTableScroll>
        {/* 为悬浮任务中心留出分页点击空间。 */}
        <div className="mt-4 flex flex-wrap items-center justify-between gap-3 pr-16 text-sm text-muted-foreground">
          <span>共 {rows.length} 条 · 每页 20 条</span>
          <div className="flex items-center gap-3">
            <Button
              variant="outline"
              aria-label="上一页任务"
              disabled={currentPage === 1}
              onClick={() => setPage(currentPage - 1)}
            >
              <ChevronLeft />
            </Button>
            <span className="tabular-nums">
              {currentPage} / {pageCount}
            </span>
            <Button
              variant="outline"
              aria-label="下一页任务"
              disabled={currentPage === pageCount}
              onClick={() => setPage(currentPage + 1)}
            >
              <ChevronRight />
            </Button>
          </div>
        </div>
      </section>
      )}
      <Dialog
        open={detail !== null}
        onOpenChange={(open) => {
          if (!open) setDetail(null)
        }}
      >
        <DialogContent className={cn(ws.dialog, ws.wideDialog)}>
          <DialogHeader className={ws.dialogHeader}>
            <DialogTitle>{detail === 'logs' ? '最近事件' : '阶段与统计'}</DialogTitle>
            <DialogDescription>当前任务范围内的运行记录与统计。</DialogDescription>
          </DialogHeader>
          <div className={ws.dialogBody}>
            {detail === 'logs' ? (
              <div className={ws.tableScroll}>
                <table className={ws.table}>
                  <thead>
                    <tr>
                      <th>时间</th>
                      <th>阶段</th>
                      <th>事件</th>
                    </tr>
                  </thead>
                  <tbody>
                    {props.executionRecentLogs.map((log) => (
                      <tr key={log.id}>
                        <td className="whitespace-nowrap tabular-nums">{log.time}</td>
                        <td>{log.stage}</td>
                        <td>{log.detail}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {!props.executionRecentLogs.length ? <p className={ws.empty}>暂无事件记录</p> : null}
              </div>
            ) : (
              <>
                <section className={ws.section}>
                  <div className={ws.sectionHeading}>
                    <h2 className={ws.sectionTitle}>处理阶段</h2>
                    <span className={ws.muted}>{props.executionPipelineEstimateLabel}</span>
                  </div>
                  <div className={ws.tableScroll}>
                    <table className={ws.table}>
                      <thead>
                        <tr>
                          <th>阶段</th>
                          <th>状态</th>
                          <th>读数</th>
                        </tr>
                      </thead>
                      <tbody>
                        {props.executionPipelineCards.map((stage) => (
                          <tr key={stage.key}>
                            <td>{stage.label}</td>
                            <td>
                              <Badge variant="outline">{stage.statusLabel}</Badge>
                            </td>
                            <td>
                              {stage.metrics.map((metric, i) => (
                                <div key={i}>{metric.join(' · ')}</div>
                              ))}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </section>
                <div className={ws.charts}>
                  {(
                    [
                      ['文件画像', props.batchProfileBarOption],
                      ['处理分布', props.radarOption],
                      ['吞吐趋势', props.predictionOption],
                    ] as const
                  ).map(([label, option]) => (
                    <section className={ws.section} key={label}>
                      <h2 className={ws.sectionTitle}>{label}</h2>
                      <div className="h-72">
                        <EChart option={option} />
                      </div>
                    </section>
                  ))}
                </div>
                <section className={ws.section}>
                  <h2 className={ws.sectionTitle}>批次信息</h2>
                  <dl className="mt-3 grid gap-x-8 gap-y-3 text-sm sm:grid-cols-2">
                    {Object.entries({
                      来源: props.executionBatchAnalysis.sourceLabel,
                      复杂度: props.executionBatchAnalysis.complexity,
                      计费方式: props.executionBatchAnalysis.pricingMode,
                      总大小: props.executionBatchAnalysis.totalSizeLabel,
                      采样范围: props.executionBatchAnalysis.samplePoolLabel,
                      采样说明: props.executionBatchAnalysis.sampleTargetDetail,
                    }).map(([label, value]) => (
                      <div key={label}>
                        <dt className="text-muted-foreground">{label}</dt>
                        <dd className="mt-1">{value}</dd>
                      </div>
                    ))}
                    {props.executionBatchAnalysis.pageCountNote === undefined ? null : (
                      <div>
                        <dt className="text-muted-foreground">页数说明</dt>
                        <dd className="mt-1">{props.executionBatchAnalysis.pageCountNote}</dd>
                      </div>
                    )}
                  </dl>
                </section>
              </>
            )}
          </div>
        </DialogContent>
      </Dialog>
    </>
  )
}
