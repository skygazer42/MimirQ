'use client'

import { AlertTriangle } from 'lucide-react'
import type { ComponentProps } from 'react'

import { EmptyState } from '@/components/ui/empty-state'

import type { DatasetReport } from '@/types'

import { reportPreviewEmptyDescription, reportPreviewEmptyTitle } from '../report-format'
import { ReportsDashboard } from './reports-dashboard'

type ReportsResultSectionProps = Readonly<
  ComponentProps<typeof ReportsDashboard> & {
    report: DatasetReport | null
    datasetId: string
    isLoadingReport: boolean
    reportErrorMessage: string
  }
>

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
}: ReportsResultSectionProps) {
  if (!report) {
    if (reportErrorMessage && datasetId && !isLoadingReport) {
      return <EmptyState icon={AlertTriangle} title="报告加载失败" description={reportErrorMessage} />
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
