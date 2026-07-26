'use client'

import { AlertTriangle } from 'lucide-react'

import { EmptyState } from '@/components/ui/empty-state'

import type {
  DatasetReport,
  DatasetReportPipelineVersion,
} from '@/types'

import {
  reportPreviewEmptyDescription,
  reportPreviewEmptyTitle,
} from '../report-format'
import { ReportsDashboard } from './reports-dashboard'

import type {
  CategoryMetricDatum,
  CoverageRow,
  IssueRow,
  PipelineVersionDatum,
  ReportMetricDatum,
  RetrievalAudit,
} from '../types'

export function ReportsResultSection({
  report,
  datasetId,
  isLoadingReport,
  reportErrorMessage,
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
  report: DatasetReport | null
  datasetId: string
  isLoadingReport: boolean
  reportErrorMessage: string
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
  if (!report) {
    if (reportErrorMessage && datasetId && !isLoadingReport) {
      return (
        <EmptyState
          icon={AlertTriangle}
          title="报告加载失败"
          description={reportErrorMessage}
        />
      )
    }
    return (
      <EmptyState
        title={reportPreviewEmptyTitle(datasetId, isLoadingReport)}
        description={reportPreviewEmptyDescription(datasetId, isLoadingReport)}
      />
    )
  }

  return (
    <ReportsDashboard
      totalDocs={totalDocs}
      totalBytes={totalBytes}
      successDocs={successDocs}
      successRate={successRate}
      failed={failed}
      failedRate={failedRate}
      pipelineVersions={pipelineVersions}
      pipelineVersionsWithFill={pipelineVersionsWithFill}
      pipelineFilterLabel={pipelineFilterLabel}
      latestAuditTime={latestAuditTime}
      retrievalAudit={retrievalAudit}
      missingFindingCount={missingFindingCount}
      duplicateFindingCount={duplicateFindingCount}
      lowQualityFindingCount={lowQualityFindingCount}
      fieldCoverageRows={fieldCoverageRows}
      fieldCoverageBadge={fieldCoverageBadge}
      topDocumentRows={topDocumentRows}
      topDocumentMax={topDocumentMax}
      onClearFolderQuery={onClearFolderQuery}
      governanceAuditUrlValue={governanceAuditUrlValue}
      governanceAuditUrlSub={governanceAuditUrlSub}
      governanceAuditImageValue={governanceAuditImageValue}
      governanceAuditImageSub={governanceAuditImageSub}
      governanceAuditHasSamples={governanceAuditHasSamples}
      sensitiveHits={sensitiveHits}
      piiHits={piiHits}
      secretHits={secretHits}
      categoryBarData={categoryBarData}
      versionTotal={versionTotal}
      issueRows={issueRows}
    />
  )
}
