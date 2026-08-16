'use client'

import {
  Download,
  FileCheck2,
  FileSearch,
  Radar,
  UploadCloud,
  Workflow,
  type LucideIcon,
} from 'lucide-react'

import { Button } from '@/components/ui/button'
import { PageTitleIcon } from '@/components/ui/page-title-icon'
import { cn } from '@/lib/utils'
import { IngestionViewSwitch } from '@/app/knowledge/ingestion/view-switch'

type IngestionHeroPanelProps = {
  demoMode: boolean
  headerBodyVisibilityClass: string
  ingestionRecommendationLabel: string
  mode: 'sales-audit' | 'execution-monitor'
  salesAuditComplexity: string
  salesAuditPocSampleLabel: string
  selectedDatasetLabel: string
  showSalesPolicyBadge: boolean
  summaryStripClassName: string
  taskQueueStatusLabel: string
  taskQueueStatusTone: string
  onDownloadReport: () => void
  onExitDemoMode: () => void
  onExportSalesAuditReport: () => void
  onUploadFormalIngest: () => void
  onUploadSampleAssessment: () => void
}

type SummaryStripItem = {
  detail: string
  icon: LucideIcon
  label: string
  tone: string
  value: string
}

export function IngestionHeroPanel({
  demoMode,
  headerBodyVisibilityClass,
  ingestionRecommendationLabel,
  mode,
  onDownloadReport,
  onExitDemoMode,
  onExportSalesAuditReport,
  onUploadFormalIngest,
  onUploadSampleAssessment,
  salesAuditComplexity,
  salesAuditPocSampleLabel,
  selectedDatasetLabel,
  showSalesPolicyBadge,
  summaryStripClassName,
  taskQueueStatusLabel,
  taskQueueStatusTone,
}: Readonly<IngestionHeroPanelProps>) {
  const summaryStripItems: SummaryStripItem[] = [
    {
      label: '范围',
      value: selectedDatasetLabel,
      icon: FileSearch,
      tone: 'text-muted-foreground/65',
      detail: '',
    },
    {
      label: '入库建议',
      value: ingestionRecommendationLabel,
      icon: Workflow,
      tone: 'text-accent',
      detail: '',
    },
    {
      label: '抽样确认量',
      value: salesAuditPocSampleLabel,
      icon: FileCheck2,
      tone: 'text-info',
      detail: '',
    },
    {
      label: '处理复杂度',
      value: salesAuditComplexity,
      icon: Radar,
      tone: 'text-warning',
      detail: '',
    },
  ]

  return (
    <div className={cn('relative px-2.5 md:px-3', mode === 'execution-monitor' ? 'py-3 md:py-3.5' : 'py-0')}>
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-1.5">
            {showSalesPolicyBadge ? (
              <span className="inline-flex items-center rounded-full border border-foreground/10 bg-foreground/[0.04] px-2 py-0.5 text-[7px] font-medium uppercase tracking-[0.16em] text-muted-foreground">
                Sensitive Data Policy
              </span>
            ) : null}
            {demoMode ? (
              <span className="inline-flex items-center rounded-full border border-info/20 bg-info/10 px-2 py-0.5 text-[7px] font-medium uppercase tracking-[0.16em] text-info">
                演示模式
              </span>
            ) : null}
          </div>
          <div
            className={cn(
              'overflow-hidden transition-[max-height,opacity,margin] duration-200 ease-out',
              headerBodyVisibilityClass
            )}
          >
            <div className="flex min-w-0 items-start gap-2">
              <div className="relative flex size-12 shrink-0 items-center justify-center rounded-[22px] border border-info/20 bg-[linear-gradient(180deg,hsl(var(--background)),hsl(var(--info)/0.12))] text-info shadow-[inset_0_1px_0_hsl(var(--background)),0_18px_36px_-24px_hsl(var(--info)/0.9)]">
                <span
                  className="absolute inset-x-2 top-1 h-px bg-card/70"
                  aria-hidden="true"
                />
                <PageTitleIcon name="ingestion-monitor" className="size-9" />
              </div>
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <h1 className="text-[clamp(0.96rem,1.18vw,1.26rem)] font-semibold tracking-[-0.015em] text-foreground">
                    <span className="bg-[linear-gradient(90deg,hsl(var(--foreground)),hsl(var(--info))_92%)] bg-clip-text text-transparent">
                      {mode === 'sales-audit' ? '入库预检工作台' : '执行监控'}
                    </span>
                  </h1>
                  {mode === 'execution-monitor' ? (
                    <span
                      className={cn(
                        'inline-flex items-center rounded-full border px-2 py-0.5 text-[8px] font-medium',
                        taskQueueStatusTone
                      )}
                    >
                      {taskQueueStatusLabel}
                    </span>
                  ) : null}
                </div>
                <p className="mt-1 max-w-[52rem] text-[9px] leading-[1.42] text-muted-foreground">
                  {mode === 'sales-audit'
                    ? '选择目标数据集后先做入库预检，确认目录、策略、重复与风险，再把文件写入知识库；入库完成后可切换执行监控查看队列和失败重试。'
                    : '集中观察处理模式、吞吐、失败重试与运行态列表，快速判断入库链路是否健康。'}
                </p>
              </div>
            </div>
          </div>
        </div>

        <div className="flex flex-wrap items-center justify-end gap-1">
          <IngestionViewSwitch />
          {demoMode ? (
            <Button
              type="button"
              variant="outline"
              className="h-7 rounded-lg px-2 text-[9px]"
              onClick={onExitDemoMode}
            >
              退出演示
            </Button>
          ) : null}
          {mode === 'sales-audit' ? (
            <>
              <Button
                type="button"
                variant="outline"
                className="h-7 rounded-lg px-2 text-[9px]"
                onClick={onUploadSampleAssessment}
              >
                <UploadCloud className="mr-1.5 h-3.5 w-3.5" />
                上传预检文件
              </Button>
              <Button
                type="button"
                className="h-7 rounded-lg px-2 text-[9px]"
                onClick={onUploadFormalIngest}
              >
                <UploadCloud className="mr-1.5 h-3.5 w-3.5" />
                正式入库
              </Button>
              <Button
                type="button"
                variant="outline"
                className="h-7 rounded-lg px-2 text-[9px]"
                onClick={onExportSalesAuditReport}
              >
                <Download className="mr-1.5 h-3.5 w-3.5" />
                入库预检报告
              </Button>
            </>
          ) : (
            <Button
              type="button"
              className="h-7 rounded-lg px-2 text-[9px]"
              onClick={onDownloadReport}
            >
              <Download className="mr-1.5 h-3.5 w-3.5" />
              导出报告
            </Button>
          )}
        </div>
      </div>

      {mode === 'sales-audit' ? (
        <div className={cn('mt-2.5', summaryStripClassName)}>
          <div className="grid gap-px sm:grid-cols-4">
            {summaryStripItems.map(({ detail, icon: Icon, label, tone, value }) => (
              <div
                key={label}
                className="relative min-h-[3.4rem] bg-background/78 px-2.5 py-2"
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="text-[7px] font-medium uppercase tracking-[0.12em] text-muted-foreground">
                    {label}
                  </div>
                  <span className="inline-flex h-4 w-4 items-center justify-center rounded-full border border-border/45 bg-muted/30">
                    <Icon className={cn('h-2.5 w-2.5 shrink-0', tone)} />
                  </span>
                </div>
                <div className="mt-1 font-mono text-[10px] tabular-nums leading-none text-foreground">
                  {value}
                </div>
                {detail ? (
                  <div className="mt-1 text-[7px] text-muted-foreground">
                    {detail}
                  </div>
                ) : null}
              </div>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  )
}
