'use client'

import {
  Trash2,
} from '@/components/icons'
import {
  useDeferredValue,
  useEffect,
  useMemo,
  useState,
  useCallback,
  useLayoutEffect,
  useRef,
} from 'react'

import { useSearchParams } from 'next/navigation'
import { toast } from 'sonner'

import { AppFrame } from '@/components/app-frame'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { OperationalWorkspace, WorkspaceNotice, workspaceStyles as ws } from '@/components/ui/operational-workspace'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from '@/components/ui/dialog'
import { useMediaQuery } from '@/hooks/use-media-query'
import { reportClientWarning } from '@/lib/client-logging'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Textarea } from '@/components/ui/textarea'
import { formatApiError } from '@/lib/api-errors'
import { datasetApi } from '@/lib/api/datasets'
import { documentApi } from '@/lib/api/documents'
import { kgApi } from '@/lib/api/graph'
import { metaApi } from '@/lib/api/meta'
import { reportApi } from '@/lib/api/reports'
import { sanitizeFilename } from '@/lib/sanitize'
import { cn, detachPromise } from '@/lib/utils'
import type { Dataset, KGGraphResponse } from '@/types'

import { JsonCodePane } from './components/json-code-pane'
import { SnapshotAuditPanel } from './components/snapshot-audit-panel'
import { SnapshotDiffView } from './components/snapshot-diff-view'
import { SnapshotGraphCanvas } from './components/snapshot-graph-canvas'
import { SnapshotNodeDetailsRail } from './components/snapshot-node-details-rail'
import {
  DiffEmptyState,
} from './components/shared'
import {
  DIFF_KEYS,
} from './constants'
import { buildSnapshotStudioGraphFromKgGraph } from './snapshot-graph'
import type {
  PipelineCandidate,
  SnapshotDeltaRow,
  SnapshotDiffPayload,
  SnapshotPayload,
  SnapshotView,
  StudioCanvasView,
} from './types'
import {
  auditSeverityForDriftScore,
  compactHashLabel,
  copyToClipboard,
  downloadJson,
  firstDisplayString,
  getDocumentMetaValue,
  getSelectedDatasetLabel,
  getSnapshotScopeSubtitle,
  mergePipelineCandidate,
  parseDocumentIds,
  prettyJson,
  sortPipelineCandidates,
} from './utils'

