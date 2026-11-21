'use client'

import { useEffect, useMemo, useState, useSyncExternalStore } from 'react'
import { skipToken, useQuery } from '@tanstack/react-query'
import { AppFrame } from '@/components/app-frame'
import { Button } from '@/components/ui/button'
import { datasetApi, datasetCategoryApi } from '@/lib/api/datasets'
import { reportApi } from '@/lib/api/reports'
import { getAuthSessionKey, subscribeAuthSession } from '@/lib/auth-storage'
import { formatApiError } from '@/lib/api-errors'
import { flattenDatasetCategoryTree } from '@/lib/dataset-categories'
import { queryKeys } from '@/lib/query-keys'
import type { DatasetReport } from '@/lib/report-schema'
import { ReportsControlPanel } from './components/reports-control-panel'
import { ReportsResultSection } from './components/reports-result-section'
import { downloadCompleteReportJson, downloadReportChartsJson, reportExportParams } from './report-export'
import { DEFAULT_PIPELINE_VERSION_VALUE } from './report-tokens'
import { useReportExports } from './use-report-exports'
import type { ReportExportParams } from './types'
import styles from './reports.module.css'

type ReportSnapshot = Readonly<{
  datasetId: string
  params: Pick<ReportExportParams, 'pipeline_hash' | 'connector_runs_limit'>
  data: DatasetReport
}>

export default function ReportsCenterPage() {
  const sessionKey = useSyncExternalStore(subscribeAuthSession, getAuthSessionKey, getAuthSessionKey)
  return <ReportsWorkspace key={sessionKey} sessionKey={sessionKey} />
}

