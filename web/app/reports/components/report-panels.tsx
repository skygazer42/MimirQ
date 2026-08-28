'use client'

import {
  AlertTriangle,
  Archive,
  BarChart3,
  CheckCircle2,
  Clock3,
  FileSearch,
  FileText,
  Layers,
  ShieldCheck,
} from 'lucide-react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Pie,
  PieChart,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { SafeResponsiveChart } from '@/components/ui/safe-responsive-chart'
import { cn, formatFileSize } from '@/lib/utils'

import type { DatasetReportPipelineVersion } from '@/types'

import {
  formatPct,
  issueLevelClass,
  pipelineVersionLabel,
  retrievalAuditFailureText,
  retrievalAuditHashText,
  retrievalAuditKgRecommendationText,
  retrievalAuditMetricRows,
  retrievalAuditStatusLabel,
  retrievalAuditTone,
  safeNumber,
} from '../report-format'
import {
  CHART_TOOLTIP_CURSOR,
  CHART_TOOLTIP_LABEL_STYLE,
  CHART_TOOLTIP_STYLE,
  PIE_COLORS,
  REPORT_METRIC_LEDGER_CLASS,
  REPORT_PANEL_CLASS,
  REPORT_PANEL_TITLE_CLASS,
  REPORT_SUBTEXT_CLASS,
  REPORT_TABLE_HEADER_CLASS,
  REPORT_TABLE_ROW_CLASS,
} from '../report-tokens'
import {
  AuditMetricCard,
  AuditMetricPlaceholder,
  CompactAuditFact,
  ProgressRow,
  ReportInlineEmpty,
  ReportSignalRow,
} from './report-atoms'

import type {
  CategoryMetricDatum,
  CoverageRow,
  IssueRow,
  PipelineVersionDatum,
  ReportMetricDatum,
  RetrievalAudit,
} from '../types'

export function ReportMetricGrid({
  totalDocs,
  totalBytes,
  successDocs,
  successRate,
  failed,
  failedRate,
  pipelineVersionsCount,
  pipelineFilterLabel,
  latestAuditTime,
}: Readonly<{
  totalDocs: number
  totalBytes: number
  successDocs: number
  successRate: string
  failed: number
  failedRate: string
  pipelineVersionsCount: number
  pipelineFilterLabel: string
  latestAuditTime: string
}>) {
  return (
    <div className={REPORT_METRIC_LEDGER_CLASS}>
      <AuditMetricCard
        icon={FileText}
        label="文档总数"
        value={String(totalDocs)}
        sub="数据集画像统计"
        tone="blue"
      />
      <AuditMetricCard
        icon={BarChart3}
        label="总大小"
        value={formatFileSize(Number(totalBytes || 0))}
        sub="累计文件体积"
        tone="violet"
      />
      <AuditMetricCard
        icon={CheckCircle2}
        label="成功"
        value={String(successDocs)}
        sub={`成功率 ${successRate}`}
        tone="green"
      />
      <AuditMetricCard
        icon={AlertTriangle}
        label="失败"
        value={String(failed)}
        sub={`失败率 ${failedRate}`}
        tone="amber"
      />
      <AuditMetricCard
        icon={Layers}
        label="版本数"
        value={String(pipelineVersionsCount)}
        sub={`过滤：${pipelineFilterLabel}`}
        tone="blue"
      />
      <AuditMetricCard
        icon={Clock3}
        label="生成时间"
        value={latestAuditTime}
        sub="当前报告快照"
        tone="slate"
      />
    </div>
  )
}