function snapshotTotal(snapshot: SnapshotPayload | null, key: string): number | null {
  const value = snapshot?.[key]
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

export function KGSnapshotsPage() {
  const searchParams = useSearchParams()
  const scopeParamKey = searchParams.toString()
  const datasetIdFromUrl = useMemo(() => {
    return (new URLSearchParams(scopeParamKey).get('dataset_id') || '').trim()
  }, [scopeParamKey])

  const [pipelineHashA, setPipelineHashA] = useState('')
  const [pipelineHashB, setPipelineHashB] = useState('')
  const [documentIdsRaw, setDocumentIdsRaw] = useState('')
  const [datasets, setDatasets] = useState<Dataset[]>([])
  const [datasetsLoading, setDatasetsLoading] = useState(false)
  const [selectedDatasetId, setSelectedDatasetId] = useState(datasetIdFromUrl)
  const [pipelineCandidates, setPipelineCandidates] = useState<PipelineCandidate[]>([])
  const [pipelineCandidatesLoading, setPipelineCandidatesLoading] = useState(false)
  const [pipelineCandidatesError, setPipelineCandidatesError] = useState<string | null>(null)
  const [liveGraph, setLiveGraph] = useState<KGGraphResponse | null>(null)
  const [liveGraphLoading, setLiveGraphLoading] = useState(false)
  const [liveGraphError, setLiveGraphError] = useState<string | null>(null)
  const [activeView, setActiveView] = useState<SnapshotView>('diff')
  const [studioCanvasView, setStudioCanvasView] =
    useState<StudioCanvasView>('table')
  const [studioSearch, setStudioSearch] = useState('')
  const [studioNodeType, setStudioNodeType] = useState('all')
  const [studioRelationType, setStudioRelationType] = useState('all')
  const [studioLayout, setStudioLayout] = useState('force')
  const [selectedStudioNodeId, setSelectedStudioNodeId] = useState('')
  const nodeTriggerRef = useRef<HTMLButtonElement | null>(null)
  const [scopeSettingsOpen, setScopeSettingsOpen] = useState(false)
  const [reloadVersion, setReloadVersion] = useState(0)
  const [datasetsError, setDatasetsError] = useState<string | null>(null)
  const [operationError, setOperationError] = useState<string | null>(null)
  const inlineScope = useMediaQuery('(min-width: 900px)')
  const inlineNode = useMediaQuery('(min-width: 1280px)')
  const [includeZeroDeltas, setIncludeZeroDeltas] = useState(true)
  const [compactAuditRows, setCompactAuditRows] = useState(true)

  const [snapA, setSnapA] = useState<SnapshotPayload | null>(null)
  const [snapB, setSnapB] = useState<SnapshotPayload | null>(null)
  const [diff, setDiff] = useState<SnapshotDiffPayload | null>(null)
  const [latencyMs, setLatencyMs] = useState<number | null>(null)
  const [isRunning, setIsRunning] = useState(false)

  const documentIds = useMemo(
    () => parseDocumentIds(documentIdsRaw),
    [documentIdsRaw]
  )
  const selectedDataset = useMemo(
    () => datasets.find((dataset) => dataset.id === selectedDatasetId) ?? null,
    [datasets, selectedDatasetId]
  )
  const scopeDatasetId = selectedDatasetId || undefined
  const scopeDocumentIds = documentIds.length > 0 ? documentIds : undefined
  const scopeDocumentIdsKey = scopeDocumentIds?.join(',') ?? ''
  const selectedDatasetLabel = getSelectedDatasetLabel(selectedDataset, selectedDatasetId)
  const requestContext = useMemo(() => ({ datasetId: selectedDatasetId, documents: scopeDocumentIdsKey, a: pipelineHashA, b: pipelineHashB }), [selectedDatasetId, scopeDocumentIdsKey, pipelineHashA, pipelineHashB])
  const requestContextRef = useRef(requestContext)
  const clearComparison = useCallback(() => {
    setSnapA(null); setSnapB(null); setDiff(null); setLatencyMs(null)
    setOperationError(null); setSelectedStudioNodeId('')
  }, [])
  useLayoutEffect(() => {
    requestContextRef.current = requestContext
    clearComparison()
    setIsRunning(false)
  }, [requestContext, clearComparison])


  useEffect(() => {
    setSelectedDatasetId(datasetIdFromUrl)
    setScopeSettingsOpen(false)
    setDocumentIdsRaw('')
    setPipelineHashA('')
    setPipelineHashB('')
    setSnapA(null)
    setSnapB(null)
    setDiff(null)
  }, [datasetIdFromUrl])

  useEffect(() => {
    let cancelled = false
    setDatasetsLoading(true)
    setDatasetsError(null)
    ;(async () => {
      try {
        const result = await datasetApi.listAll()
        if (!cancelled) {
          setDatasets(result)
        }
      } catch (error) {
        if (!cancelled) setDatasetsError(formatApiError(error, '数据集目录读取失败'))
      } finally {
        if (!cancelled) setDatasetsLoading(false)
      }
    })()

    return () => {
      cancelled = true
    }
  }, [reloadVersion])

  useEffect(() => {
    let cancelled = false
    const selectedDataset = selectedDatasetId.trim()
    setPipelineCandidatesLoading(true)
    setPipelineCandidatesError(null)
    ;(async () => {
      const candidateMap = new Map<string, PipelineCandidate>()
      try {
        if (selectedDataset) {
          const report = await reportApi.getDatasetReport(selectedDataset).catch(error => { reportClientWarning('Snapshot version report unavailable', error); return null })
          for (const version of report?.pipeline_versions ?? []) {
            mergePipelineCandidate(candidateMap, {
              hash: String(version.pipeline_hash || '').trim(),
              documents: Number(version.documents ?? 0) || 0,
              source: 'report',
              active: String(version.pipeline_hash || '').trim() === String(report?.pipeline_hash || '').trim(),
            })
          }
          const reportHash = String(report?.pipeline_hash || '').trim()
          if (reportHash) {
            const profile = report?.profile && typeof report.profile === 'object' ? report.profile : {}
            mergePipelineCandidate(candidateMap, {
              hash: reportHash,
              documents: Number((profile as Record<string, unknown>).document_count ?? 0) || 0,
              source: 'report',
              active: true,
            })
          }
        }

        const documents = await documentApi
          .list({
            skip: 0,
            limit: 200,
            dataset_id: selectedDataset || null,
            order_by: 'created_at',
            order_dir: 'desc',
          })

        for (const document of documents?.items ?? []) {
          const activeHash = firstDisplayString(
            getDocumentMetaValue(document, 'active_pipeline_hash')
          )
          const currentHash = firstDisplayString(getDocumentMetaValue(document, 'pipeline_hash'))
          if (activeHash) {
            mergePipelineCandidate(candidateMap, {
              hash: activeHash,
              documents: 1,
              source: 'documents',
              active: true,
            })
          }
          if (currentHash) {
            mergePipelineCandidate(candidateMap, {
              hash: currentHash,
              documents: 1,
              source: 'documents',
              active: currentHash === activeHash,
            })
          }
        }

        if (!cancelled) {
          const next = sortPipelineCandidates(Array.from(candidateMap.values()))
          setPipelineCandidates(next)
          setPipelineHashB((current) =>
            current.trim() ? current : next[0]?.hash ?? ''
          )
          setPipelineHashA((current) =>
            current.trim() ? current : next[1]?.hash ?? ''
          )
        }
      } catch (err) {
        if (!cancelled) {
          setPipelineCandidates([])
          setPipelineCandidatesError(formatApiError(err, '快照候选加载失败'))
        }
      } finally {
        if (!cancelled) setPipelineCandidatesLoading(false)
      }
    })()

    return () => {
      cancelled = true
    }
  }, [selectedDatasetId, reloadVersion])

  const snapAJson = useMemo(
    () => snapA ? prettyJson(snapA) : '',
    [snapA]
  )
  const snapBJson = useMemo(
    () => snapB ? prettyJson(snapB) : '',
    [snapB]
  )
  const diffJson = useMemo(
    () => diff ? prettyJson(diff) : '',
    [diff]
  )

  const diffDelta = useMemo(() => {
    const delta =
      diff?.delta && typeof diff.delta === 'object' ? diff.delta : null
    const entityTypesDelta = Array.isArray(diff?.entity_types_delta)
      ? diff.entity_types_delta
      : []
    return { delta, entityTypesDelta }
  }, [diff])
  const deferredEntityTypesDelta = useDeferredValue(diffDelta.entityTypesDelta)

  async function runExport(which: 'a' | 'b'): Promise<void> {
    const pipelineHash = (which === 'a' ? pipelineHashA : pipelineHashB).trim()
    if (!pipelineHash) {
      toast.error(which === 'a' ? '请选择快照 A' : '请选择快照 B')
      return
    }

    const currentContext = requestContext
    setOperationError(null)
    setIsRunning(true)
    try {
      const snapshot = await kgApi.exportSnapshot({
        pipeline_hash: pipelineHash,
        dataset_id: scopeDatasetId,
        document_ids: scopeDocumentIds,
        include_details: true,
      })
      if (requestContextRef.current !== currentContext) return
      setStudioCanvasView('table')
      if (which === 'a') {
        setSnapA(snapshot)
        setActiveView('a')
      } else {
        setSnapB(snapshot)
        setActiveView('b')
      }
      toast.success(`已读取版本 ${which.toUpperCase()}`)
    } catch (err) {
      if (requestContextRef.current !== currentContext) return
      setOperationError(formatApiError(err, '快照读取失败'))
    } finally {
      if (requestContextRef.current === currentContext) setIsRunning(false)
    }
  }

  async function runCompare(): Promise<void> {
    const a = pipelineHashA.trim()
    const b = pipelineHashB.trim()
    if (!a || !b) {
      toast.error('请选择快照 A / B')
      return
    }
    if (a === b) {
      toast.error('A / B pipeline_hash 不能相同')
      return
    }

    const currentContext = requestContext
    setOperationError(null)
    setIsRunning(true)
    setLatencyMs(null)
    try {
      const start = Date.now()
      const [snapshotA, snapshotB] = await Promise.all([
        kgApi.exportSnapshot({
          pipeline_hash: a,
          dataset_id: scopeDatasetId,
          document_ids: scopeDocumentIds,
          include_details: true,
        }),
        kgApi.exportSnapshot({
          pipeline_hash: b,
          dataset_id: scopeDatasetId,
          document_ids: scopeDocumentIds,
          include_details: true,
        }),
      ])
      const result = await kgApi.diffSnapshots({
        snapshot_a: snapshotA,
        snapshot_b: snapshotB,
      })
      if (requestContextRef.current !== currentContext) return
      setStudioCanvasView('table')
      setLatencyMs(Math.max(0, Date.now() - start))
      setSnapA(snapshotA)
      setSnapB(snapshotB)
      setDiff(result)
      setActiveView('diff')
      toast.success('已生成对比结果')
    } catch (err) {
      if (requestContextRef.current !== currentContext) return
      setOperationError(formatApiError(err, '快照对比失败'))
    } finally {
      if (requestContextRef.current === currentContext) setIsRunning(false)
    }
  }

  async function runBackendCompare(): Promise<void> {
    const a = pipelineHashA.trim()
    const b = pipelineHashB.trim()
    if (!a || !b) {
      toast.error('请选择快照 A / B')
      return
    }
    if (a === b) {
      toast.error('A / B pipeline_hash 不能相同')
      return
    }

    const currentContext = requestContext
    setOperationError(null)
    setIsRunning(true)
    setLatencyMs(null)
    try {
      const start = Date.now()
      const result = await kgApi.compareSnapshots({
        pipeline_hash_a: a,
        pipeline_hash_b: b,
        dataset_id: scopeDatasetId,
        document_ids: scopeDocumentIds,
      })
      if (requestContextRef.current !== currentContext) return
      setStudioCanvasView('table')
      setLatencyMs(Math.max(0, Date.now() - start))
      setDiff(result)
      setActiveView('diff')
      toast.success('已生成数量摘要')
    } catch (err) {
      if (requestContextRef.current !== currentContext) return
      setOperationError(formatApiError(err, '快照摘要读取失败'))
    } finally {
      if (requestContextRef.current === currentContext) setIsRunning(false)
    }
  }

  const hashAValue = pipelineHashA.trim()
  const hashBValue = pipelineHashB.trim()
  const liveGraphPipelineHash = hashBValue || hashAValue || undefined
  const hasHashA = Boolean(hashAValue)
  const hasHashB = Boolean(hashBValue)
  const hashATitle = hashAValue || '未设置'
  const hashBTitle = hashBValue || '未设置'
  const diffBaseName =
    sanitizeFilename(
      `kg_snapshot_${hashAValue || 'A'}_vs_${hashBValue || 'B'}`
    ) || 'kg_snapshot'
  const snapshotScopeSubtitle = getSnapshotScopeSubtitle(
    scopeDocumentIds?.length ?? 0,
    scopeDatasetId,
    selectedDatasetLabel
  )
  const snapshotAFileName =
    sanitizeFilename(`kg_snapshot_${hashAValue || 'A'}`) || 'kg_snapshot_A'
  const snapshotBFileName =
    sanitizeFilename(`kg_snapshot_${hashBValue || 'B'}`) || 'kg_snapshot_B'
  useLayoutEffect(() => {
    if (studioCanvasView !== 'graph' || scopeSettingsOpen) return
    let cancelled = false
    setLiveGraph(null)
    setLiveGraphLoading(true)
    setLiveGraphError(null)
    ;(async () => {
      try {
        const meta = await metaApi.details().catch(error => { reportClientWarning('Snapshot graph metadata unavailable', error); return null })
        if (meta?.features?.kg_enabled === false) {
          if (!cancelled) {
            setLiveGraph({ nodes: [], links: [] })
            setLiveGraphError(
              'KG 功能未启用，已按后端能力状态跳过实时图谱读取。请在设置中开启 KG 抽取后刷新。'
            )
          }
          return
        }

        const graph = await kgApi.getGraph({
          dataset_id: scopeDatasetId,
          document_ids: scopeDocumentIds,
          pipeline_hash: liveGraphPipelineHash,
          max_events: 80,
          max_entities: 80,
          max_links: 160,
          include_entity_links: true,
          include_relation_links: true,
          min_shared_events: 1,
          max_entity_links: 160,
        })
        if (!cancelled) setLiveGraph(graph)
      } catch (err) {
        if (!cancelled) {
          setLiveGraph({ nodes: [], links: [] })
          setLiveGraphError(formatApiError(err, 'KG 图谱读取失败'))
        }
      } finally {
        if (!cancelled) setLiveGraphLoading(false)
      }
    })()

    return () => {
      cancelled = true
    }
  }, [
    liveGraphPipelineHash,
    studioCanvasView,
    scopeSettingsOpen,
    reloadVersion,
    selectedDatasetId,
    scopeDatasetId,
    scopeDocumentIds,
    scopeDocumentIdsKey,
  ])

  const studioGraph = useMemo(
    () => buildSnapshotStudioGraphFromKgGraph(liveGraph),
    [liveGraph]
  )
  const nodeTypes = useMemo(
    () => Array.from(new Set(studioGraph.nodes.map((node) => node.type))),
    [studioGraph.nodes]
  )
  const relationTypes = useMemo(
    () => Array.from(new Set(studioGraph.links.map((link) => link.label))),
    [studioGraph.links]
  )
  const selectedStudioNode = useMemo(() => {
    return (
      studioGraph.nodes.find((node) => node.id === selectedStudioNodeId) ??
      null
    )
  }, [selectedStudioNodeId, studioGraph.nodes])
  useEffect(() => {
    if (selectedStudioNodeId && !studioGraph.nodes.some((node) => node.id === selectedStudioNodeId)) {
      setSelectedStudioNodeId('')
    }
  }, [selectedStudioNodeId, studioGraph.nodes])

  const totalsReady = DIFF_KEYS.every(key => snapshotTotal(snapA, key) !== null && snapshotTotal(snapB, key) !== null)
  const deltaRows = useMemo<SnapshotDeltaRow[]>(() => {
    if (!totalsReady) return []
    return DIFF_KEYS.map((key) => {
      const a = snapshotTotal(snapA, key)!
      const b = snapshotTotal(snapB, key)!
      const d = Number(diffDelta.delta?.[key] ?? b - a)
      return {
        key,
        a: Number.isFinite(a) ? a : 0,
        b: Number.isFinite(b) ? b : 0,
        delta: Number.isFinite(d) ? d : 0,
      }
    })
  }, [diffDelta.delta, snapA, snapB, totalsReady])
  const driftScore = useMemo(() => {
    const denominator = deltaRows.reduce(
      (acc, row) => acc + Math.max(Math.max(row.a, row.b), 1),
      0
    )
    if (denominator <= 0) return 0
    const totalDelta = deltaRows.reduce(
      (acc, row) => acc + Math.abs(row.delta),
      0
    )
    return totalDelta / denominator
  }, [deltaRows])
  const auditSeverity = auditSeverityForDriftScore(driftScore)
  const auditDriftRows = useMemo(() => {
    return [...deferredEntityTypesDelta].sort(
      (a, b) => Math.abs(Number(b.delta ?? 0)) - Math.abs(Number(a.delta ?? 0))
    )
  }, [deferredEntityTypesDelta])
  const view = studioCanvasView === 'table' ? activeView : studioCanvasView
  const changeDataset = (value: string) => { setSelectedDatasetId(value); setPipelineHashA(''); setPipelineHashB(''); setDocumentIdsRaw(''); setStudioSearch(''); setStudioNodeType('all'); setStudioRelationType('all') }
  const scopeFields = <div className="grid w-full gap-4 md:grid-cols-[minmax(180px,1fr)_repeat(2,minmax(150px,1fr))]">
    <label className="min-w-0 space-y-2 text-sm"><span>数据集</span><select aria-label="快照数据集" value={selectedDatasetId} disabled={datasetsLoading || isRunning} onChange={event => changeDataset(event.target.value)} className="h-10 w-full rounded-md border border-border bg-background px-3 text-sm"><option value="">全部数据集</option>{selectedDatasetId && !datasets.some(item => item.id === selectedDatasetId) ? <option value={selectedDatasetId}>{selectedDatasetLabel}</option> : null}{datasets.map(item => <option key={item.id} value={item.id}>{item.name || item.id}</option>)}</select></label>
    {(['a', 'b'] as const).map(which => { const value = which === 'a' ? pipelineHashA : pipelineHashB; return <label key={which} className="min-w-0 space-y-2 text-sm"><span>版本 {which.toUpperCase()}</span><select aria-label={`快照 ${which.toUpperCase()}`} value={value} disabled={isRunning || pipelineCandidatesLoading} onChange={event => { if (which === 'a') setPipelineHashA(event.target.value); else setPipelineHashB(event.target.value) }} className="h-10 w-full rounded-md border border-border bg-background px-3 text-sm"><option value="">{pipelineCandidatesLoading ? '正在读取版本…' : '选择版本'}</option>{value && !pipelineCandidates.some(item => item.hash === value) ? <option value={value}>手动版本 · {compactHashLabel(value)}</option> : null}{pipelineCandidates.map(item => <option key={item.hash} value={item.hash}>{item.active ? '当前' : '历史'} · {compactHashLabel(item.hash)}</option>)}</select></label> })}
  </div>
  return <AppFrame showBackground={false}><OperationalWorkspace title="图谱快照" icon="kg-snapshot" context={selectedDatasetLabel} mode="canvas" actions={<><Button variant="outline" onClick={() => setScopeSettingsOpen(true)} disabled={isRunning}>版本与范围</Button><Button disabled={isRunning || !hashAValue || !hashBValue || hashAValue === hashBValue} onClick={() => { void runCompare() }}>{isRunning ? '正在对比…' : '开始对比'}</Button><Button variant="ghost" size="icon" aria-label="清空快照对比" disabled={isRunning} onClick={() => { clearComparison(); setActiveView('diff'); setStudioCanvasView('table') }}><Trash2 /></Button></>} toolbar={inlineScope ? scopeFields : <><span className="min-w-0 flex-1 text-sm text-muted-foreground">A {hashAValue ? compactHashLabel(hashAValue) : '未选择'} → B {hashBValue ? compactHashLabel(hashBValue) : '未选择'}</span><Button variant="ghost" onClick={() => setScopeSettingsOpen(true)}>选择版本</Button></>}>
    {datasetsError ? <div className="px-5"><WorkspaceNotice retry={() => setReloadVersion(value => value + 1)}>{datasetsError}</WorkspaceNotice></div> : null}
    {pipelineCandidatesError ? <div className="px-5"><WorkspaceNotice retry={() => setReloadVersion(value => value + 1)}>{pipelineCandidatesError}</WorkspaceNotice></div> : null}
    {operationError ? <div className="px-5"><WorkspaceNotice>{operationError}</WorkspaceNotice></div> : null}
    {latencyMs !== null ? <p className="px-6 pt-2 text-right text-xs text-muted-foreground">对比耗时 {latencyMs} ms</p> : null}
    <Tabs value={view} onValueChange={value => { setSelectedStudioNodeId(''); if (value === 'graph' || value === 'stats') setStudioCanvasView(value); else { setStudioCanvasView('table'); setActiveView(value as SnapshotView) } }} className="flex min-h-0 flex-1 flex-col">
      <div className="px-4 md:px-6"><TabsList className={ws.tabList}><TabsTrigger value="diff">内容差异</TabsTrigger><TabsTrigger value="a">快照 A</TabsTrigger><TabsTrigger value="b">快照 B</TabsTrigger><TabsTrigger value="graph">图谱预览</TabsTrigger><TabsTrigger value="stats">统计</TabsTrigger></TabsList></div>
<TabsContent value="diff" className={cn(ws.tabContent, "flex min-h-0 flex-1 flex-col")}>
                        <SnapshotDiffView
                          titleA={`Snapshot A · ${hashATitle}`}
                          titleB={`Snapshot B · ${hashBTitle}`}
                          subtitleA={snapshotScopeSubtitle}
                          subtitleB={snapshotScopeSubtitle}
                          leftCode={snapAJson}
                          rightCode={snapBJson}
                          diff={diff}
                          pending={isRunning}
                          onLoadDetails={() => { void runCompare() }}
                          isEmpty={!diff}
                          emptyState={
                            <DiffEmptyState
                              title="还没有对比结果"
                              description="填写左侧的快照 A / 快照 B，可以选择文档范围，然后点击「开始对比」生成左右差异与节点/边精确变更。"
                              hint={
                                hasHashA && hasHashB
                                  ? '已就绪：直接点击「开始对比」'
                                  : '提示：A / B Hash 二者皆需填写'
                              }
                            />
                          }
                          onCopy={() =>
                            detachPromise(
                              copyToClipboard(diffJson, 'diff JSON')
                            )
                          }
                          onDownload={() => {
                            downloadJson(
                              diff ?? {},
                              `${diffBaseName}.diff.json`
                            )
                            toast.success('已导出 diff.json')
                          }}
                        />
                      </TabsContent>
<TabsContent value="a" className={cn(ws.tabContent, "flex min-h-0 flex-1 flex-col")}>
                        <JsonCodePane
                          label="A 视图"
                          title="快照内容"
                          subtitle={
                            hashAValue ? `Hash · ${hashAValue}` : '尚未导出'
                          }
                          code={snapAJson}
                          isEmpty={!snapA}
                          emptyState={
                            <DiffEmptyState
                              title="A 视图为空"
                              description="选择版本 A，再点击“读取 A”查看快照内容。"
                              hint={
                                hasHashA
                                  ? '可在“版本与范围”中读取 A'
                                  : '请先选择版本 A'
                              }
                            />
                          }
                          onCopy={() =>
                            detachPromise(
                              copyToClipboard(snapAJson, 'snapshot A JSON')
                            )
                          }
                          onDownload={() => {
                            downloadJson(
                              snapA ?? {},
                              `${snapshotAFileName}.json`
                            )
                            toast.success('已导出 snapshot A')
                          }}
                        />
                      </TabsContent>
<TabsContent value="b" className={cn(ws.tabContent, "flex min-h-0 flex-1 flex-col")}>
                        <JsonCodePane
                          label="B 视图"
                          title="快照内容"
                          subtitle={
                            hashBValue ? `Hash · ${hashBValue}` : '尚未导出'
                          }
                          code={snapBJson}
                          isEmpty={!snapB}
                          emptyState={
                            <DiffEmptyState
                              title="B 视图为空"
                              description="选择版本 B，再点击“读取 B”查看快照内容。"
                              hint={
                                hasHashB
                                  ? '可在“版本与范围”中读取 B'
                                  : '请先选择版本 B'
                              }
                            />
                          }
                          onCopy={() =>
                            detachPromise(
                              copyToClipboard(snapBJson, 'snapshot B JSON')
                            )
                          }
                          onDownload={() => {
                            downloadJson(
                              snapB ?? {},
                              `${snapshotBFileName}.json`
                            )
                            toast.success('已导出 snapshot B')
                          }}
                        />
                      </TabsContent>
      <TabsContent value="graph" className={cn(ws.tabContent, 'flex min-h-0 flex-1 flex-col')}>
        <div className="flex shrink-0 flex-wrap items-center gap-3 border-b border-border px-4 py-3 md:px-6"><Input className="w-52 max-w-full" aria-label="搜索快照节点或关系" value={studioSearch} onChange={event => setStudioSearch(event.target.value)} placeholder="搜索节点或关系" /><select aria-label="节点类型" value={studioNodeType} onChange={event => setStudioNodeType(event.target.value)} className="h-10 rounded-md border border-border bg-background px-3 text-sm"><option value="all">全部节点类型</option>{nodeTypes.map(type => <option key={type}>{type}</option>)}</select><select aria-label="关系类型" value={studioRelationType} onChange={event => setStudioRelationType(event.target.value)} className="h-10 rounded-md border border-border bg-background px-3 text-sm"><option value="all">全部关系类型</option>{relationTypes.map(type => <option key={type}>{type}</option>)}</select><select aria-label="图谱布局" value={studioLayout} onChange={event => setStudioLayout(event.target.value)} className="h-10 rounded-md border border-border bg-background px-3 text-sm"><option value="force">力导向</option><option value="radial">径向</option><option value="layered">分层</option></select><Button className="ml-auto" variant="ghost" disabled={liveGraphLoading} onClick={() => setReloadVersion(value => value + 1)}>重新读取图谱</Button></div>
        {liveGraphError ? <div className="px-6"><WorkspaceNotice retry={() => setReloadVersion(value => value + 1)}>{liveGraphError}</WorkspaceNotice></div> : null}
        <div className="flex min-h-0 flex-1"><div className="min-h-0 min-w-0 flex-1 overflow-auto"><div className="h-full min-h-[420px] min-w-[640px]">{!liveGraphError ? (                    <SnapshotGraphCanvas
                      nodes={studioGraph.nodes}
                      links={studioGraph.links}
                      layout={studioLayout}
                    selectedNodeId={selectedStudioNodeId}
                      searchValue={studioSearch}
                      nodeType={studioNodeType}
                      relationType={studioRelationType}
                      nodeCount={studioGraph.nodes.length}
                      relationCount={studioGraph.links.length}
                      isLoading={liveGraphLoading}
                      emptyMessage={
                        liveGraphError ||
                        ((studioSearch.trim() || studioNodeType !== 'all' || studioRelationType !== 'all') ? '当前筛选下没有匹配节点，可调整搜索或类型。' : selectedDatasetId
                          ? '当前数据集没有返回 KG 节点，请确认文档已完成入库且已开启 KG 抽取。'
                          : '当前后端 KG 图谱接口没有返回节点。')
                      }
                      onSelectNode={(id, trigger) => {
                        nodeTriggerRef.current = trigger
                        setSelectedStudioNodeId(id)
                      }}
                    />) : null}</div></div>{inlineNode && selectedStudioNode ? <SnapshotNodeDetailsRail className="w-80 shrink-0 border-l border-border bg-background" selectedNode={selectedStudioNode} onClose={() => setSelectedStudioNodeId('')} onSelectRelationTarget={setSelectedStudioNodeId} /> : null}</div>
      </TabsContent>
      <TabsContent value="stats" className={cn(ws.tabContent, 'min-h-0 flex-1 overflow-y-auto px-4 py-5 md:px-6')}>
        {diff ? totalsReady ? <SnapshotAuditPanel
                      deltaRows={deltaRows}
                      typeDriftRows={auditDriftRows}
                      severity={auditSeverity}
                      driftScore={driftScore}
                      includeZeroDeltas={includeZeroDeltas}
                      compactRows={compactAuditRows}
                      onIncludeZeroDeltasChange={setIncludeZeroDeltas}
                      onCompactRowsChange={setCompactAuditRows}
                    /> : <div>
          <section className={ws.section}><div className={ws.sectionHeading}><div><h2 className={ws.sectionTitle}>数量变化摘要</h2><p className={ws.sectionDescription}>变化数量已取得；读取两份快照后可计算两侧总量和变化比例。</p></div><Button variant="outline" disabled={isRunning} onClick={() => {
            const context = requestContextRef.current
            void runCompare().then(() => { if (requestContextRef.current === context) { setStudioCanvasView('stats') } })
          }}>读取完整快照</Button></div>
          <div className={ws.tableScroll}><table className={ws.table} aria-label="快照统计对比"><thead><tr><th>指标</th><th>A</th><th>B</th><th>变化</th></tr></thead><tbody>{DIFF_KEYS.map(key => {
            const change = diffDelta.delta?.[key]
            const value = typeof change === 'number' && Number.isFinite(change) ? change : null
            return <tr key={key}><td>{({ docs: '文档', events: '事件', entities: '实体', links: '关联', relations: '关系' })[key]}</td><td>{snapshotTotal(snapA, key) ?? '未取得'}</td><td>{snapshotTotal(snapB, key) ?? '未取得'}</td><td>{value === null ? '未取得' : value > 0 ? `+${value}` : value}</td></tr>
          })}</tbody></table></div></section>
          <section className={ws.section}><h2 className={ws.sectionTitle}>实体类型变化</h2>{auditDriftRows.length ? <div className={ws.tableScroll}><table className={ws.table}><thead><tr><th>类型</th><th>变化</th></tr></thead><tbody>{auditDriftRows.map((row, index) => <tr key={`${row.type || ''}:${index}`}><td>{row.type || '未返回类型名'}</td><td>{typeof row.delta === 'number' ? row.delta : '未取得'}</td></tr>)}</tbody></table></div> : <p className="py-5 text-sm text-muted-foreground">当前摘要未返回实体类型变化明细</p>}</section>
        </div> : <div className={ws.empty}><h2>尚未生成对比结果</h2><p>选择两个版本并开始对比后，查看结构变化统计。</p></div>}
      </TabsContent>
    </Tabs>
    <Dialog open={scopeSettingsOpen} onOpenChange={setScopeSettingsOpen}><DialogContent className={ws.dialog}><DialogHeader className={ws.dialogHeader}><DialogTitle>版本与对比范围</DialogTitle><DialogDescription>选择版本后生成对比；也可指定文档范围。</DialogDescription></DialogHeader><div className={cn(ws.dialogBody, 'space-y-5')}>
      {!inlineScope ? scopeFields : null}
      <details className="text-sm"><summary className="cursor-pointer font-medium">手动填写版本标识</summary><div className="mt-4 grid gap-4 sm:grid-cols-2"><label className="space-y-2"><span>快照 A 标识</span><Input value={pipelineHashA} disabled={isRunning} onChange={event => setPipelineHashA(event.target.value)} /></label><label className="space-y-2"><span>快照 B 标识</span><Input value={pipelineHashB} disabled={isRunning} onChange={event => setPipelineHashB(event.target.value)} /></label></div></details>
      <div className="space-y-2 text-sm">
        <label htmlFor="snapshot-documents">文档范围（选填）</label>
        <Textarea id="snapshot-documents" aria-describedby="snapshot-documents-help" value={documentIdsRaw} disabled={isRunning} onChange={event => setDocumentIdsRaw(event.target.value)} rows={4} placeholder="用逗号或换行分隔文档编号" />
        <p id="snapshot-documents-help" className={ws.muted}>留空按数据集范围读取。</p>
      </div>
      <div className="flex flex-wrap gap-2">
        <Button variant="outline" disabled={isRunning || !hashAValue} onClick={() => { setScopeSettingsOpen(false); void runExport('a') }}>读取 A</Button>
        <Button variant="outline" disabled={isRunning || !hashBValue} onClick={() => { setScopeSettingsOpen(false); void runExport('b') }}>读取 B</Button>
        <Button variant="ghost" disabled={isRunning || !hashAValue || !hashBValue || hashAValue === hashBValue} onClick={() => { setScopeSettingsOpen(false); void runBackendCompare() }}>仅比较摘要</Button>
      </div>
    </div><DialogFooter className={ws.dialogFooter}><Button variant="outline" onClick={() => setScopeSettingsOpen(false)}>完成</Button><Button disabled={isRunning || !hashAValue || !hashBValue || hashAValue === hashBValue} onClick={() => { setScopeSettingsOpen(false); void runCompare() }}>开始对比</Button></DialogFooter></DialogContent></Dialog>
    <Dialog open={!inlineNode && Boolean(selectedStudioNode)} onOpenChange={open => { if (!open) setSelectedStudioNodeId('') }}><DialogContent className={ws.dialog} aria-describedby={undefined} onCloseAutoFocus={event => {
      event.preventDefault()
      nodeTriggerRef.current?.focus()
    }}><DialogHeader className={ws.dialogHeader}><DialogTitle>节点详情</DialogTitle></DialogHeader><div className={ws.dialogBody}><SnapshotNodeDetailsRail hideHeader selectedNode={selectedStudioNode} onClose={() => setSelectedStudioNodeId('')} onSelectRelationTarget={setSelectedStudioNodeId} /></div></DialogContent></Dialog>
  </OperationalWorkspace></AppFrame>
}
