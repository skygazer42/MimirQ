'use client'

import { useQuery } from '@tanstack/react-query'

import { reportApi } from '@/lib/api/reports'
import { queryKeys } from '@/lib/query-keys'

import type { DatasetReport } from '@/types'

import type { ReportExportParams } from './types'

export function useDatasetReportQuery(
  datasetId: string,
  reportParams: Pick<ReportExportParams, 'pipeline_hash' | 'connector_runs_limit'>
) {
  return useQuery<DatasetReport>({
    queryKey: queryKeys.reports.dataset(datasetId, reportParams),
    queryFn: () => reportApi.getDatasetReport(datasetId, reportParams),
    enabled: Boolean(datasetId),
  })
}
