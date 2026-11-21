'use client'

import { useCallback, useMemo, useState } from 'react'
import { useSearchParams } from 'next/navigation'
import { skipToken, useQuery } from '@tanstack/react-query'
import { RefreshCcw } from '@/components/icons'
import type { EChartsOption } from 'echarts'
import { datasetApi } from '@/lib/api/datasets'
import { documentApi } from '@/lib/api/documents'
import { observabilityApi } from '@/lib/api/observability'
import { formatApiError } from '@/lib/api-errors'
import type {
  DatasetPrecheckNearDupResponse,
  DatasetPrecheckSamplesResponse,
  DatasetPrecheckSummary,
  Document,
  IngestionDashboardSummaryResponse,
  TaskQueueObservabilitySnapshotResponse,
} from '@/types'
import { formatFileSize } from '@/lib/utils'
import { useDatasets } from '@/hooks/use-datasets'
import { usePathname, useRouter } from '@/i18n/navigation'
import { OperationalWorkspace, WorkspaceNotice } from '@/components/ui/operational-workspace'
import { PageLoading } from '@/components/ui/page-loading'
import { Button } from '@/components/ui/button'
import { ExecutionMonitorPanel } from '@/components/knowledge/ingestion/execution-monitor-panel'
import { IngestionDetailDialog } from '@/components/ingestion/ingestion-detail-dialog'
import {
  buildDocumentThroughputAreaRows,
  buildSalesAuditProfile,
  buildThroughputAreaRows,
  computeDocsPerMinute,
  computeDocumentDurationP90,
} from '@/components/ingestion/monitor-utils'
import {
  collectSalesAuditSampleFiles,
  estimatePdfPageCountFromSignals,
  formatClockLabel,
  formatClockSecondsLabel,
  formatMonthDayLabel,
  getDocumentRuntimeStats,
  getPersistedSampleDisposition,
  isExecutionMonitorDocument,
} from './document-signals'
import {
  buildDocumentProfileFile,
  buildPrecheckProfileFile,
  formatPdfPageAverageLabel,
  formatStructureAverageLabel,
  getQueueOutcomeReason,
  getRecentLogDetail,
  resolveFallbackComplexity,
} from './presentation'

const DATASET_ALL = '__all__'

const PRECHECK_SAMPLE_NUMERATOR = 3

const PRECHECK_SAMPLE_DENOMINATOR = 1000

const PRECHECK_SAMPLE_MAX = 2000

const EMPTY_INGESTION_SUMMARY: IngestionDashboardSummaryResponse = {
  window_hours: 0,
  bucket_minutes: 20,
  window_start: '',
  window_end: '',
  dataset_id: null,
  created_count: 0,
  by_status: {},
  by_stage_processing: {},
  avg_completed_latency_sec: null,
  top_error_reasons: {},
  timeseries: {
    ts_ms: [],
    completed: [],
    failed: [],
    quarantined: [],
    cancelled: [],
  },
}