export function RiskMetricPanel({
  missingFindingCount,
  duplicateFindingCount,
  lowQualityFindingCount,
  totalDocs,
  failed,
  failedRate,
}: Readonly<{
  missingFindingCount: number
  duplicateFindingCount: number
  lowQualityFindingCount: number
  totalDocs: number
  failed: number
  failedRate: string
}>) {
  return (
    <div className={REPORT_PANEL_CLASS}>
      <div className={cn('mb-2', REPORT_PANEL_TITLE_CLASS)}>
        风险概览
      </div>
      <div className="grid grid-cols-2 gap-1.5">
        <ReportSignalRow
          label="缺失字段"
          value={formatPct(missingFindingCount, totalDocs)}
          sub={`${missingFindingCount} 条规则命中`}
          tone={missingFindingCount ? 'amber' : 'blue'}
        />
        <ReportSignalRow
          label="重复文档"
          value={formatPct(duplicateFindingCount, totalDocs)}
          sub={`${duplicateFindingCount} 条规则命中`}
          tone={duplicateFindingCount ? 'violet' : 'blue'}
        />
        <ReportSignalRow
          label="低置信度"
          value={formatPct(lowQualityFindingCount, totalDocs)}
          sub={`${lowQualityFindingCount} 条质量规则命中`}
          tone={lowQualityFindingCount ? 'amber' : 'green'}
        />
        <ReportSignalRow
          label="解析失败"
          value={failedRate}
          sub={`${failed} 个失败文档`}
          tone={failed ? 'rose' : 'green'}
        />
      </div>
    </div>
  )
}

export function RetrievalAuditPanel({
  retrievalAudit,
}: Readonly<{ retrievalAudit: RetrievalAudit | null | undefined }>) {
  const status = retrievalAuditStatusLabel(retrievalAudit?.status)
  const tone = retrievalAuditTone(retrievalAudit?.status)
  const metricRows = retrievalAuditMetricRows(retrievalAudit)
  const pluginRefs = retrievalAudit?.plugin_refs || []
  const gateCount = retrievalAudit?.gates?.length || 0
  const hasFailureCategories = Object.values(retrievalAudit?.failure_categories || {}).some(
    (value) => Number(value) > 0
  )
  const statusToneClass = {
    green: 'border-success/30 bg-success/10 text-success',
    amber: 'border-warning/30 bg-warning/10 text-warning',
    rose: 'border-destructive/30 bg-destructive/10 text-destructive',
    slate: 'border-border bg-muted/50 text-muted-foreground',
  }[tone]
  const statusIconClass = {
    green: 'bg-success/15 text-success',
    amber: 'bg-warning/15 text-warning',
    rose: 'bg-destructive/15 text-destructive',
    slate: 'bg-muted text-muted-foreground',
  }[tone]
  const StatusIcon = {
    green: CheckCircle2,
    amber: Clock3,
    rose: AlertTriangle,
    slate: FileSearch,
  }[tone]

  return (
    <div className={REPORT_PANEL_CLASS}>
      <div className="mb-2 overflow-hidden rounded-xl border border-info/15 bg-info/[0.025] px-2.5 py-1.5">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex min-w-0 items-center gap-2">
            <div className="flex size-7 shrink-0 items-center justify-center rounded-lg bg-info/10 text-info ring-1 ring-info/20">
              <FileSearch className="size-3.5" />
            </div>
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <div className={REPORT_PANEL_TITLE_CLASS}>召回审计</div>
                <span className="rounded-full border border-info/20 bg-info/10 px-2 py-0.5 text-[10px] font-medium tracking-[0.08em] text-info">
                  生产准入
                </span>
              </div>
              <div className={cn('mt-0.5 truncate', REPORT_SUBTEXT_CLASS)}>
                评测、元数据、KG 与压缩证据集中校验。
              </div>
            </div>
          </div>
          <Badge
            variant="outline"
            className={cn(
              'gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-semibold',
              statusToneClass
            )}
          >
            <span className={cn('rounded-full p-0.5', statusIconClass)}>
              <StatusIcon className="size-3" />
            </span>
            {status}
          </Badge>
        </div>
      </div>

      <div className="mt-2 grid gap-1.5 sm:grid-cols-2 xl:grid-cols-4">
        <CompactAuditFact
          icon={AlertTriangle}
          label="失败归因"
          value={retrievalAuditFailureText(retrievalAudit)}
          sub="范围 / 切块 / 排序 / KG"
          tone={hasFailureCategories ? 'rose' : 'slate'}
        />
        <CompactAuditFact
          icon={ShieldCheck}
          label="门禁证据"
          value={gateCount ? `${gateCount} 项` : '未配置'}
          sub="最新回归门禁"
          tone={gateCount ? 'violet' : 'slate'}
        />
        <CompactAuditFact
          icon={Layers}
          label="KG 建议"
          value={retrievalAuditKgRecommendationText(retrievalAudit)}
          sub="KG 开关对比"
          tone={retrievalAudit?.kg_recommendation === 'full_kg_assist' ? 'green' : 'slate'}
        />
        <CompactAuditFact
          icon={Archive}
          label="插件包"
          value={retrievalAuditHashText(retrievalAudit)}
          sub={pluginRefs.length ? `${pluginRefs.length} 个插件引用` : '未接入插件'}
          tone={pluginRefs.length ? 'blue' : 'slate'}
        />
      </div>

      <div className="mt-2 overflow-hidden rounded-lg border border-border/50">
        <div className="flex items-center justify-between gap-2 border-b border-border/50 bg-muted/45 px-2.5 py-1.5">
          <div className="text-[0.75rem] font-semibold tracking-[-0.01em] text-foreground/85">
            门禁指标
          </div>
          <div className="text-[0.6875rem] text-muted-foreground">
            最新回归门禁
          </div>
        </div>
        <div
          className={cn(
            'grid grid-cols-[1fr_104px] bg-background px-2.5 py-1.5',
            REPORT_TABLE_HEADER_CLASS
          )}
        >
          <span>指标</span>
          <span className="text-right">数值</span>
        </div>
        {metricRows.length === 0 ? (
          <div className="border-t border-info/15 bg-info/[0.025] px-2.5 py-1.5">
            <div className="grid gap-1.5 sm:grid-cols-2 xl:grid-cols-4">
              <AuditMetricPlaceholder
                label="Hit@K"
                hint="召回命中门槛"
              />
              <AuditMetricPlaceholder
                label="Metadata"
                hint="元数据命中/召回"
              />
              <AuditMetricPlaceholder
                label="Context"
                hint="有效上下文占比"
              />
              <AuditMetricPlaceholder
                label="Noise"
                hint="噪声与 KG 噪声"
              />
            </div>
            <div className={cn('mt-2 text-center', REPORT_SUBTEXT_CLASS)}>
              运行 Golden / regression 后填充真实门禁数据。
            </div>
          </div>
        ) : (
          metricRows.map((row) => (
            <div
              key={row.key}
              className={cn(
                'grid grid-cols-[1fr_104px] border-t border-border/50 px-2.5 py-1.5',
                REPORT_TABLE_ROW_CLASS
              )}
            >
              <span className="truncate" title={row.key}>
                {row.label}
              </span>
              <span className="text-right font-medium tabular-nums text-foreground">
                {row.value}
              </span>
            </div>
          ))
        )}
      </div>
    </div>
  )
}

