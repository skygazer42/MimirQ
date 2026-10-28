'use client'
import { useMemo, useState } from 'react'
import { ChevronLeft, ChevronRight, Activity, FileText, Search } from '@/components/icons'
import type { PlatformIcon } from '@/components/icons'
import type { EChartsOption } from 'echarts'
import type { Document } from '@/types'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { EChart } from '@/components/ui/echart'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '@/components/ui/dialog'
import { WorkspaceMetrics, WorkspaceTableScroll, workspaceStyles as ws } from '@/components/ui/operational-workspace'
import { getDocumentStatusLabel, getDocumentStatusTone } from '@/app/knowledge/ingestion/presentation'
import { formatDurationClock } from '@/app/knowledge/ingestion/document-signals'
import { cn, formatFileSize } from '@/lib/utils'
type ExecutionKpiCard = {
  label: string
  value: string
  suffix?: string
  detail: string
  icon: PlatformIcon
  tone: string
}

type ExecutionBatchAnalysis = {
  sourceLabel: string
  complexity: string
  pricingMode: string
  sampleTarget: number | null
  sampleTargetDetail: string
  totalSizeLabel: string
  samplePoolLabel: string
  imageProxyNote: string
}

type ExecutionRecentLog = {
  id: string
  time: string
  stage: string
  detail: string
  tone: string
}

type ExecutionPipelineCard = {
  key: 'parser' | 'chunker' | 'governance' | 'export'
  label: string
  metrics: string[][]
  progress: number
  statusLabel: string
  statusTone: string
}

type ExecutionMonitorPanelProps = {
  batchProfileBarOption: EChartsOption
  executionBatchAnalysis: ExecutionBatchAnalysis
  executionDocuments: Document[]
  executionKpiCards: ExecutionKpiCard[]
  executionOverallProgress: number
  executionPipelineCards: ExecutionPipelineCard[]
  executionPipelineEstimateLabel: string
  executionPipelineWarning: string | null
  executionProcessedTotal: number
  executionRecentLogs: ExecutionRecentLog[]
  executionSuccessRate: number
  executionTaskPage: number
  executionTaskPageCount: number
  executionTaskRows: Document[]
  predictionOption: EChartsOption
  radarOption: EChartsOption
  recentQueueOutcomesCount: number
  selectedDatasetId: string | null
  showEmptyShell: boolean
  visibleExecutionTaskRows: Document[]
  onNextPage: () => void
  onOpenAuditSnapshot: (documentId: string) => void
  onOpenIngestionOperation: () => void
  onPrevPage: () => void
  onScopeAllProjects: () => void
}


const stageLabels: Record<string, string> = { pending: '等待处理', preprocessing: '预处理', parsing: '解析正文', parser: '解析正文', governance: '数据治理', chunking: '文档切片', indexing: '建立索引', completed: '处理完成' }
const statusViews = [['all', '全部'], ['processing', '处理中'], ['pending', '等待中'], ['completed', '已完成'], ['failed', '失败'], ['quarantined', '已隔离'], ['cancelled', '已取消']] as const

