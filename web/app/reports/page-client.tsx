'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { FileText } from 'lucide-react'

import { AppFrame } from '@/components/app-frame'
import { AnalysisPageShell } from '@/components/ui/analysis-page-shell'
import { KNOWLEDGE_OPS_BACKGROUND_CLASS } from '@/components/ui/knowledge-ops-hero'

import { datasetApi, datasetCategoryApi } from '@/lib/api/datasets'
import { reportApi } from '@/lib/api/reports'
import { formatApiError } from '@/lib/api-errors'
import { queryKeys } from '@/lib/query-keys'
import { formatDate, detachPromise } from '@/lib/utils'

import type { DatasetCategoryNode } from '@/types'

import { ReportsControlPanel } from './components/reports-control-panel'
import { ReportsPageHero } from './components/reports-page-hero'
import { ReportsResultSection } from './components/reports-result-section'
import {
  exportChartsJsonPayload,
  exportCompleteReportJsonPayload,
  exportReportBlobFile,
} from './report-export'
import {
  capCoverageValue,
  chunkStatsCoverage,
  countFindingsByPattern,
  filterReportFindings,
  formatPct,
  governanceAuditStatValue,
  pipelineVersionLabel,
  buildIssueRows,
  buildTopDocumentRows,
  reportDataSourceLabel,
  reportDataSourceSub,
  reportPipelineFilterLabel,
  safeNumber,
  sumRecordValues,
} from './report-format'
import {
  DEFAULT_PIPELINE_VERSION_VALUE,
  PIE_COLORS,
} from './report-tokens'
import { useDatasetReportQuery } from './use-dataset-report-query'
import { useFlatReportFolders } from './use-flat-report-folders'

export { useDatasetReportQuery } from './use-dataset-report-query'

type RefetchFn = () => unknown

function selectedPipelineHashValue(value: string) {
  if (value === DEFAULT_PIPELINE_VERSION_VALUE) return ''
  return value
}

function refreshReportQueries(
  datasetId: string,
  refetchDatasets: RefetchFn,
  refetchCategories: RefetchFn,
  refetchReport: RefetchFn
) {
  refetchDatasets()
  refetchCategories()
  if (datasetId) refetchReport()
}

