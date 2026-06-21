'use client'

import { startTransition, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useParams } from 'next/navigation'
import { useQuery } from '@tanstack/react-query'
import { toast } from 'sonner'
import { ArrowLeft, BarChart3, Database, Download, FileUp, Layers, Loader2, Save, Settings2, Table2 } from 'lucide-react'

import { AppFrame } from '@/components/app-frame'
import { PageScaffold } from '@/components/ui/page-scaffold'
import { Panel } from '@/components/ui/panel'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Textarea } from '@/components/ui/textarea'

import { WorkflowEditor } from '@/components/workflow/workflow-editor'
import { datasetApi } from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'
import { reportClientError } from '@/lib/client-logging'
import { buildDatasetConfigGraph } from '@/lib/dataset-config-graph'
import type { GraphNode } from '@/lib/graph-parser'
import { queryKeys } from '@/lib/query-keys'
import { useRouter } from '@/i18n/navigation'
import { cn, detachPromise } from '@/lib/utils'

import type { Dataset, DatasetConfigBundle, DatasetConfigExport, DatasetConfigImportRequest } from '@/types'

type DatasetWorkflowGraphNode = GraphNode & {
  meta?: {
    configured?: boolean
    summary?: string[]
    json?: unknown
  }
}

function asDatasetId(raw: unknown): string | null {
  if (typeof raw === 'string' && raw.trim()) return raw
  if (Array.isArray(raw) && typeof raw[0] === 'string') return raw[0]
  return null
}