function ReportsWorkspace({ sessionKey }: Readonly<{ sessionKey: string }>) {
  const [datasetId, setDatasetId] = useState('')
  const [pipelineHash, setPipelineHash] = useState('')
  const [connectorRunsLimit, setConnectorRunsLimit] = useState(20)
  const [redact, setRedact] = useState(true)
  const [showOnlyIssues, setShowOnlyIssues] = useState(false)
  const { exporting, exportReport } = useReportExports({
    sessionKey,
    datasetId,
    pipelineHash,
    connectorRunsLimit,
    redact,
  })
  const reportParams = reportExportParams(pipelineHash, connectorRunsLimit)
  const datasetsQuery = useQuery({
    queryKey: queryKeys.datasets.exhaustive(),
    queryFn: ({ signal }) => datasetApi.listAll(undefined, { signal }),
  })
  const categoriesQuery = useQuery({
    queryKey: queryKeys.datasetCategories.tree,
    queryFn: ({ signal }) => datasetCategoryApi.listTree({ signal }),
  })
  const reportQuery = useQuery({
    queryKey: ['reports', sessionKey, 'snapshot', datasetId, reportParams],
    queryFn:
      datasetId === ''
        ? skipToken
        : async ({ signal }): Promise<ReportSnapshot> => ({
            datasetId,
            params: reportParams,
            data: await reportApi.getDatasetReport(datasetId, reportParams, { signal }),
          }),
  })
  const [acceptedSnapshot, setAcceptedSnapshot] = useState<ReportSnapshot | undefined>()
  useEffect(() => {
    if (reportQuery.data !== undefined) setAcceptedSnapshot(reportQuery.data)
  }, [reportQuery.data])
  const snapshot = reportQuery.data ?? acceptedSnapshot
  const report = snapshot?.data
  const showingPrevious =
    snapshot !== undefined &&
    (snapshot.datasetId !== datasetId ||
      snapshot.params.pipeline_hash !== reportParams.pipeline_hash ||
      snapshot.params.connector_runs_limit !== reportParams.connector_runs_limit)
  const datasets = datasetsQuery.data
  const firstDataset = datasetsQuery.isSuccess ? datasetsQuery.data[0] : undefined
  useEffect(() => {
    if (datasetId === '' && firstDataset !== undefined) setDatasetId(firstDataset.id)
  }, [datasetId, firstDataset])

  const categoryTree = categoriesQuery.data?.items
  const categoryBarData = useMemo(() => {
    if (categoryTree === undefined) return undefined
    return flattenDatasetCategoryTree(categoryTree)
      .map((node) => ({ key: node.id, name: node.name, value: node.datasets, depth: node.depth }))
      .sort((a, b) => b.value - a.value || a.key.localeCompare(b.key))
      .slice(0, 12)
  }, [categoryTree])
  const categoryErrorMessage = categoriesQuery.isError
    ? formatApiError(categoriesQuery.error, '分类读取失败')
    : undefined
  const pipelineVersionOptions =
    snapshot?.datasetId === datasetId
      ? snapshot.data.pipeline_versions.filter(
          (version) => version.pipeline_hash.length > 0 && version.pipeline_hash !== 'unknown',
        )
      : []

  function changeDataset(value: string) {
    setDatasetId(value)
    setPipelineHash('')
  }
  function changePipelineVersion(value: string) {
    setPipelineHash(value === DEFAULT_PIPELINE_VERSION_VALUE ? '' : value)
  }
  function restoreDisplayedScope() {
    if (snapshot === undefined) return
    setDatasetId(snapshot.datasetId)
    setPipelineHash(snapshot.params.pipeline_hash === undefined ? '' : snapshot.params.pipeline_hash)
    setConnectorRunsLimit(snapshot.params.connector_runs_limit)
  }
  function refresh() {
    void datasetsQuery.refetch()
    void categoriesQuery.refetch()
    if (datasetId.length > 0) void reportQuery.refetch()
  }
  function exportCharts() {
    if (report !== undefined)
      downloadReportChartsJson(report, { status: categoriesQuery.status, rows: categoryBarData })
  }
  function exportComplete() {
    if (report !== undefined)
      downloadCompleteReportJson(report, { status: categoriesQuery.status, rows: categoryBarData })
  }

  return (
    <AppFrame>
      <div className={styles.workspace} data-reports-dossier="true">
        <ReportsControlPanel
          datasetId={datasetId}
          datasets={datasets}
          isFetchingDatasets={datasetsQuery.isFetching}
          pipelineVersionSelectValue={pipelineHash.length === 0 ? DEFAULT_PIPELINE_VERSION_VALUE : pipelineHash}
          pipelineVersionOptions={pipelineVersionOptions}
          connectorRunsLimit={connectorRunsLimit}
          redact={redact}
          exporting={exporting}
          report={report}
          isFetchingReport={reportQuery.isFetching}
          refreshing={datasetsQuery.isFetching || categoriesQuery.isFetching || reportQuery.isFetching}
          showingPrevious={showingPrevious}
          onDatasetChange={changeDataset}
          onPipelineHashChange={changePipelineVersion}
          onConnectorRunsLimitChange={setConnectorRunsLimit}
          onRedactChange={setRedact}
          onExport={exportReport}
          onExportCompleteJson={exportComplete}
          onExportChartsJson={exportCharts}
          onRefresh={refresh}
        />
        {showingPrevious ? (
          <div className={styles.loadNotice} role="status">
            <span>
              当前显示上次报告：{snapshot.data.dataset_id} ·{' '}
              {snapshot.data.pipeline_hash === null ? '全部处理版本' : snapshot.data.pipeline_hash} ·{' '}
              {snapshot.params.connector_runs_limit === 0
                ? '不附带连接器运行记录'
                : `最多 ${snapshot.params.connector_runs_limit} 条连接器运行记录`}
              。所选新范围尚未取得，导出暂不可用。
            </span>
            <Button variant="ghost" onClick={restoreDisplayedScope}>
              使用已显示范围
            </Button>
          </div>
        ) : null}
        <ReportsResultSection
          report={report}
          connectorRunsIncluded={snapshot !== undefined && snapshot.params.connector_runs_limit > 0}
          datasetId={datasetId}
          showOnlyIssues={showOnlyIssues}
          onShowOnlyIssuesChange={setShowOnlyIssues}
          redact={redact}
          reportPending={datasetId.length > 0 && reportQuery.isPending}
          datasetsPending={datasetsQuery.isPending}
          reportPaused={reportQuery.isPaused}
          datasetsPaused={datasetsQuery.isPaused}
          isFetchingReport={reportQuery.isFetching}
          isFetchingDatasets={datasetsQuery.isFetching}
          onRetry={() => {
            void reportQuery.refetch()
          }}
          reportErrorMessage={reportQuery.isError ? formatApiError(reportQuery.error, '报告读取失败') : undefined}
          datasetsErrorMessage={
            datasetsQuery.isError ? formatApiError(datasetsQuery.error, '数据集读取失败') : undefined
          }
          onRetryDatasets={() => {
            void datasetsQuery.refetch()
          }}
          categoryBarData={categoryBarData}
          categoryStatus={categoriesQuery.status}
          categoryErrorMessage={categoryErrorMessage}
          isRefreshingCategories={categoriesQuery.isFetching}
          categoryPaused={categoriesQuery.isPaused}
          onRetryCategories={() => {
            void categoriesQuery.refetch()
          }}
        />
      </div>
    </AppFrame>
  )
}
