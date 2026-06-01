'use client'

import { startTransition, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useParams } from 'next/navigation'
import { useQuery } from '@tanstack/react-query'
import { toast } from 'sonner'
import { ArrowLeft, BarChart3, Download, FileUp, Layers, Loader2, RefreshCw, Save, Settings2, Table2 } from 'lucide-react'

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
  const pageTitle = dataset?.name ? `Workflow · ${dataset.name}` : 'Workflow'
  const selectedMetaStatusText =
    selectedMeta?.configured === false
      ? 'Not configured (inherits defaults)'
      : selectedMeta?.configured === true
        ? 'Configured'
        : 'Click a node in the workflow editor to inspect summary + JSON'
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
    toast.error(formatApiError(loadError, 'Failed to load workflow config'))
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
      toast.success('Exported config')
    } catch (e: unknown) {
      reportClientError('Failed to export dataset config', e)
      toast.error(formatApiError(e, 'Export failed'))
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
        toast.error('Invalid JSON: expected DatasetConfigBundle or { config: DatasetConfigBundle }')
        return
      }
      setImportFileName(file.name || 'config.json')
      setImportBundle(bundle)
      setImportOpen(true)
    } catch (e: unknown) {
      reportClientError('Failed to parse dataset config import JSON', e)
      toast.error('Failed to parse JSON file')
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
      toast.success('Imported config (replace=true)')
      setImportOpen(false)
      setImportBundle(null)
      setImportFileName('')
      await refreshWorkflow()
    } catch (e: unknown) {
      reportClientError('Failed to import dataset config', e)
      toast.error(formatApiError(e, 'Import failed'))
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
      toast.success('Saved workflow layout')
      await refreshWorkflow()
    } catch (e: unknown) {
      reportClientError('Failed to save workflow layout', e)
      toast.error(formatApiError(e, 'Save failed'))
    } finally {
      setSaving(false)
    }
  }, [datasetId, refreshWorkflow, workingConfig])

  const copySelectedJson = useCallback(async () => {
    if (!selectedJsonText.trim()) return
    try {
      await navigator.clipboard.writeText(selectedJsonText)
      toast.success('Copied JSON')
    } catch (e) {
      reportClientError('Failed to copy selected workflow JSON', e)
      toast.error('Copy failed')
    }
  }, [selectedJsonText])

  return (
    <AppFrame>
      <PageScaffold
        title={pageTitle}
        badge="Dataset Workflow"
        icon={Layers}
        iconColor="text-teal"
        description={
          <span className="text-sm text-muted-foreground">
            Editable workflow view of <span className="font-mono">DatasetConfigBundle</span> with export/import and layout persistence.
          </span>
        }
        actions={
          <div className="flex items-center gap-2">
            <Button variant="outline" className="gap-2" onClick={() => router.push('/datasets')}>
              <ArrowLeft className="w-4 h-4" />
              Back
            </Button>
            {datasetId ? (
              <Button variant="outline" className="gap-2" onClick={() => router.push(`/datasets/${datasetId}/ingestion`)}>
                <Settings2 className="w-4 h-4" />
                Ingestion
              </Button>
            ) : null}
            {datasetId ? (
              <Button variant="outline" className="gap-2" onClick={() => router.push(`/datasets/${datasetId}/profile`)}>
                <BarChart3 className="w-4 h-4" />
                Profile
              </Button>
            ) : null}
            {datasetId ? (
              <Button variant="outline" className="gap-2" onClick={() => router.push(`/datasets/${datasetId}/tables`)}>
                <Table2 className="w-4 h-4" />
                Tables
              </Button>
            ) : null}
            <Button variant="outline" className="gap-2" onClick={() => detachPromise(refreshWorkflow())} disabled={loading}>
              <RefreshCw className={cn('w-4 h-4', loading && 'animate-spin motion-reduce:animate-none')} />
              Refresh
            </Button>
            {hasUnsavedLayoutChanges ? <Badge variant="secondary">Unsaved layout</Badge> : null}
            <Button
              className="gap-2"
              onClick={() => detachPromise(doSaveLayout())}
              disabled={saving || !datasetId || !workingConfig || !hasUnsavedLayoutChanges}
            >
              {saving ? <Loader2 className="w-4 h-4 animate-spin motion-reduce:animate-none" /> : <Save className="w-4 h-4" />}
              Save Layout
            </Button>
            <Button variant="outline" className="gap-2" onClick={() => detachPromise(doExport())} disabled={exporting}>
              {exporting ? <Loader2 className="w-4 h-4 animate-spin motion-reduce:animate-none" /> : <Download className="w-4 h-4" />}
              Export JSON
            </Button>
            <Button variant="outline" className="gap-2" onClick={() => importInputRef.current?.click()} disabled={importing}>
              {importing ? <Loader2 className="w-4 h-4 animate-spin motion-reduce:animate-none" /> : <FileUp className="w-4 h-4" />}
              Import JSON
            </Button>
            <input
              ref={importInputRef}
              type="file"
              accept="application/json"
              className="hidden"
              onChange={(e) => detachPromise(onPickImportFile(e.target.files?.[0] || null))}
            />
          </div>
        }
      >
        <div className="grid gap-4 lg:grid-cols-[1fr_420px]">
          <Panel padding="none" className="overflow-hidden h-[min(720px,calc(100vh-260px))] min-h-[480px]">
            <WorkflowEditor
              graph={graph}
              workflowLayout={workingConfig?.workflow_layout ?? null}
              onWorkflowLayoutChange={onWorkflowLayoutChange}
              onNodeSelect={(node) => setSelectedNode(node)}
            />
          </Panel>

          <Panel className="h-[min(720px,calc(100vh-260px))] min-h-[480px] flex flex-col overflow-hidden">
            <div className="flex items-start justify-between gap-3 pb-3 border-b border-border/70">
              <div className="min-w-0">
                <div className="font-semibold truncate">
                  {selectedNode?.label ? String(selectedNode.label) : 'Node Details'}
                </div>
                <div className="text-xs text-muted-foreground">{selectedMetaStatusText}</div>
              </div>
              {selectedJsonText.trim() ? (
                <div className="flex items-center gap-2 flex-shrink-0">
                  <Button variant="outline" size="sm" onClick={() => detachPromise(copySelectedJson())}>
                    Copy JSON
                  </Button>
                </div>
              ) : null}
            </div>

            <div className="flex-1 min-h-0 overflow-y-auto overscroll-contain pt-3 space-y-4 no-scrollbar">
              {selectedSummary.length > 0 ? (
                <div className="space-y-2">
                  <div className="text-xs font-medium text-muted-foreground">Summary</div>
                  <div className="flex flex-wrap gap-2">
                    {selectedSummary.slice(0, 20).map((s) => (
                      <Badge key={String(s)} variant="outline" className="font-mono text-[11px]">
                        {String(s)}
                      </Badge>
                    ))}
                  </div>
                </div>
              ) : null}

              <div className="space-y-2">
                <div className="text-xs font-medium text-muted-foreground">JSON</div>
                <Textarea
                  value={selectedJsonText || ''}
                  readOnly
                  className="font-mono text-xs min-h-[280px]"
                  placeholder="Select a node to view JSON…"
                />
              </div>

              {exportRes ? (
                <div className="pt-2 text-xs text-muted-foreground">
                  Export version: <span className="font-mono">{String(exportRes.version || '')}</span>
                </div>
              ) : null}
            </div>
          </Panel>
        </div>

        <Dialog open={importOpen} onOpenChange={(open) => setImportOpen(open)}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Import workflow config?</DialogTitle>
              <DialogDescription>
                This will overwrite dataset config using <span className="font-mono">replace=true</span>. This action may clear existing keys.
              </DialogDescription>
            </DialogHeader>

            <div className="space-y-3">
              <div className="text-sm">
                File: <span className="font-mono">{importFileName || 'config.json'}</span>
              </div>
              {importKeys.length > 0 ? (
                <div className="space-y-2">
                  <div className="text-xs font-medium text-muted-foreground">Top-level keys</div>
                  <div className="flex flex-wrap gap-2">
                    {importKeys.slice(0, 24).map((k) => (
                      <Badge key={k} variant="outline" className="font-mono text-[11px]">
                        {k}
                      </Badge>
                    ))}
                    {importKeys.length > 24 ? (
                      <Badge variant="secondary" className="font-mono text-[11px]">
                        +{importKeys.length - 24} more
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
                Cancel
              </Button>
              <Button onClick={() => detachPromise(doImport())} disabled={importing || !importBundle || !datasetId} className="gap-2">
                {importing ? <Loader2 className="w-4 h-4 animate-spin motion-reduce:animate-none" /> : null}
                Import (replace)
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </PageScaffold>
    </AppFrame>
  )
}
