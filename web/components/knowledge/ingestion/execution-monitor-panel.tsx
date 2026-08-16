'use client'

import type { EChartsOption } from 'echarts'
import {
  Activity,
  ChevronLeft,
  ChevronRight,
  FileSearch,
  Radar,
  Workflow,
  type LucideIcon,
} from 'lucide-react'

import { Button } from '@/components/ui/button'
import { EChart } from '@/components/ui/echart'
import { SalesPanelHeader } from '@/app/knowledge/ingestion/components/sales-panel-header'
import { cn, formatFileSize } from '@/lib/utils'
import {
  SALES_PANEL_CLASS,
  SALES_PANEL_INSET_CLASS,
  getDocumentStatusLabel,
  getDocumentStatusTone,
  getTaskProgress,
} from '@/app/knowledge/ingestion/presentation'
import { formatDurationClock } from '@/app/knowledge/ingestion/document-signals'
import type { Document } from '@/types'

type ExecutionRunStateCard = {
  label: string
  value: string
  suffix: string
  icon: LucideIcon
  tone: string
  detail: string
}

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

type ExecutionMonitorPanelProps = {
  batchProfileBarOption: EChartsOption
  executionBatchAnalysis: ExecutionBatchAnalysis
  executionDocuments: Document[]
  executionKpiCards: ExecutionKpiCard[]
  executionProcessedTotal: number
  executionRecentLogs: ExecutionRecentLog[]
  executionRunStateCards: ExecutionRunStateCard[]
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

export function ExecutionMonitorPanel({
  batchProfileBarOption,
  executionBatchAnalysis,
  executionDocuments,
  executionKpiCards,
  executionProcessedTotal,
  executionRecentLogs,
  executionRunStateCards,
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
  return (
    <div
      title="入库预检报告"
      className={cn(
        'relative overflow-hidden rounded-[1.45rem] border border-border/60 bg-background/86 p-3 shadow-[0_28px_72px_-46px_rgba(15,23,42,0.32)] md:p-3.5'
      )}
    >
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 opacity-70"
        style={{
          background:
            'radial-gradient(circle at 36% 24%, rgba(255,255,255,0.48), transparent 28%)',
        }}
      />
      <div className="relative z-10 space-y-3">
        <div className="grid gap-2 xl:grid-cols-[0.72fr_1.28fr]">
          <section className="rounded-[1.05rem] border border-border/55 bg-background/90 p-2.5 shadow-[0_16px_36px_-30px_rgba(15,23,42,0.18)]">
            <div className="flex items-center justify-between gap-3">
              <div className="flex items-center gap-2">
                <span className="inline-flex size-6 items-center justify-center rounded-full border border-info/18 bg-info/8 text-info">
                  <Activity className="size-3.5" />
                </span>
                <div>
                  <div className="text-[10px] font-semibold text-foreground">
                    文件类型分布
                  </div>
                  <div className="mt-0.5 text-[8px] text-muted-foreground">
                    按文件格式统计
                  </div>
                </div>
              </div>
              <span className="rounded-full border border-border/45 bg-muted/20 px-2 py-0.5 font-mono text-[9px] text-foreground">
                {executionDocuments.length} 个
              </span>
            </div>
            <div className="mt-2 grid grid-cols-[6.6rem_minmax(0,1fr)] items-center gap-2">
              <div className="relative h-[6.35rem]">
                <EChart option={batchProfileBarOption} />
                <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
                  <div className="font-mono text-[15px] font-semibold text-foreground tabular-nums">
                    {executionDocuments.length}
                  </div>
                  <div className="text-[7px] text-muted-foreground">
                    文件
                  </div>
                </div>
              </div>
              <div className="rounded-[0.78rem] border border-dashed border-border/55 bg-muted/10 px-2 py-4 text-center text-[9px] text-muted-foreground">
                文件分布图已抽离，数据仍由页面查询编排。
              </div>
            </div>
          </section>

          <section className="rounded-[1.05rem] border border-border/55 bg-background/90 p-2.5 shadow-[0_16px_36px_-30px_rgba(15,23,42,0.18)]">
            <div className="flex items-center justify-between gap-3">
              <div className="flex min-w-0 items-center gap-2">
                <div className="text-[10px] font-semibold text-foreground">
                  处理流水线
                </div>
                <span className="rounded-full border border-info/20 bg-info/10 px-2 py-0.5 text-[8px] font-medium text-info">
                  自动估算
                </span>
              </div>
              <div className="text-[8px] text-muted-foreground">
                已处理{' '}
                <span className="font-mono text-foreground tabular-nums">
                  {executionProcessedTotal}
                </span>{' '}
                / {executionDocuments.length}
              </div>
            </div>
            <div className="mt-2 grid gap-1.5 sm:grid-cols-2 xl:grid-cols-4">
              {executionRunStateCards.map((card) => {
                const Icon = card.icon
                return (
                  <div
                    key={card.label}
                    className="rounded-[0.82rem] border border-border/45 bg-background/82 px-2 py-1.5"
                  >
                    <div className="flex items-center justify-between gap-1.5">
                      <div className="text-[10px] font-medium text-foreground">
                        {card.label}
                      </div>
                      <Icon className={cn('size-3.5 shrink-0', card.tone)} />
                    </div>
                    <div className="mt-1 font-mono text-[12px] font-semibold text-foreground tabular-nums">
                      {card.value}
                    </div>
                    <div className="mt-1 truncate text-[7.5px] text-muted-foreground">
                      {card.detail}
                    </div>
                  </div>
                )
              })}
            </div>
          </section>
        </div>

        <section className="overflow-hidden rounded-[1.05rem] border border-border/55 bg-card/92 p-2.5 shadow-sm">
          <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
            <div className="flex items-center gap-2">
              <span className="inline-flex size-6 items-center justify-center rounded-full border border-info/20 bg-info/10 text-info">
                <Activity className="size-3.5" />
              </span>
              <div>
                <div className="text-[10px] font-semibold text-foreground">
                  运行信息汇聚
                </div>
                <div className="mt-0.5 text-[8px] text-muted-foreground text-pretty">
                  范围、模式、吞吐与质量读数
                </div>
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-1.5 text-[8px] text-muted-foreground">
              <span className="rounded-full border border-border/55 bg-background/80 px-2 py-0.5 tabular-nums">
                已处理 {executionProcessedTotal} / {executionDocuments.length}
              </span>
              <span className="rounded-full border border-success/20 bg-success/10 px-2 py-0.5 text-success tabular-nums">
                成功率 {executionSuccessRate}%
              </span>
            </div>
          </div>

          <div className="mt-2 grid gap-1.5 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-7">
            {executionKpiCards.map((item) => {
              const Icon = item.icon
              return (
                <div
                  key={item.label}
                  className="rounded-[0.82rem] border border-border/45 bg-background/82 px-2 py-1.5"
                >
                  <div className="flex items-center justify-between gap-1.5">
                    <div className="min-w-0">
                      <div className="truncate text-[8px] text-muted-foreground">
                        {item.label}
                      </div>
                      <div className="mt-0.5 flex items-baseline gap-1">
                        <span className="truncate font-mono text-[12px] font-semibold text-foreground tabular-nums">
                          {item.value}
                        </span>
                        {item.suffix ? (
                          <span className="text-[7.5px] text-muted-foreground">
                            {item.suffix}
                          </span>
                        ) : null}
                      </div>
                    </div>
                    <Icon className={cn('size-3.5 shrink-0', item.tone)} />
                  </div>
                  <div className="mt-1 truncate text-[7.5px] text-muted-foreground">
                    {item.detail}
                  </div>
                </div>
              )
            })}
          </div>
        </section>

        <section className="rounded-[1.3rem] border border-border/55 bg-background/92 p-3 shadow-sm">
          <div className="flex flex-col gap-2 md:flex-row md:items-start md:justify-between">
            <div className="flex items-center gap-2">
              <span className="inline-flex size-7 items-center justify-center rounded-full border border-info/20 bg-info/10 text-info">
                <FileSearch className="size-3.5" />
              </span>
              <div>
                <div className="text-[11px] font-semibold text-foreground">
                  批次数据画像
                </div>
                <div className="mt-0.5 text-[9px] text-muted-foreground text-pretty">
                  按 3/1000 抽代表样本，已出现的文件类型每类至少覆盖 1 个
                </div>
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-1.5 text-[9px]">
              <span className="rounded-full border border-border/55 bg-muted/25 px-2 py-1 text-muted-foreground">
                {executionBatchAnalysis.sourceLabel}
              </span>
              <span className="rounded-full border border-info/20 bg-info/10 px-2 py-1 font-medium text-info">
                难度 {executionBatchAnalysis.complexity}
              </span>
              <span className="rounded-full border border-warning/20 bg-warning/10 px-2 py-1 font-medium text-warning">
                {executionBatchAnalysis.pricingMode}
              </span>
            </div>
          </div>
          <div className="mt-3 grid gap-3 xl:grid-cols-[1fr_210px]">
            <div className="h-[15rem] rounded-[1rem] border border-border/45 bg-card/86 p-2">
              <EChart option={batchProfileBarOption} />
            </div>
            <div className="grid gap-2">
              <div className="rounded-[1rem] border border-border/45 bg-muted/18 px-3 py-2.5">
                <div className="text-[8px] text-muted-foreground">
                  预检样本
                </div>
                <div className="mt-1 text-[18px] font-semibold text-foreground tabular-nums">
                  {executionBatchAnalysis.sampleTarget || '--'} 个
                </div>
                <div className="mt-1 text-[8px] text-muted-foreground">
                  {executionBatchAnalysis.sampleTargetDetail}
                </div>
              </div>
              <div className="rounded-[1rem] border border-border/45 bg-muted/18 px-3 py-2.5">
                <div className="text-[8px] text-muted-foreground">
                  批次体量
                </div>
                <div className="mt-1 font-mono text-[13px] font-semibold text-foreground tabular-nums">
                  {executionBatchAnalysis.totalSizeLabel}
                </div>
                <div className="mt-1 text-[8px] text-muted-foreground">
                  {executionBatchAnalysis.samplePoolLabel}
                </div>
              </div>
              <div className="rounded-[1rem] border border-border/45 bg-muted/18 px-3 py-2.5 text-[8px] leading-3.5 text-muted-foreground text-pretty">
                {executionBatchAnalysis.imageProxyNote}
              </div>
            </div>
          </div>
        </section>

        <div className="grid gap-4 xl:grid-cols-2 2xl:grid-cols-[1.1fr_0.9fr_0.9fr]">
          <section className="rounded-[1.2rem] border border-border/60 bg-background/90 p-3 shadow-[0_18px_42px_-32px_rgba(15,23,42,0.16)]">
            <div className="flex items-center justify-between gap-3">
              <div className="text-[11px] font-medium text-foreground">
                处理吞吐趋势
              </div>
            </div>
            <div className="mt-3 h-[12rem]">
              <EChart option={predictionOption} />
            </div>
          </section>

          <section className="rounded-[1.2rem] border border-border/60 bg-background/90 p-3 shadow-[0_18px_42px_-32px_rgba(15,23,42,0.16)]">
            <div className="flex items-center justify-between gap-3">
              <div className="text-[11px] font-medium text-foreground">
                成本雷达
              </div>
              <Radar className="h-4 w-4 text-accent" />
            </div>
            <div className="mt-3 h-[13rem]">
              <EChart option={radarOption} />
            </div>
          </section>

          <section className="rounded-[1.2rem] border border-border/60 bg-background/90 p-3 shadow-[0_18px_42px_-32px_rgba(15,23,42,0.16)] xl:col-span-2 2xl:col-span-1">
            <div className="flex items-center justify-between gap-3">
              <div className="text-[11px] font-medium text-foreground">
                运行日志（最近）
              </div>
              <span className="text-[9px] text-muted-foreground">
                {recentQueueOutcomesCount ? '来自任务队列' : '来自文档状态'}
              </span>
            </div>
            <div className="mt-3 space-y-2">
              {executionRecentLogs.map((log) => (
                <div
                  key={log.id}
                  className="flex items-start gap-2.5 rounded-[0.9rem] border border-border/50 bg-background/78 px-2.5 py-2"
                >
                  <span
                    className={cn(
                      'mt-1 h-2.5 w-2.5 shrink-0 rounded-full',
                      log.tone
                    )}
                  />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2 text-[9px] text-muted-foreground">
                      <span className="font-mono">{log.time}</span>
                      <span>{log.stage}</span>
                    </div>
                    <div className="mt-0.5 truncate text-[10px] text-foreground">
                      {log.detail}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </section>
        </div>

        <section className="rounded-[1.2rem] border border-border/60 bg-background/90 p-3 shadow-[0_18px_42px_-32px_rgba(15,23,42,0.16)]">
          <div className="flex items-center justify-between gap-3">
            <div className="text-[11px] font-medium text-foreground">
              任务列表
            </div>
            <div className="text-[9px] text-muted-foreground">
              {executionTaskRows.length} 个任务
            </div>
          </div>
          <div className="mt-3 overflow-hidden rounded-[1rem] border border-border/50">
            <table className="w-full text-left text-[9px]">
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
                  <tr className="border-t border-border/40">
                    <td colSpan={8} className="px-3 py-8">
                      <div className="mx-auto flex max-w-xl flex-col items-center rounded-[1rem] border border-dashed border-border/65 bg-background/74 px-4 py-5 text-center">
                        <div className="text-[11px] font-semibold text-foreground">
                          当前范围暂无执行任务
                        </div>
                        <div className="mt-1 max-w-md text-[9px] leading-4 text-muted-foreground">
                          这个监控范围可以直接打开，但当前知识库还没有解析任务。可以切到入库操作提交解析，或查看全部项目的运行态。
                        </div>
                        <div className="mt-3 flex flex-wrap justify-center gap-2">
                          <Button
                            type="button"
                            size="sm"
                            className="h-7 rounded-lg px-2 text-[9px]"
                            onClick={onOpenIngestionOperation}
                          >
                            去入库操作
                          </Button>
                          {selectedDatasetId ? (
                            <Button
                              type="button"
                              variant="outline"
                              size="sm"
                              className="h-7 rounded-lg px-2 text-[9px]"
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
                      <tr key={document.id} className="border-t border-border/40">
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
                            <span className="font-mono text-[8px] text-foreground">
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
                            className="text-[9px] font-medium text-info transition-colors hover:text-info"
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
          <div className="mt-2.5 flex flex-col gap-2 border-t border-border/45 pt-2.5 text-[9px] text-muted-foreground sm:flex-row sm:items-center sm:justify-between">
            <span className="font-mono tabular-nums">
              共 {executionTaskRows.length} 条
            </span>
            <div className="flex items-center justify-end gap-1.5">
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="h-7 rounded-lg px-2 text-[9px]"
                disabled={executionTaskPage <= 1}
                onClick={onPrevPage}
              >
                <ChevronLeft className="mr-1 h-3 w-3" />
                上一页
              </Button>
              <span className="min-w-[4.5rem] rounded-lg border border-border/50 bg-background/70 px-2 py-1 text-center font-mono tabular-nums text-foreground">
                第 {executionTaskPage} / {executionTaskPageCount} 页
              </span>
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="h-7 rounded-lg px-2 text-[9px]"
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
