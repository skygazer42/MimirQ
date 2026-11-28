'use client'

import { Archive, BarChart3, ChevronDown, Clock3, Download, FileText, RefreshCw, ShieldCheck } from '@/components/icons'
import { LoadingButton } from '@/components/ui/loading-button'
import { PageTitleIcon } from '@/components/ui/page-title-icon'
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import type { DatasetReport } from '@/lib/report-schema'
import { formatDate } from '@/lib/utils'
import { DEFAULT_PIPELINE_VERSION_VALUE } from '../report-tokens'
import { formatReportText, reportDataSourceLabel, shortPipelineHash } from '../report-format'
import type { DatasetOption, PipelineVersionOption } from '../types'
import type { ReportExportKind } from '../use-report-exports'
import styles from '../reports.module.css'

const CONNECTOR_RUN_LIMITS = [0, 10, 20, 50, 100] as const

export function ReportsControlPanel(
  props: Readonly<{
    datasetId: string
    datasets: readonly DatasetOption[] | undefined
    isFetchingDatasets: boolean
    pipelineVersionSelectValue: string
    pipelineVersionOptions: PipelineVersionOption[]
    connectorRunsLimit: number
    redact: boolean
    exporting: ReportExportKind | null
    report: DatasetReport | undefined
    isFetchingReport: boolean
    refreshing: boolean
    showingPrevious: boolean
    onDatasetChange: (value: string) => void
    onPipelineHashChange: (value: string) => void
    onConnectorRunsLimitChange: (value: number) => void
    onRedactChange: (value: boolean) => void
    onExport: (kind: ReportExportKind) => Promise<void>
    onExportCompleteJson: () => void
    onExportChartsJson: () => void
    onRefresh: () => void
  }>,
) {
  const isExporting = props.exporting !== null
  const hasReportDocuments = props.report !== undefined && props.report.profile.total_documents > 0
  const isExportDisabled =
    props.datasetId.length === 0 ||
    !hasReportDocuments ||
    props.showingPrevious ||
    props.isFetchingReport ||
    isExporting
  const selectedDataset = props.datasets?.find((dataset) => dataset.id === props.datasetId)
  const isKnownPipelineVersion = props.pipelineVersionOptions.some(
    (version) => version.pipeline_hash === props.pipelineVersionSelectValue,
  )
  const versionLabel =
    props.pipelineVersionSelectValue === DEFAULT_PIPELINE_VERSION_VALUE
      ? '全部处理版本'
      : shortPipelineHash(props.pipelineVersionSelectValue)
  let reportTimeLabel = '等待报告'
  if (props.isFetchingReport) {
    reportTimeLabel = '正在更新…'
  } else if (props.report !== undefined) {
    reportTimeLabel = `生成于 ${formatDate(props.report.generated_at)}`
  }
  return (
    <>
      <header className={styles.header}>
        <div className={styles.heading}>
          <PageTitleIcon name="report-export" />
          <h1>数据报告</h1>
        </div>
        <div className={styles.headerActions}>
          <LoadingButton variant="ghost" onClick={props.onRefresh} loading={props.refreshing} aria-label="刷新报告">
            <RefreshCw />
            <span className={styles.actionLabel}>刷新报告</span>
          </LoadingButton>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <LoadingButton
                variant={hasReportDocuments ? 'default' : 'outline'}
                className={hasReportDocuments ? styles.primary : undefined}
                loading={isExporting}
                disabled={isExportDisabled}
                aria-label="导出报告"
              >
                <Download />
                <span className={styles.actionLabel}>导出报告</span>
                <ChevronDown />
              </LoadingButton>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className={styles.exportMenu}>
              <DropdownMenuLabel>阅读与审计</DropdownMenuLabel>
              <DropdownMenuItem
                disabled={isExportDisabled}
                onSelect={() => {
                  void props.onExport('html')
                }}
                aria-label="导出 HTML"
              >
                <FileText className={styles.exportIcon} data-format="html" />
                HTML 阅读版
              </DropdownMenuItem>
              <DropdownMenuItem
                disabled={isExportDisabled}
                onSelect={() => {
                  void props.onExport('ragAudit')
                }}
                aria-label="导出 RAG 审计报告"
              >
                <ShieldCheck className={styles.exportIcon} data-format="audit" />
                RAG 审计报告
              </DropdownMenuItem>
              <DropdownMenuItem
                disabled={isExportDisabled}
                onSelect={() => {
                  void props.onExport('bundle')
                }}
                aria-label="导出数据包 ZIP"
              >
                <Archive className={styles.exportIcon} data-format="zip" />
                Bundle ZIP 归档
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuCheckboxItem
                checked={props.redact}
                onCheckedChange={props.onRedactChange}
                onSelect={(event) => event.preventDefault()}
                aria-label="HTML／ZIP 脱敏"
              >
                HTML／ZIP 脱敏
              </DropdownMenuCheckboxItem>
              <DropdownMenuSeparator />
              <DropdownMenuLabel>原始数据</DropdownMenuLabel>
              <DropdownMenuItem
                disabled={isExportDisabled}
                onSelect={() => {
                  void props.onExport('json')
                }}
                aria-label="导出 JSON"
              >
                <Download className={styles.exportIcon} data-format="json" />
                标准 JSON 报告
              </DropdownMenuItem>
              <DropdownMenuItem
                disabled={isExportDisabled}
                onSelect={props.onExportCompleteJson}
                aria-label="导出完整 JSON"
              >
                <Archive className={styles.exportIcon} data-format="json" />
                完整 JSON 快照
              </DropdownMenuItem>
              <DropdownMenuItem
                disabled={isExportDisabled}
                onSelect={props.onExportChartsJson}
                aria-label="导出 RAG 统计"
              >
                <BarChart3 className={styles.exportIcon} data-format="chart" />
                RAG 统计数据
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </header>
      <div className={styles.scopeBar}>
        <label>
          <span>数据集</span>
          <Select
            value={props.datasetId}
            onValueChange={props.onDatasetChange}
            disabled={props.isFetchingDatasets && props.datasets === undefined}
          >
            <SelectTrigger
              aria-label="数据集"
              className={styles.datasetSelect}
              title={selectedDataset === undefined ? props.datasetId : `${selectedDataset.name} · ${props.datasetId}`}
            >
              <SelectValue placeholder={props.isFetchingDatasets ? '加载中…' : '选择数据集'}>
                <span>
                  {selectedDataset === undefined
                    ? `当前选择 · ${props.datasetId}`
                    : formatReportText(selectedDataset.name).replace(/\s+\[[\da-f]{8}\]$/i, '')}
                </span>
              </SelectValue>
            </SelectTrigger>
            <SelectContent>
              {props.datasetId.length > 0 && selectedDataset === undefined ? (
                <SelectItem value={props.datasetId}>当前选择 · {props.datasetId}</SelectItem>
              ) : null}
              {props.datasets?.map((dataset) => (
                <SelectItem key={dataset.id} value={dataset.id}>
                  {formatReportText(dataset.name)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </label>
        <label>
          <span>处理版本</span>
          <Select
            value={props.pipelineVersionSelectValue}
            onValueChange={props.onPipelineHashChange}
            disabled={props.datasetId.length === 0}
          >
            <SelectTrigger aria-label="处理版本" className={styles.versionSelect}>
              <SelectValue>{versionLabel}</SelectValue>
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={DEFAULT_PIPELINE_VERSION_VALUE}>全部处理版本</SelectItem>
              {!isKnownPipelineVersion && props.pipelineVersionSelectValue !== DEFAULT_PIPELINE_VERSION_VALUE && (
                <SelectItem value={props.pipelineVersionSelectValue}>{versionLabel}</SelectItem>
              )}
              {props.pipelineVersionOptions.map((version) => (
                <SelectItem key={version.pipeline_hash} value={version.pipeline_hash}>
                  {shortPipelineHash(version.pipeline_hash)} · {version.documents} 个文档
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </label>
        <label>
          <span>附带运行</span>
          <Select
            value={String(props.connectorRunsLimit)}
            onValueChange={(value) => {
              const limit = CONNECTOR_RUN_LIMITS.find((option) => String(option) === value)
              if (limit !== undefined) props.onConnectorRunsLimitChange(limit)
            }}
            disabled={props.datasetId.length === 0}
          >
            <SelectTrigger aria-label="附带运行记录" className={styles.runSelect}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {CONNECTOR_RUN_LIMITS.map((value) => (
                <SelectItem key={value} value={String(value)}>
                  {value === 0 ? '不附带记录' : `${value} 条记录`}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </label>
        <Popover>
          <PopoverTrigger asChild>
            <button className={styles.reportTime} type="button" aria-label="查看报告信息">
              <Clock3 />
              <span>{reportTimeLabel}</span>
            </button>
          </PopoverTrigger>
          <PopoverContent align="end" className={styles.reportInfo}>
            <h2>报告信息</h2>
            <dl>
              <dt>数据来源</dt>
              <dd>{props.report === undefined ? '未取得' : reportDataSourceLabel(props.report.data_provenance)}</dd>
              <dt>生成时间</dt>
              <dd>{props.report === undefined ? '未取得' : formatDate(props.report.generated_at)}</dd>
              <dt>数据集标识</dt>
              <dd>{props.report === undefined ? '未取得' : props.report.dataset_id}</dd>
            </dl>
          </PopoverContent>
        </Popover>
      </div>
    </>
  )
}