export function FieldCoveragePanel({
  fieldCoverageRows,
  fieldCoverageBadge,
}: Readonly<{
  fieldCoverageRows: CoverageRow[]
  fieldCoverageBadge: string
}>) {
  return (
    <div className={REPORT_PANEL_CLASS}>
      <div className="mb-2.5 flex items-center justify-between gap-2">
        <div className={REPORT_PANEL_TITLE_CLASS}>字段覆盖分布</div>
        <Badge variant="outline" className="rounded-full text-[11px]">
          {fieldCoverageBadge}
        </Badge>
      </div>
      <div className="space-y-2">
        {fieldCoverageRows.map((row) => (
          <ProgressRow
            key={row.label}
            label={row.label}
            value={row.value}
            max={row.max}
          />
        ))}
      </div>
    </div>
  )
}

export function TopDocumentPanel({
  topDocumentRows,
  topDocumentMax,
  onClearFolderQuery,
}: Readonly<{
  topDocumentRows: ReportMetricDatum[]
  topDocumentMax: number
  onClearFolderQuery: () => void
}>) {
  return (
    <div className={REPORT_PANEL_CLASS}>
      <div className="mb-2.5 flex items-center justify-between gap-2">
        <div className={REPORT_PANEL_TITLE_CLASS}>文档分布 Top</div>
        <Button
          variant="link"
          className="h-auto p-0 text-[0.71875rem]"
          onClick={onClearFolderQuery}
        >
          查看全部
        </Button>
      </div>
      {topDocumentRows.length === 0 ? (
        <ReportInlineEmpty
          title="暂无分布数据"
          description="当前报告没有目录或文件类型分布。"
        />
      ) : (
        <div className="space-y-2">
          {topDocumentRows.map((row) => (
            <div
              key={row.name}
              className={cn(
                'grid grid-cols-[1fr_44px_84px] items-center gap-2',
                REPORT_TABLE_ROW_CLASS
              )}
            >
              <div className="truncate font-medium text-foreground/85" title={row.name}>
                {row.name}
              </div>
              <div className="tabular-nums text-foreground/85">{row.value}</div>
              <div className="h-1.5 rounded-full bg-muted">
                <div
                  className="h-full rounded-full bg-info/100"
                  style={{
                    width: `${Math.max(3, (safeNumber(row.value) / topDocumentMax) * 100)}%`,
                  }}
                />
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

export function ContentHealthPanel({
  governanceAuditUrlValue,
  governanceAuditUrlSub,
  governanceAuditImageValue,
  governanceAuditImageSub,
  governanceAuditHasSamples,
  sensitiveHits,
  piiHits,
  secretHits,
  lowQualityFindingCount,
}: Readonly<{
  governanceAuditUrlValue: string
  governanceAuditUrlSub: string
  governanceAuditImageValue: string
  governanceAuditImageSub: string
  governanceAuditHasSamples: boolean
  sensitiveHits: number
  piiHits: number
  secretHits: number
  lowQualityFindingCount: number
}>) {
  return (
    <div className={REPORT_PANEL_CLASS}>
      <div className={cn('mb-2', REPORT_PANEL_TITLE_CLASS)}>
        内容健康
      </div>
      <div className="grid grid-cols-2 gap-1.5">
        <ReportSignalRow
          label="可疑链接"
          value={governanceAuditUrlValue}
          sub={governanceAuditUrlSub}
          tone={governanceAuditHasSamples ? 'blue' : 'slate'}
        />
        <ReportSignalRow
          label="外部附件"
          value={governanceAuditImageValue}
          sub={governanceAuditImageSub}
          tone={governanceAuditHasSamples ? 'green' : 'slate'}
        />
        <ReportSignalRow
          label="敏感信息"
          value={String(sensitiveHits)}
          sub={`隐私 ${piiHits} / 密钥 ${secretHits}`}
          tone={sensitiveHits ? 'amber' : 'green'}
        />
        <ReportSignalRow
          label="低质量片段"
          value={String(lowQualityFindingCount)}
          sub="质量规则命中"
          tone={lowQualityFindingCount ? 'rose' : 'violet'}
        />
      </div>
    </div>
  )
}

export function CategoryChartPanel({
  categoryBarData,
}: Readonly<{ categoryBarData: CategoryMetricDatum[] }>) {
  return (
    <div className={REPORT_PANEL_CLASS}>
      <div className={cn('mb-2.5', REPORT_PANEL_TITLE_CLASS)}>知识分类</div>
      {categoryBarData.length === 0 ? (
        <ReportInlineEmpty
          title="分类尚未建立"
          description="当前数据集还没有分类计数；绑定分类或同步分类树后，这里会展示分布。"
        />
      ) : (
        <SafeResponsiveChart className="h-[180px]" minHeight={180}>
          <BarChart
            data={categoryBarData.slice(0, 8)}
            margin={{ left: 0, right: 8, top: 4, bottom: 4 }}
          >
            <CartesianGrid
              strokeDasharray="3 3"
              stroke="hsl(var(--border))"
              opacity={0.55}
            />
            <XAxis dataKey="name" />
            <YAxis allowDecimals={false} />
            <Tooltip
              cursor={CHART_TOOLTIP_CURSOR}
              contentStyle={CHART_TOOLTIP_STYLE}
              labelStyle={CHART_TOOLTIP_LABEL_STYLE}
            />
            <Bar dataKey="value" radius={[7, 7, 0, 0]} fill="hsl(var(--info))" />
          </BarChart>
        </SafeResponsiveChart>
      )}
    </div>
  )
}

export function PipelineVersionsPanel({
  pipelineVersions,
  pipelineVersionsWithFill,
  versionTotal,
}: Readonly<{
  pipelineVersions: DatasetReportPipelineVersion[]
  pipelineVersionsWithFill: PipelineVersionDatum[]
  versionTotal: number
}>) {
  return (
    <div className={REPORT_PANEL_CLASS}>
      <div className={cn('mb-2.5', REPORT_PANEL_TITLE_CLASS)}>
        处理版本分布
      </div>
      {pipelineVersions.length === 0 ? (
        <ReportInlineEmpty
          title="暂无版本快照"
          description="完成一次解析或治理后，这里会展示不同处理版本的文档分布。"
        />
      ) : (
        <div className="grid gap-2.5 lg:grid-cols-[1fr_1fr] xl:grid-cols-1 2xl:grid-cols-[1fr_1fr]">
          <SafeResponsiveChart className="h-[160px]" minHeight={160}>
            <PieChart>
              <Pie
                data={pipelineVersionsWithFill}
                dataKey="documents"
                nameKey="display_label"
                innerRadius={38}
                outerRadius={64}
              />
              <Tooltip
                cursor={CHART_TOOLTIP_CURSOR}
                contentStyle={CHART_TOOLTIP_STYLE}
                labelStyle={CHART_TOOLTIP_LABEL_STYLE}
              />
            </PieChart>
          </SafeResponsiveChart>
          <div className="space-y-1.5 self-center">
            {pipelineVersions.slice(0, 5).map((version, idx) => (
              <div
                key={version.pipeline_hash}
                className={cn(
                  'flex items-center justify-between gap-2',
                  REPORT_TABLE_ROW_CLASS
                )}
              >
                <span className="flex min-w-0 items-center gap-2">
                  <span
                    className="size-2 rounded-full"
                    style={{ background: PIE_COLORS[idx % PIE_COLORS.length] }}
                  />
                  <span
                    className="truncate font-mono"
                    title={version.pipeline_hash}
                  >
                    {pipelineVersionLabel(version.pipeline_hash)}
                  </span>
                </span>
                <span className="tabular-nums text-muted-foreground">
                  {version.documents} ({formatPct(version.documents, versionTotal)})
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

export function IssueRowsPanel({ issueRows }: Readonly<{ issueRows: IssueRow[] }>) {
  return (
    <div className={REPORT_PANEL_CLASS}>
      <div className="mb-2.5 flex items-center justify-between gap-2">
        <div className={REPORT_PANEL_TITLE_CLASS}>风险命中记录</div>
        <Badge variant="outline" className="rounded-full px-2 text-[11px]">
          命中项
        </Badge>
      </div>
      {issueRows.length === 0 ? (
        <ReportInlineEmpty
          title="暂无风险命中"
          description="当前报告没有失败任务或质量规则命中；后续出现异常会在这里列出。"
        />
      ) : (
        <div className="overflow-hidden rounded-xl border border-border/50">
          <div
            className={cn(
            'grid grid-cols-[104px_64px_104px_1fr_56px] bg-muted/50 px-2.5 py-1.5',
              REPORT_TABLE_HEADER_CLASS
            )}
          >
            <span>来源/时间</span>
            <span>级别</span>
            <span>类型</span>
            <span>描述</span>
            <span className="text-right">命中数</span>
          </div>
          {issueRows.map((row) => (
            <div
              key={row.id}
              className={cn(
                'grid grid-cols-[104px_64px_104px_1fr_56px] items-center border-t border-border/50 px-2.5 py-2',
                REPORT_TABLE_ROW_CLASS
              )}
            >
              <span className="truncate">{row.time}</span>
              <span className={cn('font-medium', issueLevelClass(row.level))}>
                {row.level}
              </span>
              <span className="truncate">{row.type}</span>
              <span className="truncate" title={row.description}>
                {row.description}
              </span>
              <span className="text-right tabular-nums">{row.target}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

export function ReportSectionHeading({
  index,
  title,
  description,
}: Readonly<{
  index: string
  title: string
  description: string
}>) {
  return (
    <div className="flex items-end gap-3 border-b border-info/15 pb-2">
      <span className="pb-0.5 font-mono text-[11px] font-semibold tracking-[0.16em] text-info">
        {index}
      </span>
      <div className="min-w-0 flex-1">
        <h2 className="text-[0.9375rem] font-semibold tracking-[-0.015em] text-foreground">
          {title}
        </h2>
        <p className="mt-0.5 text-xs leading-4 text-muted-foreground">{description}</p>
      </div>
      <span
        className="mb-1 hidden h-px w-16 bg-info/30 sm:block"
        aria-hidden="true"
      />
    </div>
  )
}