export function ExecutionMonitorPanel(props: Readonly<ExecutionMonitorPanelProps>) {
  const [status, setStatus] = useState('all')
  const [query, setQuery] = useState('')
  const [page, setPage] = useState(1)
  const [detail, setDetail] = useState<'analysis' | 'logs' | null>(null)
  const rows = useMemo(() => props.executionTaskRows.filter(doc => (status === 'all' || doc.status === status) && doc.filename.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase())), [props.executionTaskRows, status, query])
  const pageCount = Math.max(1, Math.ceil(rows.length / 20))
  const currentPage = Math.min(page, pageCount)
  const visibleRows = rows.slice((currentPage - 1) * 20, currentPage * 20)
  const counts = (state: string) => props.executionTaskRows.filter(doc => doc.status === state).length
  return <>
    <WorkspaceMetrics className={ws.compactMetrics} items={[
      { label: '当前载入任务', value: props.executionTaskRows.length },
      { label: '处理中', value: counts('processing') },
      { label: '等待中', value: counts('pending') },
      { label: '已完成', value: counts('completed') },
      { label: '失败', value: counts('failed'), tone: counts('failed') ? 'danger' : undefined },
    ]} />
    {props.executionPipelineWarning ? <p role="alert" className="py-3 text-sm text-destructive">{props.executionPipelineWarning}</p> : null}
    <section className={ws.section}>
      <div className={ws.sectionHeading}><h2 className={ws.sectionTitle}>执行任务</h2><div className="flex flex-wrap gap-2"><Button variant="ghost" onClick={() => setDetail('logs')}>最近事件</Button><Button variant="outline" onClick={() => setDetail('analysis')}><Activity />阶段与统计</Button></div></div>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div role="group" aria-label="任务状态" className="flex flex-wrap gap-1">{statusViews.map(([value, label]) => <Button key={value} variant={status === value ? 'secondary' : 'ghost'} aria-pressed={status === value} onClick={() => { setStatus(value); setPage(1) }}>{label}{value === 'all' ? '' : ` ${counts(value)}`}</Button>)}</div>
        <div className="relative w-full max-w-xs"><Search className="absolute left-3 top-2.5 size-4 text-muted-foreground" /><Input aria-label="搜索执行任务" placeholder="搜索文件名" className="pl-9" value={query} onChange={e => { setQuery(e.target.value); setPage(1) }} /></div>
      </div>
      <WorkspaceTableScroll label="执行任务表格" stickyActions><table className={cn(ws.table, 'min-w-[880px]')}><thead><tr><th>文件</th><th>当前阶段</th><th>状态</th><th>进度</th><th>耗时</th><th>操作</th></tr></thead><tbody>
        {visibleRows.map(doc => {
          const progress = typeof doc.processing_progress === 'number' ? Math.round(doc.processing_progress) : doc.status === 'completed' ? 100 : null
          const duration = new Date(doc.updated_at).getTime() - new Date(doc.created_at).getTime()
          return <tr key={doc.id}><td><div className="flex items-center gap-3"><FileText appearance="color" className="size-5 shrink-0 text-muted-foreground" /><div className="min-w-0"><div className="max-w-[360px] truncate font-medium" title={doc.filename}>{doc.filename}</div><p>{(doc.file_type || '—').toUpperCase()} · {typeof doc.file_size === 'number' ? formatFileSize(doc.file_size) : '—'}</p></div></div></td><td className="whitespace-nowrap">{doc.current_stage ? stageLabels[doc.current_stage.toLowerCase()] ?? doc.current_stage : '—'}</td><td className={cn(getDocumentStatusTone(doc.status), 'whitespace-nowrap')}>{getDocumentStatusLabel(doc.status)}</td><td><div className="flex items-center gap-2">{progress !== null ? <><div className={ws.progressTrack} role="progressbar" aria-valuenow={progress} aria-valuemin={0} aria-valuemax={100} aria-label={`${doc.filename} 处理进度`}><span data-state={doc.status} style={{ width: `${progress}%` }} /></div><span className="tabular-nums">{progress}%</span></> : <span className="text-muted-foreground">—</span>}</div></td><td className="tabular-nums">{Number.isFinite(duration) && duration > 0 ? formatDurationClock(duration / 1000) : '—'}</td><td><Button variant="ghost" aria-label={`查看任务 ${doc.filename}`} onClick={() => props.onOpenAuditSnapshot(doc.id)}>详情</Button></td></tr>
        })}
        {!visibleRows.length ? <tr><td colSpan={6}><div className={ws.empty}><h2>{props.executionTaskRows.length ? '没有匹配的任务' : '当前范围暂无执行任务'}</h2>{props.executionTaskRows.length ? <Button variant="outline" onClick={() => { setStatus('all'); setQuery(''); setPage(1) }}>清除筛选</Button> : <div className="flex flex-wrap gap-2"><Button onClick={props.onOpenIngestionOperation}>去入库操作</Button>{props.selectedDatasetId ? <Button variant="outline" onClick={props.onScopeAllProjects}>查看全部数据集</Button> : null}</div>}</div></td></tr> : null}
      </tbody></table></WorkspaceTableScroll>
      <div className="mt-4 flex flex-wrap items-center justify-between gap-3 text-sm text-muted-foreground"><span>共 {rows.length} 条 · 每页 20 条</span><div className="flex items-center gap-3"><Button variant="outline" aria-label="上一页任务" disabled={currentPage === 1} onClick={() => setPage(currentPage - 1)}><ChevronLeft /></Button><span className="tabular-nums">{currentPage} / {pageCount}</span><Button variant="outline" aria-label="下一页任务" disabled={currentPage === pageCount} onClick={() => setPage(currentPage + 1)}><ChevronRight /></Button></div></div>
    </section>
    <Dialog open={detail !== null} onOpenChange={open => { if (!open) setDetail(null) }}><DialogContent className={cn(ws.dialog, ws.wideDialog)}><DialogHeader className={ws.dialogHeader}><DialogTitle>{detail === 'logs' ? '最近事件' : '阶段与统计'}</DialogTitle><DialogDescription>当前任务范围内的运行记录与统计。</DialogDescription></DialogHeader><div className={ws.dialogBody}>
      {detail === 'logs' ? <div className={ws.tableScroll}><table className={ws.table}><thead><tr><th>时间</th><th>阶段</th><th>事件</th></tr></thead><tbody>{props.executionRecentLogs.map(log => <tr key={log.id}><td className="whitespace-nowrap tabular-nums">{log.time}</td><td>{log.stage}</td><td>{log.detail}</td></tr>)}</tbody></table>{!props.executionRecentLogs.length ? <p className={ws.empty}>暂无事件记录</p> : null}</div> : <>
        <section className={ws.section}><div className={ws.sectionHeading}><h2 className={ws.sectionTitle}>处理阶段</h2><span className={ws.muted}>{props.executionPipelineEstimateLabel}</span></div><div className={ws.tableScroll}><table className={ws.table}><thead><tr><th>阶段</th><th>状态</th><th>读数</th></tr></thead><tbody>{props.executionPipelineCards.map(stage => <tr key={stage.key}><td>{stage.label}</td><td><Badge variant="outline">{stage.statusLabel}</Badge></td><td>{stage.metrics.map((metric, i) => <div key={i}>{metric.join(' · ')}</div>)}</td></tr>)}</tbody></table></div></section>
        <div className={ws.charts}>{[['文件画像', props.batchProfileBarOption], ['处理分布', props.radarOption], ['耗时估计', props.predictionOption]].map(([label, option]) => <section className={ws.section} key={label as string}><h2 className={ws.sectionTitle}>{label as string}</h2><div className="h-72"><EChart option={option as EChartsOption} /></div></section>)}</div>
        <section className={ws.section}><h2 className={ws.sectionTitle}>批次信息</h2><dl className="mt-3 grid gap-x-8 gap-y-3 text-sm sm:grid-cols-2">{Object.entries({ '来源': props.executionBatchAnalysis.sourceLabel, '复杂度': props.executionBatchAnalysis.complexity, '计费方式': props.executionBatchAnalysis.pricingMode, '总大小': props.executionBatchAnalysis.totalSizeLabel, '采样范围': props.executionBatchAnalysis.samplePoolLabel, '采样说明': props.executionBatchAnalysis.sampleTargetDetail, '图像统计': props.executionBatchAnalysis.imageProxyNote }).map(([label, value]) => <div key={label}><dt className="text-muted-foreground">{label}</dt><dd className="mt-1">{value || '—'}</dd></div>)}</dl></section>
      </>}
    </div></DialogContent></Dialog>
  </>
}
