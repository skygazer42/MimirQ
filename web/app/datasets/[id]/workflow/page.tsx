'use client'

import { startTransition, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useParams } from 'next/navigation'
import { useQuery } from '@tanstack/react-query'
import { toast } from 'sonner'
import { ArrowLeft, BarChart3, Database, Download, FileUp, Layers, Loader2, Save, Settings2, Table2 } from '@/components/icons'

import { AppFrame } from '@/components/app-frame'
import { OperationalWorkspace, DirectoryWorkspace, WorkspaceNotice, workspaceStyles as ws } from '@/components/ui/operational-workspace'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
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

const workflowPanelClass = ws.canvasPanel

export default function DatasetWorkflowPage() {
  const router = useRouter()
  const params = useParams()
  const routeParams = params as Readonly<Record<string, string | string[] | undefined>>
  const datasetId = asDatasetId(routeParams.id)

  const importInputRef = useRef<HTMLInputElement>(null)

  const [workingConfig, setWorkingConfig] = useState<DatasetConfigBundle | null>(null)
  const [selectedNode, setSelectedNode] = useState<DatasetWorkflowGraphNode | null>(null)

  const [saveError, setSaveError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [importing, setImporting] = useState(false)

  const [nodeDetailOpen, setNodeDetailOpen] = useState(false)
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
    setSaveError(null)
    setSaving(true)
    try {
      const payload: DatasetConfigImportRequest = { config: workingConfig, replace: true }
      await datasetApi.importConfig(datasetId, payload)
      toast.success('已保存工作流布局')
      await refreshWorkflow()
    } catch (e: unknown) {
      reportClientError('Failed to save workflow layout', e)
      setSaveError(formatApiError(e, '保存布局失败'))
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

  return <AppFrame><OperationalWorkspace title="工作流配置" icon="ingestion-operation" mode="canvas" context={dataset?.name ?? '正在读取数据集…'} back={() => router.push('/datasets')} actions={<><Button className={ws.inspectorTrigger} variant="outline" onClick={() => setNodeDetailOpen(true)}>节点详情</Button><Button disabled={saving || !datasetId || !workingConfig || !hasUnsavedLayoutChanges} onClick={() => { void doSaveLayout() }}>{saving ? <Loader2 className="animate-spin motion-reduce:animate-none" /> : <Save />}{saving ? '正在保存…' : '保存布局'}</Button><Button variant="outline" size="icon" disabled={exporting} onClick={() => { void doExport() }} aria-label="导出工作流配置"><Download /></Button><Button variant="outline" size="icon" disabled={importing} onClick={() => importInputRef.current?.click()} aria-label="导入工作流配置"><FileUp /></Button><input ref={importInputRef} type="file" accept="application/json" className="hidden" onChange={event => { void onPickImportFile(event.target.files?.[0] ?? null) }} /></>}>
    <div className="flex shrink-0 flex-wrap items-center gap-3 border-b border-border px-5 py-3 text-xs text-muted-foreground"><span>拖动节点只改变布局，不修改业务配置。</span><span className="ml-auto">{layoutStatusLabel}</span></div>
    {datasetQuery.error || configQuery.error ? <div className="px-5"><WorkspaceNotice retry={() => { void refreshWorkflow() }}>{formatApiError(datasetQuery.error || configQuery.error, '工作流读取失败')}</WorkspaceNotice></div> : null}
    {saveError ? <div className="px-5"><WorkspaceNotice retry={() => { void doSaveLayout() }} retryLabel="重试保存" pending={saving}>{saveError}</WorkspaceNotice></div> : null}
    <div className={ws.canvasSplit}><Panel variant="seamless" padding="none" className={cn(workflowPanelClass, 'flex min-h-0 min-w-0 flex-col')}>
              <div className="flex shrink-0 items-center justify-between gap-3 border-b border-border/60 bg-card/65 px-3.5 py-2.5 dark:border-border/60 dark:bg-muted/20">
                <div className="min-w-0">
                  <div className="text-sm font-semibold text-foreground dark:text-foreground">配置链路图</div>

                </div>
                <div className="hidden shrink-0 items-center gap-1.5 text-[11px] text-muted-foreground md:flex">
                  <span className="rounded-full border border-border/60 bg-card/70 px-2 py-1 dark:border-border/60 dark:bg-muted/30">version {configVersionLabel}</span>
                  <span className="rounded-full border border-border/60 bg-card/70 px-2 py-1 dark:border-border/60 dark:bg-muted/30">{graph.nodes.length} nodes</span>
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
            </Panel><div className={cn(ws.canvasPanel, ws.inspector)}><Panel variant="seamless" className={cn(workflowPanelClass, 'flex min-h-0 flex-col p-0')}>
              <div className="flex shrink-0 items-start justify-between gap-3 border-b border-border/60 bg-card/65 px-3.5 py-3 dark:border-border/60 dark:bg-muted/20">
                <div className="min-w-0">
                  <div className="truncate text-sm font-semibold text-foreground dark:text-foreground">
                    {selectedNode?.label ? String(selectedNode.label) : '节点详情'}
                  </div>
                  <div className="mt-0.5 text-xs leading-4 text-muted-foreground">{selectedMetaStatusText}</div>
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
                    <div className="text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground/70">摘要</div>
                    <div className="flex flex-wrap gap-1.5">
                      {selectedSummary.slice(0, 20).map((s) => (
                        <Badge key={s} variant="outline" className="rounded-lg border-border/60 bg-card/70 font-mono text-xs dark:border-border/60 dark:bg-muted/30">
                          {String(s)}
                        </Badge>
                      ))}
                    </div>
                  </div>
                ) : null}

                <div className="space-y-2">
                  <div className="text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground/70">JSON</div>
                  <Textarea
                    value={selectedJsonText || ''}
                    readOnly
                    className="min-h-[200px] resize-none rounded-md border-border bg-muted/20 font-mono text-xs leading-5 shadow-none dark:border-border/60 dark:bg-muted/20"
                    placeholder="选择左侧节点后查看 JSON..."
                  />
                </div>
              </div>

              <div className="flex shrink-0 items-center justify-between gap-3 border-t border-border/60 px-3.5 py-2.5 text-xs text-muted-foreground dark:border-border/60">
                <span>导出版本 <span className="font-mono text-foreground">{configVersionLabel}</span></span>
                <span className="font-medium text-foreground">{layoutStatusLabel}</span>
              </div>
            </Panel></div></div>
    <Dialog open={nodeDetailOpen} onOpenChange={setNodeDetailOpen}><DialogContent className={ws.dialog}><DialogHeader className={ws.dialogHeader}><DialogTitle>节点详情</DialogTitle><DialogDescription>查看选中节点的配置。</DialogDescription></DialogHeader><div className={ws.dialogBody}><Panel variant="seamless" className={cn(workflowPanelClass, 'flex min-h-0 flex-col p-0')}>
              <div className="flex shrink-0 items-start justify-between gap-3 border-b border-border/60 bg-card/65 px-3.5 py-3 dark:border-border/60 dark:bg-muted/20">
                <div className="min-w-0">
                  <div className="truncate text-sm font-semibold text-foreground dark:text-foreground">
                    {selectedNode?.label ? String(selectedNode.label) : '节点详情'}
                  </div>
                  <div className="mt-0.5 text-xs leading-4 text-muted-foreground">{selectedMetaStatusText}</div>
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
                    <div className="text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground/70">摘要</div>
                    <div className="flex flex-wrap gap-1.5">
                      {selectedSummary.slice(0, 20).map((s) => (
                        <Badge key={s} variant="outline" className="rounded-lg border-border/60 bg-card/70 font-mono text-xs dark:border-border/60 dark:bg-muted/30">
                          {String(s)}
                        </Badge>
                      ))}
                    </div>
                  </div>
                ) : null}

                <div className="space-y-2">
                  <div className="text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground/70">JSON</div>
                  <Textarea
                    value={selectedJsonText || ''}
                    readOnly
                    className="min-h-[200px] resize-none rounded-md border-border bg-muted/20 font-mono text-xs leading-5 shadow-none dark:border-border/60 dark:bg-muted/20"
                    placeholder="选择左侧节点后查看 JSON..."
                  />
                </div>
              </div>

              <div className="flex shrink-0 items-center justify-between gap-3 border-t border-border/60 px-3.5 py-2.5 text-xs text-muted-foreground dark:border-border/60">
                <span>导出版本 <span className="font-mono text-foreground">{configVersionLabel}</span></span>
                <span className="font-medium text-foreground">{layoutStatusLabel}</span>
              </div>
            </Panel></div></DialogContent></Dialog>
        <Dialog open={importOpen} onOpenChange={(open) => setImportOpen(open)}>
          <DialogContent  className={ws.dialog}>
<DialogHeader  className={ws.dialogHeader}>
              <DialogTitle>导入工作流配置？</DialogTitle>
              <DialogDescription>
                将使用 <span className="font-mono">replace=true</span> 覆盖当前数据集配置。请确认 JSON 来源可靠。
              </DialogDescription>
            </DialogHeader>
<div className={ws.dialogBody}>

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

</div>
<DialogFooter  className={ws.dialogFooter}>
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
</OperationalWorkspace></AppFrame>
}
