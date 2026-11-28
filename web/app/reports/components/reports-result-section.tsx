'use client'

import { AlertCircle, CheckCircle2, Database, RefreshCw, Upload } from '@/components/icons'
import { Button } from '@/components/ui/button'
import { LoadingButton } from '@/components/ui/loading-button'
import { WorkspaceNotice, WorkspaceNoticeStack } from '@/components/ui/operational-workspace'
import { SplitEmptyStudio } from '@/components/ui/split-empty-studio'
import { Link } from '@/i18n/navigation'
import type { DatasetReport } from '@/lib/report-schema'
import { ReportsDashboard, ReportsDashboardSkeleton, type ReportsDashboardProps } from './reports-dashboard'
import styles from '../reports.module.css'

const REPORT_EMPTY_STEPS = [
  {
    index: '01',
    title: '数据质量画像',
    description: '统计文档状态、分块覆盖率、语言分布与合规命中',
  },
  {
    index: '02',
    title: '召回与结构审计',
    description: '汇总门禁指标、处理版本差异与连接器运行状态',
  },
  {
    index: '03',
    title: '多格式脱敏导出',
    description: '导出 HTML、RAG 审计报告与 ZIP 归档',
  },
] as const

function ReportStudioIllustration() {
  return (
    <svg width="156" height="128" viewBox="0 0 156 128" fill="none" aria-hidden="true">
      <rect x="24" y="18" width="90" height="92" rx="10" fill="hsl(var(--card))" stroke="hsl(var(--border))" strokeWidth="1.25" />
      <line x1="38" y1="36" x2="74" y2="36" stroke="hsl(var(--muted-foreground) / 0.55)" strokeWidth="2.5" strokeLinecap="round" />
      <line x1="38" y1="47" x2="96" y2="47" stroke="hsl(var(--border))" strokeWidth="1.25" />
      <rect x="40" y="76" width="12" height="20" rx="2.5" fill="hsl(var(--muted))" />
      <rect x="58" y="64" width="12" height="32" rx="2.5" fill="hsl(var(--muted-foreground) / 0.45)" />
      <rect x="76" y="56" width="12" height="40" rx="2.5" fill="hsl(var(--accent) / 0.85)" />
      <circle cx="114" cy="86" r="21" fill="hsl(var(--accent))" />
      <path d="M107 89L112 83L116 86.5L122 79.5" stroke="hsl(var(--accent-foreground))" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

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
      <SplitEmptyStudio
        illustration={<ReportStudioIllustration />}
        title={datasetId.length === 0 ? '先选择数据集' : '尚未取得报告'}
        description="选择数据集以查看质量、召回审计与结构风险报告。"
        actions={
          <Button asChild className={styles.primary}>
            <Link href="/datasets">查看数据集</Link>
          </Button>
        }
        stepsHeading="报告分析维度"
        steps={REPORT_EMPTY_STEPS}
        shortcutsHeading="常用入口"
        shortcuts={[
          {
            key: 'ingestion',
            icon: <Upload />,
            title: '入库管理',
            description: '上传本地文档或接入外部数据源',
            href: '/knowledge/ingestion',
          },
          {
            key: 'knowledge',
            icon: <Database />,
            title: '前往知识库',
            description: '查看文档解析进度与分块状态',
            href: '/knowledge',
          },
          {
            key: 'evaluations',
            icon: <CheckCircle2 />,
            title: 'RAG 评测',
            description: '查看问答质量与检索集健康度',
            href: '/evaluations',
          },
        ]}
      />
    )
  }
  return (
    <>
      {datasetsErrorMessage !== undefined || reportErrorMessage !== undefined ? (
        <WorkspaceNoticeStack>
          {datasetsErrorMessage !== undefined ? (
            <WorkspaceNotice
              tone="warning"
              title="数据集目录更新失败，保留当前选择"
              retry={onRetryDatasets}
              retryLabel="重试数据集"
              pending={isFetchingDatasets}
            >
              {datasetsErrorMessage}
            </WorkspaceNotice>
          ) : null}
          {reportErrorMessage !== undefined ? (
            <WorkspaceNotice
              tone="warning"
              title="更新失败，保留已显示报告"
              retry={onRetry}
              retryLabel="重试"
              retryAriaLabel="重试报告"
              pending={isFetchingReport}
            >
              {reportErrorMessage}
            </WorkspaceNotice>
          ) : null}
        </WorkspaceNoticeStack>
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
      {report.profile.total_documents === 0 &&
      !isFetchingReport &&
      !isFetchingDatasets &&
      !reportPaused &&
      !datasetsPaused &&
      reportErrorMessage === undefined &&
      datasetsErrorMessage === undefined ? (
        <SplitEmptyStudio
          illustration={<ReportStudioIllustration />}
          title="当前报告范围没有文档"
          description="导入并解析文档后生成分析报告。"
          actions={
            <>
              <Button asChild className={styles.primary}>
                <Link href="/knowledge">前往知识库</Link>
              </Button>
              <LoadingButton variant="outline" loading={isFetchingReport} onClick={onRetry}>
                <RefreshCw />
                刷新报告
              </LoadingButton>
            </>
          }
          stepsHeading="报告分析维度"
          steps={REPORT_EMPTY_STEPS}
          shortcutsHeading="常用入口"
          shortcuts={[
            {
              key: 'ingestion',
              icon: <Upload />,
              title: '入库管理',
              description: '上传本地文档或接入外部数据源',
              href: '/knowledge/ingestion',
            },
            {
              key: 'datasets',
              icon: <Database />,
              title: '数据集管理',
              description: '查看或新建其他知识库数据集',
              href: '/datasets',
            },
            {
              key: 'evaluations',
              icon: <CheckCircle2 />,
              title: 'RAG 评测',
              description: '查看问答质量与检索集健康度',
              href: '/evaluations',
            },
          ]}
        />
      ) : (
        <ReportsDashboard {...props} report={report} />
      )}
    </>
  )
}
