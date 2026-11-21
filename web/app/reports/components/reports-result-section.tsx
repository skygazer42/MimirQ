'use client'

import { AlertCircle } from '@/components/icons'
import { LoadingButton } from '@/components/ui/loading-button'
import { Link } from '@/i18n/navigation'
import type { DatasetReport } from '@/lib/report-schema'
import { ReportsDashboard, ReportsDashboardSkeleton, type ReportsDashboardProps } from './reports-dashboard'
import styles from '../reports.module.css'

type Props = Omit<ReportsDashboardProps, 'report'> & {
  report: DatasetReport | undefined
  datasetId: string
  reportPending: boolean
  datasetsPending: boolean
  reportPaused: boolean
  datasetsPaused: boolean
  isFetchingReport: boolean
  isFetchingDatasets: boolean
  reportErrorMessage: string | undefined
  onRetry: () => void
  datasetsErrorMessage: string | undefined
  onRetryDatasets: () => void
}
export function ReportsResultSection({
  datasetId,
  reportPending,
  datasetsPending,
  reportPaused,
  datasetsPaused,
  isFetchingReport,
  isFetchingDatasets,
  reportErrorMessage,
  onRetry,
  datasetsErrorMessage,
  onRetryDatasets,
  report,
  ...props
}: Readonly<Props>) {
  if (report === undefined) {
    const reportFailed = reportErrorMessage !== undefined
    const error = reportErrorMessage ?? datasetsErrorMessage
    if (error !== undefined)
      return (
        <div className={styles.pageState} role="alert">
          <AlertCircle />
          <h2>{reportFailed ? '报告读取失败' : '数据集读取失败'}</h2>
          <p>{error}</p>
          <LoadingButton
            loading={reportFailed ? isFetchingReport : isFetchingDatasets}
            variant="outline"
            aria-label={reportFailed ? '重试报告' : '重试数据集'}
            onClick={reportFailed ? onRetry : onRetryDatasets}
          >
            重试
          </LoadingButton>
        </div>
      )
    if (reportPaused || datasetsPaused)
      return (
        <div className={styles.pageState} role="status">
          <h2>读取已暂停</h2>
          <p>网络恢复后会继续读取，当前尚未取得报告。</p>
        </div>
      )
    if (reportPending || datasetsPending) return <ReportsDashboardSkeleton />
    return (
      <div className={styles.pageState}>
        <h2>{datasetId.length === 0 ? '先选择数据集' : '尚未取得报告'}</h2>
        <p>选择数据集后可以查看报告。</p>
        <Link href="/datasets">查看数据集</Link>
      </div>
    )
  }
  return (
    <>
      {datasetsErrorMessage !== undefined ? (
        <div className={styles.loadNotice} role="alert">
          <span>数据集目录更新失败，保留当前选择：{datasetsErrorMessage}</span>
          <LoadingButton loading={isFetchingDatasets} variant="ghost" onClick={onRetryDatasets}>
            重试数据集
          </LoadingButton>
        </div>
      ) : null}
      {reportErrorMessage !== undefined ? (
        <div className={styles.loadNotice} role="alert">
          <span>更新失败，保留已显示报告：{reportErrorMessage}</span>
          <LoadingButton loading={isFetchingReport} variant="ghost" aria-label="重试报告" onClick={onRetry}>
            重试
          </LoadingButton>
        </div>
      ) : null}
      {reportPaused ? (
        <div className={styles.loadNotice} role="status">
          报告更新已暂停，保留当前快照并等待网络恢复。
        </div>
      ) : null}
      {datasetsPaused ? (
        <div className={styles.loadNotice} role="status">
          数据集目录更新已暂停，保留当前选择并等待网络恢复。
        </div>
      ) : null}
      <ReportsDashboard {...props} report={report} />
    </>
  )
}
