'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useParams, useRouter } from 'next/navigation'
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
import { PageScaffold } from '@/components/ui/page-scaffold'
import { Panel } from '@/components/ui/panel'
import { StepIndicator } from '@/components/ui/step-indicator'

import { datasetApi, documentApi, kgApi } from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'
import { cn, detachPromise } from '@/lib/utils'
import { GraphService } from '@/lib/graph-service'

import type { Dataset, Document, KGExtractResponse, KGGraphNode, KGStatsResponse } from '@/types'

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

export default function DatasetKGWorkbenchPage() {
  const router = useRouter()
  const params = useParams()
  const datasetId = asDatasetId((params as any)?.id)

  const graphRef = useRef<GraphViewerRef>(null)

  const [dataset, setDataset] = useState<Dataset | null>(null)
  const [docs, setDocs] = useState<Document[]>([])
  const [docsTotal, setDocsTotal] = useState<number>(0)
  const [docsLoading, setDocsLoading] = useState(false)
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
  const [graphData, setGraphData] = useState<{ nodes: any[]; links: any[] } | null>(null)
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

  const scopedDocIds = useMemo(() => Array.from(selectedDocIds), [selectedDocIds])
  const effectivePipelineHash = useMemo(() => pipelineHash.trim() || undefined, [pipelineHash])

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

  const loadDocs = useCallback(async (query?: string) => {
    if (!datasetId) return
    setDocsLoading(true)
    try {
	      const q = (query ?? '').trim()
	      const [ds, list] = await Promise.all([
	        datasetApi.get(datasetId),
	        documentApi.list({
	          skip: 0,
	          limit: 100,
	          dataset_id: datasetId,
	          q: q || null,
	          order_by: 'created_at',
	          order_dir: 'desc',
	        }),
	      ])
      setDataset(ds)
      setDocs(Array.isArray(list.items) ? list.items : [])
      setDocsTotal(Number(list.total || 0))
    } catch (e: any) {
      console.error('Failed to load dataset kg workbench', e)
      toast.error(formatApiError(e, '加载数据失败'))
      setDocs([])
      setDocsTotal(0)
    } finally {
      setDocsLoading(false)
    }
  }, [datasetId])

  useEffect(() => {
    detachPromise(loadDocs(''))
  }, [loadDocs])

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
    } catch (e: any) {
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
        } catch (e: any) {
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

      setGraphData(graph as any)
      setGraphStats(stats)
    } catch (e: any) {
      console.error('Failed to load graph preview', e)
      toast.error(formatApiError(e, '加载图预览失败'))
      setGraphData(null)
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
    } catch (e: any) {
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
	        iconColor="text-primary"
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
            <Button variant="outline" className="gap-2" onClick={() => detachPromise(loadDocs(docQuery))} disabled={docsLoading}>
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
                <Badge variant="secondary" className="font-mono text-[10px]">
                  loaded={docs.length} total={docsTotal}
                </Badge>
              ) : (
                <Badge variant="outline" className="font-mono text-[10px]">
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
                      onClick={() => detachPromise(loadDocs(docQuery))}
                      disabled={docsLoading}
                    >
                      {docsLoading ? <Loader2 className="w-4 h-4 animate-spin motion-reduce:animate-none" /> : <Search className="w-4 h-4" />}
                      搜索
                    </Button>
                  </div>
                </div>

	                <div className="max-h-[420px] overflow-y-auto overscroll-contain pr-1 space-y-1">
	                  {docsLoading && (
	                    <div className="flex items-center gap-2 text-xs text-muted-foreground py-8 justify-center">
	                      <Loader2 className="w-4 h-4 animate-spin motion-reduce:animate-none" />
	                      加载中…
	                    </div>
	                  )}
	                  {!docsLoading && docs.length === 0 && (
	                    <div className="text-xs text-muted-foreground py-8 text-center">没有文档</div>
	                  )}
	                  {!docsLoading && docs.length > 0 && (
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
                            <div className="text-[10px] text-muted-foreground flex items-center gap-2">
                              <span className="font-mono truncate">{id}</span>
                              {status ? (
                                <Badge variant="outline" className="font-mono text-[10px] px-1.5 py-0">
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
                            <span className="font-mono text-[10px] truncate">{docId}</span>
                            {r.ok ? (
                              <Badge variant="outline" className="font-mono text-[10px]">
                                events={r.res.event_count}
                              </Badge>
                            ) : (
                              <Badge variant="soft" className="font-mono text-[10px]">
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

                {searchResults.length > 0 ? (
                  <div className="max-h-[220px] overflow-y-auto overscroll-contain pr-1 space-y-1">
                    {searchResults.map((n) => (
                      <button
                        key={n.id}
                        type="button"
                        className="w-full text-left rounded-lg border border-border/60 px-2 py-2 hover:bg-muted/40 transition-colors"
                        onClick={() => {
                          graphRef.current?.focusNode(String(n.id))
                          toast.message(`聚焦节点：${String(n.label || n.id)}`)
                        }}
                      >
                        <div className="text-xs font-medium truncate">{String(n.label || n.id)}</div>
                        <div className="text-[10px] text-muted-foreground font-mono truncate">{String(n.id)}</div>
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

                {graphStats ? (
                  <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                    <Badge variant="outline" className="font-mono text-[10px]">
                      entities={Number((graphStats as any).entities || 0)}
                    </Badge>
                    <Badge variant="outline" className="font-mono text-[10px]">
                      events={Number((graphStats as any).events || 0)}
                    </Badge>
                    <Badge variant="outline" className="font-mono text-[10px]">
                      links={Number((graphStats as any).links || 0)}
                    </Badge>
                  </div>
                ) : null}
              </Panel>

              <Panel padding="none" className="overflow-hidden h-[min(720px,calc(100vh-260px))] min-h-[520px]">
                {graphData ? (
                  <GraphViewer ref={graphRef} data={graphData} />
                ) : (
                  <div className="h-full flex items-center justify-center text-sm text-muted-foreground">
                    先点击“加载预览”拉取 KG 图数据
                  </div>
                )}
              </Panel>
            </div>
          </div>
        </div>
      </PageScaffold>
    </AppFrame>
  )
}
