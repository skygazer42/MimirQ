'use client'

import { useEffect, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useParams } from 'next/navigation'
import { toast } from 'sonner'
import { Activity, BarChart3, ChevronDown, Download, MoreHorizontal } from '@/components/icons'
import { Bar, BarChart, CartesianGrid, Pie, PieChart, Tooltip, XAxis, YAxis } from 'recharts'

import { AppFrame } from '@/components/app-frame'
import {
  OperationalWorkspace,
  WorkspaceMetrics,
  WorkspaceNotice,
  workspaceStyles as ws,
} from '@/components/ui/operational-workspace'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { Panel } from '@/components/ui/panel'
import { Button } from '@/components/ui/button'
import { EmptyState } from '@/components/ui/empty-state'
import { SafeResponsiveChart } from '@/components/ui/safe-responsive-chart'

import { buildDatasetProfileModel } from '@/lib/dataset-profile-model'
import { datasetApi } from '@/lib/api/datasets'
import { formatApiError } from '@/lib/api-errors'
import { reportClientError } from '@/lib/client-logging'
import { datasetHealthToMarkdown } from '@/lib/dataset-health-export'
import { downloadBlob } from '@/lib/download'
import { queryKeys } from '@/lib/query-keys'
import { sanitizeFilename } from '@/lib/sanitize'
import { formatDate, formatFileSize } from '@/lib/utils'
import { Link, useRouter } from '@/i18n/navigation'
import styles from './health.module.css'

const PIE_COLORS = [
  'hsl(var(--chart-5))',
  'hsl(var(--chart-2))',
  'hsl(var(--chart-4))',
  'hsl(var(--chart-6))',
  'hsl(var(--chart-3))',
  'hsl(var(--chart-1))',
  'hsl(var(--chart-8))',
] as const

