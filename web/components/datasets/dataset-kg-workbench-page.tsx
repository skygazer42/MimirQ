'use client'

import { useQuery } from '@tanstack/react-query'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { Remote } from 'comlink'
import { useParams } from 'next/navigation'
import { toast } from 'sonner'
import {
  ArrowLeft,
  Loader2,
  Network,
  RefreshCw,
  Search,
  Settings2,
  Sparkles,
  Wrench,
} from 'lucide-react'

import { AppFrame } from '@/components/app-frame'
import { GraphViewer, type GraphViewerRef } from '@/components/graph/graph-viewer'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { PageLoading } from '@/components/ui/page-loading'
import { PageScaffold } from '@/components/ui/page-scaffold'
import { Panel } from '@/components/ui/panel'
import { Skeleton } from '@/components/ui/skeleton'
import { StepIndicator } from '@/components/ui/step-indicator'
import { useRouter } from '@/i18n/navigation'

import { datasetApi, documentApi, kgApi } from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'
import { applyClusterPalette } from '@/lib/graph-cluster-palette'
import type { GraphClusterResult } from '@/lib/graph-clustering'
import type { GraphData } from '@/lib/graph-parser'
import { queryKeys } from '@/lib/query-keys'
import { cn, detachPromise } from '@/lib/utils'
import { GraphService } from '@/lib/graph-service'
import type { GraphClusteringWorkerApi } from '@/workers/graph-clustering.worker'

import type { Document, KGExtractResponse, KGGraphNode, KGStatsResponse } from '@/types'

function asDatasetId(raw: unknown): string | null {
  if (typeof raw === 'string' && raw.trim()) return raw
  if (Array.isArray(raw) && typeof raw[0] === 'string') return raw[0]
  return null
}

function limitPositiveInt(raw: unknown, fallback: number, opts?: { min?: number; max?: number }): number {
  const n = Math.floor(Number(raw))
  if (!Number.isFinite(n)) return fallback
  const min = opts?.min ?? 1
  const max = opts?.max ?? 10_000
  return Math.min(max, Math.max(min, n))
}

function primitiveText(value: unknown, fallback = ''): string {
  if (typeof value === 'string') return value
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  return fallback
}

async function runWithConcurrency<T>(
  items: T[],
  concurrency: number,
  worker: (item: T, index: number) => Promise<void>
): Promise<void> {
  const resolvedConcurrency = Math.max(1, Math.floor(concurrency))
  let nextIndex = 0

  async function runOne() {
    for (;;) {
      const current = nextIndex
      nextIndex += 1
      if (current >= items.length) return
      await worker(items[current], current)
    }
  }

  await Promise.all(Array.from({ length: Math.min(resolvedConcurrency, items.length) }, () => runOne()))
}

const DOCS_LOADING_SKELETON_KEYS = ['docs-loading-1', 'docs-loading-2', 'docs-loading-3', 'docs-loading-4']
const SEARCH_RESULTS_SKELETON_KEYS = ['search-loading-1', 'search-loading-2', 'search-loading-3']
const GRAPH_STATS_SKELETON_KEYS = ['graph-stat-loading-1', 'graph-stat-loading-2', 'graph-stat-loading-3', 'graph-stat-loading-4']
const KG_WORKBENCH_DOCUMENT_PARAMS = {
  skip: 0,
  limit: 100,
  order_by: 'created_at' as const,
  order_dir: 'desc' as const,
}
const EMPTY_DOCS: Document[] = []

function DocsLoadingSkeleton() {
  return (
    <div className="rounded-xl border border-border/60 bg-muted/10 p-3">
      <div className="rounded-lg border border-dashed border-border/60 bg-background/80 p-3">
        <PageLoading
          className="min-h-0 flex-none justify-start"
          message="正在加载文档范围..."
          srMessage="Loading dataset documents"
        />
      </div>
      <div className="mt-3 space-y-2">
        {DOCS_LOADING_SKELETON_KEYS.map((key) => (
          <div
            key={key}
            className="flex items-start gap-3 rounded-lg border border-border/60 bg-background/70 px-3 py-3"
          >
            <Skeleton className="mt-0.5 h-4 w-4 rounded-sm" />
            <div className="min-w-0 flex-1 space-y-2">
              <Skeleton className="h-4 w-4/5" />
              <Skeleton className="h-3 w-3/5" />
            </div>
            <Skeleton className="h-7 w-16 rounded-lg" />
          </div>
        ))}
      </div>
    </div>
  )
}

function SearchResultsSkeleton() {
  return (
    <div className="rounded-xl border border-border/60 bg-muted/10 p-3">
      <div className="space-y-2">
        {SEARCH_RESULTS_SKELETON_KEYS.map((key) => (
          <div key={key} className="rounded-lg border border-border/60 bg-background/70 px-3 py-3">
            <Skeleton className="h-4 w-3/5" />
            <Skeleton className="mt-2 h-3 w-2/5" />
          </div>
        ))}
      </div>
    </div>
  )
}