export default function ReportsCenterPage() {
  const [datasetId, setDatasetId] = useState<string>('')
  const [pipelineHash, setPipelineHash] = useState<string>('')
  const [connectorRunsLimit, setConnectorRunsLimit] = useState<number>(20)
  const [redact, setRedact] = useState<boolean>(true)
  const [showOnlyIssues, setShowOnlyIssues] = useState<boolean>(false)

  const [isExportingJson, setIsExportingJson] = useState(false)
  const [isExportingHtml, setIsExportingHtml] = useState(false)
  const [isExportingRagAuditHtml, setIsExportingRagAuditHtml] = useState(false)
  const [isExportingBundle, setIsExportingBundle] = useState(false)

  const [folderQuery, setFolderQuery] = useState<string>('')
  const [categoryQuery] = useState<string>('')

  const reportParams = useMemo(
    () => ({
      pipeline_hash: pipelineHash.trim() || undefined,
      connector_runs_limit: connectorRunsLimit,
    }),
    [connectorRunsLimit, pipelineHash]
  )

  const datasetsQuery = useQuery<Awaited<ReturnType<typeof datasetApi.list>>>({
    queryKey: queryKeys.datasets.list({ skip: 0, limit: 200, purpose: 'reports' }),
    queryFn: () => datasetApi.list({ skip: 0, limit: 200 }),
  })
  const categoriesQuery = useQuery<
    Awaited<ReturnType<typeof datasetCategoryApi.listTree>>
  >({
    queryKey: queryKeys.reports.categories,
    queryFn: () => datasetCategoryApi.listTree(),
  })
  const reportQuery = useDatasetReportQuery(datasetId, reportParams)

  const datasets = useMemo(
    () => datasetsQuery.data?.items || [],
    [datasetsQuery.data?.items]
  )
  const categoryTree = useMemo(
    () => categoriesQuery.data?.items || [],
    [categoriesQuery.data?.items]
  )
  const report = reportQuery.data ?? null
  const isLoadingDatasets = datasetsQuery.isFetching
  const isLoadingReport = reportQuery.isFetching
  const reportErrorMessage = reportQuery.error
    ? formatApiError(reportQuery.error, '报告加载失败')
    : ''
  const selectedDataset = useMemo(
    () => datasets.find((d) => d.id === datasetId) || null,
    [datasets, datasetId]
  )

  useEffect(() => {
    if (!datasets.length) return
    if (datasetId && datasets.some((dataset) => dataset.id === datasetId)) {
      return
    }
    setDatasetId(datasets[0].id)
    setPipelineHash('')
  }, [datasetId, datasets])

  const handleDatasetChange = useCallback((value: string) => {
    setDatasetId(value)
    setPipelineHash('')
  }, [])
  const handlePipelineHashChange = useCallback((value: string) => {
    setPipelineHash(selectedPipelineHashValue(value))
  }, [])
  const handleRefresh = useCallback(() => {
    refreshReportQueries(
      datasetId,
      datasetsQuery.refetch,
      categoriesQuery.refetch,
      reportQuery.refetch
    )
  }, [categoriesQuery.refetch, datasetId, datasetsQuery.refetch, reportQuery.refetch])
  const handleClearFolderQuery = useCallback(() => {
    setFolderQuery('')
  }, [])

  const handleExportJson = useCallback(() => {
    detachPromise(
      exportReportBlobFile({
        datasetId,
        datasetName: selectedDataset?.name || 'dataset',
        pipelineHash,
        connectorRunsLimit,
        setLoading: setIsExportingJson,
        getBlob: reportApi.exportDatasetReportJson,
        filenameStem: 'report',
        extension: 'json',
        errorFallback: '导出 JSON 报告失败',
      })
    )
  }, [connectorRunsLimit, datasetId, pipelineHash, selectedDataset?.name])

  const handleExportHtml = useCallback(() => {
    detachPromise(
      exportReportBlobFile({
        datasetId,
        datasetName: selectedDataset?.name || 'dataset',
        pipelineHash,
        connectorRunsLimit,
        redact,
        setLoading: setIsExportingHtml,
        getBlob: reportApi.exportDatasetReportHtml,
        filenameStem: 'report',
        extension: 'html',
        errorFallback: '导出 HTML 报告失败',
      })
    )
  }, [
    connectorRunsLimit,
    datasetId,
    pipelineHash,
    redact,
    selectedDataset?.name,
  ])

  const handleExportRagAuditHtml = useCallback(() => {
    detachPromise(
      exportReportBlobFile({
        datasetId,
        datasetName: selectedDataset?.name || 'dataset',
        pipelineHash,
        connectorRunsLimit,
        redact,
        setLoading: setIsExportingRagAuditHtml,
        getBlob: reportApi.exportDatasetRagAuditHtml,
        filenameStem: 'rag_audit',
        extension: 'html',
        errorFallback: '导出 RAG Audit 报告失败',
      })
    )
  }, [
    connectorRunsLimit,
    datasetId,
    pipelineHash,
    redact,
    selectedDataset?.name,
  ])

  const handleExportBundleZip = useCallback(() => {
    detachPromise(
      exportReportBlobFile({
        datasetId,
        datasetName: selectedDataset?.name || 'dataset',
        pipelineHash,
        connectorRunsLimit,
        redact,
        setLoading: setIsExportingBundle,
        getBlob: reportApi.exportDatasetReportBundleZip,
        filenameStem: 'report-bundle',
        extension: 'zip',
        errorFallback: '导出完整归档包失败',
      })
    )
  }, [
    connectorRunsLimit,
    datasetId,
    pipelineHash,
    redact,
    selectedDataset?.name,
  ])

  const totalDocs = report?.profile?.total_documents || 0
  const totalBytes = report?.profile?.total_size_bytes || 0
  const quarantined = report?.compliance?.quarantined_documents || 0
  const failed = report?.compliance?.failed_documents || 0
  const pipelineVersions = useMemo(
    () => report?.pipeline_versions ?? [],
    [report?.pipeline_versions]
  )
  const pipelineVersionsWithFill = useMemo(
    () =>
      pipelineVersions.map((version, idx) => ({
        ...version,
        display_label: pipelineVersionLabel(version.pipeline_hash),
        fill: PIE_COLORS[idx % PIE_COLORS.length],
      })),
    [pipelineVersions]
  )
  const connectorRuns = report?.connectors || []
  const folderTree = report?.folder_tree || null
  const flatFolders = useFlatReportFolders(folderTree)
  const governance = report?.governance_metrics || null
  const governanceAudit = report?.governance_audit || null
  const retrievalAudit = report?.retrieval_audit || null
  const pipelineVersionOptions = useMemo(() => {
    const seen = new Set<string>()
    return pipelineVersions
      .map((v) => ({
        pipeline_hash: String(v.pipeline_hash || '').trim(),
        documents: Number(v.documents || 0),
      }))
      .filter((v) => {
        if (
          !v.pipeline_hash ||
          v.pipeline_hash === 'unknown' ||
          seen.has(v.pipeline_hash)
        )
          return false
        seen.add(v.pipeline_hash)
        return true
      })
  }, [pipelineVersions])
  const pipelineVersionSelectValue =
    pipelineHash.trim() || DEFAULT_PIPELINE_VERSION_VALUE

  const folderBarData = useMemo(() => {
    const rows = flatFolders ?? []
    const q = folderQuery.trim().toLowerCase()
    const filtered = q
      ? rows.filter((f) => f.path.toLowerCase().includes(q))
      : rows
    return filtered
      .slice()
      .sort((a, b) => b.documents - a.documents)
      .slice(0, 12)
      .map((f) => ({ name: f.path || '/', value: Number(f.documents || 0) }))
  }, [flatFolders, folderQuery])

  const flatCategories = useMemo(() => {
    const out: Array<{
      id: string
      name: string
      depth: number
      datasets: number
    }> = []
    const walk = (node: DatasetCategoryNode) => {
      out.push({
        id: String(node.id),
        name: String(node.name || ''),
        depth: Number(node.depth || 0),
        datasets: Number(node.datasets || 0),
      })
      for (const child of node.children || []) walk(child)
    }
    for (const n of categoryTree || []) walk(n)
    return out
  }, [categoryTree])

  const categoryBarData = useMemo(() => {
    const q = categoryQuery.trim().toLowerCase()
    const filtered = q
      ? flatCategories.filter((c) => c.name.toLowerCase().includes(q))
      : flatCategories
    return filtered
      .slice()
      .sort((a, b) => b.datasets - a.datasets)
      .slice(0, 12)
      .map((c) => ({
        name: c.name || c.id,
        value: Number(c.datasets || 0),
        depth: c.depth,
      }))
  }, [categoryQuery, flatCategories])

  const dropReasonsData = useMemo(() => {
    const m = governance?.drop_reasons_total || {}
    return Object.entries(m)
      .map(([name, value]) => ({ name, value: Number(value || 0) }))
      .filter((x) => x.value > 0)
      .sort((a, b) => b.value - a.value)
      .slice(0, 12)
  }, [governance?.drop_reasons_total])

  const rulePacksData = useMemo(() => {
    const m = governance?.rule_packs_docs || {}
    return Object.entries(m)
      .map(([name, value]) => ({ name, value: Number(value || 0) }))
      .filter((x) => x.value > 0)
      .sort((a, b) => b.value - a.value)
      .slice(0, 12)
  }, [governance?.rule_packs_docs])

  const govAuditCharData = useMemo(() => {
    if (!governanceAudit) return []
    return [
      {
        name: 'original_chars_total',
        value: Number(governanceAudit.original_chars_total || 0),
      },
      {
        name: 'cleaned_chars_total',
        value: Number(governanceAudit.cleaned_chars_total || 0),
      },
    ]
  }, [governanceAudit])

  const govAuditReductionHistData = useMemo(() => {
    if (!governanceAudit) return []
    const bins = governanceAudit.char_reduction_pct_histogram || []
    return bins.map((b) => ({
      name: String(b.label || ''),
      value: Number(b.count || 0),
    }))
  }, [governanceAudit])

  const govAuditDensityHistData = useMemo(() => {
    if (!governanceAudit) return []
    const bins = governanceAudit.density_pct_histogram || []
    return bins.map((b) => ({
      name: String(b.label || ''),
      value: Number(b.count || 0),
    }))
  }, [governanceAudit])

  const govAuditHeadingRatioHistData = useMemo(() => {
    if (!governanceAudit) return []
    const bins = governanceAudit.heading_ratio_pct_histogram || []
    return bins.map((b) => ({
      name: String(b.label || ''),
      value: Number(b.count || 0),
    }))
  }, [governanceAudit])

  const govAuditEffectsData = useMemo(() => {
    if (!governanceAudit) return []
    const items = [
      {
        name: '段落去重（dropped）',
        value: Number(governanceAudit.paragraphs_dropped_total || 0),
      },
      {
        name: '裁剪 References（lines）',
        value: Number(governanceAudit.references_removed_lines_total || 0),
      },
      {
        name: 'URL 规范化（changed）',
        value: Number(governanceAudit.urls_changed_total || 0),
      },
      {
        name: '去样板（lines）',
        value: Number(governanceAudit.boilerplate_removed_lines_total || 0),
      },
      {
        name: '移除图片（count）',
        value: Number(governanceAudit.images_removed_total || 0),
      },
      {
        name: '表格规范化（tables）',
        value: Number(governanceAudit.tables_normalized_total || 0),
      },
      {
        name: '代码行号移除（lines）',
        value: Number(governanceAudit.code_lines_stripped_total || 0),
      },
    ]
    return items
      .filter((x) => x.value > 0)
      .sort((a, b) => b.value - a.value)
      .slice(0, 12)
  }, [governanceAudit])

  const statusCounts = report?.profile?.by_status || {}
  const hasStatusCounts = Object.keys(statusCounts).length > 0
  const completedDocs = safeNumber(
    statusCounts.completed ?? statusCounts.ready ?? statusCounts.done
  )
  const successDocs = hasStatusCounts
    ? completedDocs
    : Math.max(0, totalDocs - failed - quarantined)
  const successRate = formatPct(successDocs, totalDocs)
  const failedRate = formatPct(failed, totalDocs)
  const selectedDatasetName =
    selectedDataset?.name || report?.dataset_name || '未选择数据集'
  const latestAuditTime = report?.generated_at
    ? formatDate(report.generated_at)
    : '-'
  const dataProvenance = report?.data_provenance || null
  const dataSourceLabel = reportDataSourceLabel(dataProvenance)
  const dataSourceSub = reportDataSourceSub(dataProvenance)
  const piiHits = sumRecordValues(report?.compliance?.pii_hits_total)
  const secretHits = sumRecordValues(report?.compliance?.secrets_hits_total)
  const sensitiveHits = piiHits + secretHits
  const findingRows = filterReportFindings(
    report?.profile?.findings || [],
    showOnlyIssues
  )
  const duplicateFindingCount = countFindingsByPattern(
    findingRows,
    /duplicate|重复/i
  )
  const missingFindingCount = countFindingsByPattern(
    findingRows,
    /missing|缺失/i
  )
  const lowQualityFindingCount = countFindingsByPattern(
    findingRows,
    /quality|低质量|low/i
  )
  const topDocumentRows = buildTopDocumentRows(
    folderBarData,
    report?.profile?.by_file_type
  )
  const topDocumentMax = Math.max(
    1,
    ...topDocumentRows.map((item) => safeNumber(item.value))
  )
  const versionTotal = pipelineVersions.reduce(
    (acc, item) => acc + safeNumber(item.documents),
    0
  )
  const pipelineFilterLabel = reportPipelineFilterLabel(pipelineHash)
  const activeFindingRows = findingRows.filter(
    (item) => safeNumber(item.count) > 0
  )
  const issueRows = buildIssueRows(activeFindingRows, connectorRuns)
  const governanceCoverageMax =
    safeNumber(governanceAudit?.used_documents) ||
    safeNumber(governance?.used_documents)
  const governanceAuditHasSamples =
    safeNumber(governanceAudit?.used_documents) > 0
  const governanceAuditUnavailableSub = '运行治理审计后展示'
  const governanceAuditUrlValue = governanceAuditHasSamples
    ? String(governanceAudit?.urls_changed_total || 0)
    : governanceAuditStatValue(governanceAuditHasSamples, governanceAudit?.urls_changed_total)
  const governanceAuditImageValue = governanceAuditHasSamples
    ? String(governanceAudit?.images_removed_total || 0)
    : governanceAuditStatValue(governanceAuditHasSamples, governanceAudit?.images_removed_total)
  const governanceAuditUrlSub = governanceAuditHasSamples
    ? 'URL 变更记录'
    : governanceAuditUnavailableSub
  const governanceAuditImageSub = governanceAuditHasSamples
    ? '图片处理记录'
    : governanceAuditUnavailableSub
  const hasGovernanceCoverage = governanceCoverageMax > 0
  const chunkStatsCovered = chunkStatsCoverage(report, totalDocs)
  const baseCoverageRows = [
    {
      label: '状态字段覆盖',
      value: capCoverageValue(sumRecordValues(statusCounts), totalDocs),
      max: totalDocs,
    },
    {
      label: '文件类型覆盖',
      value: capCoverageValue(
        sumRecordValues(report?.profile?.by_file_type),
        totalDocs
      ),
      max: totalDocs,
    },
    {
      label: '目录字段覆盖',
      value: capCoverageValue(
        sumRecordValues(report?.profile?.by_directory),
        totalDocs
      ),
      max: totalDocs,
    },
    {
      label: '解析来源覆盖',
      value: capCoverageValue(
        report?.profile?.parsing_provenance?.docs_with_provenance,
        totalDocs
      ),
      max: totalDocs,
    },
    {
      label: '分块统计覆盖',
      value: capCoverageValue(chunkStatsCovered, totalDocs),
      max: totalDocs,
    },
  ]
  const governanceCoverageRows = [
    {
      label: '字符统计覆盖',
      value: capCoverageValue(
        governanceAudit?.docs_with_char_stats,
        governanceCoverageMax
      ),
      max: governanceCoverageMax,
    },
    {
      label: '解析内容持久化',
      value: capCoverageValue(
        governanceAudit?.docs_with_parsed_content_persisted,
        governanceCoverageMax
      ),
      max: governanceCoverageMax,
    },
    {
      label: '治理记录覆盖',
      value: capCoverageValue(
        governance?.docs_with_governance,
        governanceCoverageMax
      ),
      max: governanceCoverageMax,
    },
    {
      label: '变更文档占比',
      value: capCoverageValue(governanceAudit?.docs_changed, governanceCoverageMax),
      max: governanceCoverageMax,
    },
    {
      label: '过滤/隔离占比',
      value: capCoverageValue(
        governanceAudit?.docs_dropped || quarantined,
        governanceCoverageMax
      ),
      max: governanceCoverageMax,
    },
  ]
  const fieldCoverageRows = hasGovernanceCoverage
    ? governanceCoverageRows
    : baseCoverageRows
  const fieldCoverageBadge = hasGovernanceCoverage ? '治理审计' : '基础画像'

  const handleExportChartsJson = useCallback(() => {
    exportChartsJsonPayload({
      datasetId,
      report,
      selectedDatasetName: selectedDataset?.name,
      pipelineHash,
      dropReasonsData,
      rulePacksData,
      govAuditCharData,
      govAuditReductionHistData,
      govAuditDensityHistData,
      govAuditHeadingRatioHistData,
      govAuditEffectsData,
      folderQuery,
      folderBarData,
      categoryQuery,
      categoryBarData,
    })
  }, [
    categoryBarData,
    categoryQuery,
    datasetId,
    dropReasonsData,
    folderBarData,
    folderQuery,
    govAuditCharData,
    govAuditDensityHistData,
    govAuditReductionHistData,
    govAuditHeadingRatioHistData,
    govAuditEffectsData,
    pipelineHash,
    report,
    rulePacksData,
    selectedDataset?.name,
  ])

  const handleExportCompleteJson = useCallback(() => {
    exportCompleteReportJsonPayload({
      datasetId,
      report,
      selectedDatasetName: selectedDataset?.name,
      pipelineHash,
      successDocs,
      successRate,
      failedRate,
      sensitiveHits,
      findingRows,
      fieldCoverageRows,
      topDocumentRows,
      categoryBarData,
      versionTotal,
    })
  }, [
    categoryBarData,
    datasetId,
    failedRate,
    fieldCoverageRows,
    findingRows,
    pipelineHash,
    report,
    selectedDataset?.name,
    sensitiveHits,
    successDocs,
    successRate,
    topDocumentRows,
    versionTotal,
  ])

  return (
    <AppFrame>
      <div className={KNOWLEDGE_OPS_BACKGROUND_CLASS}>
        <AnalysisPageShell
          title="数据报告与审计概览"
          description="一键导出数据报告与审计结果，支持多种格式与指标视图，便于数据治理与合规审查。"
          icon={FileText}
          iconColor="text-primary"
          badge="报告"
          size="full"
          showHeader={false}
          bodyGutter="none"
          bodyClassName="!pb-0 !pt-0"
          bodyContainerClassName="max-w-none"
        >
          <div
            data-reports-dossier="true"
            className="space-y-4 px-4 py-4 md:px-6 md:py-5"
          >
            <ReportsPageHero
              selectedDatasetName={selectedDatasetName}
              datasetId={datasetId}
              totalDocs={totalDocs}
              isLoadingReport={isLoadingReport}
              report={report}
              latestAuditTime={latestAuditTime}
              dataSourceLabel={dataSourceLabel}
              dataSourceSub={dataSourceSub}
              dataProvenance={dataProvenance}
            />
            <ReportsControlPanel
              datasetId={datasetId}
              datasets={datasets}
              isLoadingDatasets={isLoadingDatasets}
              pipelineVersionSelectValue={pipelineVersionSelectValue}
              pipelineVersionOptions={pipelineVersionOptions}
              connectorRunsLimit={connectorRunsLimit}
              showOnlyIssues={showOnlyIssues}
              redact={redact}
              isExportingJson={isExportingJson}
              isExportingHtml={isExportingHtml}
              isExportingRagAuditHtml={isExportingRagAuditHtml}
              isExportingBundle={isExportingBundle}
              report={report}
              isLoadingReport={isLoadingReport}
              onDatasetChange={handleDatasetChange}
              onPipelineHashChange={handlePipelineHashChange}
              onConnectorRunsLimitChange={setConnectorRunsLimit}
              onShowOnlyIssuesChange={setShowOnlyIssues}
              onRedactChange={setRedact}
              onExportJson={handleExportJson}
              onExportCompleteJson={handleExportCompleteJson}
              onExportChartsJson={handleExportChartsJson}
              onExportRagAuditHtml={handleExportRagAuditHtml}
              onExportBundleZip={handleExportBundleZip}
              onExportHtml={handleExportHtml}
              onRegenerateReport={reportQuery.refetch}
              onRefresh={handleRefresh}
            />

            <ReportsResultSection
              report={report}
              datasetId={datasetId}
              isLoadingReport={isLoadingReport}
              reportErrorMessage={reportErrorMessage}
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
              onClearFolderQuery={handleClearFolderQuery}
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
          </div>
        </AnalysisPageShell>
      </div>
    </AppFrame>
  )
}
