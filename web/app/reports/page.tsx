'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { toast } from 'sonner'
import { AlertTriangle, BarChart3, Download, FileSearch, FileText, Layers, Loader2, RefreshCw, ShieldAlert } from 'lucide-react'

import { AppFrame } from '@/components/app-frame'
import { PageScaffold } from '@/components/ui/page-scaffold'
import { Panel } from '@/components/ui/panel'
import { Button } from '@/components/ui/button'
import { EmptyState } from '@/components/ui/empty-state'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { StatCard, StatsGrid } from '@/components/ui/stats-card'

import { datasetApi, reportApi } from '@/lib/api-client'
import { formatApiError } from '@/lib/api-errors'
import { formatDate, formatFileSize } from '@/lib/utils'

import type { Dataset, DatasetReport } from '@/types'

function sanitizeFilename(name: string) {
  const base = (name || '').trim() || 'dataset'
  return base.replace(/[\\/:*?"<>|]+/g, '_')
}

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}

export default function ReportsCenterPage() {
  const [datasets, setDatasets] = useState<Dataset[]>([])
  const [datasetId, setDatasetId] = useState<string>('')
  const [pipelineHash, setPipelineHash] = useState<string>('')
  const [connectorRunsLimit, setConnectorRunsLimit] = useState<number>(20)
  const [redact, setRedact] = useState<boolean>(true)

  const [isLoadingDatasets, setIsLoadingDatasets] = useState(false)
  const [isLoadingReport, setIsLoadingReport] = useState(false)
  const [isExportingJson, setIsExportingJson] = useState(false)
  const [isExportingHtml, setIsExportingHtml] = useState(false)

  const [report, setReport] = useState<DatasetReport | null>(null)

  const selectedDataset = useMemo(() => datasets.find((d) => d.id === datasetId) || null, [datasets, datasetId])

  const loadDatasets = useCallback(async () => {
    setIsLoadingDatasets(true)
    try {
      const res = await datasetApi.list({ skip: 0, limit: 200 })
      const items = res?.items || []
      setDatasets(items)
      if (!datasetId && items.length > 0) setDatasetId(items[0].id)
    } catch (e: any) {
      console.error('Failed to load datasets', e)
      toast.error(formatApiError(e, '加载数据集失败'))
    } finally {
      setIsLoadingDatasets(false)
    }
  }, [datasetId])

  const loadReport = useCallback(async () => {
    if (!datasetId) return
    setIsLoadingReport(true)
    try {
      const r = await reportApi.getDatasetReport(datasetId, {
        pipeline_hash: pipelineHash.trim() || undefined,
        connector_runs_limit: connectorRunsLimit,
      })
      setReport(r)
    } catch (e: any) {
      console.error('Failed to load dataset report', e)
      toast.error(formatApiError(e, '加载报告预览失败'))
      setReport(null)
    } finally {
      setIsLoadingReport(false)
    }
  }, [connectorRunsLimit, datasetId, pipelineHash])

  useEffect(() => {
    void loadDatasets()
  }, [loadDatasets])

  useEffect(() => {
    void loadReport()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [datasetId])

  const handleExportJson = useCallback(async () => {
    if (!datasetId) return
    setIsExportingJson(true)
    try {
      const blob = await reportApi.exportDatasetReportJson(datasetId, {
        pipeline_hash: pipelineHash.trim() || undefined,
        connector_runs_limit: connectorRunsLimit,
      })
      const safe = sanitizeFilename(selectedDataset?.name || 'dataset')
      const suffix = pipelineHash.trim() ? `.${pipelineHash.trim().slice(0, 8)}` : ''
      downloadBlob(blob, `${safe}.report${suffix}.json`)
    } catch (e: any) {
      console.error('Export report json failed', e)
      toast.error(formatApiError(e, '导出 JSON 报告失败'))
    } finally {
      setIsExportingJson(false)
    }
  }, [connectorRunsLimit, datasetId, pipelineHash, selectedDataset?.name])

  const handleExportHtml = useCallback(async () => {
    if (!datasetId) return
    setIsExportingHtml(true)
    try {
      const blob = await reportApi.exportDatasetReportHtml(datasetId, {
        pipeline_hash: pipelineHash.trim() || undefined,
        connector_runs_limit: connectorRunsLimit,
        redact,
      })
      const safe = sanitizeFilename(selectedDataset?.name || 'dataset')
      const suffix = pipelineHash.trim() ? `.${pipelineHash.trim().slice(0, 8)}` : ''
      downloadBlob(blob, `${safe}.report${suffix}.html`)
    } catch (e: any) {
      console.error('Export report html failed', e)
      toast.error(formatApiError(e, '导出 HTML 报告失败'))
    } finally {
      setIsExportingHtml(false)
    }
  }, [connectorRunsLimit, datasetId, pipelineHash, redact, selectedDataset?.name])

  const totalDocs = report?.profile?.total_documents || 0
  const totalBytes = report?.profile?.total_size_bytes || 0
  const quarantined = report?.compliance?.quarantined_documents || 0
  const failed = report?.compliance?.failed_documents || 0
  const pipelineVersions = report?.pipeline_versions || []
  const connectorRuns = report?.connectors || []
  const folderTree = report?.folder_tree || null
  const topFolders = folderTree?.root?.children || []

  return (
    <AppFrame>
      <PageScaffold
        title="报告中心"
        description="一键导出数据集「质量报告 + 合规报告」，支持按 pipeline_hash 过滤并生成可分享的 HTML。"
        icon={FileText}
        iconColor="text-primary"
      >
        <div className="space-y-6">
          <Panel padding="lg" className="space-y-4">
            <div className="flex items-start justify-between gap-4 flex-wrap">
              <div className="space-y-1">
                <div className="text-sm font-semibold text-foreground">参数</div>
                <div className="text-xs text-muted-foreground">选择数据集与可选 pipeline_hash，点击“刷新预览”或直接导出。</div>
              </div>
              <div className="flex items-center gap-2">
                <Button variant="secondary" onClick={() => void loadDatasets()} disabled={isLoadingDatasets} aria-label="刷新数据集列表">
                  {isLoadingDatasets ? <Loader2 className="h-4 w-4 animate-spin motion-reduce:animate-none" /> : <RefreshCw className="h-4 w-4" />}
                  <span className="ml-2">刷新数据集</span>
                </Button>
                <Button onClick={() => void loadReport()} disabled={!datasetId || isLoadingReport} aria-label="刷新报告预览">
                  {isLoadingReport ? <Loader2 className="h-4 w-4 animate-spin motion-reduce:animate-none" /> : <RefreshCw className="h-4 w-4" />}
                  <span className="ml-2">刷新预览</span>
                </Button>
              </div>
            </div>
            <div className="grid gap-4 md:grid-cols-3">
              <div className="space-y-2">
                <Label htmlFor="dataset-select">数据集</Label>
                <Select value={datasetId} onValueChange={(v) => setDatasetId(v)}>
                  <SelectTrigger id="dataset-select" className="w-full">
                    <SelectValue placeholder={isLoadingDatasets ? '加载中...' : '请选择数据集'} />
                  </SelectTrigger>
                  <SelectContent>
                    {datasets.map((ds) => (
                      <SelectItem key={ds.id} value={ds.id}>
                        {ds.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <div className="space-y-2">
                <Label htmlFor="pipeline-hash">pipeline_hash（可选）</Label>
                <Input
                  id="pipeline-hash"
                  value={pipelineHash}
                  onChange={(e) => setPipelineHash(e.target.value)}
                  placeholder="留空表示 all（active versions）"
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="connector-limit">Connector Runs（最多）</Label>
                <Select
                  value={String(connectorRunsLimit)}
                  onValueChange={(v) => setConnectorRunsLimit(Number(v || 20))}
                >
                  <SelectTrigger id="connector-limit" className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="0">0</SelectItem>
                    <SelectItem value="10">10</SelectItem>
                    <SelectItem value="20">20</SelectItem>
                    <SelectItem value="50">50</SelectItem>
                    <SelectItem value="100">100</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>

            <div className="mt-4 flex items-center justify-between gap-3 flex-wrap">
              <div className="flex items-center gap-3">
                <div className="flex items-center gap-2">
                  <Switch id="redact-switch" checked={redact} onCheckedChange={setRedact} />
                  <Label htmlFor="redact-switch">导出 HTML 时脱敏（推荐分享用）</Label>
                </div>
              </div>

              <div className="flex items-center gap-2">
                <Button
                  variant="secondary"
                  onClick={() => void handleExportJson()}
                  disabled={!datasetId || isExportingJson}
                  aria-label="导出 JSON 报告"
                >
                  {isExportingJson ? <Loader2 className="h-4 w-4 animate-spin motion-reduce:animate-none" /> : <Download className="h-4 w-4" />}
                  <span className="ml-2">导出 JSON</span>
                </Button>
                <Button
                  onClick={() => void handleExportHtml()}
                  disabled={!datasetId || isExportingHtml}
                  aria-label="导出 HTML 报告"
                >
                  {isExportingHtml ? <Loader2 className="h-4 w-4 animate-spin motion-reduce:animate-none" /> : <Download className="h-4 w-4" />}
                  <span className="ml-2">导出 HTML</span>
                </Button>
              </div>
            </div>
          </Panel>

          {!datasetId ? (
            <EmptyState title="请选择数据集" description="选择一个数据集后即可生成报告预览并导出。" />
          ) : !report ? (
            <EmptyState
              title={isLoadingReport ? '报告加载中...' : '暂无预览'}
              description={isLoadingReport ? '正在拉取报告数据...' : '点击“刷新预览”生成报告。'}
            />
          ) : (
            <Panel padding="lg" className="space-y-4">
              <div className="space-y-1">
                <div className="text-sm font-semibold text-foreground">预览</div>
                <div className="text-xs text-muted-foreground">
                  dataset: {selectedDataset?.name || report.dataset_name || datasetId} · generated_at: {formatDate(report.generated_at)}
                </div>
              </div>
              <StatsGrid className="mb-4">
                <StatCard icon={FileSearch} label="文档总数" value={String(totalDocs)} color="cyan" />
                <StatCard icon={BarChart3} label="总大小" value={formatFileSize(Number(totalBytes || 0))} color="teal" />
                <StatCard icon={ShieldAlert} label="隔离（Quarantine）" value={String(quarantined)} color="amber" />
                <StatCard icon={AlertTriangle} label="失败（Failed）" value={String(failed)} color="rose" />
                <StatCard icon={Layers} label="Pipeline Versions" value={String(pipelineVersions.length)} color="blue" />
                <StatCard icon={RefreshCw} label="Connector Runs" value={String(connectorRuns.length)} color="gray" />
              </StatsGrid>

              <div className="grid gap-4 md:grid-cols-2">
                <div className="rounded-xl border border-border/60 bg-card/40 p-4">
                  <div className="flex items-start justify-between gap-2">
                    <div>
                      <div className="text-sm font-semibold text-foreground">目录分布（Top）</div>
                      {folderTree ? (
                        <div className="text-xs text-muted-foreground">
                          with source_path: {folderTree.total_with_source_path}/{folderTree.total_documents}
                        </div>
                      ) : null}
                    </div>
                  </div>
                  {!folderTree ? (
                    <div className="mt-3 text-sm text-muted-foreground">后端未提供目录统计</div>
                  ) : topFolders.length === 0 ? (
                    <div className="mt-3 text-sm text-muted-foreground">暂无目录（未上传带路径的文件）</div>
                  ) : (
                    <div className="mt-3 space-y-2">
                      {topFolders.slice(0, 10).map((f) => (
                        <div key={f.path} className="flex items-center justify-between gap-3">
                          <span className="font-mono text-xs text-foreground truncate" title={f.path}>
                            {f.path}
                          </span>
                          <span className="font-mono text-xs text-muted-foreground">{f.documents}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>

                <div className="rounded-xl border border-border/60 bg-card/40 p-4">
                  <div className="text-sm font-semibold text-foreground mb-3">Pipeline 版本分布（Top）</div>
                  {pipelineVersions.length === 0 ? (
                    <div className="text-sm text-muted-foreground">暂无数据</div>
                  ) : (
                    <div className="space-y-2">
                      {pipelineVersions.slice(0, 10).map((v) => (
                        <div key={v.pipeline_hash} className="flex items-center justify-between gap-3">
                          <span className="font-mono text-xs text-foreground truncate" title={v.pipeline_hash}>
                            {v.pipeline_hash}
                          </span>
                          <span className="font-mono text-xs text-muted-foreground">{v.documents}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>

                <div className="rounded-xl border border-border/60 bg-card/40 p-4">
                  <div className="text-sm font-semibold text-foreground mb-3">最近 Connector Runs</div>
                  {connectorRuns.length === 0 ? (
                    <div className="text-sm text-muted-foreground">暂无数据</div>
                  ) : (
                    <div className="space-y-2">
                      {connectorRuns.slice(0, 8).map((r) => (
                        <div key={r.id} className="flex items-start justify-between gap-3">
                          <div className="min-w-0">
                            <div className="font-mono text-xs text-foreground truncate" title={r.connector_id}>
                              {r.connector_id}
                            </div>
                            <div className="text-xs text-muted-foreground">{formatDate(r.created_at)}</div>
                          </div>
                          <div className="font-mono text-xs text-muted-foreground">{r.status}</div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            </Panel>
          )}
        </div>
      </PageScaffold>
    </AppFrame>
  )
}