function GraphPreviewSkeleton() {
  return (
    <div className="flex h-full min-h-[520px] items-center justify-center p-6">
      <div className="w-full max-w-3xl rounded-2xl border border-border/70 bg-card/90 p-6 shadow-soft backdrop-blur-sm">
        <PageLoading
          className="min-h-0 flex-none justify-start"
          message="正在构建图谱预览..."
          srMessage="Loading dataset graph preview"
        />
        <div className="mt-5 flex flex-wrap gap-2">
          {GRAPH_STATS_SKELETON_KEYS.map((key) => (
            <Skeleton key={key} className="h-6 w-24 rounded-full" />
          ))}
        </div>
        <div className="mt-6 grid gap-3 lg:grid-cols-[minmax(0,1.45fr)_minmax(260px,0.85fr)]">
          <Skeleton className="h-[320px] w-full rounded-xl" />
          <div className="space-y-3">
            <Skeleton className="h-24 w-full rounded-xl" />
            <Skeleton className="h-24 w-full rounded-xl" />
            <Skeleton className="h-10 w-40 rounded-xl" />
          </div>
        </div>
      </div>
    </div>
  )
}

export default function DatasetKGWorkbenchPage() {
  const router = useRouter()
  const params = useParams()
  const datasetId = asDatasetId((params as Record<string, unknown>)?.id)

  const graphRef = useRef<GraphViewerRef>(null)
  const graphClusteringSeqRef = useRef(0)
  const graphClusteringWorkerRef = useRef<Worker | null>(null)
  const graphClusteringApiRef = useRef<Remote<GraphClusteringWorkerApi> | null>(null)
  const graphClusteringDisabledRef = useRef(false)

  const [activeDocQuery, setActiveDocQuery] = useState('')
  const [docQuery, setDocQuery] = useState('')

  const [selectedDocIds, setSelectedDocIds] = useState<Set<string>>(() => new Set())

  // Step 2: Extract controls
  const [pipelineHash, setPipelineHash] = useState('')
  const [replaceExisting, setReplaceExisting] = useState(true)
  const [pruneOrphans, setPruneOrphans] = useState(false)
  const [bulkMaxDocs, setBulkMaxDocs] = useState(20)
  const [bulkConcurrency, setBulkConcurrency] = useState(3)
  const [extractRunning, setExtractRunning] = useState(false)
  const [singleExtractingDocId, setSingleExtractingDocId] = useState<string | null>(null)
  const [extractProgress, setExtractProgress] = useState<{ done: number; total: number } | null>(null)
  const [extractResults, setExtractResults] = useState<Record<string, { ok: true; res: KGExtractResponse } | { ok: false; error: string }>>({})

  // Step 3: Graph preview
  const [graphLoading, setGraphLoading] = useState(false)
  const [graphData, setGraphData] = useState<GraphData | null>(null)
  const [graphClusterResult, setGraphClusterResult] = useState<GraphClusterResult | null>(null)
  const [selectedGraphNodeId, setSelectedGraphNodeId] = useState<string | null>(null)
  const [graphStats, setGraphStats] = useState<KGStatsResponse | null>(null)
  const [includeEntityLinks, setIncludeEntityLinks] = useState(true)
  const [includeRelationLinks, setIncludeRelationLinks] = useState(false)
  const [minSharedEvents, setMinSharedEvents] = useState(2)
  const [graphMaxDocs, setGraphMaxDocs] = useState(50)

  // Step 4: Quick search
  const [searchQuery, setSearchQuery] = useState('')
  const [searchKind, setSearchKind] = useState<'all' | 'entity' | 'event'>('entity')
  const [searchLoading, setSearchLoading] = useState(false)
  const [searchResults, setSearchResults] = useState<KGGraphNode[]>([])

  const datasetQuery = useQuery({
    queryKey: datasetId ? queryKeys.datasets.detail(datasetId) : queryKeys.datasets.detail(''),
    enabled: Boolean(datasetId),
    queryFn: () => datasetApi.get(datasetId as string),
  })
  const docsQuery = useQuery({
    queryKey: datasetId
      ? queryKeys.documents.list({
          ...KG_WORKBENCH_DOCUMENT_PARAMS,
          dataset_id: datasetId,
          q: activeDocQuery || null,
        })
      : queryKeys.documents.list(KG_WORKBENCH_DOCUMENT_PARAMS),
    enabled: Boolean(datasetId),
    queryFn: () =>
      documentApi.list({
        ...KG_WORKBENCH_DOCUMENT_PARAMS,
        dataset_id: datasetId as string,
        q: activeDocQuery || null,
      }),
  })

  const dataset = datasetQuery.data ?? null
  const docs = docsQuery.data?.items ?? EMPTY_DOCS
  const docsTotal = Number(docsQuery.data?.total || 0)
  const docsLoading = docsQuery.isLoading || docsQuery.isFetching

  const scopedDocIds = useMemo(() => Array.from(selectedDocIds), [selectedDocIds])
  const effectivePipelineHash = useMemo(() => pipelineHash.trim() || undefined, [pipelineHash])
  const graphPaletteSeed = useMemo(() => datasetId || effectivePipelineHash || null, [datasetId, effectivePipelineHash])

  const graphPreviewData = useMemo(() => {
    if (!graphData) return null
    return applyClusterPalette({
      graphRenderData: graphData,
      paletteSeed: graphPaletteSeed,
      clusterResult: graphClusterResult,
    })
  }, [graphClusterResult, graphData, graphPaletteSeed])

  const selectedNodeDetail = useMemo(() => {
    if (!graphData || !selectedGraphNodeId) return null

    const selectedNode = graphData.nodes.find((node) => String(node.id || '') === selectedGraphNodeId)
    if (!selectedNode) return null

    const nodeRecord = selectedNode as Record<string, unknown>
    const meta = (nodeRecord.meta ?? {}) as Record<string, unknown>
    const label = primitiveText(nodeRecord.label ?? nodeRecord.name, selectedGraphNodeId).trim() || selectedGraphNodeId
    const type = primitiveText(meta.type ?? nodeRecord.type, 'unknown').trim() || 'unknown'
    const kind = primitiveText(meta.kind ?? nodeRecord.kind, 'entity').trim() || 'entity'

    let degree = 0
    for (const link of graphData.links) {
      const source = typeof link.source === 'object' && link.source
        ? String((link.source as { id?: string }).id ?? '')
        : String(link.source ?? '')
      const target = typeof link.target === 'object' && link.target
        ? String((link.target as { id?: string }).id ?? '')
        : String(link.target ?? '')
      if (source === selectedGraphNodeId || target === selectedGraphNodeId) {
        degree += 1
      }
    }

    const cluster = Math.max(1, Math.floor(Number(graphClusterResult?.nodeToCluster?.[selectedGraphNodeId] ?? 1)))
    return {
      id: selectedGraphNodeId,
      label,
      type,
      kind,
      degree,
      cluster,
    }
  }, [graphClusterResult, graphData, selectedGraphNodeId])

  const steps = useMemo(
    () => [
      { label: 'Scope', description: '选文档' },
      { label: 'Extract', description: '抽取 KG' },
      { label: 'Preview', description: '图预览' },
      { label: 'Search', description: '快速检索' },
    ],
    []
  )

  const currentStep = useMemo(() => {
    if (scopedDocIds.length === 0) return 0
    if (!graphData) return 1
    if (!searchQuery.trim()) return 2
    return 3
  }, [graphData, scopedDocIds.length, searchQuery])

  useEffect(() => {
    const error = datasetQuery.error || docsQuery.error
    if (!error) return
    console.error('Failed to load dataset kg workbench', error)
    toast.error(formatApiError(error, '加载数据失败'))
  }, [datasetQuery.error, docsQuery.error])

  useEffect(() => {
    const seq = ++graphClusteringSeqRef.current
    let cancelled = false

    if (!graphData?.nodes.length) {
      setGraphClusterResult(null)
      return
    }

    const nodes = graphData.nodes.map((node) => ({ id: node.id, label: node.label }))
    const links = graphData.links.map((link) => ({ source: link.source, target: link.target, label: link.label }))

    const computeOnMainThread = async () => {
      try {
        const { computeConnectedComponents } = await import('@/lib/graph-clustering')
        if (cancelled) return
        const result = computeConnectedComponents({ nodes, links })
        if (graphClusteringSeqRef.current === seq) {
          setGraphClusterResult(result)
        }
      } catch (e) {
        console.warn('Failed to compute dataset graph clusters', e)
        if (graphClusteringSeqRef.current === seq) {
          setGraphClusterResult(null)
        }
      }
    }

    if (graphClusteringDisabledRef.current || typeof Worker === 'undefined') {
      detachPromise(computeOnMainThread())
      return () => {
        cancelled = true
      }
    }

    detachPromise((async () => {
      try {
        let api = graphClusteringApiRef.current
        if (!graphClusteringWorkerRef.current || !api) {
          const { wrap } = await import('comlink')
          if (cancelled) return
          graphClusteringWorkerRef.current = new Worker(
            new URL('../../workers/graph-clustering.worker.ts', import.meta.url),
            { type: 'module' }
          )
          api = wrap<GraphClusteringWorkerApi>(graphClusteringWorkerRef.current)
          graphClusteringApiRef.current = api
        }

        const result = await api.computeConnectedComponents({ nodes, links })
        if (cancelled) return
        if (graphClusteringSeqRef.current !== seq) return
        setGraphClusterResult(result)
      } catch (e) {
        console.warn('Dataset graph clustering worker failed; falling back to main thread', e)
        graphClusteringDisabledRef.current = true
        detachPromise(computeOnMainThread())
      }
    })())

    return () => {
      cancelled = true
    }
  }, [graphData])

  useEffect(() => {
    return () => {
      graphClusteringApiRef.current = null
      graphClusteringWorkerRef.current?.terminate()
      graphClusteringWorkerRef.current = null
    }
  }, [])

  useEffect(() => {
    if (!graphData?.nodes.length) {
      setSelectedGraphNodeId(null)
      return
    }

    setSelectedGraphNodeId((prev) => {
      if (!prev) return null
      const stillExists = graphData.nodes.some((node) => String(node.id || '') === prev)
      return stillExists ? prev : null
    })
  }, [graphData])

  const toggleDoc = useCallback((docId: string, checked: boolean) => {
    setSelectedDocIds((prev) => {
      const next = new Set(prev)
      if (checked) next.add(docId)
      else next.delete(docId)
      return next
    })
  }, [])

  const selectAllLoaded = useCallback(() => {
    setSelectedDocIds((prev) => {
      const next = new Set(prev)
      docs.forEach((d) => {
        const id = String(d.id || '')
        if (id) next.add(id)
      })
      return next
    })
  }, [docs])

  const clearSelection = useCallback(() => setSelectedDocIds(new Set()), [])

  const extractOneDoc = useCallback(async (docId: string) => {
    const id = String(docId || '').trim()
    if (!id) return
    if (singleExtractingDocId) return

    setSingleExtractingDocId(id)
    try {
      const res = await kgApi.extract(id, {
        async: false,
        pipeline_hash: effectivePipelineHash,
        replace_existing: replaceExisting,
        prune_orphan_entities: pruneOrphans,
      })
      setExtractResults((prev) => ({ ...prev, [id]: { ok: true, res } }))
      toast.success(`KG 抽取完成：events=${Number(res?.event_count || 0)}`)
    } catch (e: unknown) {
      const msg = formatApiError(e, 'KG 抽取失败')
      setExtractResults((prev) => ({ ...prev, [id]: { ok: false, error: msg } }))
      toast.error(msg)
    } finally {
      setSingleExtractingDocId(null)
    }
  }, [effectivePipelineHash, pruneOrphans, replaceExisting, singleExtractingDocId])

  const extractSelected = useCallback(async () => {
    if (extractRunning) return
    if (scopedDocIds.length === 0) {
      toast.error('请先选择要抽取 KG 的文档')
      return
    }

    const maxDocs = limitPositiveInt(bulkMaxDocs, 20, { min: 1, max: 200 })
    const concurrency = limitPositiveInt(bulkConcurrency, 3, { min: 1, max: 8 })
    const docIds = scopedDocIds.slice(0, maxDocs)

    if (scopedDocIds.length > docIds.length) {
      toast.message(`已限制批量抽取数量：${docIds.length}/${scopedDocIds.length}`)
    }

    setExtractRunning(true)
    setExtractProgress({ done: 0, total: docIds.length })
    setExtractResults({})

    const nextResults: Record<string, { ok: true; res: KGExtractResponse } | { ok: false; error: string }> = {}

    try {
      await runWithConcurrency(docIds, concurrency, async (docId) => {
        try {
          const res = await kgApi.extract(docId, {
            async: false,
            pipeline_hash: effectivePipelineHash,
            replace_existing: replaceExisting,
            prune_orphan_entities: pruneOrphans,
          })
          nextResults[docId] = { ok: true, res }
        } catch (e: unknown) {
          const msg = formatApiError(e, 'KG 抽取失败')
          nextResults[docId] = { ok: false, error: msg }
        } finally {
          setExtractProgress((prev) => (prev ? { ...prev, done: prev.done + 1 } : prev))
          setExtractResults({ ...nextResults })
        }
      })

      const okCount = Object.values(nextResults).filter((x) => x.ok).length
      const failCount = docIds.length - okCount
      toast.success(`KG 抽取完成：ok=${okCount} fail=${failCount}`)
    } finally {
      setExtractRunning(false)
    }
  }, [
    bulkConcurrency,
    bulkMaxDocs,
    effectivePipelineHash,
    extractRunning,
    pruneOrphans,
    replaceExisting,
    scopedDocIds,
  ])

  const loadGraphPreview = useCallback(async () => {
    if (!datasetId) return
    if (graphLoading) return
    if (scopedDocIds.length === 0) {
      toast.error('请先选择要预览的文档范围')
      return
    }

    const maxDocs = limitPositiveInt(graphMaxDocs, 50, { min: 1, max: 200 })
    const docIds = scopedDocIds.slice(0, maxDocs)
    if (scopedDocIds.length > docIds.length) {
      toast.message(`已限制图预览文档数：${docIds.length}/${scopedDocIds.length}`)
    }

    setGraphLoading(true)
    setGraphClusterResult(null)
    setSelectedGraphNodeId(null)
    try {
      const [graph, stats] = await Promise.all([
        GraphService.fetchInitialGraph({
          includeEntityLinks,
          includeRelationLinks,
          minSharedEvents: includeRelationLinks ? minSharedEvents : undefined,
          maxEntityLinks: 1000,
          documentIds: docIds,
          pipelineHash: effectivePipelineHash,
        }),
        kgApi.getStats({ document_ids: docIds, pipeline_hash: effectivePipelineHash }).catch(() => null),
      ])

      setGraphData(graph)
      setGraphStats(stats)
    } catch (e: unknown) {
      console.error('Failed to load graph preview', e)
      toast.error(formatApiError(e, '加载图预览失败'))
      setGraphData(null)
      setGraphClusterResult(null)
      setSelectedGraphNodeId(null)
      setGraphStats(null)
    } finally {
      setGraphLoading(false)
    }
  }, [
    datasetId,
    effectivePipelineHash,
    graphLoading,
    graphMaxDocs,
    includeEntityLinks,
    includeRelationLinks,
    minSharedEvents,
    scopedDocIds,
  ])

	  const scopedGraphUrl = useMemo(() => {
	    const maxDocs = limitPositiveInt(graphMaxDocs, 50, { min: 1, max: 200 })
	    const docIds = scopedDocIds.slice(0, maxDocs)
	    const qs = new URLSearchParams()
	    if (docIds.length) qs.set('document_ids', docIds.join(','))
	    if (effectivePipelineHash) qs.set('pipeline_hash', effectivePipelineHash)
	    const query = qs.toString()
	    return query ? `/graph?${query}` : '/graph'
	  }, [effectivePipelineHash, graphMaxDocs, scopedDocIds])

  const runQuickSearch = useCallback(async () => {
    const q = searchQuery.trim()
    if (!q) return
    if (searchLoading) return
    if (scopedDocIds.length === 0) {
      toast.error('请先选择文档范围（Scope）')
      return
    }

    const maxDocs = limitPositiveInt(graphMaxDocs, 50, { min: 1, max: 200 })
    const docIds = scopedDocIds.slice(0, maxDocs)

    setSearchLoading(true)
    try {
      const nodes = await kgApi.searchGraphNodes({
        q,
        kind: searchKind === 'all' ? 'all' : searchKind,
        limit: 20,
        document_ids: docIds,
        pipeline_hash: effectivePipelineHash,
      })
      setSearchResults(Array.isArray(nodes) ? nodes : [])
      if (!nodes?.length) {
        toast.message('未找到匹配节点')
      }
    } catch (e: unknown) {
      console.error('KG quick search failed', e)
      toast.error(formatApiError(e, 'KG 搜索失败'))
      setSearchResults([])
    } finally {
      setSearchLoading(false)
    }
  }, [effectivePipelineHash, graphMaxDocs, scopedDocIds, searchKind, searchLoading, searchQuery])

  const headerDescription = (
    <span className="text-sm text-muted-foreground">
      Dataset-scoped KG Workbench: 先选文档范围，再做抽取与图检索。批量操作会自动限流与限量。
    </span>
  )

	  return (
	    <AppFrame>
	      <PageScaffold
	        title={dataset?.name ? `KG Workbench · ${dataset.name}` : 'KG Workbench'}
	        badge="Dataset KG"
	        icon={Network}
	        iconColor="text-indigo"
	        description={headerDescription}
        actions={
          <div className="flex items-center gap-2">
            <Button variant="outline" className="gap-2" onClick={() => router.push('/datasets')}>
              <ArrowLeft className="w-4 h-4" />
              返回
            </Button>
            {datasetId ? (
              <Button variant="outline" className="gap-2" onClick={() => router.push(`/datasets/${datasetId}/ingestion`)}>
                <Settings2 className="w-4 h-4" />
                入库设置
              </Button>
            ) : null}
            <Button variant="outline" className="gap-2" onClick={() => router.push('/graph/diagnostics')}>
              <Wrench className="w-4 h-4" />
              诊断
            </Button>
            <Button variant="outline" className="gap-2" onClick={() => router.push('/graph/snapshots')}>
              <Sparkles className="w-4 h-4" />
              Snapshots
            </Button>
            <Button variant="outline" className="gap-2" onClick={() => router.push(scopedGraphUrl)} disabled={scopedDocIds.length === 0}>
              <Network className="w-4 h-4" />
              打开全图
            </Button>
            <Button
              variant="outline"
              className="gap-2"
              onClick={() => setActiveDocQuery(docQuery.trim())}
              disabled={docsLoading}
            >
              <RefreshCw className={cn('w-4 h-4', docsLoading && 'animate-spin motion-reduce:animate-none')} />
              刷新
            </Button>
          </div>
        }
      >
        <div className="space-y-4">
          <Panel className="space-y-3">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="text-sm font-semibold">Steps</div>
                <div className="text-xs text-muted-foreground">
                  当前范围：<span className="font-mono">{scopedDocIds.length}</span> docs
                </div>
              </div>
              {docsTotal > docs.length ? (
                <Badge variant="secondary" className="font-mono text-[11px]">
                  loaded={docs.length} total={docsTotal}
                </Badge>
              ) : (
                <Badge variant="outline" className="font-mono text-[11px]">
                  loaded={docs.length}
                </Badge>
              )}
            </div>
            <StepIndicator steps={steps} currentStep={currentStep} />
          </Panel>

          <div className="grid gap-4 lg:grid-cols-[420px_1fr]">
            <div className="space-y-4">
              <Panel className="space-y-3">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="font-semibold">1. Scope docs</div>
                    <div className="text-xs text-muted-foreground">选择要参与 KG 的文档范围（可用搜索过滤）。</div>
                  </div>
                  <div className="flex items-center gap-2 flex-shrink-0">
                    <Button variant="outline" size="sm" onClick={selectAllLoaded} disabled={docs.length === 0}>
                      全选已加载
                    </Button>
                    <Button variant="outline" size="sm" onClick={clearSelection} disabled={selectedDocIds.size === 0}>
                      清空
                    </Button>
                  </div>
                </div>

                <div className="flex items-center gap-2">
                  <div className="flex-1">
                    <Label className="text-xs text-muted-foreground">文档搜索</Label>
                    <Input
                      value={docQuery}
                      onChange={(e) => setDocQuery(e.target.value)}
                      placeholder="filename / q…"
                      className="h-9"
                    />
                  </div>
                  <div className="pt-5">
                    <Button
                      variant="outline"
                      className="gap-2"
                      onClick={() => setActiveDocQuery(docQuery.trim())}
                      disabled={docsLoading}
                    >
                      {docsLoading ? <Loader2 className="w-4 h-4 animate-spin motion-reduce:animate-none" /> : <Search className="w-4 h-4" />}
                      搜索
                    </Button>
                  </div>
                </div>

                <div className="max-h-[420px] overflow-y-auto overscroll-contain pr-1 space-y-1">
                  {docsLoading ? (
                    <DocsLoadingSkeleton />
                  ) : docs.length === 0 ? (
                    <div className="text-xs text-muted-foreground py-8 text-center">没有文档</div>
                  ) : (
                    docs.map((doc) => {
                      const id = String(doc.id || '')
                      const filename = String(doc.filename || id || '')
                      const status = String(doc.status || '')
                      const checked = selectedDocIds.has(id)
                      const isExtracting = singleExtractingDocId === id

                      return (
                        <label
                          key={id}
                          className={cn(
                            'flex items-start gap-2 rounded-lg border px-2 py-2 cursor-pointer transition-colors',
                            checked ? 'border-primary/30 bg-primary/5' : 'border-border/60 hover:bg-muted/40'
                          )}
                        >
                          <Checkbox
                            checked={checked}
                            onCheckedChange={(v) => toggleDoc(id, Boolean(v))}
                            className="mt-0.5"
                          />
                          <div className="min-w-0 flex-1">
                            <div className="text-xs font-medium truncate">{filename || id}</div>
                            <div className="text-[11px] text-muted-foreground flex items-center gap-2">
                              <span className="font-mono truncate">{id}</span>
                              {status ? (
                                <Badge variant="outline" className="font-mono text-[11px] px-1.5 py-0">
                                  {status}
                                </Badge>
                              ) : null}
                            </div>
	                          </div>
	                          <div className="flex-shrink-0">
                            <Button
                              variant="outline"
                              size="sm"
                              className="h-7 px-2 gap-1 text-[11px]"
                              disabled={isExtracting}
                              onClick={(e) => {
                                e.preventDefault()
                                e.stopPropagation()
                                detachPromise(extractOneDoc(id))
                              }}
                            >
                              {isExtracting ? (
                                <Loader2 className="w-3.5 h-3.5 animate-spin motion-reduce:animate-none" />
                              ) : (
                                <Sparkles className="w-3.5 h-3.5" />
                              )}
                              Extract
                            </Button>
                          </div>
	                        </label>
	                      )
                    })
                  )}
                </div>
              </Panel>

              <Panel className="space-y-3">
                <div className="font-semibold">2. Extract KG (bounded)</div>
                <div className="grid gap-3 grid-cols-2">
                  <div className="space-y-1">
                    <Label className="text-xs text-muted-foreground">pipeline_hash (optional)</Label>
                    <Input value={pipelineHash} onChange={(e) => setPipelineHash(e.target.value)} placeholder="e.g. 9f8a…" className="h-9 font-mono text-xs" />
                  </div>
                  <div className="space-y-1">
                    <Label className="text-xs text-muted-foreground">max docs</Label>
                    <Input
                      value={String(bulkMaxDocs)}
                      onChange={(e) => setBulkMaxDocs(limitPositiveInt(e.target.value, 20, { min: 1, max: 200 }))}
                      className="h-9 font-mono text-xs"
                      inputMode="numeric"
                    />
                  </div>
                  <div className="flex items-center gap-2 col-span-2">
                    <Checkbox checked={replaceExisting} onCheckedChange={(v) => setReplaceExisting(Boolean(v))} />
                    <span className="text-xs">replace existing</span>
                    <Checkbox checked={pruneOrphans} onCheckedChange={(v) => setPruneOrphans(Boolean(v))} className="ml-4" />
                    <span className="text-xs">prune orphans</span>
                  </div>
                  <div className="space-y-1 col-span-2">
                    <Label className="text-xs text-muted-foreground">concurrency</Label>
                    <Input
                      value={String(bulkConcurrency)}
                      onChange={(e) => setBulkConcurrency(limitPositiveInt(e.target.value, 3, { min: 1, max: 8 }))}
                      className="h-9 font-mono text-xs"
                      inputMode="numeric"
                    />
                  </div>
                </div>

                <div className="flex items-center justify-between gap-3">
                  <Button
                    className="gap-2"
                    onClick={() => detachPromise(extractSelected())}
                    disabled={extractRunning || scopedDocIds.length === 0}
                  >
                    {extractRunning ? <Loader2 className="w-4 h-4 animate-spin motion-reduce:animate-none" /> : <Sparkles className="w-4 h-4" />}
                    抽取选中文档
                  </Button>
                  {extractProgress ? (
                    <div className="text-xs text-muted-foreground font-mono">
                      {extractProgress.done}/{extractProgress.total}
                    </div>
                  ) : null}
                </div>

                {Object.keys(extractResults).length > 0 ? (
                  <div className="text-xs text-muted-foreground space-y-1">
                    <div className="font-medium text-foreground">最近结果</div>
                    <div className="max-h-[160px] overflow-y-auto overscroll-contain pr-1 space-y-1">
                      {Object.entries(extractResults)
                        .slice(0, 50)
                        .map(([docId, r]) => (
                          <div key={docId} className="flex items-center justify-between gap-2 rounded-md border border-border/60 px-2 py-1">
                            <span className="font-mono text-[11px] truncate">{docId}</span>
                            {r.ok ? (
                              <Badge variant="outline" className="font-mono text-[11px]">
                                events={r.res.event_count}
                              </Badge>
                            ) : (
                              <Badge variant="soft" className="font-mono text-[11px]">
                                fail
                              </Badge>
                            )}
                          </div>
                        ))}
                    </div>
                  </div>
                ) : null}
              </Panel>

              <Panel className="space-y-3">
                <div className="font-semibold">4. Quick KG search</div>
                <div className="grid gap-2 grid-cols-[1fr_110px]">
                  <Input
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    placeholder="Search entity/event…"
                    className="h-9"
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') detachPromise(runQuickSearch())
                    }}
                  />
                  <Button variant="outline" className="gap-2" onClick={() => detachPromise(runQuickSearch())} disabled={searchLoading}>
                    {searchLoading ? <Loader2 className="w-4 h-4 animate-spin motion-reduce:animate-none" /> : <Search className="w-4 h-4" />}
                    搜索
                  </Button>
                </div>
                <div className="flex items-center gap-2 text-xs text-muted-foreground">
                  <span>kind:</span>
                  <Button
                    variant={searchKind === 'entity' ? 'secondary' : 'outline'}
                    size="sm"
                    onClick={() => setSearchKind('entity')}
                  >
                    entity
                  </Button>
                  <Button
                    variant={searchKind === 'event' ? 'secondary' : 'outline'}
                    size="sm"
                    onClick={() => setSearchKind('event')}
                  >
                    event
                  </Button>
                  <Button variant={searchKind === 'all' ? 'secondary' : 'outline'} size="sm" onClick={() => setSearchKind('all')}>
                    all
                  </Button>
                </div>

                {searchLoading ? (
                  <SearchResultsSkeleton />
                ) : searchResults.length > 0 ? (
                  <div className="max-h-[220px] overflow-y-auto overscroll-contain pr-1 space-y-1">
                    {searchResults.map((n) => (
                      <button
                        key={n.id}
                        type="button"
                        className="w-full text-left rounded-lg border border-border/60 px-2 py-2 hover:bg-muted/40 transition-colors"
                        onClick={() => {
                          const nodeId = String(n.id || '')
                          setSelectedGraphNodeId(nodeId)
                          graphRef.current?.focusNode(nodeId)
                          toast.message(`聚焦节点：${String(n.label || n.id)}`)
                        }}
                      >
                        <div className="text-xs font-medium truncate">{String(n.label || n.id)}</div>
                        <div className="text-[11px] text-muted-foreground font-mono truncate">{String(n.id)}</div>
                      </button>
                    ))}
                  </div>
                ) : (
                  <div className="text-xs text-muted-foreground">输入关键词后点击搜索。</div>
                )}
              </Panel>
            </div>

            <div className="space-y-4">
              <Panel className="space-y-3">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="font-semibold">3. Graph preview</div>
                    <div className="text-xs text-muted-foreground">
                      预览当前 Scope 的 KG 图（自动限制文档数，避免一次拉太多）。
                    </div>
                  </div>
                  <div className="flex items-center gap-2 flex-shrink-0">
                    <Button variant="outline" size="sm" className="gap-2" onClick={() => detachPromise(loadGraphPreview())} disabled={graphLoading}>
                      {graphLoading ? <Loader2 className="w-4 h-4 animate-spin motion-reduce:animate-none" /> : <RefreshCw className="w-4 h-4" />}
                      加载预览
                    </Button>
                    <Button variant="outline" size="sm" className="gap-2" onClick={() => router.push(scopedGraphUrl)} disabled={scopedDocIds.length === 0}>
                      <Network className="w-4 h-4" />
                      全屏
                    </Button>
                  </div>
                </div>

                <div className="grid gap-3 md:grid-cols-4">
                  <div className="space-y-1">
                    <Label className="text-xs text-muted-foreground">max docs</Label>
                    <Input
                      value={String(graphMaxDocs)}
                      onChange={(e) => setGraphMaxDocs(limitPositiveInt(e.target.value, 50, { min: 1, max: 200 }))}
                      className="h-9 font-mono text-xs"
                      inputMode="numeric"
                    />
                  </div>
                  <div className="flex items-center gap-2 pt-5">
                    <Checkbox checked={includeEntityLinks} onCheckedChange={(v) => setIncludeEntityLinks(Boolean(v))} />
                    <span className="text-xs">entity links</span>
                  </div>
                  <div className="flex items-center gap-2 pt-5">
                    <Checkbox checked={includeRelationLinks} onCheckedChange={(v) => setIncludeRelationLinks(Boolean(v))} />
                    <span className="text-xs">relation links</span>
                  </div>
                  <div className="space-y-1">
                    <Label className="text-xs text-muted-foreground">min shared events</Label>
                    <Input
                      value={String(minSharedEvents)}
                      onChange={(e) => setMinSharedEvents(limitPositiveInt(e.target.value, 2, { min: 1, max: 10 }))}
                      className="h-9 font-mono text-xs"
                      inputMode="numeric"
                    />
                  </div>
                </div>

                {graphLoading ? (
                  <div className="flex flex-wrap items-center gap-2">
                    {GRAPH_STATS_SKELETON_KEYS.map((key) => (
                      <Skeleton key={key} className="h-6 w-24 rounded-full" />
                    ))}
                  </div>
                ) : graphStats || graphClusterResult ? (
                  <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                    {graphStats ? (
                      <>
                        <Badge variant="outline" className="font-mono text-[11px]">
                          entities={Number(graphStats.entities || 0)}
                        </Badge>
                        <Badge variant="outline" className="font-mono text-[11px]">
                          events={Number(graphStats.events || 0)}
                        </Badge>
                        <Badge variant="outline" className="font-mono text-[11px]">
                          links={Number(graphStats.links || 0)}
                        </Badge>
                      </>
                    ) : null}
                    {graphClusterResult ? (
                      <>
                        <Badge variant="secondary" className="font-mono text-[11px]">
                          clusters={graphClusterResult.clusterCount}
                        </Badge>
                        <Badge variant="secondary" className="font-mono text-[11px]">
                          maxCluster={Number(graphClusterResult.clusterSizes[0] || 0)}
                        </Badge>
                      </>
                    ) : null}
                  </div>
                ) : null}
              </Panel>

              {selectedNodeDetail ? (
                <Panel className="space-y-2">
                  <div className="flex items-center justify-between gap-2">
                    <div className="font-semibold">Node drill-down</div>
                    <Badge variant="secondary" className="font-mono text-[11px]">
                      cluster={selectedNodeDetail.cluster}
                    </Badge>
                  </div>
                  <div className="grid gap-1 text-[11px] text-muted-foreground md:grid-cols-2">
                    <div className="truncate">
                      label=<span className="font-medium text-foreground">{selectedNodeDetail.label}</span>
                    </div>
                    <div className="font-mono truncate">id={selectedNodeDetail.id}</div>
                    <div className="font-mono truncate">type={selectedNodeDetail.type}</div>
                    <div className="font-mono truncate">kind={selectedNodeDetail.kind}</div>
                    <div className="font-mono truncate">degree={selectedNodeDetail.degree}</div>
                  </div>
                </Panel>
              ) : null}

              <Panel padding="none" className="relative overflow-hidden h-[min(720px,calc(100vh-260px))] min-h-[520px]">
                {graphData && graphPreviewData ? (
                  <GraphViewer
                    ref={graphRef}
                    data={graphPreviewData}
                    onNodeClick={(node) => {
                      const nodeId = String(node?.id || '').trim()
                      if (!nodeId) return
                      setSelectedGraphNodeId(nodeId)
                    }}
                    selectedNodeId={selectedGraphNodeId}
                    onBackgroundClick={() => setSelectedGraphNodeId(null)}
                  />
                ) : graphLoading ? null : (
                  <div className="h-full flex items-center justify-center text-sm text-muted-foreground">
                    先点击“加载预览”拉取 KG 图数据
                  </div>
                )}
                {graphLoading ? (
                  <div className="absolute inset-0 z-10 bg-background/80 backdrop-blur-sm">
                    <GraphPreviewSkeleton />
                  </div>
                ) : null}
              </Panel>
            </div>
          </div>
        </div>
      </PageScaffold>
    </AppFrame>
  )
}