function downloadJson(value: unknown, filename: string) {
  const blob = new Blob([JSON.stringify(value, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

function normalizeImportedBundle(raw: unknown): DatasetConfigBundle | null {
  if (!raw || typeof raw !== 'object') return null
  if ('config' in raw && raw.config && typeof raw.config === 'object') return raw.config
  return raw
}

const workflowHeroCard = 'relative overflow-hidden rounded-2xl border border-white/70 bg-[radial-gradient(circle_at_0%_0%,rgba(20,184,166,0.18),transparent_34%),linear-gradient(135deg,rgba(255,255,255,0.97),rgba(240,253,250,0.9))] shadow-[0_18px_55px_rgba(15,23,42,0.08)] ring-1 ring-slate-100/70 dark:border-border/60 dark:bg-card dark:ring-white/5'
const workflowActionButtonClass = 'h-9 gap-1.5 rounded-xl bg-card/70 px-3 text-[13px] shadow-[inset_0_1px_0_rgba(255,255,255,0.65)]'
const workflowPanelClass = 'overflow-hidden border-white/70 bg-[linear-gradient(180deg,rgba(255,255,255,0.98),rgba(248,250,252,0.92))] shadow-[0_16px_45px_rgba(15,23,42,0.07)] ring-1 ring-slate-100/70 dark:border-border/60 dark:bg-card/95 dark:ring-white/5'

export default function DatasetWorkflowPage() {
  const router = useRouter()
  const params = useParams()
  const routeParams = params as Readonly<Record<string, string | string[] | undefined>>
  const datasetId = asDatasetId(routeParams.id)

  const importInputRef = useRef<HTMLInputElement>(null)

  const [workingConfig, setWorkingConfig] = useState<DatasetConfigBundle | null>(null)
  const [selectedNode, setSelectedNode] = useState<DatasetWorkflowGraphNode | null>(null)

  const [saving, setSaving] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [importing, setImporting] = useState(false)

  const [importOpen, setImportOpen] = useState(false)
  const [importFileName, setImportFileName] = useState<string>('')
  const [importBundle, setImportBundle] = useState<DatasetConfigBundle | null>(null)

  const datasetQuery = useQuery({
    queryKey: queryKeys.datasets.detail(datasetId || ''),
    queryFn: () => {
      if (!datasetId) throw new Error('缺少数据集 ID')
      return datasetApi.get(datasetId)
    },
    enabled: Boolean(datasetId),
  })
  const configQuery = useQuery({
    queryKey: queryKeys.datasets.config(datasetId || ''),
    queryFn: () => {
      if (!datasetId) throw new Error('缺少数据集 ID')
      return datasetApi.exportConfig(datasetId)
    },
    enabled: Boolean(datasetId),
  })
  const dataset = (datasetQuery.data ?? null) as Dataset | null
  const exportRes = (configQuery.data ?? null) as DatasetConfigExport | null
  const loading = datasetQuery.isFetching || configQuery.isFetching
  const loadError = datasetQuery.error ?? configQuery.error
  const loadErrorUpdatedAt = Math.max(
    datasetQuery.errorUpdatedAt,
    configQuery.errorUpdatedAt
  )
  const { refetch: refetchDataset } = datasetQuery
  const { refetch: refetchConfig } = configQuery
  const refreshWorkflow = useCallback(async () => {
    await Promise.all([refetchDataset(), refetchConfig()])
  }, [refetchConfig, refetchDataset])

  const importKeys = useMemo(() => {
    if (!importBundle || typeof importBundle !== 'object') return []
    return Object.keys(importBundle).sort((a, b) => a.localeCompare(b))
  }, [importBundle])

  const activeConfig = workingConfig ?? exportRes?.config ?? null
  const graph = useMemo(() => buildDatasetConfigGraph(activeConfig ?? {}), [activeConfig])
  const savedConfigJson = useMemo(() => JSON.stringify(exportRes?.config ?? null), [exportRes?.config])
  const workingConfigJson = useMemo(() => JSON.stringify(workingConfig ?? null), [workingConfig])
  const hasUnsavedLayoutChanges = !!workingConfig && workingConfigJson !== savedConfigJson

  const selectedMeta = selectedNode?.meta
  const selectedSummary = Array.isArray(selectedMeta?.summary) ? selectedMeta.summary : []
  const selectedJson = selectedMeta?.json
  const datasetName = dataset?.name || datasetId || '未选择数据集'
  const topLevelKeyCount = activeConfig && typeof activeConfig === 'object' ? Object.keys(activeConfig).length : 0
  const configuredNodeCount = graph.nodes.filter((node) => {
    const meta = (node as DatasetWorkflowGraphNode).meta
    return meta?.configured === true
  }).length
  const configVersionLabel = exportRes?.version ? String(exportRes.version) : '—'
  const layoutStatusLabel = loading ? '加载中' : hasUnsavedLayoutChanges ? '有未保存布局' : '已同步'
  const selectedMetaStatusText =
    selectedMeta?.configured === false
      ? '未单独配置，继承默认策略'
      : selectedMeta?.configured === true
        ? '已配置'
        : '点击左侧节点查看摘要与 JSON'
  const selectedJsonText = useMemo(() => {
    if (selectedJson === undefined) return ''
    try {
      return JSON.stringify(selectedJson, null, 2)
    } catch {
      if (
        typeof selectedJson === 'string'
        || typeof selectedJson === 'number'
        || typeof selectedJson === 'boolean'
        || typeof selectedJson === 'bigint'
      ) {
        return String(selectedJson)
      }
      return '[unserializable JSON]'
    }
  }, [selectedJson])

  useEffect(() => {
    if (!loadError) return
    toast.error(formatApiError(loadError, '加载工作流配置失败'))
  }, [loadError, loadErrorUpdatedAt])

  useEffect(() => {
    if (!exportRes) return
    setWorkingConfig(exportRes.config ?? {})
    setSelectedNode(null)
  }, [exportRes])

  const doExport = useCallback(async () => {
    if (!datasetId) return
    setExporting(true)
    try {
      const exp = await datasetApi.exportConfig(datasetId)
      const id8 = datasetId.slice(0, 8)
      const name = (dataset?.name || 'dataset').replaceAll(/[^a-zA-Z0-9._-]+/g, '_').slice(0, 60)
      downloadJson(exp, `dataset-config-${name}-${id8}.json`)
      toast.success('已导出配置')
    } catch (e: unknown) {
      reportClientError('Failed to export dataset config', e)
      toast.error(formatApiError(e, '导出失败'))
    } finally {
      setExporting(false)
    }
  }, [dataset?.name, datasetId])

  const onPickImportFile = useCallback(async (file: File | null) => {
    if (!file) return
    setImporting(true)
    try {
      const text = await file.text()
      const raw = JSON.parse(text)
      const bundle = normalizeImportedBundle(raw)
      if (!bundle) {
        toast.error('JSON 格式不正确：需要 DatasetConfigBundle 或 { config: DatasetConfigBundle }')
        return
      }
      setImportFileName(file.name || 'config.json')
      setImportBundle(bundle)
      setImportOpen(true)
    } catch (e: unknown) {
      reportClientError('Failed to parse dataset config import JSON', e)
      toast.error('解析 JSON 文件失败')
    } finally {
      setImporting(false)
      if (importInputRef.current) importInputRef.current.value = ''
    }
  }, [])

  const doImport = useCallback(async () => {
    if (!datasetId || !importBundle) return
    setImporting(true)
    try {
      const payload: DatasetConfigImportRequest = { config: importBundle, replace: true }
      await datasetApi.importConfig(datasetId, payload)
      toast.success('已导入配置（replace=true）')
      setImportOpen(false)
      setImportBundle(null)
      setImportFileName('')
      await refreshWorkflow()
    } catch (e: unknown) {
      reportClientError('Failed to import dataset config', e)
      toast.error(formatApiError(e, '导入失败'))
    } finally {
      setImporting(false)
    }
  }, [datasetId, importBundle, refreshWorkflow])

  const onWorkflowLayoutChange = useCallback((workflowLayout: Record<string, unknown>) => {
    startTransition(() => {
      setWorkingConfig((prev) => ({
        ...(prev ?? exportRes?.config),
        workflow_layout: workflowLayout,
      }))
    })
  }, [exportRes?.config])

  const doSaveLayout = useCallback(async () => {
    if (!datasetId || !workingConfig) return
    setSaving(true)
    try {
      const payload: DatasetConfigImportRequest = { config: workingConfig, replace: true }
      await datasetApi.importConfig(datasetId, payload)
      toast.success('已保存工作流布局')
      await refreshWorkflow()
    } catch (e: unknown) {
      reportClientError('Failed to save workflow layout', e)
      toast.error(formatApiError(e, '保存失败'))
    } finally {
      setSaving(false)
    }
  }, [datasetId, refreshWorkflow, workingConfig])

  const copySelectedJson = useCallback(async () => {
    if (!selectedJsonText.trim()) return
    try {
      await navigator.clipboard.writeText(selectedJsonText)
      toast.success('已复制 JSON')
    } catch (e) {
      reportClientError('Failed to copy selected workflow JSON', e)
      toast.error('复制失败')
    }
  }, [selectedJsonText])

  return (
    <AppFrame>
      <PageScaffold
        title="工作流配置"
        showHeader={false}
        size="full"
        density="system-dense"
        bodyGutter="dense"
        bodyClassName="h-full overflow-hidden bg-[radial-gradient(circle_at_18%_0%,rgba(20,184,166,0.10),transparent_28%),linear-gradient(180deg,rgba(248,250,252,0.96),rgba(241,245,249,0.68))] pb-3 dark:bg-[radial-gradient(circle_at_18%_0%,rgba(20,184,166,0.13),transparent_28%),linear-gradient(180deg,rgba(15,23,42,0.96),rgba(15,23,42,0.86))]"
        bodyContainerClassName="h-full min-h-0 overflow-hidden"
        top={
          <div className={workflowHeroCard}>
            <div className="absolute inset-y-4 left-3 w-1 rounded-full bg-gradient-to-b from-teal-500 via-cyan-400 to-sky-300" />
            <div className="relative flex flex-col gap-3 px-5 py-3.5 pl-8 lg:flex-row lg:items-center lg:justify-between">
              <div className="flex min-w-0 items-start gap-3.5">
                <div className="flex size-11 shrink-0 items-center justify-center rounded-2xl border border-teal-200/80 bg-white/82 text-teal-600 shadow-[inset_0_1px_0_rgba(255,255,255,0.9),0_10px_26px_rgba(20,184,166,0.14)] dark:border-teal-500/25 dark:bg-teal-500/10 dark:text-teal-300">
                  <Layers className="size-5" />
                </div>
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <h1 className="truncate text-[20px] font-medium leading-none tracking-[-0.01em] text-slate-800 dark:text-foreground">工作流配置</h1>
                    <span className="inline-flex h-5 items-center rounded-full border border-slate-200/80 bg-white/70 px-2 text-[10px] font-medium leading-none text-slate-500 shadow-[inset_0_1px_0_rgba(255,255,255,0.75)] dark:border-border/60 dark:bg-muted/30 dark:text-muted-foreground">
                      DatasetConfigBundle
                    </span>
                    <Badge variant="soft" className="h-5 border-teal-200 bg-teal-50 px-2 text-[10px] font-medium leading-none text-teal-700">
                      CONFIG GRAPH
                    </Badge>
                  </div>
                  <div className="mt-1.5 text-[13px] leading-tight text-muted-foreground">
                    <span className="font-semibold text-foreground">数据集：</span>
                    <span className="font-medium text-foreground">{datasetName}</span>
                    <span> · 可视化查看配置链路、节点 JSON 与布局持久化</span>
                  </div>
                  <div className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-1.5 text-[11px] leading-none text-muted-foreground">
                    <span className="inline-flex items-center gap-1.5">
                      <Layers className="size-3.5 text-teal-500" />
                      <span>节点</span>
                      <span className="font-mono font-semibold text-foreground">{graph.nodes.length}</span>
                    </span>
                    <span className="inline-flex items-center gap-1.5">
                      <BarChart3 className="size-3.5 text-cyan-500" />
                      <span>边</span>
                      <span className="font-mono font-semibold text-foreground">{graph.links.length}</span>
                    </span>
                    <span className="inline-flex items-center gap-1.5">
                      <Database className="size-3.5 text-sky-500" />
                      <span>配置键</span>
                      <span className="font-mono font-semibold text-foreground">{topLevelKeyCount}</span>
                    </span>
                    <span className="inline-flex items-center gap-1.5">
                      <Settings2 className="size-3.5 text-emerald-500" />
                      <span>已配置节点</span>
                      <span className="font-mono font-semibold text-foreground">{configuredNodeCount}</span>
                    </span>
                  </div>
                </div>
              </div>
              <div className="flex shrink-0 items-center gap-2 lg:self-end">
                <div className={cn(
                  'inline-flex h-9 items-center gap-2 rounded-lg border px-3 text-[13px] font-medium shadow-[inset_0_1px_0_rgba(255,255,255,0.75)]',
                  hasUnsavedLayoutChanges
                    ? 'border-amber-200/80 bg-amber-50/90 text-amber-700 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-300'
                    : 'border-emerald-200/80 bg-emerald-50/90 text-emerald-700 dark:border-emerald-500/30 dark:bg-emerald-500/10 dark:text-emerald-300'
                )}>
                  <span className={cn('size-2 rounded-full', loading ? 'animate-pulse bg-sky-500' : hasUnsavedLayoutChanges ? 'bg-amber-500' : 'bg-emerald-500')} />
                  {layoutStatusLabel}
                </div>
              </div>
            </div>
          </div>
        }
        toolbar={
          <div className="flex w-full flex-col gap-2 lg:flex-row lg:items-center lg:justify-between">
            <div className="flex min-w-0 flex-wrap items-center gap-1.5">
              <Button variant="outline" onClick={() => router.push('/datasets')} className={workflowActionButtonClass}>
                <ArrowLeft className="size-3.5" />
                返回
              </Button>
              {datasetId ? (
                <Button variant="outline" onClick={() => router.push(`/datasets/${datasetId}/ingestion`)} className={workflowActionButtonClass}>
                  <Settings2 className="size-3.5" />
                  入库策略
                </Button>
              ) : null}
              {datasetId ? (
                <Button variant="outline" onClick={() => router.push(`/datasets/${datasetId}/profile`)} className={workflowActionButtonClass}>
                  <BarChart3 className="size-3.5" />
                  数据画像
                </Button>
              ) : null}
              {datasetId ? (
                <Button variant="outline" onClick={() => router.push(`/datasets/${datasetId}/tables`)} className={workflowActionButtonClass}>
                  <Table2 className="size-3.5" />
                  表格 / TAG
                </Button>
              ) : null}
            </div>
            <div className="flex min-w-0 flex-wrap items-center gap-1.5">
              <Button
                onClick={() => detachPromise(doSaveLayout())}
                disabled={saving || !datasetId || !workingConfig || !hasUnsavedLayoutChanges}
                className="h-10 min-w-[118px] gap-2 rounded-xl bg-gradient-to-r from-teal-500 to-cyan-500 text-[13px] text-white shadow-[0_14px_30px_rgba(20,184,166,0.24)] hover:from-teal-600 hover:to-cyan-600"
              >
                {saving ? <Loader2 className="size-3.5 animate-spin motion-reduce:animate-none" /> : <Save className="size-3.5" />}
                保存布局
              </Button>
              <Button variant="outline" onClick={() => detachPromise(doExport())} disabled={exporting} className={workflowActionButtonClass}>
                {exporting ? <Loader2 className="size-3.5 animate-spin motion-reduce:animate-none" /> : <Download className="size-3.5" />}
                导出 JSON
              </Button>
              <Button variant="outline" onClick={() => importInputRef.current?.click()} disabled={importing} className={workflowActionButtonClass}>
                {importing ? <Loader2 className="size-3.5 animate-spin motion-reduce:animate-none" /> : <FileUp className="size-3.5" />}
                导入 JSON
              </Button>
              <input
                ref={importInputRef}
                type="file"
                accept="application/json"
                className="hidden"
                onChange={(e) => detachPromise(onPickImportFile(e.target.files?.[0] || null))}
              />
            </div>
          </div>
        }
      >
        <div className="flex h-full min-h-0 flex-col gap-3 overflow-hidden">
          <div className="grid min-h-0 flex-1 grid-cols-1 gap-3 xl:grid-cols-[minmax(0,1fr)_400px]">
            <Panel padding="none" className={cn(workflowPanelClass, 'flex min-h-0 min-w-0 flex-col')}>
              <div className="flex shrink-0 items-center justify-between gap-3 border-b border-slate-200/70 bg-white/65 px-3.5 py-2.5 dark:border-border/60 dark:bg-muted/20">
                <div className="min-w-0">
                  <div className="text-sm font-semibold text-slate-900 dark:text-foreground">配置链路图</div>
                  <div className="mt-0.5 text-[11px] text-muted-foreground">拖动节点只保存布局，不会改变业务配置值。</div>
                </div>
                <div className="hidden shrink-0 items-center gap-1.5 text-[11px] text-muted-foreground md:flex">
                  <span className="rounded-full border border-slate-200/80 bg-white/70 px-2 py-1 dark:border-border/60 dark:bg-muted/30">version {configVersionLabel}</span>
                  <span className="rounded-full border border-slate-200/80 bg-white/70 px-2 py-1 dark:border-border/60 dark:bg-muted/30">{graph.nodes.length} nodes</span>
                </div>
              </div>
              <div className="min-h-0 flex-1">
                <WorkflowEditor
                  graph={graph}
                  workflowLayout={workingConfig?.workflow_layout ?? null}
                  onWorkflowLayoutChange={onWorkflowLayoutChange}
                  onNodeSelect={(node) => setSelectedNode(node)}
                />
              </div>
            </Panel>

            <Panel className={cn(workflowPanelClass, 'flex min-h-0 flex-col p-0')}>
              <div className="flex shrink-0 items-start justify-between gap-3 border-b border-slate-200/70 bg-white/65 px-3.5 py-3 dark:border-border/60 dark:bg-muted/20">
                <div className="min-w-0">
                  <div className="truncate text-sm font-semibold text-slate-900 dark:text-foreground">
                    {selectedNode?.label ? String(selectedNode.label) : '节点详情'}
                  </div>
                  <div className="mt-0.5 text-[11px] leading-4 text-muted-foreground">{selectedMetaStatusText}</div>
                </div>
                {selectedJsonText.trim() ? (
                  <Button variant="outline" size="sm" onClick={() => detachPromise(copySelectedJson())} className="h-8 shrink-0 rounded-lg px-2.5 text-xs">
                    复制 JSON
                  </Button>
                ) : null}
              </div>

              <div className="min-h-0 flex-1 space-y-3 overflow-y-auto overscroll-contain p-3 no-scrollbar">
                {selectedSummary.length > 0 ? (
                  <div className="space-y-2">
                    <div className="text-[11px] font-medium uppercase tracking-[0.14em] text-muted-foreground/70">摘要</div>
                    <div className="flex flex-wrap gap-1.5">
                      {selectedSummary.slice(0, 20).map((s) => (
                        <Badge key={String(s)} variant="outline" className="rounded-lg border-slate-200/80 bg-white/70 font-mono text-[11px] dark:border-border/60 dark:bg-muted/30">
                          {String(s)}
                        </Badge>
                      ))}
                    </div>
                  </div>
                ) : null}

                <div className="space-y-2">
                  <div className="text-[11px] font-medium uppercase tracking-[0.14em] text-muted-foreground/70">JSON</div>
                  <Textarea
                    value={selectedJsonText || ''}
                    readOnly
                    className="min-h-[320px] resize-none rounded-xl border-slate-200/80 bg-slate-50/80 font-mono text-[11px] leading-5 shadow-inner dark:border-border/60 dark:bg-muted/20"
                    placeholder="选择左侧节点后查看 JSON..."
                  />
                </div>
              </div>

              <div className="flex shrink-0 items-center justify-between gap-3 border-t border-slate-200/70 px-3.5 py-2.5 text-[11px] text-muted-foreground dark:border-border/60">
                <span>导出版本 <span className="font-mono text-foreground">{configVersionLabel}</span></span>
                <span className="font-medium text-foreground">{layoutStatusLabel}</span>
              </div>
            </Panel>
          </div>
        </div>

        <Dialog open={importOpen} onOpenChange={(open) => setImportOpen(open)}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>导入工作流配置？</DialogTitle>
              <DialogDescription>
                将使用 <span className="font-mono">replace=true</span> 覆盖当前数据集配置。请确认 JSON 来源可靠。
              </DialogDescription>
            </DialogHeader>

            <div className="space-y-3">
              <div className="text-sm">
                文件：<span className="font-mono">{importFileName || 'config.json'}</span>
              </div>
              {importKeys.length > 0 ? (
                <div className="space-y-2">
                  <div className="text-xs font-medium text-muted-foreground">顶层配置键</div>
                  <div className="flex flex-wrap gap-2">
                    {importKeys.slice(0, 24).map((k) => (
                      <Badge key={k} variant="outline" className="font-mono text-[11px]">
                        {k}
                      </Badge>
                    ))}
                    {importKeys.length > 24 ? (
                      <Badge variant="secondary" className="font-mono text-[11px]">
                        +{importKeys.length - 24} 项
                      </Badge>
                    ) : null}
                  </div>
                </div>
              ) : null}
            </div>

            <DialogFooter>
              <Button
                variant="outline"
                onClick={() => {
                  setImportOpen(false)
                  setImportBundle(null)
                  setImportFileName('')
                }}
                disabled={importing}
              >
                取消
              </Button>
              <Button onClick={() => detachPromise(doImport())} disabled={importing || !importBundle || !datasetId} className="gap-2">
                {importing ? <Loader2 className="w-4 h-4 animate-spin motion-reduce:animate-none" /> : null}
                导入并覆盖
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </PageScaffold>
    </AppFrame>
  )
}