export default function DatasetHealthPage() {
  const router = useRouter()
  const { id: datasetId } = useParams<{ id: string }>()

  const datasetQuery = useQuery({
    queryKey: queryKeys.datasets.detail(datasetId),
    queryFn: ({ signal }) => datasetApi.get(datasetId, { signal }),
  })

  const healthQuery = useQuery({
    queryKey: queryKeys.datasets.health(datasetId),
    queryFn: ({ signal }) => datasetApi.getHealth(datasetId, { signal }),
  })

  const dataset = datasetQuery.data ?? null
  const health = healthQuery.data ?? null
  const isLoading = datasetQuery.isFetching || healthQuery.isFetching

  function refreshHealth() {
    void datasetQuery.refetch()
    void healthQuery.refetch()
  }

  const loadError = datasetQuery.error ?? healthQuery.error

  useEffect(() => {
    if (!loadError) return
    reportClientError('Failed to load dataset health', loadError)
  }, [loadError])

  const profile = health?.profile

  const model = useMemo(
    () => (profile === undefined ? undefined : buildDatasetProfileModel(profile, PIE_COLORS)),
    [profile],
  )

  const topFindings = useMemo(() => {
    if (profile === undefined) return undefined
    return profile.findings
      .filter((finding) => finding.count > 0)
      .sort((a, b) => b.count - a.count)
      .slice(0, 8)
  }, [profile])
  const totalSizeLabel = profile === undefined ? '未取得' : formatFileSize(profile.total_size_bytes)
  const scannedPdfLabel =
    model === undefined || profile === undefined ? '未取得' : `${profile.pdf_scan.scanned}/${model.pdfCount}`
  const piiLabel = model === undefined ? '未取得' : model.piiRecorded ? model.piiCount : '无命中记录'
  const secretsLabel = model === undefined ? '未取得' : model.secretsRecorded ? model.secretsCount : '无命中记录'
  const hasUnrecordedHits = model !== undefined && (!model.piiRecorded || !model.secretsRecorded)
  const generatedAtLabel = health === null ? '未取得' : formatDate(health.generated_at)

  const exportHealth = (format: 'json' | 'markdown') => {
    if (dataset === null || health === null) return
    try {
      const exportPayload = {
        schema: 'mimirq.dataset_health.v1',
        exported_at: new Date().toISOString(),
        dataset: { id: dataset.id, name: dataset.name },
        health,
      }
      const filename = sanitizeFilename(dataset.name)
      const text = format === 'json' ? JSON.stringify(exportPayload, null, 2) : datasetHealthToMarkdown(exportPayload)
      downloadBlob(
        `${filename}.health.${format === 'json' ? 'json' : 'md'}`,
        new Blob([text], { type: format === 'json' ? 'application/json' : 'text/markdown;charset=utf-8' }),
      )
      toast.success('已发起健康报告下载')
    } catch (error) {
      reportClientError('Failed to export dataset health', error)
      toast.error(formatApiError(error, '健康报告导出失败'))
    }
  }
  return (
    <AppFrame>
      <OperationalWorkspace
        title="健康概览"
        icon="diagnostics"
        context={dataset?.name ?? (datasetQuery.isPending ? '正在读取数据集…' : '数据集未取得')}
        back={() => router.push('/datasets')}
        actions={
          <>
            <Button variant="outline" onClick={() => router.push(`/datasets/${datasetId}/profile`)}>
              <BarChart3 />
              数据画像
            </Button>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="outline" aria-label="导出健康报告" disabled={dataset === null || health === null}>
                  <Download />
                  导出
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem onSelect={() => exportHealth('json')}>JSON 报告</DropdownMenuItem>
                <DropdownMenuItem onSelect={() => exportHealth('markdown')}>Markdown 报告</DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="ghost" size="icon" aria-label="数据集操作">
                  <MoreHorizontal />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem onSelect={() => router.push(`/datasets/${datasetId}/precheck`)}>
                  文档预检
                </DropdownMenuItem>
                <DropdownMenuItem onSelect={() => router.push(`/datasets/${datasetId}/ingestion`)}>
                  入库策略
                </DropdownMenuItem>
                <DropdownMenuItem onSelect={() => router.push(`/datasets/${datasetId}/tables`)}>
                  表格资产
                </DropdownMenuItem>
                <DropdownMenuItem disabled={isLoading} onSelect={refreshHealth}>
                  重新读取健康概览
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </>
        }
      >
        {loadError ? (
          <WorkspaceNotice
            placement={health ? 'floating' : 'inline'}
            tone={health ? 'warning' : 'error'}
            title={health ? '更新失败，保留上次快照' : '健康概览读取失败'}
            error={loadError}
            fallbackMessage="健康概览读取失败"
            retry={refreshHealth}
            retryLabel="重新读取健康概览"
            pending={isLoading}
          />
        ) : null}
        {health !== null && model !== undefined ? (
          <>
            <WorkspaceMetrics
              className={hasUnrecordedHits ? styles.metricsWithNotes : undefined}
              items={[
                { label: '文档总数', value: <span data-health-document-count>{health.profile.total_documents}</span> },
                { label: '总大小', value: totalSizeLabel },
                {
                  label: '处理失败',
                  value: (
                    <Link
                      href={
                        '/knowledge?' + new URLSearchParams({ dataset: datasetId, status: 'failed', lifecycle: 'all' })
                      }
                      aria-label="查看处理失败文档"
                      className="inline-flex min-h-11 min-w-11 items-center underline decoration-dotted underline-offset-4 sm:min-h-0 sm:min-w-0"
                    >
                      {health.ingestion.failed}
                    </Link>
                  ),
                  tone: health.ingestion.failed > 0 ? 'danger' : undefined,
                },
                {
                  label: '隔离文档',
                  value: (
                    <Link
                      href={
                        '/knowledge?' +
                        new URLSearchParams({ dataset: datasetId, status: 'quarantined', lifecycle: 'all' })
                      }
                      aria-label="查看隔离文档"
                      className="inline-flex min-h-11 min-w-11 items-center underline decoration-dotted underline-offset-4 sm:min-h-0 sm:min-w-0"
                    >
                      {health.ingestion.quarantined}
                    </Link>
                  ),
                  tone: health.ingestion.quarantined > 0 ? 'warning' : undefined,
                },
                { label: '扫描版 PDF', value: scannedPdfLabel },
                ...(model.piiRecorded ? [{ label: '个人信息命中', value: piiLabel }] : []),
                ...(model.secretsRecorded ? [{ label: '密钥命中', value: secretsLabel }] : []),
              ]}
            />
            {hasUnrecordedHits ? (
              <p className={styles.metricNotes} aria-label="命中记录说明">
                {!model.piiRecorded ? <span>个人信息命中：{piiLabel}</span> : null}
                {!model.secretsRecorded ? <span>密钥命中：{secretsLabel}</span> : null}
              </p>
            ) : null}
            <section className={ws.section}>
              <div className={ws.sectionHeading}>
                <h2 className={ws.sectionTitle}>异常清单</h2>
                <span className={ws.muted}>更新于 {generatedAtLabel}</span>
              </div>
              {topFindings?.length ? (
                <div className={ws.tableScroll}>
                  <table aria-label="健康异常清单" className={ws.table}>
                    <thead>
                      <tr>
                        <th>问题与说明</th>
                        <th>级别</th>
                        <th className="text-right">命中文件</th>
                      </tr>
                    </thead>
                    <tbody>
                      {topFindings?.map((finding) => (
                        <tr key={finding.key}>
                          <td>
                            <strong className="font-medium">{finding.label}</strong>
                            {finding.description ? <p>{finding.description}</p> : null}
                          </td>
                          <td>
                            <span
                              className={
                                finding.severity === 'error'
                                  ? 'text-destructive'
                                  : finding.severity === 'warning'
                                    ? ws.warning
                                    : ws.muted
                              }
                            >
                              {finding.severity === 'error' ? '错误' : finding.severity === 'warning' ? '注意' : '提示'}
                            </span>
                          </td>
                          <td className="text-right tabular-nums">{finding.count}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <p className={ws.muted}>当前报告没有命中的问题条目。</p>
              )}
            </section>
            <details className={`group ${ws.section}`}>
              <summary className="flex cursor-pointer list-none items-center gap-2 text-[15px] font-semibold [&::-webkit-details-marker]:hidden">
                <ChevronDown
                  className="size-3.5 shrink-0 text-muted-foreground transition-transform group-open:rotate-180"
                  aria-hidden="true"
                />
                状态与格式分布
              </summary>
              <div className={ws.charts}>
                <Panel variant="seamless" className={ws.section}>
                  <div className="flex items-center justify-between mb-4">
                    <div className="font-semibold">入库状态分布</div>
                    <div className="text-xs text-muted-foreground font-mono">
                      更新于 {formatDate(health.generated_at)}
                    </div>
                  </div>
                  {model.statuses.length ? (
                    <>
                      <SafeResponsiveChart className="h-[160px]" minHeight={160}>
                        <BarChart data={model.statuses} margin={{ top: 10, right: 10, left: 0, bottom: 0 }}>
                          <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                          <XAxis dataKey="name" tick={{ fontSize: 12 }} />
                          <YAxis tick={{ fontSize: 12 }} allowDecimals={false} />
                          <Tooltip
                            contentStyle={{
                              backgroundColor: 'hsl(var(--popover))',
                              color: 'hsl(var(--popover-foreground))',
                              borderColor: 'hsl(var(--border))',
                            }}
                            itemStyle={{ color: 'hsl(var(--popover-foreground))' }}
                          />
                          <Bar
                            isAnimationActive={false}
                            dataKey="value"
                            fill="hsl(var(--chart-1))"
                            radius={[8, 8, 0, 0]}
                          />
                        </BarChart>
                      </SafeResponsiveChart>
                      <div role="list" aria-label="入库状态图例" className="mt-3 flex flex-wrap gap-2">
                        {model.statuses.map((item) => (
                          <span key={item.name} role="listitem" className="inline-flex items-center gap-2 text-xs">
                            <span
                              aria-hidden="true"
                              className="size-2 rounded-full"
                              style={{ backgroundColor: item.fill }}
                            />
                            <span className="font-medium">{item.name}</span>
                            <span className="font-mono text-muted-foreground">{item.value}</span>
                          </span>
                        ))}
                      </div>
                    </>
                  ) : (
                    <EmptyState
                      icon={Activity}
                      title="暂无状态数据"
                      className="min-h-[160px]"
                    />
                  )}
                </Panel>

                <Panel variant="seamless" className={ws.section}>
                  <div className="flex items-center justify-between mb-4">
                    <div className="font-semibold">格式分布</div>
                    <div className="text-xs text-muted-foreground font-mono">
                      更新于 {formatDate(health.profile.generated_at)}
                    </div>
                  </div>
                  {model.fileTypes.some((row) => row.value > 0) ? (
                    <>
                      <SafeResponsiveChart className="h-[160px]" minHeight={160}>
                        <PieChart>
                          <Pie
                            isAnimationActive={false}
                            data={model.fileTypes}
                            dataKey="value"
                            nameKey="name"
                            outerRadius={70}
                          />
                          <Tooltip
                            contentStyle={{
                              backgroundColor: 'hsl(var(--popover))',
                              color: 'hsl(var(--popover-foreground))',
                              borderColor: 'hsl(var(--border))',
                            }}
                            itemStyle={{ color: 'hsl(var(--popover-foreground))' }}
                          />
                        </PieChart>
                      </SafeResponsiveChart>
                      <div role="list" aria-label="格式分布图例" className="mt-3 flex flex-wrap gap-2">
                        {model.fileTypes.map((item) => (
                          <span key={item.name} role="listitem" className="inline-flex items-center gap-2 text-xs">
                            <span
                              aria-hidden="true"
                              className="size-2 rounded-full"
                              style={{ backgroundColor: item.fill }}
                            />
                            <span className="font-medium">{item.name}</span>
                            <span className="font-mono text-muted-foreground">{item.value}</span>
                          </span>
                        ))}
                      </div>
                    </>
                  ) : (
                    <EmptyState
                      icon={BarChart3}
                      title="当前格式计数为 0"
                      description="当前报告没有可绘制的格式占比。"
                      className="min-h-[160px]"
                    />
                  )}
                </Panel>
              </div>
            </details>
          </>
        ) : (
          <div className={ws.empty} role="status">
            {healthQuery.isPending ? '正在读取健康概览…' : '当前健康概览暂不可用。'}
          </div>
        )}
      </OperationalWorkspace>
    </AppFrame>
  )
}