export default function KnowledgeIngestionPageClient() {
  const searchParams = useSearchParams()

  const pathname = usePathname()

  const router = useRouter()

  const [datasetScope, setDatasetScope] = useState(searchParams.get('datasetId') || DATASET_ALL)

  const [activeDetailId, setActiveDetailId] = useState<string | null>(null)

  const selectedDatasetId = datasetScope === DATASET_ALL ? null : datasetScope

  const {
    datasets,
    isLoading: datasetsLoading,
    isFetching: datasetsFetching,
    error: datasetsError,
    refreshDatasets,
  } = useDatasets()

  const documentsQuery = useQuery({
    queryKey: ['knowledge-ingestion-documents', selectedDatasetId],
    queryFn: async ({ signal }) => {
      const response = await documentApi.list(
        {
          limit: 200,
          dataset_id: selectedDatasetId ?? undefined,
        },
        { signal },
      )
      return response.items
    },
    staleTime: 10_000,
    refetchInterval: 25_000,
  })

  const summaryQuery = useQuery<IngestionDashboardSummaryResponse | null>({
    queryKey: ['knowledge-ingestion-summary', selectedDatasetId],
    queryFn: () =>
      observabilityApi.getIngestionDashboardSummary({
        window_hours: 12,
        bucket_minutes: 20,
        dataset_id: selectedDatasetId ?? undefined,
      }),
    staleTime: 10_000,
    refetchInterval: 25_000,
  })

  const taskQueueQuery = useQuery<TaskQueueObservabilitySnapshotResponse | null>({
    queryKey: ['knowledge-ingestion-task-queue'],
    queryFn: () => observabilityApi.getTaskQueueSnapshot(),
    staleTime: 10_000,
    refetchInterval: 25_000,
  })

  const precheckRunsQuery = useQuery({
    queryKey: ['knowledge-ingestion-precheck-runs', selectedDatasetId],
    queryFn:
      selectedDatasetId === null
        ? skipToken
        : async ({ signal }) => {
            const response = await datasetApi.listPrecheckScanRuns(
              selectedDatasetId,
              { skip: 0, limit: 20 },
              { signal },
            )
            return response.items
          },
    staleTime: 10_000,
  })

  const latestPrecheckRun = useMemo(
    () =>
      precheckRunsQuery.data?.find((run) => run.status.toLowerCase() === 'completed') ??
      precheckRunsQuery.data?.[0] ??
      null,
    [precheckRunsQuery.data],
  )

  const precheckSummaryQuery = useQuery<DatasetPrecheckSummary | null>({
    queryKey: ['knowledge-ingestion-precheck-summary', selectedDatasetId, latestPrecheckRun?.id],
    queryFn:
      selectedDatasetId === null || latestPrecheckRun === null
        ? skipToken
        : ({ signal }) => datasetApi.getPrecheckSummary(selectedDatasetId, latestPrecheckRun.id, { signal }),
    staleTime: 10_000,
  })

  const precheckSamplesQuery = useQuery<DatasetPrecheckSamplesResponse | null>({
    queryKey: ['knowledge-ingestion-precheck-samples', selectedDatasetId, latestPrecheckRun?.id],
    queryFn:
      selectedDatasetId === null || latestPrecheckRun === null
        ? skipToken
        : ({ signal }) =>
            datasetApi.getPrecheckSamples(
              selectedDatasetId,
              latestPrecheckRun.id,
              { prefer_artifact: true, size: 12 },
              { signal },
            ),
    staleTime: 10_000,
  })

  const precheckNearDupQuery = useQuery<DatasetPrecheckNearDupResponse | null>({
    queryKey: ['knowledge-ingestion-precheck-near-dup', selectedDatasetId, latestPrecheckRun?.id],
    queryFn:
      selectedDatasetId === null || latestPrecheckRun === null
        ? skipToken
        : ({ signal }) => datasetApi.getPrecheckNearDups(selectedDatasetId, latestPrecheckRun.id, { signal }),
    staleTime: 10_000,
  })

  const documents = useMemo(() => documentsQuery.data ?? [], [documentsQuery.data])

  const executionDocuments = useMemo(() => documents.filter(isExecutionMonitorDocument), [documents])

  const summary = useMemo(() => summaryQuery.data ?? EMPTY_INGESTION_SUMMARY, [summaryQuery.data])

  const taskQueueSnapshot = taskQueueQuery.data ?? null

  const salesAuditSummary = precheckSummaryQuery.data ?? null

  const salesAuditSamples = precheckSamplesQuery.data ?? null

  const salesAuditNearDup = precheckNearDupQuery.data ?? null

  const selectedDatasetLabel = useMemo(() => {
    if (selectedDatasetId === null) return '全部项目'
    const selectedDataset = datasets.find((dataset) => dataset.id === selectedDatasetId)
    return selectedDataset === undefined || selectedDataset.name === '' ? selectedDatasetId : selectedDataset.name
  }, [datasets, selectedDatasetId])

  const datasetNotice =
    datasetsError !== null ? (
      <WorkspaceNotice retry={() => void refreshDatasets()} retryLabel="重新读取数据集目录" pending={datasetsFetching}>
        {formatApiError(datasetsError, '数据集目录读取失败，监控范围已保留')}
      </WorkspaceNotice>
    ) : datasetsFetching && !datasetsLoading ? (
      <p role="status" className="text-sm text-muted-foreground">
        正在更新数据集目录，保留当前范围。
      </p>
    ) : null

  const summaryThroughputRows = useMemo(() => buildThroughputAreaRows(summary.timeseries), [summary.timeseries])

  const documentThroughputRows = useMemo(
    () =>
      buildDocumentThroughputAreaRows(executionDocuments, {
        bucketMinutes: summary.bucket_minutes,
        maxRows: 96,
      }),
    [executionDocuments, summary.bucket_minutes],
  )

  const throughputRowsSource =
    summaryThroughputRows.length === 0 && documentThroughputRows.length > 0 ? 'documents' : 'backend'

  const throughputRows = throughputRowsSource === 'documents' ? documentThroughputRows : summaryThroughputRows

  const docsPerMinute = computeDocsPerMinute(throughputRows, summary.bucket_minutes)

  const durationP90Minutes = useMemo(() => computeDocumentDurationP90(executionDocuments), [executionDocuments])

  const failedDocumentCount = executionDocuments.filter(
    (document) => document.status === 'failed' || document.status === 'quarantined',
  ).length
  const completedDocumentCount = executionDocuments.filter((document) => document.status === 'completed').length
  const processedDocumentCount = completedDocumentCount + failedDocumentCount
  const executionFailureRate =
    processedDocumentCount === 0 ? 0 : Math.round((failedDocumentCount / processedDocumentCount) * 100)

  const executionPipelineState = useMemo(() => {
    const total = executionDocuments.length
    const parserFailures = failedDocumentCount
    const processingDocuments = executionDocuments.filter((document) => document.status.toLowerCase() === 'processing')
    const totalChunks = executionDocuments.reduce((sum, document) => sum + document.chunk_count, 0)

    const stageIncludes = (document: Document, keywords: string[]) => {
      const stage = document.current_stage?.toLowerCase()
      return keywords.some((keyword) => stage?.includes(keyword) === true)
    }
    const progressOf = (document: Document) => Math.max(0, Math.min(100, document.processing_progress))
    const isCompleted = (document: Document) => document.status.toLowerCase() === 'completed'
    const isTerminal = (document: Document) =>
      ['completed', 'failed', 'quarantined'].includes(document.status.toLowerCase())

    const parserDoneDocuments = executionDocuments.filter(
      (document) => isTerminal(document) || progressOf(document) >= 45,
    )
    const parserDoneDocumentIds = new Set(parserDoneDocuments.map((document) => document.id))
    const parserRunning = processingDocuments.filter(
      (document) =>
        !parserDoneDocumentIds.has(document.id) &&
        (progressOf(document) < 45 || stageIncludes(document, ['parse', 'parser', 'extract', 'ocr', 'mineru'])),
    ).length
    const parserDone = parserDoneDocuments.length - parserFailures
    const parserWaiting = total - parserDone - parserFailures - parserRunning

    const chunkerDoneDocuments = executionDocuments.filter(
      (document) => isCompleted(document) || progressOf(document) >= 85,
    )
    const chunkerDoneDocumentIds = new Set(chunkerDoneDocuments.map((document) => document.id))
    const chunkerRunning = processingDocuments.filter(
      (document) =>
        !chunkerDoneDocumentIds.has(document.id) &&
        (progressOf(document) >= 45 ||
          stageIncludes(document, ['chunk', 'split', 'segment', 'embed', 'index', 'vector', 'bm25'])),
    ).length
    const chunkerDone = chunkerDoneDocuments.length
    const chunkerWaiting = Math.max(0, total - chunkerDone - chunkerRunning)

    let governanceQueue = 0
    let governanceDone = 0
    for (const document of executionDocuments) {
      const disposition = getPersistedSampleDisposition(document)
      if (document.status === 'failed' || document.status === 'quarantined' || disposition === 'manual') {
        governanceQueue += 1
      } else if (document.status === 'completed' || disposition === 'approved') {
        governanceDone += 1
      }
    }
    const governanceWaiting = total - governanceDone - governanceQueue
    const exportReady = completedDocumentCount
    const exportWaiting = Math.max(0, total - exportReady)

    const getStageStatusLabel = ({
      done,
      running,
      waiting,
      failed = 0,
    }: {
      done: number
      running: number
      waiting: number
      failed?: number
    }) => {
      if (total === 0) return '未开始'
      if (failed > 0) return '有失败'
      if (running > 0) return '进行中'
      if (done >= total && waiting === 0) return '已完成'
      if (waiting > 0) return '等待中'
      return '未开始'
    }

    const parserStatusLabel = getStageStatusLabel({
      done: parserDone,
      failed: parserFailures,
      running: parserRunning,
      waiting: parserWaiting,
    })
    const chunkerStatusLabel = getStageStatusLabel({
      done: chunkerDone,
      running: chunkerRunning,
      waiting: chunkerWaiting,
    })
    const governanceStatusLabel = getStageStatusLabel({
      done: governanceDone,
      running: governanceQueue,
      waiting: governanceWaiting,
    })
    const exportStatusLabel = getStageStatusLabel({
      done: exportReady,
      running: 0,
      waiting: exportWaiting,
    })

    return {
      estimateLabel: taskQueueSnapshot?.enabled ? '队列联动' : '自动估算',
      cards: [
        {
          key: 'parser' as const,
          label: '解析',
          statusLabel: parserStatusLabel,
          metrics: [
            ['完成文档', `${parserDone}`],
            ['失败', `${parserFailures}`],
            ['待处理', `${parserWaiting}`],
          ],
        },
        {
          key: 'chunker' as const,
          label: '切块',
          statusLabel: chunkerStatusLabel,
          metrics: [
            ['完成文档', `${chunkerDone}`],
            ['分块数', String(totalChunks)],
            ['等待中', `${chunkerWaiting}`],
          ],
        },
        {
          key: 'governance' as const,
          label: '治理',
          statusLabel: governanceStatusLabel,
          metrics: [
            ['已通过', `${governanceDone}`],
            ['待复核', `${governanceQueue}`],
            ['等待中', `${governanceWaiting}`],
          ],
        },
        {
          key: 'export' as const,
          label: '索引',
          statusLabel: exportStatusLabel,
          metrics: [
            ['可入索引', `${exportReady}`],
            ['待同步', `${exportWaiting}`],
            ['范围', selectedDatasetId ? '单库' : '跨库'],
          ],
        },
      ],
    }
  }, [completedDocumentCount, executionDocuments, failedDocumentCount, selectedDatasetId, taskQueueSnapshot?.enabled])

  const executionPipelineCards = executionPipelineState.cards

  const recentQueueOutcomes = useMemo(() => {
    const outcomes = taskQueueSnapshot?.recent_job_outcomes ?? []
    return outcomes
      .filter((item) => selectedDatasetId === null || item.dataset_id === selectedDatasetId)
      .slice(0, 5)
      .map((item, index) => {
        const jobName =
          [item.job_name, item.run_id, item.document_id].find(
            (value): value is string => typeof value === 'string' && value.trim().length > 0,
          ) ?? '未记录任务'
        const ok = item.ok === true
        const finishedAt = typeof item.finished_at === 'string' ? item.finished_at : undefined
        const elapsed = item.elapsed_sec
        const outcomeDetail =
          ok && typeof elapsed === 'number' && Number.isFinite(elapsed) && elapsed > 0
            ? `${elapsed.toFixed(2)}s`
            : getQueueOutcomeReason(item, ok)
        return {
          detail: `${jobName} · ${outcomeDetail}`,
          id: `${jobName}-${index}`,
          stage: ok ? '队列完成' : '队列异常',
          time: finishedAt === undefined ? '—' : formatClockSecondsLabel(finishedAt),
        }
      })
  }, [selectedDatasetId, taskQueueSnapshot?.recent_job_outcomes])

  const executionTaskRows = useMemo(
    () => [...executionDocuments].sort((left, right) => Date.parse(right.updated_at) - Date.parse(left.updated_at)),
    [executionDocuments],
  )

  const executionRecentLogs = useMemo(() => {
    if (recentQueueOutcomes.length > 0) return recentQueueOutcomes

    return executionTaskRows.slice(0, 5).map((document) => {
      const status = document.status.toLowerCase()
      return {
        id: document.id,
        time: formatClockSecondsLabel(document.updated_at),
        stage: document.current_stage ?? '系统',
        detail: getRecentLogDetail(status, document.filename),
      }
    })
  }, [executionTaskRows, recentQueueOutcomes])

  const forecastPoints = useMemo(() => {
    const last = throughputRows.at(-1)
    if (last === undefined || docsPerMinute === null) return []
    return Array.from({ length: 3 }, (_, index) => ({
      ts: last.ts + (index + 1) * summary.bucket_minutes * 60_000,
      total: Number((docsPerMinute * summary.bucket_minutes).toFixed(1)),
    }))
  }, [docsPerMinute, summary.bucket_minutes, throughputRows])

  const predictionOption = useMemo<EChartsOption>(() => {
    const actualSeries = throughputRows.map((row) => [row.ts, row.total])
    const hasActualSeries = actualSeries.length > 0
    const lastActualPoint = actualSeries.at(-1)
    const forecastSeries = lastActualPoint
      ? [[lastActualPoint[0], lastActualPoint[1]], ...forecastPoints.map((row) => [row.ts, row.total])]
      : []

    return {
      tooltip: {
        trigger: 'axis',
      },
      grid: {
        left: 40,
        right: 16,
        top: 24,
        bottom: 28,
      },
      xAxis: hasActualSeries
        ? {
            type: 'time',
            axisLabel: {
              color: '#64748b',
              formatter: (value: number) =>
                throughputRowsSource === 'documents' ? formatMonthDayLabel(value) : formatClockLabel(value),
            },
            axisLine: {
              lineStyle: { color: 'rgba(100,116,139,0.35)' },
            },
          }
        : {
            type: 'category',
            boundaryGap: false,
            data: ['-60m', '-45m', '-30m', '-15m', '现在'],
            axisLabel: { color: '#64748b', fontSize: 9 },
            axisLine: {
              lineStyle: { color: 'rgba(100,116,139,0.35)' },
            },
            axisTick: { show: false },
          },
      yAxis: {
        type: 'value',
        min: 0,
        max: hasActualSeries ? undefined : 4,
        interval: hasActualSeries ? undefined : 1,
        axisLabel: { color: '#64748b' },
        splitLine: {
          lineStyle: { color: 'rgba(148,163,184,0.18)' },
        },
      },
      series: [
        {
          name: throughputRowsSource === 'documents' ? '文档完成数' : '处理文件数',
          type: 'line',
          smooth: true,
          showSymbol: !hasActualSeries,
          symbolSize: hasActualSeries ? 0 : 4,
          lineStyle: {
            color: '#0284c7',
            opacity: hasActualSeries ? 1 : 0.42,
            width: hasActualSeries ? 2.5 : 1.5,
          },
          areaStyle: {
            color: hasActualSeries ? 'rgba(2,132,199,0.14)' : 'rgba(2,132,199,0.035)',
          },
          data: hasActualSeries ? actualSeries : [0, 0, 0, 0, 0],
        },
        {
          name: '预测',
          type: 'line',
          smooth: true,
          showSymbol: false,
          lineStyle: { color: '#b45309', width: 2, type: 'dashed' },
          areaStyle: {
            color: 'rgba(180,83,9,0.08)',
          },
          data: forecastSeries,
        },
      ],
    }
  }, [forecastPoints, throughputRows, throughputRowsSource])

  const costRadarValues = useMemo(() => {
    const pdfDocuments = executionDocuments.filter((document) => document.file_type.toLowerCase() === 'pdf')
    const pdfCount = pdfDocuments.length
    const totalFiles = Math.max(1, executionDocuments.length)
    const precheckSampleFiles = collectSalesAuditSampleFiles(salesAuditSamples)
    const totalCharacters = executionDocuments.reduce((sum, document) => sum + document.total_characters, 0)
    const totalPdfPagesFromSamples = precheckSampleFiles.reduce(
      (sum, file) => sum + (file.pdf_pages?.page_count ?? 0),
      0,
    )
    const totalPdfPagesFromDocuments = pdfDocuments.reduce(
      (sum, document) => sum + getDocumentRuntimeStats(document).pageCount,
      0,
    )
    const totalPdfPagesEstimated = pdfDocuments.reduce(
      (sum, document) =>
        sum +
        estimatePdfPageCountFromSignals({
          characters: document.total_characters,
          fileSize: document.file_size,
        }),
      0,
    )
    const totalPdfPages = totalPdfPagesFromSamples || totalPdfPagesFromDocuments || totalPdfPagesEstimated
    const totalImageAssets = executionDocuments.reduce(
      (sum, document) => sum + getDocumentRuntimeStats(document).imageCount,
      0,
    )
    const totalSizeMb = executionDocuments.reduce((sum, document) => sum + document.file_size, 0) / (1024 * 1024)

    return [
      Math.min(100, Math.round((pdfCount / totalFiles) * 100)),
      Math.min(100, Math.round((totalPdfPages / Math.max(1, pdfCount * 80)) * 100)),
      Math.min(100, Math.round((totalCharacters / Math.max(1, totalFiles * 50_000)) * 100)),
      Math.min(100, Math.round((totalSizeMb / Math.max(1, totalFiles * 20)) * 100)),
      Math.min(100, Math.round((totalImageAssets / Math.max(1, pdfCount * 120)) * 100)),
      durationP90Minutes === null ? 0 : Math.min(100, Math.round((durationP90Minutes / 20) * 100)),
      executionFailureRate,
    ]
  }, [durationP90Minutes, executionDocuments, executionFailureRate, salesAuditSamples])

  const radarOption = useMemo<EChartsOption>(
    () => ({
      tooltip: { trigger: 'item' },
      radar: {
        radius: '56%',
        center: ['50%', '54%'],
        splitNumber: 4,
        axisName: { color: '#475569', fontSize: 9 },
        splitLine: { lineStyle: { color: 'rgba(148,163,184,0.22)' } },
        splitArea: {
          areaStyle: {
            color: ['rgba(148,163,184,0.08)', 'rgba(148,163,184,0.025)'],
          },
        },
        indicator: [
          { name: 'PDF 占比', max: 100 },
          { name: '页数压力', max: 100 },
          { name: '字数压力', max: 100 },
          { name: '体积压力', max: 100 },
          { name: '图片资源', max: 100 },
          { name: '耗时压力', max: 100 },
          { name: '失败重试', max: 100 },
        ],
      },
      series: [
        {
          type: 'radar',
          data: [
            {
              value: costRadarValues,
              areaStyle: { color: 'hsl(var(--primary) / 0.12)' },
              lineStyle: { color: 'hsl(var(--primary))', width: 2 },
              itemStyle: { color: 'hsl(var(--primary))' },
            },
          ],
        },
      ],
    }),
    [costRadarValues],
  )

  const salesAuditProfile = useMemo(
    () => (salesAuditSummary ? buildSalesAuditProfile(salesAuditSummary, salesAuditNearDup) : null),
    [salesAuditNearDup, salesAuditSummary],
  )

  const executionBatchAnalysis = useMemo(() => {
    const average = (values: number[]) => {
      const valid = values.filter((value) => Number.isFinite(value) && value > 0)
      if (!valid.length) return 0
      return valid.reduce((sum, value) => sum + value, 0) / valid.length
    }
    const clampScore = (value: number) => Math.max(0, Math.min(100, Math.round(value)))

    const totalFiles = salesAuditSummary?.total_files ?? executionDocuments.length
    const totalSizeBytes =
      salesAuditSummary?.total_size_bytes ?? executionDocuments.reduce((sum, document) => sum + document.file_size, 0)
    const fileTypes =
      salesAuditSummary === null
        ? executionDocuments.map((document) => document.file_type)
        : Object.entries(salesAuditSummary.by_file_type).flatMap(([fileType, count]) => (count > 0 ? [fileType] : []))
    const presentTypeCount = new Set(
      fileTypes.map((fileType) => fileType.trim().toLowerCase()).filter((fileType) => fileType !== ''),
    ).size
    const pdfTotal =
      salesAuditSummary === null
        ? executionDocuments.filter((document) => document.file_type.toLowerCase() === 'pdf').length
        : salesAuditSummary.pdf_scan.scanned +
          salesAuditSummary.pdf_scan.not_scanned +
          salesAuditSummary.pdf_scan.unknown
    const totalCharacters = executionDocuments.reduce((sum, document) => sum + document.total_characters, 0)
    const samplePool = collectSalesAuditSampleFiles(salesAuditSamples)
    const needsReviewCount = Object.values(salesAuditSamples?.needs_review ?? {}).flat().length
    const hasPrecheckProfile = salesAuditSummary !== null || salesAuditSamples !== null
    const profileFiles = hasPrecheckProfile
      ? samplePool.map(buildPrecheckProfileFile)
      : executionDocuments.map(buildDocumentProfileFile)
    const pdfProfileFiles = profileFiles.filter((file) => file.fileType.toLowerCase() === 'pdf')
    const avgPdfChars = average(pdfProfileFiles.map((file) => file.chars))
    const avgPdfPages = average(pdfProfileFiles.map((file) => file.pdfPages))
    const avgPdfImages = average(pdfProfileFiles.map((file) => file.imageCount))
    const avgPdfTables = average(pdfProfileFiles.map((file) => file.tableCount))
    const avgPdfBlocks = average(pdfProfileFiles.map((file) => file.blockCount))
    const hasPdfProfiles = pdfProfileFiles.length > 0
    const hasEstimatedPdfPages = pdfProfileFiles.some((file) => file.pdfPages > 0 && file.pageCountEstimated)
    const avgSizeMb = average(profileFiles.map((file) => file.fileSize)) / (1024 * 1024)
    const proportionalSampleTarget = totalFiles
      ? Math.ceil((totalFiles * PRECHECK_SAMPLE_NUMERATOR) / PRECHECK_SAMPLE_DENOMINATOR)
      : 0
    const sampleTarget = totalFiles
      ? Math.min(totalFiles, Math.min(PRECHECK_SAMPLE_MAX, Math.max(1, presentTypeCount, proportionalSampleTarget)))
      : 0
    const sampleTargetDetail =
      totalFiles > 0
        ? `3/1000 抽样 · 覆盖 ${presentTypeCount} 类，每类至少 1 个 / 总 ${totalFiles.toLocaleString()} 个`
        : '等待文件进入监控'
    const pdfRatio = totalFiles ? pdfTotal / totalFiles : 0
    const fallbackComplexity = resolveFallbackComplexity({
      durationP90: durationP90Minutes,
      executionFailureRate,
      pdfRatio,
      totalCharacters,
      totalSizeBytes,
    })

    return {
      complexity: salesAuditProfile?.complexity ?? fallbackComplexity,
      sampleTarget,
      sourceLabel: salesAuditSummary ? '来自最新预检扫描' : '来自后端文档统计',
      totalFiles,
      pricingMode: salesAuditProfile?.pricingMode ?? (fallbackComplexity === '高' ? 'POC优先' : '阶梯报价'),
      distributionBars: [
        {
          color: '#2563eb',
          detail: totalFiles ? `${pdfTotal.toLocaleString()} / ${totalFiles.toLocaleString()} 个` : '等待文件进入监控',
          label: 'PDF 占比',
          score: clampScore(pdfRatio * 100),
          value: totalFiles ? `${Math.round(pdfRatio * 100)}%` : '待统计',
        },
        {
          color: '#0f766e',
          detail: '按 PDF 样本 text_characters 均值',
          label: 'PDF 平均字数',
          score: clampScore((avgPdfChars / 50_000) * 100),
          value: avgPdfChars ? `${Math.round(avgPdfChars).toLocaleString()} chars` : '待统计',
        },
        {
          color: '#f97316',
          detail: '优先使用后端 page_count，缺失时才按字数/体量估算',
          label: 'PDF 平均页数',
          score: clampScore((avgPdfPages / 80) * 100),
          value: formatPdfPageAverageLabel({
            avgPdfPages,
            hasEstimatedPdfPages,
            hasPdfProfiles,
          }),
        },
        ...(hasPrecheckProfile
          ? []
          : [
              {
                color: '#64748b',
                label: 'PDF 平均图片数',
                score: clampScore((avgPdfImages / 120) * 100),
                value: hasPdfProfiles ? `${Math.round(avgPdfImages)} 个` : '无 PDF',
              },
              {
                color: '#7c3aed',
                label: '表格/结构块',
                score: clampScore(Math.max(avgPdfTables * 10, avgPdfBlocks / 8)),
                value: formatStructureAverageLabel({ avgPdfBlocks, avgPdfTables, hasPdfProfiles }),
              },
            ]),
        {
          color: '#0891b2',
          detail: '按当前批次文件均值',
          label: '平均体积',
          score: clampScore((avgSizeMb / 20) * 100),
          value: avgSizeMb ? `${avgSizeMb.toFixed(1)} MB` : '待统计',
        },
        {
          color: '#dc2626',
          detail: `失败或隔离 ${failedDocumentCount} 个`,
          label: '失败或隔离占比',
          score: clampScore(executionFailureRate),
          value: processedDocumentCount === 0 ? '待统计' : `${executionFailureRate}%`,
        },
      ],
      pageCountNote: hasEstimatedPdfPages ? '缺失的 PDF 页数根据字数和文件体积估算。' : undefined,
      samplePoolLabel:
        salesAuditSamples === null
          ? '暂无预检样本数据'
          : `已回传样本池 ${samplePool.length} 个 · 大文件 ${salesAuditSamples.top_large_files.length} · 长文本 ${salesAuditSamples.top_long_text.length} · 复核 ${needsReviewCount}`,
      sampleTargetDetail,
      totalSizeLabel: formatFileSize(totalSizeBytes),
    }
  }, [
    durationP90Minutes,
    executionDocuments,
    executionFailureRate,
    salesAuditProfile?.complexity,
    salesAuditProfile?.pricingMode,
    salesAuditSamples,
    salesAuditSummary,
    failedDocumentCount,
    processedDocumentCount,
  ])

  const batchProfileBarOption = useMemo<EChartsOption>(
    () => ({
      grid: { bottom: 8, left: 86, right: 74, top: 8 },
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'shadow' },
      },
      xAxis: {
        max: 100,
        min: 0,
        splitLine: { lineStyle: { color: 'rgba(148,163,184,0.14)' } },
        type: 'value',
      },
      yAxis: {
        axisLabel: { color: '#475569', fontSize: 10 },
        axisLine: { show: false },
        axisTick: { show: false },
        data: executionBatchAnalysis.distributionBars.map((item) => item.label),
        inverse: true,
        type: 'category',
      },
      series: [
        {
          barWidth: 13,
          data: executionBatchAnalysis.distributionBars.map((item) => ({
            itemStyle: { color: item.color },
            value: item.score,
          })),
          label: {
            color: '#64748b',
            fontSize: 10,
            formatter: (params: { dataIndex: number }) =>
              executionBatchAnalysis.distributionBars[params.dataIndex]?.value ?? '',
            position: 'right',
            show: true,
          },
          name: '批次画像',
          type: 'bar',
        },
      ],
    }),
    [executionBatchAnalysis.distributionBars],
  )

  const handleOpenAuditSnapshot = useCallback((documentId: string) => {
    setActiveDetailId(documentId)
  }, [])

  const handleDatasetScopeChange = useCallback(
    (value: string) => {
      setDatasetScope(value)
      setActiveDetailId(null)

      const params = new URLSearchParams(searchParams.toString())
      if (value === DATASET_ALL) {
        params.delete('datasetId')
      } else {
        params.set('datasetId', value)
      }
      params.set('mode', 'execution-monitor')
      router.replace(`${pathname}?${params.toString()}`)
    },
    [pathname, router, searchParams],
  )

  const handleOpenIngestionOperation = useCallback(() => {
    const params = new URLSearchParams(searchParams.toString())
    params.delete('mode')

    const query = params.toString()
    router.replace(query ? `${pathname}?${query}` : pathname)
  }, [pathname, router, searchParams])

  return (
    <OperationalWorkspace
      title="入库执行监控"
      icon="ingestion-monitor"
      context={selectedDatasetLabel}
      actions={
        <>
          <Button
            variant="outline"
            onClick={() => {
              void documentsQuery.refetch()
              void summaryQuery.refetch()
              void taskQueueQuery.refetch()
            }}
            disabled={documentsQuery.isFetching}
          >
            <RefreshCcw />
            重新读取
          </Button>
          <Button onClick={handleOpenIngestionOperation}>入库操作</Button>
        </>
      }
      toolbar={
        <>
          <label htmlFor="execution-dataset" className="text-sm text-muted-foreground">
            数据集
          </label>
          <select
            id="execution-dataset"
            value={datasetScope}
            disabled={datasetsLoading}
            onChange={(event) => handleDatasetScopeChange(event.target.value)}
            className="h-10 max-w-full rounded-md border border-border bg-background px-3 text-sm"
          >
            <option value={DATASET_ALL}>全部数据集</option>
            {selectedDatasetId !== null && !datasets.some((dataset) => dataset.id === selectedDatasetId) ? (
              <option value={selectedDatasetId} disabled>
                已选数据集：{selectedDatasetId}
              </option>
            ) : null}
            {datasets.map((item) => (
              <option key={item.id} value={item.id}>
                {item.name === '' ? item.id : item.name}
              </option>
            ))}
          </select>
          <span className="text-sm text-muted-foreground">最近载入的任务 · 每 25 秒更新</span>
        </>
      }
    >
      {datasetNotice}
      {documentsQuery.isError ? (
        <WorkspaceNotice
          retry={() => {
            void documentsQuery.refetch()
          }}
        >
          {formatApiError(documentsQuery.error, '任务读取失败')}
        </WorkspaceNotice>
      ) : documentsQuery.isLoading ? (
        <PageLoading message="正在读取执行任务…" className="min-h-48" />
      ) : (
        <ExecutionMonitorPanel
          batchProfileBarOption={batchProfileBarOption}
          executionBatchAnalysis={executionBatchAnalysis}
          executionPipelineCards={executionPipelineCards}
          executionPipelineEstimateLabel={executionPipelineState.estimateLabel}
          executionPipelineWarning={
            taskQueueSnapshot?.enabled && !taskQueueSnapshot.broker_up ? taskQueueSnapshot.error || 'Broker 异常' : null
          }
          executionRecentLogs={executionRecentLogs}
          executionTaskRows={executionTaskRows}
          predictionOption={predictionOption}
          radarOption={radarOption}
          selectedDatasetId={selectedDatasetId}
          onOpenAuditSnapshot={handleOpenAuditSnapshot}
          onOpenIngestionOperation={handleOpenIngestionOperation}
          onScopeAllProjects={() => handleDatasetScopeChange(DATASET_ALL)}
        />
      )}
      {summaryQuery.isError ? (
        <WorkspaceNotice
          retry={() => {
            void summaryQuery.refetch()
          }}
        >
          {formatApiError(summaryQuery.error, '运行统计暂不可用')}
        </WorkspaceNotice>
      ) : null}
      {taskQueueQuery.isError ? (
        <WorkspaceNotice
          retry={() => {
            void taskQueueQuery.refetch()
          }}
        >
          {formatApiError(taskQueueQuery.error, '任务队列状态暂不可用')}
        </WorkspaceNotice>
      ) : null}
      <IngestionDetailDialog
        open={activeDetailId !== null}
        documentId={activeDetailId}
        onOpenChange={(open) => {
          if (!open) setActiveDetailId(null)
        }}
      />
    </OperationalWorkspace>
  )
}
