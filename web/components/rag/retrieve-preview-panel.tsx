'use client'

import { useCallback, useMemo, useRef, useState } from 'react'
import {
  Copy,
  ExternalLink,
  File as FileIcon,
  FileStack,
  Loader2,
  Search,
  Sparkles,
  TestTube2,
  Zap,
} from 'lucide-react'
import type {
  Citation,
  EvidenceRetrieveResponse,
  ReferenceSource,
  RegressionCaseCreate,
} from '@/types'
import { AuthImage, AuthImageLink, useResolvedAuthAssetUrl } from '@/components/auth-image'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { IconButton } from '@/components/ui/icon-button'
import { Panel } from '@/components/ui/panel'
import { formatApiError } from '@/lib/api-errors'
import { resolveSafeCitationImageUrl } from '@/lib/citation-images'
import { getDocumentPreviewAnchorFromCitation } from '@/lib/document-preview-anchor'
import { prefetchDocumentView } from '@/lib/document-view-prefetch'
import { cn, detachPromise } from '@/lib/utils'
import { evaluationApi, ragApi } from '@/lib/api'
import { useDocumentView } from '@/store/document-view'
import { toast } from 'sonner'

type RetrievePreviewPanelProps = {
  selectedDatasetId: string | null | undefined
  className?: string
}

type JsonRecord = Record<string, unknown>

type KgPathStep = {
  entity_id: string
  type?: string
}

type KgPathProvenanceNode = {
  kind?: string
  entity_id?: string
  event_id?: string
  type?: string
  document_id?: string
  chunk_id?: string
}

type KgPathProvenanceEdge = {
  kind?: string
  predicate?: string
  confidence_bucket?: string
  evidence_source?: string
  relation_id?: string
  document_id?: string
  chunk_id?: string
}

type KgPathProvenance = JsonRecord & {
  kind?: string
  hops?: number
  nodes?: KgPathProvenanceNode[]
  edges?: KgPathProvenanceEdge[]
}

type RetrievePreviewCitation = Omit<Citation, 'kg_path' | 'kg_path_provenance'> & {
  kg_path?: KgPathStep[]
  kg_path_provenance?: KgPathProvenance
  family_hit?: boolean
  family_collapse_key?: string
  hierarchy_family_key?: string
}

function isRecord(value: unknown): value is JsonRecord {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

function toOptionalString(value: unknown): string | undefined {
  return typeof value === 'string' && value.trim() ? value : undefined
}

function toOptionalNumber(value: unknown): number | undefined {
  if (typeof value === 'number' && Number.isFinite(value)) return value
  if (typeof value === 'string' && value.trim()) {
    const next = Number(value)
    if (Number.isFinite(next)) return next
  }
  return undefined
}

function toOptionalBoolean(value: unknown): boolean | undefined {
  return typeof value === 'boolean' ? value : undefined
}

function toStringList(value: unknown): string[] | undefined {
  if (!Array.isArray(value)) return undefined
  const items = value.filter((item): item is string => typeof item === 'string' && item.length > 0)
  return items.length ? items : undefined
}

function toKgPath(value: unknown): KgPathStep[] | undefined {
  if (!Array.isArray(value)) return undefined
  const items = value
    .filter(isRecord)
    .map((item) => {
      const entityId = toOptionalString(item.entity_id)
      if (!entityId) return null
      const step: KgPathStep = { entity_id: entityId }
      const type = toOptionalString(item.type)
      if (type) step.type = type
      return step
    })
    .filter((item): item is KgPathStep => item !== null)
  return items.length ? items : undefined
}

function toKgPathProvenanceNode(value: unknown): KgPathProvenanceNode | null {
  if (!isRecord(value)) return null
  return {
    kind: toOptionalString(value.kind),
    entity_id: toOptionalString(value.entity_id),
    event_id: toOptionalString(value.event_id),
    type: toOptionalString(value.type),
    document_id: toOptionalString(value.document_id),
    chunk_id: toOptionalString(value.chunk_id),
  }
}

function toKgPathProvenanceEdge(value: unknown): KgPathProvenanceEdge | null {
  if (!isRecord(value)) return null
  return {
    kind: toOptionalString(value.kind),
    predicate: toOptionalString(value.predicate),
    confidence_bucket: toOptionalString(value.confidence_bucket),
    evidence_source: toOptionalString(value.evidence_source),
    relation_id: toOptionalString(value.relation_id),
    document_id: toOptionalString(value.document_id),
    chunk_id: toOptionalString(value.chunk_id),
  }
}

function toKgPathProvenance(value: unknown): KgPathProvenance | undefined {
  if (!isRecord(value)) return undefined

  const nodes = Array.isArray(value.nodes)
    ? value.nodes.map(toKgPathProvenanceNode).filter((item): item is KgPathProvenanceNode => item !== null)
    : undefined
  const edges = Array.isArray(value.edges)
    ? value.edges.map(toKgPathProvenanceEdge).filter((item): item is KgPathProvenanceEdge => item !== null)
    : undefined

  return {
    kind: toOptionalString(value.kind),
    hops: toOptionalNumber(value.hops),
    nodes: nodes?.length ? nodes : undefined,
    edges: edges?.length ? edges : undefined,
  }
}

function buildReferenceSource(citation: RetrievePreviewCitation): ReferenceSource | null {
  const chunkId = toOptionalString(citation.chunk_id)
  if (!chunkId) return null

  return {
    document_id: citation.document_id,
    chunk_id: chunkId,
    page_number: citation.page_number,
    start_char: citation.start_char,
    end_char: citation.end_char,
    doc_pipeline_key: citation.doc_pipeline_key,
    pipeline_hash: citation.pipeline_hash,
    quote: citation.chunk_content,
    label: 'ground_truth',
  }
}

function toCitation(value: unknown): RetrievePreviewCitation | null {
  if (!isRecord(value)) return null
  const document_id = typeof value.document_id === 'string' ? value.document_id : ''
  const document_name = typeof value.document_name === 'string' ? value.document_name : ''
  const chunk_content = typeof value.chunk_content === 'string' ? value.chunk_content : ''
  const relevance_score =
    typeof value.relevance_score === 'number' ? value.relevance_score : Number(value.relevance_score ?? 0) || 0

  if (!document_id || !document_name) return null

  const citation: RetrievePreviewCitation = {
    document_id,
    document_name,
    chunk_content,
    relevance_score,
  }

  citation.chunk_id = toOptionalString(value.chunk_id)
  citation.matched_terms = toStringList(value.matched_terms)
  citation.page_number = toOptionalNumber(value.page_number)
  citation.chunk_index = toOptionalNumber(value.chunk_index)
  citation.start_char = toOptionalNumber(value.start_char)
  citation.end_char = toOptionalNumber(value.end_char)
  citation.evidence_start_char = toOptionalNumber(value.evidence_start_char)
  citation.evidence_end_char = toOptionalNumber(value.evidence_end_char)
  citation.header_path = toOptionalString(value.header_path)
  citation.chunk_strategy = toOptionalString(value.chunk_strategy)
  citation.chunk_role = toOptionalString(value.chunk_role)
  citation.chunk_semantic_role = toOptionalString(value.chunk_semantic_role)
  citation.policy_clause_id = toOptionalString(value.policy_clause_id)
  citation.policy_clause_number = toOptionalString(value.policy_clause_number)
  citation.policy_path = toStringList(value.policy_path)
  citation.policy_path_str = toOptionalString(value.policy_path_str)
  citation.parent_id = toOptionalString(value.parent_id)
  citation.retrieval_role = toOptionalString(value.retrieval_role)
  citation.neighbor_of = toOptionalString(value.neighbor_of)
  citation.kg_path = toKgPath(value.kg_path)
  citation.kg_path_provenance = toKgPathProvenance(value.kg_path_provenance)
  citation.doc_pipeline_key = toOptionalString(value.doc_pipeline_key)
  citation.pipeline_hash = toOptionalString(value.pipeline_hash)
  citation.vector_score = toOptionalNumber(value.vector_score)
  citation.bm25_score = toOptionalNumber(value.bm25_score)
  citation.keyword_score = toOptionalNumber(value.keyword_score)
  citation.rerank_score = toOptionalNumber(value.rerank_score)
  citation.retrieval_score = toOptionalNumber(value.retrieval_score)
  citation.reranker_provider = toOptionalString(value.reranker_provider)
  citation.rerank_elapsed_sec = toOptionalNumber(value.rerank_elapsed_sec)
  citation.rerank_model_used = toOptionalString(value.rerank_model_used)
  citation.retrieval_mode = toOptionalString(value.retrieval_mode)
  citation.vector_backend = toOptionalString(value.vector_backend)
  citation.retrieval_elapsed_sec = toOptionalNumber(value.retrieval_elapsed_sec)
  citation.hit_type = toOptionalString(value.hit_type)
  citation.has_image = toOptionalBoolean(value.has_image)
  citation.img_id = toOptionalString(value.img_id)
  citation.img_url = toOptionalString(value.img_url)
  citation.family_hit = toOptionalBoolean(value.family_hit)
  citation.family_collapse_key = toOptionalString(value.family_collapse_key)
  citation.hierarchy_family_key = toOptionalString(value.hierarchy_family_key)

  return citation
}

function shortId(id: string, opts?: { head?: number; tail?: number }): string {
  const s = String(id || '').trim()
  if (!s) return ''
  const head = Math.max(1, Number(opts?.head ?? 8) || 8)
  const tail = Math.max(0, Number(opts?.tail ?? 4) || 4)
  if (s.length <= head + tail + 1) return s
  return `${s.slice(0, head)}...${s.slice(-tail)}`
}

function toInt(value: unknown): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) return Math.trunc(value)
  if (typeof value === 'string' && value.trim()) {
    const n = Number(value)
    if (Number.isFinite(n)) return Math.trunc(n)
  }
  if (typeof value === 'boolean') return value ? 1 : 0
  return null
}

