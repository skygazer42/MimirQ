'use client'

import type { EChartsOption } from 'echarts'
import {
  Activity,
  ChevronLeft,
  ChevronRight,
  CircleAlert,
  Database,
  FileText,
  FileSearch,
  Radar,
  Scissors,
  ShieldCheck,
  Workflow,
  type LucideIcon,
} from 'lucide-react'

import { Button } from '@/components/ui/button'
import { EChart } from '@/components/ui/echart'
import { cn, formatFileSize } from '@/lib/utils'
import {
  getDocumentStatusLabel,
  getDocumentStatusTone,
  getTaskProgress,
} from '@/app/knowledge/ingestion/presentation'
import { formatDurationClock } from '@/app/knowledge/ingestion/document-signals'
import type { Document } from '@/types'

type ExecutionKpiCard = {
  label: string
  value: string
  suffix?: string
  detail: string
  icon: LucideIcon
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

const PIPELINE_STAGE_ICONS: Record<ExecutionPipelineCard['key'], LucideIcon> = {
  parser: FileText,
  chunker: Scissors,
  governance: ShieldCheck,
  export: Database,
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

function CompactEmptyVisual({
  message,
  className,
}: Readonly<{
  message: string
  className?: string
}>) {
  return (
    <div
      data-execution-empty-visual="true"
      className={cn(
        'flex min-h-12 items-center justify-center gap-2 border-l-2 border-info/25 bg-muted/[0.05] px-3 py-2.5 text-center text-[11px] leading-4 text-muted-foreground',
        className
      )}
    >
      <Workflow className="size-4 text-info/70" />
      <span>{message}</span>
    </div>
  )
}

export function ExecutionMonitorPanel({
  batchProfileBarOption,
  executionBatchAnalysis,
  executionDocuments,
  executionKpiCards,
  executionOverallProgress,
  executionPipelineCards,
  executionPipelineEstimateLabel,
  executionPipelineWarning,
  executionProcessedTotal,
  executionRecentLogs,
  executionSuccessRate,
  executionTaskPage,
  executionTaskPageCount,
  executionTaskRows,
  onNextPage,
  onOpenAuditSnapshot,
  onOpenIngestionOperation,
  onPrevPage,
  onScopeAllProjects,
  predictionOption,
  radarOption,
  recentQueueOutcomesCount,
  selectedDatasetId,
  showEmptyShell,
  visibleExecutionTaskRows,
}: Readonly<ExecutionMonitorPanelProps>) {
  const fileTypeSummary = Object.entries(
    executionDocuments.reduce<Record<string, number>>((summary, document) => {
      const fileType = String(document.file_type || '其他').trim().toUpperCase()
      summary[fileType] = (summary[fileType] ?? 0) + 1
      return summary
    }, {})
  ).sort(([, left], [, right]) => right - left)
  const hasExecutionData = executionDocuments.length > 0
  const fileTypePalette = ['#0ea5e9', '#14b8a6', '#8b5cf6', '#f59e0b', '#64748b']
  const fileTypeDonutData = fileTypeSummary.length
    ? fileTypeSummary.slice(0, 5).map(([name, value], index) => ({
        name,
        value,
        itemStyle: { color: fileTypePalette[index] },
      }))
    : [
        {
          name: '暂无数据',
          value: 1,
          itemStyle: { color: 'rgba(148,163,184,0.22)' },
        },
      ]
  const fileTypeDonutOption: EChartsOption = {
    animationDuration: 280,
    tooltip: fileTypeSummary.length
      ? { trigger: 'item', formatter: '{b}<br/>{c} 个 · {d}%' }
      : { show: false },
    legend: {
      show: fileTypeSummary.length > 0,
      orient: 'vertical',
      right: 0,
      top: 'center',
      itemWidth: 8,
      itemHeight: 8,
      itemGap: 6,
      textStyle: {
        color: 'hsl(var(--muted-foreground))',
        fontSize: 10,
      },
      formatter: (name: string) => {
        const count = fileTypeSummary.find(([fileType]) => fileType === name)?.[1] ?? 0
        return `${name}  ${count}`
      },
    },
    series: [
      {
        type: 'pie',
        radius: ['52%', '76%'],
        center: fileTypeSummary.length ? ['34%', '52%'] : ['50%', '52%'],
        avoidLabelOverlap: true,
        label: { show: false },
        labelLine: { show: false },
        emphasis: { scale: true, scaleSize: 3 },
        data: fileTypeDonutData,
      },
    ],
  }

  return (
    <div
      data-monitor-flat-canvas="true"
      data-monitor-boundary-system="ruled"
      data-monitor-visual-tone="enterprise"
      title="入库预检报告"
      className="bg-transparent"
    >
      <div>
        <div data-monitor-overview-band="true" className="grid items-stretch border-y border-foreground/15 xl:grid-cols-[minmax(18rem,0.64fr)_minmax(0,1.36fr)]">
          <section data-execution-file-type-summary="true" className="border-b border-foreground/10 px-3 py-3 xl:border-b-0 xl:border-r">
            <div className="flex items-center justify-between gap-3">
              <div className="flex items-center gap-2">
                <Activity className="size-5 shrink-0 text-info" />
                <div>
                  <div className="text-[13px] font-semibold text-foreground text-balance">
                    文件类型分布
                  </div>
                  <div className="mt-0.5 text-[10px] text-muted-foreground">
                    按文件格式统计
                  </div>
                </div>
              </div>
              <span className="rounded-md border border-border/45 bg-muted/15 px-2 py-0.5 font-mono text-[10px] text-foreground">
                {executionDocuments.length} 个
              </span>
            </div>
            <div data-monitor-chart="file-type-donut" className="relative mt-1 h-20">
              <EChart option={fileTypeDonutOption} />
              <div
                className={cn(
                  'pointer-events-none absolute top-1/2 -translate-x-1/2 -translate-y-1/2 text-center',
                  fileTypeSummary.length ? 'left-[34%]' : 'left-1/2'
                )}
              >
                <div className="font-mono text-[13px] font-semibold text-foreground tabular-nums">
                  {executionDocuments.length}
                </div>
                <div className="text-[9px] text-muted-foreground">文件</div>
              </div>
            </div>
          </section>

          <section data-monitor-run-strip="true" data-monitor-pipeline-visual="true" className="px-3 py-3">
            <div className="flex items-center justify-between gap-3">
              <div className="flex min-w-0 items-center gap-2">
                <div className="text-[13px] font-semibold text-foreground text-balance">
                  处理流水线
                </div>
                <span className="rounded-md border border-info/20 bg-info/8 px-1.5 py-0.5 text-[10px] font-medium text-info">
                  {executionPipelineEstimateLabel}
                </span>
                {executionPipelineWarning ? (
                  <span className="inline-flex max-w-48 items-center gap-1 truncate rounded-md border border-warning/20 bg-warning/8 px-1.5 py-0.5 text-[9px] text-warning">
                    <CircleAlert className="size-3 shrink-0" />
                    <span className="truncate">{executionPipelineWarning}</span>
                  </span>
                ) : null}
              </div>
              <div className="flex items-center gap-2 text-[10px] text-muted-foreground">
                <span>总体进度</span>
                <span className="font-mono text-[12px] font-semibold text-foreground tabular-nums">
                  {executionOverallProgress}%
                </span>
              </div>
            </div>

            <div className="mt-1.5 flex items-center gap-2">
              <div className="h-1 flex-1 overflow-hidden rounded-full bg-muted/45">
                <div
                  className="h-full rounded-full bg-info transition-[width] duration-300"
                  style={{ width: `${executionOverallProgress}%` }}
                />
              </div>
              <span className="font-mono text-[9px] text-muted-foreground tabular-nums">
                {executionProcessedTotal}/{executionDocuments.length}
              </span>
            </div>

            <div className="relative mt-2 grid gap-px overflow-hidden border-y border-foreground/10 bg-foreground/10 sm:grid-cols-2 xl:grid-cols-4">
              <span
                aria-hidden="true"
                className="pointer-events-none absolute left-[12%] right-[12%] top-4 hidden h-px bg-foreground/15 xl:block"
              />
              {executionPipelineCards.map((card) => {
                const Icon = PIPELINE_STAGE_ICONS[card.key]
                return (
                  <article
                    data-monitor-pipeline-stage="true"
                    key={card.key}
                    className="relative z-10 min-w-0 bg-background px-2 py-2"
                  >
                    <div className="flex items-center gap-2">
                      <span className="inline-flex size-7 shrink-0 items-center justify-center rounded-sm border border-foreground/10 bg-background/80 text-info">
                        <Icon className="size-4" />
                      </span>
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-1.5">
                          <span className="truncate text-[11px] font-semibold text-foreground">
                            {card.label}
                          </span>
                          <span className="inline-flex items-center gap-1 text-[9px] text-muted-foreground">
                            <span className={cn('size-1.5 rounded-full', card.statusTone)} />
                            {card.statusLabel}
                          </span>
                        </div>
                        <div className="mt-1 h-1 overflow-hidden rounded-full bg-muted/50">
                          <div
                            className="h-full rounded-full bg-info transition-[width] duration-300"
                            style={{ width: `${card.progress}%` }}
                          />
                        </div>
                      </div>
                      <span className="font-mono text-[10px] font-semibold text-foreground tabular-nums">
                        {card.progress}%
                      </span>
                    </div>

                    <div className="mt-2 grid grid-cols-3 gap-1 border-t border-foreground/10 pt-1.5">
                      {card.metrics.map(([label, value]) => (
                        <div key={label} className="min-w-0 text-center">
                          <div className="truncate font-mono text-[10px] font-semibold text-foreground tabular-nums">
                            {value}
                          </div>
                          <div className="truncate text-[9px] text-muted-foreground">
                            {label}
                          </div>
                        </div>
                      ))}
                    </div>
                  </article>
                )
              })}
            </div>
          </section>
        </div>

        <section data-monitor-quality-kpis="true" data-monitor-flat-section="quality" className="border-b border-foreground/15 px-3 py-3">
          <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
            <div className="flex items-center gap-2">
              <Activity className="size-5 shrink-0 text-info" />
              <div>
                <div className="text-[13px] font-semibold text-foreground text-balance">
                  质量与耗时
                </div>
                <div className="mt-0.5 text-[10px] text-muted-foreground text-pretty">
                  解析质量、处理耗时与失败重试
                </div>
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-1.5 text-[10px] text-muted-foreground">
              <span className="rounded-md border border-border/50 bg-background/75 px-2 py-0.5 tabular-nums">
                已处理 {executionProcessedTotal} / {executionDocuments.length}
              </span>
              <span className="rounded-md border border-success/20 bg-success/8 px-2 py-0.5 text-success tabular-nums">
                成功率 {executionSuccessRate}%
              </span>
            </div>
          </div>

          <div className="mt-2 grid gap-px overflow-hidden border-y border-foreground/10 bg-foreground/10 sm:grid-cols-2 xl:grid-cols-4">
            {executionKpiCards.map((item) => {
              const Icon = item.icon
              return (
                <div
                  key={item.label}
                  className="bg-background/90 px-3 py-2"
                >
                  <div className="flex items-center justify-between gap-1.5">
                    <div className="min-w-0">
                      <div className="truncate text-[10px] text-muted-foreground">
                        {item.label}
                      </div>
                      <div className="mt-0.5 flex items-baseline gap-1">
                        <span className="truncate font-mono text-[14px] font-semibold text-foreground tabular-nums">
                          {item.value}
                        </span>
                        {item.suffix ? (
                          <span className="text-[10px] text-muted-foreground">
                            {item.suffix}
                          </span>
                        ) : null}
                      </div>
                    </div>
                    <Icon className={cn('size-4 shrink-0', item.tone)} />
                  </div>
                  <div className="mt-0.5 truncate text-[10px] text-muted-foreground">
                    {item.detail}
                  </div>
                </div>
              )
            })}
          </div>
        </section>

        <section className="border-b border-foreground/15 px-3 py-3">
          <div className="flex flex-col gap-2 md:flex-row md:items-start md:justify-between">
            <div className="flex items-center gap-2">
              <FileSearch className="size-5 shrink-0 text-info" />
              <div>
                <div className="text-[13px] font-semibold text-foreground">
                  批次数据画像
                </div>
                <div className="mt-0.5 text-[11px] text-muted-foreground text-pretty">
                  按 3/1000 抽代表样本，已出现的文件类型每类至少覆盖 1 个
                </div>
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-1.5 text-[10px]">
              <span className="rounded-md border border-border/50 bg-muted/15 px-2 py-0.5 text-muted-foreground">
                {executionBatchAnalysis.sourceLabel}
              </span>
              <span className="rounded-md border border-info/20 bg-info/8 px-2 py-0.5 font-medium text-info">
                难度 {executionBatchAnalysis.complexity}
              </span>
              <span className="rounded-md border border-warning/20 bg-warning/8 px-2 py-0.5 font-medium text-warning">
                {executionBatchAnalysis.pricingMode}
              </span>
            </div>
          </div>
          {hasExecutionData ? (
            <div className="mt-2 grid gap-2 xl:grid-cols-[1fr_220px]">
              <div className="h-[15rem] border-y border-foreground/10 bg-muted/[0.04] p-2">
                <EChart option={batchProfileBarOption} />
              </div>
              <div className="divide-y divide-foreground/10 border-y border-foreground/10">
                <div className="px-3 py-2.5">
                  <div className="text-[10px] text-muted-foreground">
                    预检样本
                  </div>
                  <div className="mt-1 text-[18px] font-semibold text-foreground tabular-nums">
                    {executionBatchAnalysis.sampleTarget ?? 0} 个
                  </div>
                  <div className="mt-1 text-[10px] text-muted-foreground">
                    {executionBatchAnalysis.sampleTargetDetail}
                  </div>
                </div>
                <div className="px-3 py-2.5">
                  <div className="text-[10px] text-muted-foreground">
                    批次体量
                  </div>
                  <div className="mt-1 font-mono text-[14px] font-semibold text-foreground tabular-nums">
                    {executionBatchAnalysis.totalSizeLabel}
                  </div>
                  <div className="mt-1 text-[10px] text-muted-foreground">
                    {executionBatchAnalysis.samplePoolLabel}
                  </div>
                </div>
                <div className="px-3 py-2.5 text-[10px] leading-4 text-muted-foreground text-pretty">
                  {executionBatchAnalysis.imageProxyNote}
                </div>
              </div>
            </div>
          ) : (
            <div data-monitor-empty-batch="true" className="mt-2">
              <CompactEmptyVisual message="暂无批次画像；文件进入处理后将显示抽样规模、体量与结构特征。" />
            </div>
          )}
        </section>

        <div data-monitor-analytics-grid="true" className="grid min-w-0 border-b border-foreground/15 xl:grid-cols-2 2xl:grid-cols-[1.1fr_0.9fr_0.9fr]">
          <section className="min-w-0 border-b border-foreground/10 px-3 py-3 xl:border-b-0 xl:border-r">
            <div className="flex items-center justify-between gap-3">
              <div className="text-[13px] font-semibold text-foreground text-balance">
                处理吞吐趋势
              </div>
              {!hasExecutionData ? (
                <span className="rounded-md bg-muted/25 px-1.5 py-0.5 text-[9px] text-muted-foreground">
                  暂无真实数据
                </span>
              ) : null}
            </div>
            <div data-monitor-chart="throughput-line" className="mt-1 h-36">
              <EChart option={predictionOption} />
            </div>
          </section>

          <section className="min-w-0 border-b border-foreground/10 px-3 py-3 xl:border-b-0 2xl:border-r">
            <div className="flex items-center justify-between gap-3">
              <div className="text-[13px] font-semibold text-foreground text-balance">
                成本雷达
              </div>
              <div className="flex items-center gap-2">
                {!hasExecutionData ? (
                  <span className="rounded-md bg-muted/25 px-1.5 py-0.5 text-[9px] text-muted-foreground">
                    暂无真实数据
                  </span>
                ) : null}
                <Radar className="h-4 w-4 text-accent" />
              </div>
            </div>
            <div data-monitor-chart="cost-radar" className="mt-1 h-36">
              <EChart option={radarOption} />
            </div>
          </section>

          <section className="min-w-0 px-3 py-3 xl:col-span-2 xl:border-t xl:border-foreground/10 2xl:col-span-1 2xl:border-t-0">
            <div className="flex items-center justify-between gap-3">
              <div className="text-[13px] font-semibold text-foreground text-balance">
                运行日志（最近）
              </div>
              <span className="text-[10px] text-muted-foreground">
                {recentQueueOutcomesCount ? '来自任务队列' : '来自文档状态'}
              </span>
            </div>
            {executionRecentLogs.length ? (
              <div className="mt-2 space-y-2">
                {executionRecentLogs.map((log) => (
                  <div
                    key={log.id}
                    className="flex items-start gap-2.5 rounded-md border border-foreground/10 bg-background/78 px-2.5 py-2"
                  >
                    <span
                      className={cn(
                        'mt-1 h-2.5 w-2.5 shrink-0 rounded-full',
                        log.tone
                      )}
                    />
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2 text-[10px] text-muted-foreground">
                        <span className="font-mono">{log.time}</span>
                        <span>{log.stage}</span>
                      </div>
                      <div className="mt-0.5 truncate text-[11px] text-foreground">
                        {log.detail}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <CompactEmptyVisual className="mt-2" message="暂无最近运行日志" />
            )}
          </section>
        </div>

        <section className="px-3 py-3">
          <div className="flex items-center justify-between gap-3">
            <div className="text-[13px] font-semibold text-foreground text-balance">
              任务列表
            </div>
            <div className="text-[10px] text-muted-foreground">
              {executionTaskRows.length} 个任务
            </div>
          </div>
          <div className="mt-2 overflow-hidden border-y border-foreground/10">
            <table className="w-full text-left text-[11px]">
              <thead className="bg-muted/20 text-muted-foreground">
                <tr>
                  <th className="px-3 py-2 font-medium">文件名</th>
                  <th className="px-3 py-2 font-medium">类型</th>
                  <th className="px-3 py-2 font-medium">大小</th>
                  <th className="px-3 py-2 font-medium">当前阶段</th>
                  <th className="px-3 py-2 font-medium">状态</th>
                  <th className="px-3 py-2 font-medium">处理进度</th>
                  <th className="px-3 py-2 font-medium">耗时</th>
                  <th className="px-3 py-2 font-medium">操作</th>
                </tr>
              </thead>
              <tbody>
                {showEmptyShell ? (
                  <tr className="border-t border-foreground/10">
                    <td colSpan={8} className="px-3 py-3">
                      <div className="mx-auto flex max-w-xl flex-col items-center px-4 py-1 text-center">
                        <div className="text-[12px] font-semibold text-foreground">
                          当前范围暂无执行任务
                        </div>
                        <div className="mt-1 max-w-md text-[11px] leading-4 text-muted-foreground">
                          这个监控范围可以直接打开，但当前知识库还没有解析任务。可以切到入库操作提交解析，或查看全部项目的运行态。
                        </div>
                        <div className="mt-2 flex flex-wrap justify-center gap-2">
                          <Button
                            type="button"
                            size="sm"
                            className="h-8 rounded-md px-2.5 text-[11px]"
                            onClick={onOpenIngestionOperation}
                          >
                            去入库操作
                          </Button>
                          {selectedDatasetId ? (
                            <Button
                              type="button"
                              variant="outline"
                              size="sm"
                              className="h-8 rounded-md px-2.5 text-[11px]"
                              onClick={onScopeAllProjects}
                            >
                              查看全部项目
                            </Button>
                          ) : null}
                        </div>
                      </div>
                    </td>
                  </tr>
                ) : (
                  visibleExecutionTaskRows.map((document) => {
                    const progress = getTaskProgress(document)
                    const elapsedMinutes = (() => {
                      const created = new Date(
                        String(document.created_at || '')
                      ).getTime()
                      const updated = new Date(
                        String(document.updated_at || '')
                      ).getTime()
                      if (
                        !Number.isFinite(created) ||
                        !Number.isFinite(updated) ||
                        updated <= created
                      )
                        return '--'
                      return formatDurationClock((updated - created) / 1000)
                    })()
                    const statusLabel = getDocumentStatusLabel(document.status)
                    const statusTone = getDocumentStatusTone(document.status)

                    return (
                      <tr key={document.id} className="border-t border-foreground/10">
                        <td className="px-3 py-2 font-medium text-foreground">
                          {document.filename}
                        </td>
                        <td className="px-3 py-2 text-muted-foreground">
                          {String(document.file_type || '').toUpperCase()}
                        </td>
                        <td className="px-3 py-2 font-mono text-muted-foreground">
                          {formatFileSize(document.file_size || 0)}
                        </td>
                        <td className="px-3 py-2 text-muted-foreground">
                          {String(document.current_stage || 'Parser')}
                        </td>
                        <td
                          className={cn(
                            'px-3 py-2 font-medium',
                            statusTone
                          )}
                        >
                          {statusLabel}
                        </td>
                        <td className="px-3 py-2">
                          <div className="flex items-center gap-2">
                            <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-muted/60">
                              <div
                                className="h-full rounded-full bg-info"
                                style={{
                                  width: `${progress}%`,
                                }}
                              />
                            </div>
                            <span className="font-mono text-[10px] text-foreground">
                              {progress}%
                            </span>
                          </div>
                        </td>
                        <td className="px-3 py-2 font-mono text-muted-foreground">
                          {elapsedMinutes}
                        </td>
                        <td className="px-3 py-2">
                          <button
                            type="button"
                            className="text-[11px] font-medium text-info transition-colors hover:text-info"
                            onClick={() => onOpenAuditSnapshot(document.id)}
                          >
                            详情
                          </button>
                        </td>
                      </tr>
                    )
                  })
                )}
              </tbody>
            </table>
          </div>
          <div className="mt-2 flex flex-col gap-2 border-t border-foreground/10 pt-2 text-[10px] text-muted-foreground sm:flex-row sm:items-center sm:justify-between">
            <span className="font-mono tabular-nums">
              共 {executionTaskRows.length} 条
            </span>
            <div className="flex items-center justify-end gap-1.5">
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="h-8 rounded-md px-2.5 text-[10px]"
                disabled={executionTaskPage <= 1}
                onClick={onPrevPage}
              >
                <ChevronLeft className="mr-1 h-3 w-3" />
                上一页
              </Button>
              <span className="min-w-[4.5rem] rounded-md border border-foreground/10 bg-background/70 px-2 py-1 text-center font-mono tabular-nums text-foreground">
                第 {executionTaskPage} / {executionTaskPageCount} 页
              </span>
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="h-8 rounded-md px-2.5 text-[10px]"
                disabled={executionTaskPage >= executionTaskPageCount}
                onClick={onNextPage}
              >
                下一页
                <ChevronRight className="ml-1 h-3 w-3" />
              </Button>
            </div>
          </div>
        </section>
      </div>
    </div>
  )
}
