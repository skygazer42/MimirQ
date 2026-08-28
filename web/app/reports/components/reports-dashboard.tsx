'use client'

import type { DatasetReportPipelineVersion } from '@/types'

import {
  CategoryChartPanel,
  ContentHealthPanel,
  FieldCoveragePanel,
  IssueRowsPanel,
  PipelineVersionsPanel,
  ReportMetricGrid,
  ReportSectionHeading,
  RetrievalAuditPanel,
  RiskMetricPanel,
  TopDocumentPanel,
} from './report-panels'

import type {
  CategoryMetricDatum,
  CoverageRow,
  IssueRow,
  PipelineVersionDatum,
  ReportMetricDatum,
  RetrievalAudit,
} from '../types'

export function ReportsDashboard({
  totalDocs,
  totalBytes,
  successDocs,
  successRate,
  failed,
  failedRate,
  pipelineVersions,
  pipelineVersionsWithFill,
  pipelineFilterLabel,
  latestAuditTime,
  retrievalAudit,
  missingFindingCount,
  duplicateFindingCount,
  lowQualityFindingCount,
  fieldCoverageRows,
  fieldCoverageBadge,
  topDocumentRows,
  topDocumentMax,
  onClearFolderQuery,
  governanceAuditUrlValue,
  governanceAuditUrlSub,
  governanceAuditImageValue,
  governanceAuditImageSub,
  governanceAuditHasSamples,
  sensitiveHits,
  piiHits,
  secretHits,
  categoryBarData,
  versionTotal,
  issueRows,
}: Readonly<{
  totalDocs: number
  totalBytes: number
  successDocs: number
  successRate: string
  failed: number
  failedRate: string
  pipelineVersions: DatasetReportPipelineVersion[]
  pipelineVersionsWithFill: PipelineVersionDatum[]
  pipelineFilterLabel: string
  latestAuditTime: string
  retrievalAudit: RetrievalAudit | null
  missingFindingCount: number
  duplicateFindingCount: number
  lowQualityFindingCount: number
  fieldCoverageRows: CoverageRow[]
  fieldCoverageBadge: string
  topDocumentRows: ReportMetricDatum[]
  topDocumentMax: number
  onClearFolderQuery: () => void
  governanceAuditUrlValue: string
  governanceAuditUrlSub: string
  governanceAuditImageValue: string
  governanceAuditImageSub: string
  governanceAuditHasSamples: boolean
  sensitiveHits: number
  piiHits: number
  secretHits: number
  categoryBarData: CategoryMetricDatum[]
  versionTotal: number
  issueRows: IssueRow[]
}>) {
  return (
    <section className="space-y-3">
      <ReportSectionHeading
        index="01"
        title="报告摘要"
        description="先核对规模、处理结果与召回门禁，再进入质量细节。"
      />
      <ReportMetricGrid
        totalDocs={totalDocs}
        totalBytes={totalBytes}
        successDocs={successDocs}
        successRate={successRate}
        failed={failed}
        failedRate={failedRate}
        pipelineVersionsCount={pipelineVersions.length}
        pipelineFilterLabel={pipelineFilterLabel}
        latestAuditTime={latestAuditTime}
      />

      <RetrievalAuditPanel retrievalAudit={retrievalAudit} />

      <ReportSectionHeading
        index="02"
        title="数据质量"
        description="从风险、字段覆盖、内容规模和治理痕迹四个维度检查当前快照。"
      />
      <div className="grid items-start gap-2.5 xl:grid-cols-2 2xl:grid-cols-[1.05fr_1.2fr_1.05fr_0.95fr]">
        <RiskMetricPanel
          missingFindingCount={missingFindingCount}
          duplicateFindingCount={duplicateFindingCount}
          lowQualityFindingCount={lowQualityFindingCount}
          totalDocs={totalDocs}
          failed={failed}
          failedRate={failedRate}
        />
        <FieldCoveragePanel
          fieldCoverageRows={fieldCoverageRows}
          fieldCoverageBadge={fieldCoverageBadge}
        />
        <TopDocumentPanel
          topDocumentRows={topDocumentRows}
          topDocumentMax={topDocumentMax}
          onClearFolderQuery={onClearFolderQuery}
        />
        <ContentHealthPanel
          governanceAuditUrlValue={governanceAuditUrlValue}
          governanceAuditUrlSub={governanceAuditUrlSub}
          governanceAuditImageValue={governanceAuditImageValue}
          governanceAuditImageSub={governanceAuditImageSub}
          governanceAuditHasSamples={governanceAuditHasSamples}
          sensitiveHits={sensitiveHits}
          piiHits={piiHits}
          secretHits={secretHits}
          lowQualityFindingCount={lowQualityFindingCount}
        />
      </div>

      <ReportSectionHeading
        index="03"
        title="结构与风险"
        description="查看分类分布、处理版本与可追溯的风险命中记录。"
      />
      <div className="grid items-start gap-2.5 xl:grid-cols-2 2xl:grid-cols-[1.2fr_0.9fr_1.4fr]">
        <CategoryChartPanel categoryBarData={categoryBarData} />
        <PipelineVersionsPanel
          pipelineVersions={pipelineVersions}
          pipelineVersionsWithFill={pipelineVersionsWithFill}
          versionTotal={versionTotal}
        />
        <div className="xl:col-span-2 2xl:col-span-1">
          <IssueRowsPanel issueRows={issueRows} />
        </div>
      </div>
    </section>
  )
}
