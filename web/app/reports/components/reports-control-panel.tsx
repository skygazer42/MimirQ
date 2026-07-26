'use client'

import {
  Archive,
  BarChart3,
  ChevronDown,
  Download,
  FileText,
  Loader2,
  PlayCircle,
  RefreshCw,
  ShieldCheck,
  type LucideIcon,
} from 'lucide-react'

import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'

import type { DatasetReport } from '@/types'

import { shortPipelineHash } from '../report-format'
import {
  DEFAULT_PIPELINE_VERSION_VALUE,
  REPORT_FILTER_LABEL_CLASS,
  REPORT_PRIMARY_ACTION_CLASS,
  REPORT_SECONDARY_ACTION_CLASS,
  REPORT_SELECT_ITEM_CLASS,
  REPORT_SELECT_TRIGGER_CLASS,
} from '../report-tokens'

import type { DatasetOption, PipelineVersionOption } from '../types'

export function LoadingButtonIcon({
  loading,
  icon: Icon,
}: Readonly<{ loading: boolean; icon: LucideIcon }>) {
  if (loading) {
    return <Loader2 className="size-3.5 animate-spin motion-reduce:animate-none" />
  }
  return <Icon className="size-3.5" />
}

export function ReportsControlPanel({
  datasetId,
  datasets,
  isLoadingDatasets,
  pipelineVersionSelectValue,
  pipelineVersionOptions,
  connectorRunsLimit,
  showOnlyIssues,
  redact,
  isExportingJson,
  isExportingHtml,
  isExportingRagAuditHtml,
  isExportingBundle,
  report,
  isLoadingReport,
  onDatasetChange,
  onPipelineHashChange,
  onConnectorRunsLimitChange,
  onShowOnlyIssuesChange,
  onRedactChange,
  onExportJson,
  onExportCompleteJson,
  onExportChartsJson,
  onExportRagAuditHtml,
  onExportBundleZip,
  onExportHtml,
  onRegenerateReport,
  onRefresh,
}: Readonly<{
  datasetId: string
  datasets: DatasetOption[]
  isLoadingDatasets: boolean
  pipelineVersionSelectValue: string
  pipelineVersionOptions: PipelineVersionOption[]
  connectorRunsLimit: number
  showOnlyIssues: boolean
  redact: boolean
  isExportingJson: boolean
  isExportingHtml: boolean
  isExportingRagAuditHtml: boolean
  isExportingBundle: boolean
  report: DatasetReport | null
  isLoadingReport: boolean
  onDatasetChange: (value: string) => void
  onPipelineHashChange: (value: string) => void
  onConnectorRunsLimitChange: (value: number) => void
  onShowOnlyIssuesChange: (value: boolean) => void
  onRedactChange: (value: boolean) => void
  onExportJson: () => void
  onExportCompleteJson: () => void
  onExportChartsJson: () => void
  onExportRagAuditHtml: () => void
  onExportBundleZip: () => void
  onExportHtml: () => void
  onRegenerateReport: () => void
  onRefresh: () => void
}>) {
  return (
    <section className="space-y-3 rounded-[1.2rem] border border-border/60 bg-card/88 p-3.5 shadow-[0_18px_44px_-36px_rgba(15,23,42,0.35)] backdrop-blur">
      <div className="grid gap-3 xl:grid-cols-[1.25fr_1.1fr_0.85fr_auto] xl:items-end">
        <div className="space-y-1.5">
          <Label
            htmlFor="dataset-select"
            className={REPORT_FILTER_LABEL_CLASS}
          >
            数据集
          </Label>
          <Select value={datasetId} onValueChange={onDatasetChange}>
            <SelectTrigger
              id="dataset-select"
              className={REPORT_SELECT_TRIGGER_CLASS}
            >
              <SelectValue
                placeholder={isLoadingDatasets ? '加载中...' : '请选择数据集'}
              />
            </SelectTrigger>
            <SelectContent>
              {datasets.map((ds) => (
                <SelectItem
                  key={ds.id}
                  value={ds.id}
                  className={REPORT_SELECT_ITEM_CLASS}
                >
                  {ds.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div className="space-y-1.5">
          <Label
            htmlFor="pipeline-hash"
            className={REPORT_FILTER_LABEL_CLASS}
          >
            处理版本
          </Label>
          <Select
            value={pipelineVersionSelectValue}
            onValueChange={onPipelineHashChange}
          >
            <SelectTrigger
              id="pipeline-hash"
              className={REPORT_SELECT_TRIGGER_CLASS}
            >
              <SelectValue placeholder="选择处理版本" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem
                value={DEFAULT_PIPELINE_VERSION_VALUE}
                className={REPORT_SELECT_ITEM_CLASS}
              >
                当前版本（默认）
              </SelectItem>
              {pipelineVersionOptions.map((v) => (
                <SelectItem
                  key={v.pipeline_hash}
                  value={v.pipeline_hash}
                  className={REPORT_SELECT_ITEM_CLASS}
                >
                  {shortPipelineHash(v.pipeline_hash)} · {v.documents} 个文档
                </SelectItem>
              ))}
              {pipelineVersionOptions.length === 0 ? (
                <SelectItem
                  value="__mimirq_no_pipeline_versions__"
                  disabled
                  className={REPORT_SELECT_ITEM_CLASS}
                >
                  暂无可选历史版本
                </SelectItem>
              ) : null}
            </SelectContent>
          </Select>
        </div>

        <div className="space-y-1.5">
          <Label
            htmlFor="connector-limit"
            className={REPORT_FILTER_LABEL_CLASS}
          >
            运行记录
          </Label>
          <Select
            value={String(connectorRunsLimit)}
            onValueChange={(value) => onConnectorRunsLimitChange(Number(value || 20))}
          >
            <SelectTrigger
              id="connector-limit"
              className={REPORT_SELECT_TRIGGER_CLASS}
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="0" className={REPORT_SELECT_ITEM_CLASS}>
                不附带记录
              </SelectItem>
              <SelectItem value="10" className={REPORT_SELECT_ITEM_CLASS}>
                10 条记录
              </SelectItem>
              <SelectItem value="20" className={REPORT_SELECT_ITEM_CLASS}>
                20 条记录（默认）
              </SelectItem>
              <SelectItem value="50" className={REPORT_SELECT_ITEM_CLASS}>
                50 条记录
              </SelectItem>
              <SelectItem value="100" className={REPORT_SELECT_ITEM_CLASS}>
                100 条记录
              </SelectItem>
            </SelectContent>
          </Select>
        </div>

        <div className="flex h-9 items-center gap-2 rounded-xl border border-border/60 bg-muted/40 px-3">
          <Switch
            id="only-issues-switch"
            checked={showOnlyIssues}
            onCheckedChange={onShowOnlyIssuesChange}
          />
          <Label
            htmlFor="only-issues-switch"
            className="whitespace-nowrap text-xs font-medium text-muted-foreground"
          >
            只看异常
          </Label>
        </div>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border/60 pt-3">
        <div className="flex h-9 items-center gap-2 rounded-xl bg-muted/45 px-3 ring-1 ring-inset ring-border/60">
          <Switch
            id="redact-switch"
            checked={redact}
            onCheckedChange={onRedactChange}
          />
          <Label
            htmlFor="redact-switch"
            className="text-xs font-medium text-muted-foreground"
          >
            导出脱敏
          </Label>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                variant="outline"
                className={REPORT_SECONDARY_ACTION_CLASS}
                disabled={!datasetId}
                aria-label="打开报告导出菜单"
              >
                <LoadingButtonIcon
                  loading={
                    isExportingJson ||
                    isExportingHtml ||
                    isExportingRagAuditHtml ||
                    isExportingBundle
                  }
                  icon={Download}
                />
                <span>导出报告</span>
                <ChevronDown className="size-3.5 text-muted-foreground/70" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent
              align="end"
              className="w-64 rounded-2xl border-border/60 bg-popover/95 p-1.5 shadow-[0_24px_70px_-28px_rgba(15,23,42,0.38)] backdrop-blur-xl"
            >
              <DropdownMenuLabel className="px-2.5 pb-1 pt-2 text-[11px] font-semibold tracking-[0.08em] text-muted-foreground/70">
                基础与完整数据
              </DropdownMenuLabel>
              <DropdownMenuGroup>
                <DropdownMenuItem
                  onSelect={onExportJson}
                  disabled={!datasetId || isExportingJson}
                  className="rounded-xl px-2.5 py-2 text-xs focus:bg-info/10 focus:text-info"
                  aria-label="导出 JSON"
                >
                  <LoadingButtonIcon loading={isExportingJson} icon={Download} />
                  <span>标准 JSON 报告</span>
                </DropdownMenuItem>
                <DropdownMenuItem
                  onSelect={onExportCompleteJson}
                  disabled={!datasetId || !report}
                  className="rounded-xl px-2.5 py-2 text-xs focus:bg-info/10 focus:text-info"
                  aria-label="导出完整 JSON"
                >
                  <Archive className="size-3.5" />
                  <span>完整 JSON 快照</span>
                </DropdownMenuItem>
                <DropdownMenuItem
                  onSelect={onExportChartsJson}
                  disabled={!datasetId || !report}
                  className="rounded-xl px-2.5 py-2 text-xs focus:bg-info/10 focus:text-info"
                  aria-label="导出 RAG 统计"
                >
                  <BarChart3 className="size-3.5" />
                  <span>RAG 统计数据</span>
                </DropdownMenuItem>
              </DropdownMenuGroup>
              <DropdownMenuSeparator className="my-1.5" />
              <DropdownMenuLabel className="px-2.5 pb-1 pt-1 text-[11px] font-semibold tracking-[0.08em] text-muted-foreground/70">
                审计与交付物
              </DropdownMenuLabel>
              <DropdownMenuGroup>
                <DropdownMenuItem
                  onSelect={onExportRagAuditHtml}
                  disabled={!datasetId || isExportingRagAuditHtml}
                  className="rounded-xl px-2.5 py-2 text-xs focus:bg-info/10 focus:text-info"
                  aria-label="导出 RAG 审计报告"
                >
                  <LoadingButtonIcon
                    loading={isExportingRagAuditHtml}
                    icon={ShieldCheck}
                  />
                  <span>RAG 审计报告</span>
                </DropdownMenuItem>
                <DropdownMenuItem
                  onSelect={onExportBundleZip}
                  disabled={!datasetId || isExportingBundle}
                  className="rounded-xl px-2.5 py-2 text-xs focus:bg-info/10 focus:text-info"
                  aria-label="导出数据包 ZIP"
                >
                  <LoadingButtonIcon loading={isExportingBundle} icon={Archive} />
                  <span>数据包 Bundle ZIP</span>
                </DropdownMenuItem>
                <DropdownMenuItem
                  onSelect={onExportHtml}
                  disabled={!datasetId || isExportingHtml}
                  className="rounded-xl px-2.5 py-2 text-xs focus:bg-info/10 focus:text-info"
                  aria-label="导出 HTML"
                >
                  <LoadingButtonIcon loading={isExportingHtml} icon={FileText} />
                  <span>HTML 阅读版</span>
                </DropdownMenuItem>
              </DropdownMenuGroup>
            </DropdownMenuContent>
          </DropdownMenu>
          <Button
            className={REPORT_PRIMARY_ACTION_CLASS}
            onClick={onRegenerateReport}
            disabled={!datasetId || isLoadingReport}
            aria-label="重新生成报告"
          >
            <LoadingButtonIcon loading={isLoadingReport} icon={PlayCircle} />
            <span>重新生成</span>
          </Button>
          <Button
            variant="outline"
            className={REPORT_SECONDARY_ACTION_CLASS}
            onClick={onRefresh}
            disabled={isLoadingDatasets}
            aria-label="刷新"
          >
            <LoadingButtonIcon loading={isLoadingDatasets} icon={RefreshCw} />
            <span>刷新</span>
          </Button>
        </div>
      </div>
    </section>
  )
}