function formatCount(value: unknown): string {
  const n = toInt(value)
  return typeof n === 'number' ? String(n) : '—'
}

async function copyToClipboard(text: string, label: string): Promise<void> {
  const v = String(text || '')
  if (!v) {
    toast.error('无可复制内容')
    return
  }
  try {
    await navigator.clipboard.writeText(v)
    toast.success(`已复制 ${label}`)
  } catch (err) {
    console.error('clipboard.writeText failed:', err)
    toast.error('复制失败（浏览器权限限制）')
  }
}

export function RetrievePreviewPanel({ selectedDatasetId, className }: Readonly<RetrievePreviewPanelProps>) {
  const { openDocument } = useDocumentView()
  const [searchQuery, setSearchQuery] = useState('')
  const [searchResults, setSearchResults] = useState<RetrievePreviewCitation[]>([])
  const [searchQueryForRetrieval, setSearchQueryForRetrieval] = useState<string>('')
  const [searchMetrics, setSearchMetrics] = useState<JsonRecord | null>(null)
  const [searchRetrievalTrace, setSearchRetrievalTrace] = useState<JsonRecord | null>(null)
  const [searchHasEvidence, setSearchHasEvidence] = useState<boolean | null>(null)
  const [searchAbstainTriggered, setSearchAbstainTriggered] = useState<boolean | null>(null)
  const [searchAbstainReason, setSearchAbstainReason] = useState<string | null>(null)
  const [searchError, setSearchError] = useState<string | null>(null)
  const [isSearching, setIsSearching] = useState(false)
  const [selectedEvidenceChunkIds, setSelectedEvidenceChunkIds] = useState<string[]>([])
  const [isCreatingRegressionCase, setIsCreatingRegressionCase] = useState(false)

  const [detailOpen, setDetailOpen] = useState(false)
  const [activeHit, setActiveHit] = useState<RetrievePreviewCitation | null>(null)
  const prefetchedHitTargetsRef = useRef<Set<string>>(new Set())
  const activeHitImageUrl = useMemo(() => {
    if (!activeHit?.has_image) return null
    return resolveSafeCitationImageUrl(activeHit.img_url)
  }, [activeHit])
  const resolvedActiveHitImageUrl = useResolvedAuthAssetUrl(activeHitImageUrl)

  const selectedEvidenceSet = useMemo(() => new Set(selectedEvidenceChunkIds || []), [selectedEvidenceChunkIds])

  const retrievalPerQuery = useMemo(() => {
    const raw = searchMetrics?.retrieval_per_query
    if (!Array.isArray(raw)) return []
    return raw.slice(0, 12).filter((x) => isRecord(x))
  }, [searchMetrics])

  const mainRetrieverDebug = useMemo(() => {
    const main = retrievalPerQuery.find((x) => String(x.kind || '').trim().toLowerCase() === 'main') || retrievalPerQuery[0]
    if (!isRecord(main)) return null
    const dbg = main.retriever_debug
    return isRecord(dbg) ? dbg : null
  }, [retrievalPerQuery])

  const selectedTracePass = useMemo(() => {
    const trace = searchRetrievalTrace
    if (!isRecord(trace)) return null
    const passes = trace.passes
    if (!Array.isArray(passes) || !passes.length) return null
    const selected = typeof trace.selected_pass === 'string' ? trace.selected_pass : null
    const picked =
      (selected ? passes.find((p) => isRecord(p) && p.pass === selected) : null) ||
      passes.find((p) => isRecord(p)) ||
      null
    if (!isRecord(picked)) return null
    return picked
  }, [searchRetrievalTrace])

  const selectedPassTrace = useMemo(() => {
    const picked = selectedTracePass
    if (!isRecord(picked)) return null
    const t = picked.trace
    return isRecord(t) ? t : null
  }, [selectedTracePass])

  const selectedPassRetrieval = useMemo(() => {
    const t = selectedPassTrace
    if (!isRecord(t)) return null
    const r = t.retrieval
    return isRecord(r) ? r : null
  }, [selectedPassTrace])

  const selectedPassQueryVariantFusion = useMemo(() => {
    const fusion = selectedPassTrace?.query_variant_fusion
    return isRecord(fusion) ? fusion : null
  }, [selectedPassTrace])

  const handleSearch = useCallback(async () => {
    const q = searchQuery.trim()
    if (!q) return

    setIsSearching(true)
    setSearchError(null)
    setSearchResults([])
    setSearchQueryForRetrieval('')
    setSearchMetrics(null)
    setSearchRetrievalTrace(null)
    setSearchHasEvidence(null)
    setSearchAbstainTriggered(null)
    setSearchAbstainReason(null)
    setSelectedEvidenceChunkIds([])
    try {
      // Use the production retrieval-only endpoint so this workbench answers:
      // "Do we have evidence in the corpus?" (no answer generation).
      const res: EvidenceRetrieveResponse = await ragApi.retrieveEvidence({
        query: q,
        history: [],
        dataset_id: selectedDatasetId || undefined,
        document_ids: [],
      })
      const citations = Array.isArray(res.citations) ? res.citations : []
      setSearchResults(citations.map(toCitation).filter((citation): citation is RetrievePreviewCitation => citation !== null))
      setSearchQueryForRetrieval(res.query_for_retrieval || '')
      setSearchMetrics(isRecord(res.metrics) ? res.metrics : null)
      setSearchRetrievalTrace(isRecord(res.retrieval_trace) ? res.retrieval_trace : null)
      setSearchHasEvidence(res.has_evidence)
      setSearchAbstainTriggered(res.abstain_triggered)
      setSearchAbstainReason(res.abstain_reason ?? null)
    } catch (error) {
      console.error('Search failed:', error)
      setSearchError(formatApiError(error, '检索失败，请检查后端服务状态'))
    } finally {
      setIsSearching(false)
    }
  }, [searchQuery, selectedDatasetId])

  const toggleEvidenceSelection = useCallback((chunkId: string) => {
    const key = String(chunkId || '').trim()
    if (!key) return
    setSelectedEvidenceChunkIds((prev) => {
      const set = new Set(prev || [])
      if (set.has(key)) set.delete(key)
      else set.add(key)
      return Array.from(set)
    })
  }, [])

  const handleExportEvidencePack = useCallback(() => {
    if (!searchResults.length) return

    const exportedAt = new Date().toISOString()
    const safeTs = exportedAt.replaceAll(/[:.]/g, '-')
    const ds = selectedDatasetId || 'all'
    const filename = `evidence-pack-${ds}-${safeTs}.json`

    const referenceSources = (searchResults || [])
      .filter((c) => !!c?.chunk_id && selectedEvidenceSet.has(String(c.chunk_id)))
      .map((c) => ({
        document_id: c.document_id,
        chunk_id: c.chunk_id,
        page_number: c.page_number ?? null,
        start_char: c.start_char ?? null,
        end_char: c.end_char ?? null,
        doc_pipeline_key: c.doc_pipeline_key ?? null,
        pipeline_hash: c.pipeline_hash ?? null,
        quote: c.chunk_content,
        label: 'ground_truth',
      }))

    const payload = {
      dataset_id: selectedDatasetId || null,
      query: searchQuery.trim(),
      query_for_retrieval: searchQueryForRetrieval || searchQuery.trim(),
      metrics: searchMetrics || null,
      citations: searchResults,
      reference_sources: referenceSources,
      selected_chunk_ids: Array.from(selectedEvidenceSet),
      exported_at: exportedAt,
    }

    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    try {
      const a = document.createElement('a')
      a.href = url
      a.download = filename
      a.click()
      toast.success('已导出 Evidence Pack')
    } finally {
      URL.revokeObjectURL(url)
    }
  }, [searchMetrics, searchQuery, searchQueryForRetrieval, searchResults, selectedDatasetId, selectedEvidenceSet])

  const handleCreateRegressionCaseFromSelection = useCallback(async () => {
    if (!selectedDatasetId) {
      toast.error('请先选择数据集')
      return
    }
    const q = (searchQuery || '').trim()
    if (!q) {
      toast.error('请输入问题')
      return
    }
    if (!selectedEvidenceSet.size) {
      toast.error('请先勾选至少 1 条 Ground Truth 证据')
      return
    }

    const refs: ReferenceSource[] = (searchResults || [])
      .filter((c) => !!c?.chunk_id && selectedEvidenceSet.has(String(c.chunk_id)))
      .map(buildReferenceSource)
      .filter((ref): ref is ReferenceSource => ref !== null)
    if (!refs.length) {
      toast.error('选中的证据引用无效（缺少 chunk_id/document_id）')
      return
    }

    setIsCreatingRegressionCase(true)
    try {
      const payload: RegressionCaseCreate = {
        question: q,
        dataset_id: selectedDatasetId,
        reference_sources: refs,
        tags: ['from_retrieval_preview'],
        extra: {
          query_for_retrieval: searchQueryForRetrieval || q,
          retrieval_metrics: searchMetrics || null,
          created_from: 'knowledge.retrieval',
        },
      }
      await evaluationApi.createRegressionCase(payload)
      toast.success('已创建回归用例')
    } catch (err) {
      console.error('Failed to create regression case from selection', err)
      toast.error(formatApiError(err, '创建回归用例失败'))
    } finally {
      setIsCreatingRegressionCase(false)
    }
  }, [searchMetrics, searchQuery, searchQueryForRetrieval, searchResults, selectedDatasetId, selectedEvidenceSet])

  const openDetails = useCallback((hit: RetrievePreviewCitation) => {
    setActiveHit(hit)
    setDetailOpen(true)
  }, [])

  const handlePrefetchHitDocument = useCallback((hit: RetrievePreviewCitation) => {
    const documentId = String(hit.document_id || '').trim()
    if (!documentId) return

    const chunkId = String(hit.chunk_id || '').trim() || undefined
    const cacheKey = `${documentId}:${chunkId || ''}`
    if (prefetchedHitTargetsRef.current.has(cacheKey)) return
    prefetchedHitTargetsRef.current.add(cacheKey)

    prefetchDocumentView({ documentId, chunkId })
  }, [])

  const handleOpenHitInDocumentViewer = useCallback((hit: RetrievePreviewCitation) => {
    const documentId = String(hit.document_id || '').trim()
    if (!documentId) return

    const chunkId = String(hit.chunk_id || '').trim() || undefined
    const start = typeof hit.evidence_start_char === 'number' ? hit.evidence_start_char : hit.start_char
    const end = typeof hit.evidence_end_char === 'number' ? hit.evidence_end_char : hit.end_char
    const range =
      typeof start === 'number' && Number.isFinite(start) && typeof end === 'number' && Number.isFinite(end) && end > start
        ? { start, end }
        : undefined

    openDocument(documentId, chunkId, range, {
      previewAnchor: getDocumentPreviewAnchorFromCitation(hit),
    })
  }, [openDocument])

  const closeDetails = useCallback((open: boolean) => {
    setDetailOpen(open)
    if (!open) setActiveHit(null)
  }, [])

  const activeMatchedTerms = useMemo(() => {
    const terms = activeHit?.matched_terms
    if (!Array.isArray(terms)) return []
    return terms.filter(Boolean).slice(0, 24).map(String)
  }, [activeHit])
  const activeKgPath = activeHit?.kg_path || []
  const activeKgPathProvenance = activeHit?.kg_path_provenance
  const activeKgPathNodes = activeKgPathProvenance?.nodes || []
  const activeKgPathEdges = activeKgPathProvenance?.edges || []

  return (
    <>
      <Panel padding="none" className={cn("rounded-2xl p-8 text-center relative overflow-hidden", className)}>
        <div className="mb-8">
          <div className="w-16 h-16 bg-primary/10 text-primary rounded-2xl flex items-center justify-center mx-auto mb-4 shadow-soft">
            <Sparkles className="w-8 h-8" />
          </div>
          <h3 className="text-xl font-bold text-foreground text-balance">语义检索测试</h3>
          <p className="text-muted-foreground mt-2 text-pretty">
            输入问题，模拟 RAG 系统的检索召回过程（包含混合检索、RRF 融合、rerank 等）
          </p>
        </div>

        <div className="max-w-2xl mx-auto relative mb-10">
          <div
            className={cn(
              "flex items-center bg-background/60 border-2 border-border/60 rounded-2xl p-2 shadow-soft transition-colors transition-shadow duration-200 motion-reduce:transition-none",
              "focus-within:border-primary/60 focus-within:ring-4 focus-within:ring-ring/15 focus-within:shadow-strong/10"
            )}
          >
            <Search className="w-5 h-5 text-muted-foreground ml-3" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && detachPromise(handleSearch())}
              placeholder="例如：请按第十二条说明例外条件"
              className="flex-1 px-4 py-3 bg-transparent outline-none text-foreground placeholder:text-muted-foreground/60 text-lg"
            />
            <Button
              onClick={() => detachPromise(handleSearch())}
              disabled={isSearching || !searchQuery.trim()}
              className="rounded-xl px-6 h-12 text-base font-medium shadow-md border border-primary/20"
            >
              {isSearching ? (
                <span className="inline-flex items-center gap-2">
                  <Loader2 className="w-5 h-5 animate-spin motion-reduce:animate-none" />
                  检索中…
                </span>
              ) : (
                '开始检索'
              )}
            </Button>
          </div>
        </div>

        {searchError && (
          <div className="max-w-2xl mx-auto mb-6 text-left">
            <div className="rounded-xl border border-destructive/25 bg-destructive/10 p-4 text-sm text-destructive">
              {searchError}
            </div>
          </div>
        )}

        {searchResults.length > 0 && (
          <div className="text-left space-y-4 animate-in fade-in slide-in-from-bottom-4 motion-reduce:animate-none motion-reduce:transition-none">
            <div className="flex flex-col gap-2 px-2 sm:flex-row sm:items-center sm:justify-between">
              <h4 className="text-sm font-semibold text-foreground">召回结果</h4>
              <div className="flex flex-wrap items-center gap-2">
                <Button
                  type="button"
                  variant="outline"
                  className="h-7 rounded-full px-3 gap-1.5 border-border/60 bg-background/60 text-muted-foreground hover:bg-background"
                  disabled={isCreatingRegressionCase || selectedEvidenceSet.size === 0 || !selectedDatasetId}
                  onClick={() => detachPromise(handleCreateRegressionCaseFromSelection())}
                  title={selectedDatasetId ? '用选中的证据创建回归用例' : '请先选择数据集'}
                >
                  {isCreatingRegressionCase ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin motion-reduce:animate-none" />
                  ) : (
                    <TestTube2 className="h-3.5 w-3.5" />
                  )}
                  创建回归用例
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  className="h-7 rounded-full px-3 gap-1.5 border-border/60 bg-background/60 text-muted-foreground hover:bg-background"
                  onClick={handleExportEvidencePack}
                >
                  <FileStack className="h-3.5 w-3.5" />
                  导出 Evidence Pack
                </Button>

                {selectedEvidenceSet.size > 0 && (
                  <span className="text-xs text-muted-foreground bg-muted/60 border border-border/60 px-2 py-1 rounded-full tabular-nums">
                    已选 {selectedEvidenceSet.size}
                  </span>
                )}
                <span className="text-xs text-muted-foreground bg-muted/60 border border-border/60 px-2 py-1 rounded-full tabular-nums">
                  Top {searchResults.length}
                </span>
              </div>
            </div>

            {searchQueryForRetrieval && searchQueryForRetrieval !== searchQuery.trim() && (
              <div className="px-2 text-xs text-muted-foreground">
                实际检索 Query：<span className="font-mono">{searchQueryForRetrieval}</span>
              </div>
            )}

            {(searchHasEvidence !== null || searchAbstainTriggered !== null) && (
              <div className="px-2 text-xs text-muted-foreground flex flex-wrap items-center gap-2">
                {searchHasEvidence !== null && (
                  <span className="font-mono bg-muted/60 border border-border/60 px-2 py-1 rounded-full">
                    has_evidence={String(searchHasEvidence)}
                  </span>
                )}
                {searchAbstainTriggered !== null && (
                  <span className="font-mono bg-muted/60 border border-border/60 px-2 py-1 rounded-full">
                    abstain_triggered={String(searchAbstainTriggered)}
                  </span>
                )}
                {searchAbstainReason ? (
                  <span className="font-mono bg-muted/60 border border-border/60 px-2 py-1 rounded-full">
                    abstain_reason={searchAbstainReason}
                  </span>
                ) : null}
              </div>
            )}

            <div className="rounded-xl border border-border/60 bg-background/60 overflow-auto">
              <table aria-label="检索结果候选列表" className="min-w-[980px] w-full text-xs">
                <thead className="bg-muted/30 text-muted-foreground">
                  <tr className="border-b border-border/60">
                    <th className="p-3 text-left font-semibold w-10">GT</th>
                    <th className="p-3 text-left font-semibold w-10">#</th>
                    <th className="p-3 text-left font-semibold w-20">role</th>
                    <th className="p-3 text-left font-semibold w-20">chunk</th>
                    <th className="p-3 text-left font-semibold w-28">clause</th>
                    <th className="p-3 text-left font-semibold">path</th>
                    <th className="p-3 text-left font-semibold w-44">doc</th>
                    <th className="p-3 text-left font-semibold w-14 tabular-nums">P</th>
                    <th className="p-3 text-left font-semibold w-16 tabular-nums">final</th>
                    <th className="p-3 text-left font-semibold w-16 tabular-nums">vec</th>
                    <th className="p-3 text-left font-semibold w-16 tabular-nums">bm25</th>
                    <th className="p-3 text-left font-semibold w-16 tabular-nums">rerank</th>
                    <th className="p-3 text-left font-semibold w-28">chunk_id</th>
                    <th className="p-3 text-right font-semibold w-20">actions</th>
                  </tr>
                </thead>
                <tbody>
                  {searchResults.map((hit, idx) => {
                    const staggerDelayMs = Math.min(idx, 10) * 40
                    const documentId = String(hit.document_id || '').trim()
                    const chunkId = String(hit.chunk_id || '')
                    const checked = !!chunkId && selectedEvidenceSet.has(chunkId)
                    const role = String(hit.retrieval_role || 'main')
                    const isExpanded = role.startsWith('hierarchy_')
                    const familyHit =
                      typeof hit.family_hit === 'boolean'
                        ? hit.family_hit
                        : Boolean(String(hit.family_collapse_key || hit.hierarchy_family_key || '').trim())
                    const chunkRole = String(hit.chunk_role || '')
                    const clause = String(hit.policy_clause_number || '')
                    const pathStr = String(hit.policy_path_str || '')
                    const docName = String(hit.document_name || '')
                    return (
                      <tr
                        key={`${String(hit.document_id || '')}:${chunkId}:${role}:${clause}:${pathStr}`}
                        className="border-b border-border/40 hover:bg-muted/20 animate-in fade-in-0 slide-in-from-bottom-1 duration-300 motion-reduce:animate-none"
                        style={{ animationDelay: `${staggerDelayMs}ms` }}
                      >
                        <td className="p-3 align-top">
                          <input
                            type="checkbox"
                            className="h-4 w-4 rounded border-border"
                            aria-label={`Ground truth: #${idx + 1}`}
                            disabled={!chunkId}
                            checked={checked}
                            onChange={() => toggleEvidenceSelection(chunkId)}
                          />
                        </td>
                        <td className="p-3 align-top text-muted-foreground tabular-nums">{idx + 1}</td>
                        <td className="p-3 align-top">
                          <div className="flex flex-wrap items-center gap-1">
                            <span className="font-mono bg-muted/60 border border-border/60 px-2 py-1 rounded-md">
                              {role}
                            </span>
                            {isExpanded ? (
                              <span className="font-mono bg-sky-500/10 text-sky-700 dark:text-sky-300 border border-sky-500/20 px-2 py-1 rounded-md">
                                expanded
                              </span>
                            ) : null}
                            {familyHit ? (
                              <span className="font-mono bg-amber-500/10 text-amber-800 dark:text-amber-300 border border-amber-500/20 px-2 py-1 rounded-md">
                                family_hit
                              </span>
                            ) : null}
                          </div>
                        </td>
                        <td className="p-3 align-top">
                          {chunkRole ? (
                            <span className="font-mono bg-muted/60 border border-border/60 px-2 py-1 rounded-md">
                              {chunkRole}
                            </span>
                          ) : (
                            <span className="text-muted-foreground">—</span>
                          )}
                        </td>
                        <td className="p-3 align-top">
                          {clause ? (
                            <span className="font-mono bg-primary/10 text-primary border border-primary/20 px-2 py-1 rounded-md">
                              {clause}
                            </span>
                          ) : (
                            <span className="text-muted-foreground">—</span>
                          )}
                        </td>
                        <td className="p-3 align-top">
                          {pathStr ? (
                            <span className="text-foreground/90 line-clamp-2">{pathStr}</span>
                          ) : (
                            <span className="text-muted-foreground">—</span>
                          )}
                        </td>
                        <td className="p-3 align-top">
                          <div className="flex items-start gap-2">
                            {hit.has_image && hit.img_url ? (
                              (() => {
                                const safeUrl = resolveSafeCitationImageUrl(hit.img_url)
                                if (!safeUrl) return null
                                return (
                                  <AuthImageLink
                                    src={safeUrl}
                                    className="shrink-0 relative h-10 w-10 rounded-md overflow-hidden border border-border/60 bg-muted/20"
                                    title="Open image"
                                    onClick={(e) => e.stopPropagation()}
                                  >
                                    <AuthImage
                                      src={safeUrl}
                                      alt="citation thumbnail"
                                      fill
                                      unoptimized
                                      sizes="40px"
                                      className="object-cover"
                                    />
                                  </AuthImageLink>
                                )
                              })()
                            ) : null}
                            <span className="inline-flex items-center gap-1 text-muted-foreground min-w-0">
                              <FileIcon className="w-3 h-3" />
                              <span className="truncate max-w-[180px]" title={docName}>
                                {docName || 'Unknown'}
                              </span>
                            </span>
                          </div>
                        </td>
                        <td className="p-3 align-top text-muted-foreground tabular-nums">
                          {typeof hit.page_number === 'number' ? hit.page_number : '—'}
                        </td>
                        <td className="p-3 align-top font-mono tabular-nums text-primary">
                          {typeof hit.relevance_score === 'number' ? hit.relevance_score.toFixed(2) : '—'}
                        </td>
                        <td className="p-3 align-top font-mono tabular-nums text-muted-foreground">
                          {typeof hit.vector_score === 'number' ? hit.vector_score.toFixed(3) : '—'}
                        </td>
                        <td className="p-3 align-top font-mono tabular-nums text-muted-foreground">
                          {typeof hit.bm25_score === 'number' ? hit.bm25_score.toFixed(3) : '—'}
                        </td>
                        <td className="p-3 align-top font-mono tabular-nums text-muted-foreground">
                          {typeof hit.rerank_score === 'number' ? hit.rerank_score.toFixed(3) : '—'}
                        </td>
                        <td className="p-3 align-top">
                          {chunkId ? (
                            <span className="font-mono text-muted-foreground" title={chunkId}>
                              {shortId(chunkId)}
                            </span>
                          ) : (
                            <span className="text-muted-foreground">—</span>
                          )}
                        </td>
                        <td className="p-3 align-top text-right">
                          <div className="inline-flex items-center justify-end gap-1">
                            <IconButton
                              label="在文档查看器中打开"
                              variant="ghost"
                              className="h-8 w-8 text-muted-foreground hover:text-primary hover:bg-muted"
                              onClick={() => handleOpenHitInDocumentViewer(hit)}
                              onMouseEnter={() => handlePrefetchHitDocument(hit)}
                              onFocus={() => handlePrefetchHitDocument(hit)}
                              disabled={!documentId}
                            >
                              <ExternalLink className="w-4 h-4" />
                            </IconButton>
                            <IconButton
                              label="复制 chunk_id"
                              variant="ghost"
                              className="h-8 w-8 text-muted-foreground hover:text-primary hover:bg-muted"
                              onClick={() => detachPromise(copyToClipboard(chunkId, 'chunk_id'))}
                              disabled={!chunkId}
                            >
                              <Copy className="w-4 h-4" />
                            </IconButton>
                            <Button
                              type="button"
                              variant="outline"
                              className="h-8 px-2 rounded-lg"
                              onClick={() => openDetails(hit)}
                            >
                              详情
                            </Button>
                          </div>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>

            <details className="px-2">
              <summary className="cursor-pointer select-none text-xs font-semibold text-foreground inline-flex items-center gap-2">
                <Zap className="h-4 w-4 text-primary" />
                检索 Debug（RRF / trimming / per-query metrics）
              </summary>
              <div className="mt-3 rounded-xl border border-border/60 bg-background/60 p-4 space-y-3">
                <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                  <span className="font-mono bg-muted/60 border border-border/60 px-2 py-1 rounded-full">
                    retrieval_mode={String(searchMetrics?.retrieval_mode ?? '—')}
                  </span>
                  <span className="font-mono bg-muted/60 border border-border/60 px-2 py-1 rounded-full tabular-nums">
                    retrieval_query_count={String(searchMetrics?.retrieval_query_count ?? '—')}
                  </span>
                  <span className="font-mono bg-muted/60 border border-border/60 px-2 py-1 rounded-full tabular-nums">
                    retrieval_elapsed_sec={String(searchMetrics?.retrieval_elapsed_sec ?? '—')}
                  </span>
                  {selectedTracePass ? (
                    <span className="font-mono bg-muted/60 border border-border/60 px-2 py-1 rounded-full">
                      selected_pass={String(selectedTracePass.pass ?? '—')}
                    </span>
                  ) : null}
                </div>

                <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
                  <div className="rounded-xl border border-border/60 bg-background/60 p-4">
                    <div className="text-xs font-semibold text-foreground">预算与配额</div>
                    <div className="mt-3 grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs">
                      <div className="rounded-lg border border-border/60 bg-background/60 p-2">
                        <div className="text-[11px] text-muted-foreground">top_k</div>
                        <div className="mt-1 font-mono tabular-nums text-foreground/90">
                          {formatCount(selectedPassRetrieval?.top_k ?? mainRetrieverDebug?.requested_k)}
                        </div>
                      </div>
                      <div className="rounded-lg border border-border/60 bg-background/60 p-2">
                        <div className="text-[11px] text-muted-foreground">search_k</div>
                        <div className="mt-1 font-mono tabular-nums text-foreground/90">
                          {formatCount(mainRetrieverDebug?.search_k)}
                        </div>
                      </div>
                      <div className="rounded-lg border border-border/60 bg-background/60 p-2">
                        <div className="text-[11px] text-muted-foreground">fetch_k</div>
                        <div className="mt-1 font-mono tabular-nums text-foreground/90">
                          {formatCount(mainRetrieverDebug?.fetch_k)}
                        </div>
                      </div>
                      <div className="rounded-lg border border-border/60 bg-background/60 p-2">
                        <div className="text-[11px] text-muted-foreground">overfetch</div>
                        <div className="mt-1 font-mono tabular-nums text-foreground/90">
                          {mainRetrieverDebug ? (
                            String(Boolean(mainRetrieverDebug.overfetch_enabled))
                          ) : (
                            <span className="text-muted-foreground">—</span>
                          )}
                        </div>
                      </div>
                    </div>

                    <div className="mt-3 grid grid-cols-1 sm:grid-cols-2 gap-2 text-xs text-muted-foreground">
                      <div className="rounded-lg border border-border/60 bg-background/60 p-2">
                        <div className="text-[11px]">fusion_strategy</div>
                        <div className="mt-1 font-mono text-foreground/90">
                          {String(selectedPassRetrieval?.channel_fusion_strategy ?? '—')}
                        </div>
                      </div>
                      <div className="rounded-lg border border-border/60 bg-background/60 p-2">
                        <div className="text-[11px]">query_variant_fusion</div>
                        <div className="mt-1 font-mono text-foreground/90">
                          {String(selectedPassQueryVariantFusion?.strategy ?? '—')}
                        </div>
                      </div>
                    </div>

                    {(() => {
                      const ch = isRecord(mainRetrieverDebug?.channels) ? mainRetrieverDebug?.channels : null
                      const fusion = isRecord(ch?.fusion_budgeted_rrf) ? ch?.fusion_budgeted_rrf : null
                      if (!fusion) return null
                      const budgets = isRecord(fusion.budgets) ? fusion.budgets : null
                      const picked = isRecord(fusion.picked_by_channel) ? fusion.picked_by_channel : null
                      return (
                        <div className="mt-3 rounded-lg border border-border/60 bg-background/60 p-3">
                          <div className="text-xs font-semibold text-foreground">Budgeted RRF（按通道配额）</div>
                          <div className="mt-2 grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs">
                            <div className="rounded-md border border-border/60 bg-background/60 p-2">
                              <div className="text-[11px] text-muted-foreground">k_prefix</div>
                              <div className="mt-1 font-mono tabular-nums text-foreground/90">{formatCount(fusion.k_prefix)}</div>
                            </div>
                            <div className="rounded-md border border-border/60 bg-background/60 p-2">
                              <div className="text-[11px] text-muted-foreground">eligible_total</div>
                              <div className="mt-1 font-mono tabular-nums text-foreground/90">{formatCount(fusion.eligible_total)}</div>
                            </div>
                            <div className="rounded-md border border-border/60 bg-background/60 p-2">
                              <div className="text-[11px] text-muted-foreground">selected_prefix</div>
                              <div className="mt-1 font-mono tabular-nums text-foreground/90">
                                {formatCount(fusion.selected_prefix)}
                              </div>
                            </div>
                            <div className="rounded-md border border-border/60 bg-background/60 p-2">
                              <div className="text-[11px] text-muted-foreground">rrf_k</div>
                              <div className="mt-1 font-mono tabular-nums text-foreground/90">{formatCount(fusion.rrf_k)}</div>
                            </div>
                          </div>
                          <div className="mt-2 text-[11px] text-muted-foreground">
                            quotas:{' '}
                            {budgets ? (
                              <span className="font-mono tabular-nums text-foreground/90">
                                {Object.entries(budgets)
                                  .slice(0, 8)
                                  .map(([k, v]) => `${k}=${formatCount(v)}`)
                                  .join('  ')}
                              </span>
                            ) : (
                              <span className="text-muted-foreground">—</span>
                            )}
                          </div>
                          <div className="mt-1 text-[11px] text-muted-foreground">
                            picked:{' '}
                            {picked ? (
                              <span className="font-mono tabular-nums text-foreground/90">
                                {Object.entries(picked)
                                  .slice(0, 8)
                                  .map(([k, v]) => `${k}=${formatCount(v)}`)
                                  .join('  ')}
                              </span>
                            ) : (
                              <span className="text-muted-foreground">—</span>
                            )}
                          </div>
                        </div>
                      )
                    })()}
                  </div>

                  <div className="rounded-xl border border-border/60 bg-background/60 p-4">
                    <div className="text-xs font-semibold text-foreground">裁剪原因（trimming / caps）</div>

                    {(() => {
                      const dbg = mainRetrieverDebug
                      if (!dbg) {
                        return <div className="mt-2 text-xs text-muted-foreground">无 retriever_debug（可能是旧版本后端或被裁剪）。</div>
                      }

                      const div = isRecord(dbg.diversity) ? dbg.diversity : null
                      const ch = isRecord(dbg.channels) ? dbg.channels : null

                      const mergedPre = toInt(ch?.merged_pre_dedup)
                      const mergedPost = toInt(ch?.merged_post_dedup)
                      const dedupDropped =
                        typeof mergedPre === 'number' && typeof mergedPost === 'number' ? Math.max(0, mergedPre - mergedPost) : null

                      const divChan = isRecord(ch?.diversity) ? ch?.diversity : null
                      const divDropped = toInt(divChan?.dropped)

                      const enrich = (() => {
    if (isRecord(dbg.enrich_pass2)) {
        return dbg.enrich_pass2;
    }
    else if (isRecord(dbg.enrich_pass1)) {
            return dbg.enrich_pass1;
        }
        else {
            return null;
        }
})()
                      const trimKeys: Array<[string, string]> = [
                        ['filtered_metadata_filter', 'metadata_filter'],
                        ['filtered_acl', 'acl'],
                        ['filtered_dataset', 'dataset'],
                        ['filtered_pipeline_version', 'pipeline_version'],
                        ['filtered_embedding_space', 'embedding_space'],
                        ['filtered_not_ready', 'not_ready'],
                        ['filtered_orphaned', 'orphaned_vectors'],
                      ]
                      const trims = trimKeys
                        .map(([k, label]) => {
                          const n = toInt(enrich?.[k])
                          return { key: k, label, n: typeof n === 'number' ? n : 0 }
                        })
                        .filter((x) => x.n > 0)
                        .sort((a, b) => b.n - a.n || a.label.localeCompare(b.label))

                      const capsEnabled = Boolean(
                        (toInt(div?.max_chunks_per_doc) ?? 0) > 0 || (toInt(div?.max_chunks_per_page) ?? 0) > 0 || (toInt(div?.min_distinct_docs) ?? 0) > 0
                      )

                      return (
                        <div className="mt-3 space-y-3">
                          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs">
                            <div className="rounded-lg border border-border/60 bg-background/60 p-2">
                              <div className="text-[11px] text-muted-foreground">dedup_dropped</div>
                              <div className="mt-1 font-mono tabular-nums text-foreground/90">
                                {typeof dedupDropped === 'number' ? String(dedupDropped) : '—'}
                              </div>
                            </div>
                            <div className="rounded-lg border border-border/60 bg-background/60 p-2">
                              <div className="text-[11px] text-muted-foreground">diversity_dropped</div>
                              <div className="mt-1 font-mono tabular-nums text-foreground/90">
                                {typeof divDropped === 'number' ? String(divDropped) : '—'}
                              </div>
                            </div>
                            <div className="rounded-lg border border-border/60 bg-background/60 p-2">
                              <div className="text-[11px] text-muted-foreground">enrich_input</div>
                              <div className="mt-1 font-mono tabular-nums text-foreground/90">{formatCount(enrich?.input_results)}</div>
                            </div>
                            <div className="rounded-lg border border-border/60 bg-background/60 p-2">
                              <div className="text-[11px] text-muted-foreground">enrich_output</div>
                              <div className="mt-1 font-mono tabular-nums text-foreground/90">{formatCount(enrich?.output_results)}</div>
                            </div>
                          </div>

                          <div className="rounded-lg border border-border/60 bg-background/60 p-3">
                            <div className="text-xs font-semibold text-foreground">Diversity caps（doc/page）</div>
                            <div className="mt-2 text-[11px] text-muted-foreground">
                              {capsEnabled ? (
                                <>
                                  max_chunks_per_doc=<span className="font-mono tabular-nums text-foreground/90">{formatCount(div?.max_chunks_per_doc)}</span>{' '}
                                  max_chunks_per_page=<span className="font-mono tabular-nums text-foreground/90">{formatCount(div?.max_chunks_per_page)}</span>{' '}
                                  min_distinct_docs=<span className="font-mono tabular-nums text-foreground/90">{formatCount(div?.min_distinct_docs)}</span>
                                </>
                              ) : (
                                <span className="text-muted-foreground">caps disabled</span>
                              )}
                            </div>
                            {capsEnabled ? (
                              <div className="mt-2 grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs">
                                <div className="rounded-md border border-border/60 bg-background/60 p-2">
                                  <div className="text-[11px] text-muted-foreground">unique_docs</div>
                                  <div className="mt-1 font-mono tabular-nums text-foreground/90">
                                    {formatCount(div?.pre_unique_docs)}→{formatCount(div?.post_unique_docs)}
                                  </div>
                                </div>
                                <div className="rounded-md border border-border/60 bg-background/60 p-2">
                                  <div className="text-[11px] text-muted-foreground">unique_pages</div>
                                  <div className="mt-1 font-mono tabular-nums text-foreground/90">
                                    {formatCount(div?.pre_unique_pages)}→{formatCount(div?.post_unique_pages)}
                                  </div>
                                </div>
                                <div className="rounded-md border border-border/60 bg-background/60 p-2">
                                  <div className="text-[11px] text-muted-foreground">moved_out</div>
                                  <div className="mt-1 font-mono tabular-nums text-foreground/90">{formatCount(div?.moved_out)}</div>
                                </div>
                                <div className="rounded-md border border-border/60 bg-background/60 p-2">
                                  <div className="text-[11px] text-muted-foreground">moved_in</div>
                                  <div className="mt-1 font-mono tabular-nums text-foreground/90">{formatCount(div?.moved_in)}</div>
                                </div>
                              </div>
                            ) : null}
                          </div>

                          <div className="rounded-lg border border-border/60 bg-background/60 p-3">
                            <div className="text-xs font-semibold text-foreground">Trimming reasons（DB enrich）</div>
                            {trims.length ? (
                              <div className="mt-2 flex flex-wrap gap-2 text-[11px]">
                                {trims.slice(0, 10).map((t) => (
                                  <span
                                    key={t.key}
                                    className="font-mono tabular-nums bg-muted/60 border border-border/60 px-2 py-1 rounded-full text-foreground/90"
                                  >
                                    {t.label}=-{t.n}
                                  </span>
                                ))}
                              </div>
                            ) : (
                              <div className="mt-2 text-xs text-muted-foreground">未观察到显著 trimming（或该版本未上报 enrich 计数）。</div>
                            )}
                          </div>
                        </div>
                      )
                    })()}
                  </div>
                </div>

                {retrievalPerQuery.length ? (
                  <div className="rounded-lg border border-border/60 overflow-auto">
                    <table aria-label="按查询聚合的检索统计" className="min-w-[720px] w-full text-xs">
                      <thead className="bg-muted/30 text-muted-foreground">
                        <tr className="border-b border-border/60">
                          <th className="p-2 text-left font-semibold w-24">kind</th>
                          <th className="p-2 text-left font-semibold w-24 tabular-nums">elapsed</th>
                          <th className="p-2 text-left font-semibold w-20">ok</th>
                          <th className="p-2 text-left font-semibold w-28 tabular-nums">query_chars</th>
                          <th className="p-2 text-left font-semibold">retriever_debug</th>
                        </tr>
                      </thead>
                      <tbody>
                        {retrievalPerQuery.map((item) => (
                          <tr key={`${String(item.kind || 'query')}:${String(item.query_chars ?? '')}:${String(item.elapsed_sec ?? '')}`} className="border-b border-border/40 align-top">
                            <td className="p-2 font-mono text-foreground/90">{String(item.kind || '—')}</td>
                            <td className="p-2 font-mono tabular-nums text-muted-foreground">
                              {typeof item.elapsed_sec === 'number' ? item.elapsed_sec.toFixed(3) : String(item.elapsed_sec ?? '—')}
                            </td>
                            <td className="p-2 font-mono text-muted-foreground">{String(Boolean(item.ok))}</td>
                            <td className="p-2 font-mono tabular-nums text-muted-foreground">{String(item.query_chars ?? '—')}</td>
                            <td className="p-2">
                              <pre className="whitespace-pre-wrap text-[11px] leading-relaxed text-muted-foreground font-mono">
                                {JSON.stringify(item.retriever_debug || null, null, 2)}
                              </pre>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <div className="text-xs text-muted-foreground">无 per-query debug 数据（可能是旧版本后端或被裁剪）。</div>
                )}
              </div>
            </details>
          </div>
        )}
      </Panel>

      <Dialog open={detailOpen} onOpenChange={closeDetails}>
        <DialogContent
          className={cn(
            // "Drawer-like" right panel (still a dialog for a11y + focus).
            "left-auto right-0 top-0 translate-x-0 translate-y-0 h-dvh w-[min(760px,100vw)] max-w-[760px] rounded-none",
            "p-0 overflow-hidden"
          )}
        >
          <div className="flex h-full flex-col">
            <div className="border-b border-border/60 bg-background/80 px-6 py-4">
              <DialogHeader className="space-y-1">
                <DialogTitle className="text-base">
                  {activeHit?.document_name || 'Hit Details'}
                </DialogTitle>
                <DialogDescription>
                  chunk_id <span className="font-mono">{activeHit?.chunk_id ? shortId(activeHit.chunk_id) : '—'}</span>
                </DialogDescription>
              </DialogHeader>
            </div>

            <div className="flex-1 overflow-auto px-6 py-5 space-y-5">
              {activeHit ? (
                <>
                  {resolvedActiveHitImageUrl ? (
                    <div className="rounded-xl border border-border/60 bg-background/60 overflow-hidden">
                      <a href={resolvedActiveHitImageUrl} target="_blank" rel="noopener noreferrer" className="block relative aspect-video">
                        <AuthImage
                          src={activeHitImageUrl}
                          alt="cited image"
                          fill
                          unoptimized
                          sizes="(max-width: 768px) 100vw, 640px"
                          className="object-contain bg-muted/10"
                        />
                      </a>
                    </div>
                  ) : null}

                  <div className="flex flex-wrap items-center gap-2">
                    <Button
                      type="button"
                      variant="outline"
                      className="h-8 rounded-full px-3 gap-2"
                      onClick={() => detachPromise(copyToClipboard(String(activeHit.chunk_id || ''), 'chunk_id'))}
                      disabled={!activeHit.chunk_id}
                    >
                      <Copy className="h-4 w-4" />
                      复制 chunk_id
                    </Button>
                    <Button
                      type="button"
                      variant="outline"
                      className="h-8 rounded-full px-3 gap-2"
                      onClick={() => detachPromise(copyToClipboard(String(activeHit.doc_pipeline_key || ''), 'doc_pipeline_key'))}
                      disabled={!activeHit.doc_pipeline_key}
                    >
                      <Copy className="h-4 w-4" />
                      复制 doc_pipeline_key
                    </Button>
                    <Button
                      type="button"
                      variant="outline"
                      className="h-8 rounded-full px-3 gap-2"
                      onClick={() => detachPromise(copyToClipboard((activeMatchedTerms || []).join(' '), 'matched_terms'))}
                      disabled={!activeMatchedTerms.length}
                    >
                      <Copy className="h-4 w-4" />
                      复制 matched_terms
                    </Button>
                  </div>

                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                    <div className="rounded-xl border border-border/60 bg-background/60 p-3">
                      <div className="text-xs text-muted-foreground">retrieval_role</div>
                      <div className="mt-1 text-xs font-mono text-foreground/90">{String(activeHit.retrieval_role || 'main')}</div>
                    </div>
                    <div className="rounded-xl border border-border/60 bg-background/60 p-3">
                      <div className="text-xs text-muted-foreground">chunk_role</div>
                      <div className="mt-1 text-xs font-mono text-foreground/90">{String(activeHit.chunk_role || '—')}</div>
                    </div>
                    <div className="rounded-xl border border-border/60 bg-background/60 p-3">
                      <div className="text-xs text-muted-foreground">chunk_strategy</div>
                      <div className="mt-1 text-xs font-mono text-foreground/90">{String(activeHit.chunk_strategy || '—')}</div>
                    </div>
                    <div className="rounded-xl border border-border/60 bg-background/60 p-3">
                      <div className="text-xs text-muted-foreground">doc_pipeline_key</div>
                      <div className="mt-1 text-[11px] font-mono text-foreground/90 break-all">{String(activeHit.doc_pipeline_key || '—')}</div>
                    </div>
                  </div>

                  <div className="rounded-xl border border-border/60 bg-background/60 p-4">
                    <div className="text-xs font-semibold text-foreground mb-3">Scores</div>
                    <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 text-xs">
                      {[
                        ['final(relevance_score)', activeHit.relevance_score],
                        ['retrieval_score', activeHit.retrieval_score],
                        ['vector_score', activeHit.vector_score],
                        ['bm25_score', activeHit.bm25_score],
                        ['keyword_score', activeHit.keyword_score],
                        ['rerank_score', activeHit.rerank_score],
                      ].map(([k, v]) => (
                        <div key={String(k)} className="rounded-lg border border-border/60 bg-background/60 p-2">
                          <div className="text-[11px] text-muted-foreground">{String(k)}</div>
                          <div className="mt-1 font-mono tabular-nums text-foreground/90">
                            {typeof v === 'number' ? v.toFixed(3) : '—'}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>

                  <div className="rounded-xl border border-border/60 bg-background/60 p-4">
                    <div className="text-xs font-semibold text-foreground mb-3">Policy Metadata</div>
                    <div className="space-y-2 text-xs">
                      <div className="flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between">
                        <div className="text-muted-foreground">policy_clause_number</div>
                        <div className="font-mono text-foreground/90">{String(activeHit.policy_clause_number || '—')}</div>
                      </div>
                      <div className="flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between">
                        <div className="text-muted-foreground">parent_id</div>
                        <div className="font-mono text-foreground/90 break-all">{String(activeHit.parent_id || '—')}</div>
                      </div>
                      <div className="flex flex-col gap-1">
                        <div className="text-muted-foreground">policy_path_str</div>
                        <div className="font-mono text-foreground/90">{String(activeHit.policy_path_str || '—')}</div>
                      </div>
                    </div>
                  </div>

                  {activeMatchedTerms.length ? (
                    <div className="rounded-xl border border-border/60 bg-background/60 p-4">
                      <div className="text-xs font-semibold text-foreground mb-3">Matched Terms</div>
                      <div className="flex flex-wrap gap-2">
                        {activeMatchedTerms.map((t) => (
                          <span
                            key={t}
                            className="text-[11px] font-mono bg-muted/60 border border-border/60 px-2 py-1 rounded-full"
                          >
                            {t}
                          </span>
                        ))}
                      </div>
                    </div>
                  ) : null}

                  {activeKgPath.length ? (
                    <div className="rounded-xl border border-border/60 bg-background/60 p-4">
                      <div className="flex items-center justify-between gap-3 mb-3">
                        <div className="text-xs font-semibold text-foreground">KG Path</div>
                        <Button
                          type="button"
                          variant="outline"
                          className="h-8 rounded-full px-3 gap-2"
                          onClick={() =>
                            detachPromise(copyToClipboard(
                              JSON.stringify(activeKgPath, null, 0),
                              'kg_path'
                            ))
                          }
                        >
                          <Copy className="h-4 w-4" />
                          复制 kg_path
                        </Button>
                      </div>
                      <div className="space-y-2 text-xs">
                        {activeKgPath.map((step) => (
                          <div
                            key={`${String(step.entity_id || '')}:${String(step.type || 'entity')}`}
                            className="flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between rounded-lg border border-border/60 bg-muted/20 px-3 py-2"
                          >
                            <div className="text-muted-foreground">{String(step.type || 'entity')}</div>
                            <div className="font-mono text-foreground/90 break-all">
                              {step.entity_id ? shortId(String(step.entity_id)) : '—'}
                            </div>
                          </div>
                        ))}
                      </div>
                      <div className="mt-2 text-[11px] text-muted-foreground">
                        注：kg_path 只包含 entity_id/type（PII-safe），可在 Graph 页面查看实体详情。
                      </div>
                    </div>
                  ) : null}

                  {activeKgPathProvenance ? (
                    <div className="rounded-xl border border-border/60 bg-background/60 p-4">
                      <div className="flex items-center justify-between gap-3 mb-3">
                        <div className="text-xs font-semibold text-foreground">KG Path Provenance</div>
                        <Button
                          type="button"
                          variant="outline"
                          className="h-8 rounded-full px-3 gap-2"
                          onClick={() =>
                            detachPromise(copyToClipboard(
                              JSON.stringify(activeKgPathProvenance, null, 2),
                              'kg_path_provenance'
                            ))
                          }
                        >
                          <Copy className="h-4 w-4" />
                          复制 provenance
                        </Button>
                      </div>

                      <div className="grid grid-cols-2 gap-3 text-xs">
                        <div className="rounded-lg border border-border/60 bg-background/60 p-2">
                          <div className="text-[11px] text-muted-foreground">kind</div>
                          <div className="mt-1 font-mono text-foreground/90">
                            {String(activeKgPathProvenance.kind || '—')}
                          </div>
                        </div>
                        <div className="rounded-lg border border-border/60 bg-background/60 p-2">
                          <div className="text-[11px] text-muted-foreground">hops</div>
                          <div className="mt-1 font-mono tabular-nums text-foreground/90">
                            {Number.isFinite(Number(activeKgPathProvenance.hops))
                              ? Number(activeKgPathProvenance.hops)
                              : '—'}
                          </div>
                        </div>
                      </div>

                      {activeKgPathNodes.length ? (
                        <div className="mt-3">
                          <div className="text-xs font-semibold text-foreground mb-2">Nodes</div>
                          <div className="space-y-2 text-xs">
                            {activeKgPathNodes.slice(0, 12).map((node) => {
                              const kind = String(node.kind || 'node')
                              const id = String(node.entity_id || node.event_id || '—')
                              const typ = String(node.type || '')
                              const doc = node.document_id ? shortId(String(node.document_id)) : ''
                              const chunk = node.chunk_id ? shortId(String(node.chunk_id)) : ''
                              return (
                                <div
                                  key={`${kind}:${id}:${typ}:${doc}:${chunk}`}
                                  className="rounded-lg border border-border/60 bg-muted/20 px-3 py-2"
                                >
                                  <div className="flex flex-wrap items-center justify-between gap-2">
                                    <div className="text-muted-foreground">{kind}{typ ? ` · ${typ}` : ''}</div>
                                    <div className="font-mono text-foreground/90 break-all">{id === '—' ? '—' : shortId(id, { head: 10, tail: 6 })}</div>
                                  </div>
                                  {doc || chunk ? (
                                    <div className="mt-1 text-[11px] text-muted-foreground break-all">
                                      {doc ? `doc=${doc}` : null}
                                      {doc && chunk ? ' · ' : null}
                                      {chunk ? `chunk=${chunk}` : null}
                                    </div>
                                  ) : null}
                                </div>
                              )
                            })}
                          </div>
                        </div>
                      ) : null}

                      {activeKgPathEdges.length ? (
                        <div className="mt-3">
                          <div className="text-xs font-semibold text-foreground mb-2">Edges</div>
                          <div className="space-y-2 text-xs">
                            {activeKgPathEdges.slice(0, 12).map((edge) => {
                              const kind = String(edge.kind || 'edge')
                              const pred = String(edge.predicate || '')
                              const bucket = String(edge.confidence_bucket || '')
                              const src = String(edge.evidence_source || '')
                              const rel = edge.relation_id ? shortId(String(edge.relation_id)) : ''
                              const doc = edge.document_id ? shortId(String(edge.document_id)) : ''
                              const chunk = edge.chunk_id ? shortId(String(edge.chunk_id)) : ''
                              return (
                                <div
                                  key={`${kind}:${pred}:${bucket}:${src}:${rel}:${doc}:${chunk}`}
                                  className="rounded-lg border border-border/60 bg-muted/20 px-3 py-2"
                                >
                                  <div className="flex flex-wrap items-center justify-between gap-2">
                                    <div className="text-muted-foreground">
                                      {kind}
                                      {pred ? ` · ${pred}` : ''}
                                      {bucket ? ` · conf=${bucket}` : ''}
                                      {src ? ` · src=${src}` : ''}
                                    </div>
                                    <div className="font-mono text-foreground/90 break-all">
                                      {rel ? `rel=${rel}` : '—'}
                                    </div>
                                  </div>
                                  {doc || chunk ? (
                                    <div className="mt-1 text-[11px] text-muted-foreground break-all">
                                      {doc ? `doc=${doc}` : null}
                                      {doc && chunk ? ' · ' : null}
                                      {chunk ? `chunk=${chunk}` : null}
                                    </div>
                                  ) : null}
                                </div>
                              )
                            })}
                          </div>
                        </div>
                      ) : null}

                      <div className="mt-2 text-[11px] text-muted-foreground">
                        注：该 provenance 只包含 id/type/桶（不含实体名/引用原文），用于 UI/诊断展示与溯源。
                      </div>
                    </div>
                  ) : null}

                  <div className="rounded-xl border border-border/60 bg-background/60 p-4">
                    <div className="text-xs font-semibold text-foreground mb-3">Snippet</div>
                    <pre className="whitespace-pre-wrap text-xs leading-relaxed text-foreground/90 font-mono">
                      {String(activeHit.chunk_content || '')}
                    </pre>
                  </div>
                </>
              ) : (
                <div className="text-sm text-muted-foreground">无选中条目</div>
              )}
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </>
  )
}
