'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
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
import { Badge } from '@/components/ui/badge'
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

function formatScore(value: number | undefined, digits = 3): string {
  return typeof value === 'number' && Number.isFinite(value) ? value.toFixed(digits) : '—'
}

function toHitKey(hit: Pick<RetrievePreviewCitation, 'document_id' | 'chunk_id' | 'retrieval_role'>): string {
  return [
    String(hit.document_id || '').trim(),
    String(hit.chunk_id || '').trim(),
    String(hit.retrieval_role || '').trim(),
  ].join(':')
}

function previewChunkContent(value: string | undefined, maxLen = 360): string {
  const text = String(value || '').trim().replaceAll(/\s+/g, ' ')
  if (!text) return '该命中未返回可预览的 chunk 内容。'
  if (text.length <= maxLen) return text
  return `${text.slice(0, maxLen).trimEnd()}…`
}

const noResultActionTips = ['缩短问题', '切换数据集', '改用原文关键词', '补充条款编号'] as const

const noResultDiagnosticTips = [
  {
    title: '问题过长或太泛',
    description: '先压缩成一个核心问题，减少背景描述和泛化措辞，再观察是否能形成稳定召回。',
  },
  {
    title: '检索范围过窄',
    description: '切到更大的数据集范围，确认目标文档已经入库、解析完成，并且当前数据集选择正确。',
  },
  {
    title: '表达不贴近原文',
    description: '优先使用条款编号、章节名、专有名词和文档中的原句关键词，不要只用口语化转述。',
  },
] as const

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
  const [hasSearched, setHasSearched] = useState(false)
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
  const searchInputRef = useRef<HTMLTextAreaElement | null>(null)
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

  const resizeSearchComposer = useCallback((target?: HTMLTextAreaElement | null) => {
    const el = target ?? searchInputRef.current
    if (!el) return
    el.style.height = '0px'
    el.style.height = `${Math.min(Math.max(el.scrollHeight, 64), 224)}px`
  }, [])

  const handleSearch = useCallback(async () => {
    const q = searchQuery.trim()
    if (!q) return

    setHasSearched(true)
    setIsSearching(true)
    setSearchError(null)
    setSearchResults([])
    setActiveHit(null)
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
      const nextResults = citations.map(toCitation).filter((citation): citation is RetrievePreviewCitation => citation !== null)
      setSearchResults(nextResults)
      setActiveHit(nextResults[0] ?? null)
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

  useEffect(() => {
    resizeSearchComposer()
  }, [resizeSearchComposer, searchQuery])

  useEffect(() => {
    if (!searchResults.length) {
      if (!detailOpen) setActiveHit(null)
      return
    }

    if (!activeHit) return
    const activeKey = toHitKey(activeHit)
    if (!searchResults.some((hit) => toHitKey(hit) === activeKey)) {
      setActiveHit(searchResults[0])
    }
  }, [activeHit, detailOpen, searchResults])

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
  const activeResult = activeHit ?? searchResults[0] ?? null
  const activeResultMatchedTerms = useMemo(() => {
    const terms = activeResult?.matched_terms
    if (!Array.isArray(terms)) return []
    return terms.filter(Boolean).slice(0, 24).map(String)
  }, [activeResult])
  const composerPinned = hasSearched || isSearching || Boolean(searchError)
  const hasResultList = searchResults.length > 0
  const activeKgPath = activeHit?.kg_path || []
  const activeKgPathProvenance = activeHit?.kg_path_provenance
  const activeKgPathNodes = activeKgPathProvenance?.nodes || []
  const activeKgPathEdges = activeKgPathProvenance?.edges || []
  const noResultQuerySummary = searchQueryForRetrieval || searchQuery.trim()
  const noResultDatasetSummary = selectedDatasetId || '全部数据集'

  return (
    <>
      <div
        className={cn(
          "relative overflow-hidden",
          className
        )}
      >
        <div className="sticky top-0 z-20 border-b border-border/60 bg-background/82 px-4 py-4 backdrop-blur-xl md:px-6">
          <div className="mx-auto max-w-6xl">
            <div
              className={cn(
                "transition-all duration-300 motion-reduce:transition-none",
                composerPinned ? "space-y-4" : "space-y-6 py-6"
              )}
            >
              <div className={cn(composerPinned ? "flex items-start gap-4" : "text-center")}>
                <div
                  className={cn(
                    "flex items-center justify-center rounded-2xl bg-primary/10 text-primary shadow-soft",
                    composerPinned ? "h-12 w-12 shrink-0" : "mx-auto h-16 w-16"
                  )}
                >
                  <Sparkles className={cn(composerPinned ? "size-6" : "size-8")} />
                </div>
                <div className={cn("min-w-0", composerPinned ? "pt-1 text-left" : "mt-4")}>
                  <h3 className={cn("font-bold text-foreground text-balance", composerPinned ? "text-lg" : "text-xl")}>
                    语义检索测试
                  </h3>
                  <p className="mt-2 text-pretty text-sm leading-6 text-muted-foreground">
                    输入复杂问题或长 Prompt，验证 RAG 的召回质量、排序结果和调试指标。
                  </p>
                </div>
              </div>

              <div className="rounded-[24px] border border-border/60 bg-background/72 shadow-soft">
                <div className="flex items-start gap-3 p-3">
                  <div className="pt-3 text-muted-foreground">
                    <Search className="size-5" />
                  </div>
                  <div className="min-w-0 flex-1">
                    <textarea
                      ref={searchInputRef}
                      rows={1}
                      value={searchQuery}
                      aria-label="检索问题"
                      onChange={(e) => {
                        setSearchQuery(e.target.value)
                        resizeSearchComposer(e.currentTarget)
                      }}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter' && !e.shiftKey) {
                          e.preventDefault()
                          detachPromise(handleSearch())
                        }
                      }}
                      placeholder="例如：请按第十二条说明例外条件，并指出适用范围与例外条款"
                      className="min-h-[64px] max-h-56 w-full resize-none bg-transparent px-1 py-2 text-[15px] leading-6 text-foreground outline-none placeholder:text-muted-foreground/60"
                    />
                    <div className="mt-2 flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
                      <span className="inline-flex items-center rounded-full border border-border/60 bg-muted/30 px-2 py-1">
                        Enter 发送
                      </span>
                      <span className="inline-flex items-center rounded-full border border-border/60 bg-muted/30 px-2 py-1">
                        Shift + Enter 换行
                      </span>
                      <span className="inline-flex items-center rounded-full border border-border/60 bg-muted/30 px-2 py-1">
                        当前数据集：<span className="ml-1 font-mono text-foreground">{selectedDatasetId || '全部'}</span>
                      </span>
                    </div>
                  </div>
                  <Button
                    onClick={() => detachPromise(handleSearch())}
                    disabled={isSearching || !searchQuery.trim()}
                    className="mt-1 h-11 rounded-xl border border-primary/20 px-5 text-sm font-medium shadow-md"
                  >
                    {isSearching ? (
                      <span className="inline-flex items-center gap-2">
                        <Loader2 className="size-4 animate-spin motion-reduce:animate-none" />
                        检索中…
                      </span>
                    ) : (
                      '开始检索'
                    )}
                  </Button>
                </div>
              </div>
            </div>
          </div>
        </div>

        <div className="mx-auto max-w-6xl px-4 pb-6 pt-5 md:px-6">
          {isSearching && !hasResultList ? (
            <div className="space-y-3">
              {[0, 1, 2].map((item) => (
                <div key={item} className="animate-pulse rounded-2xl border border-border/60 bg-background/60 p-4">
                  <div className="h-4 w-32 rounded bg-muted/70" />
                  <div className="mt-3 h-3 w-full rounded bg-muted/60" />
                  <div className="mt-2 h-3 w-11/12 rounded bg-muted/50" />
                  <div className="mt-4 grid grid-cols-4 gap-2">
                    <div className="h-12 rounded-xl bg-muted/40" />
                    <div className="h-12 rounded-xl bg-muted/40" />
                    <div className="h-12 rounded-xl bg-muted/40" />
                    <div className="h-12 rounded-xl bg-muted/40" />
                  </div>
                </div>
              ))}
            </div>
          ) : null}

          {searchError ? (
            <div className="mb-6 max-w-3xl text-left">
              <div className="rounded-2xl border border-destructive/25 bg-destructive/10 p-4 text-sm text-destructive">
                {searchError}
              </div>
            </div>
          ) : null}

          {hasSearched && !isSearching && !searchError && !hasResultList ? (
            <Panel padding="none" className="overflow-hidden rounded-[28px] border border-border/60 bg-background/75 shadow-soft">
              <div className="grid gap-0 xl:grid-cols-[minmax(0,1.12fr)_18rem]">
                <div className="space-y-5 p-5 sm:p-6">
                  <div className="flex items-start gap-4">
                    <div className="flex size-12 shrink-0 items-center justify-center rounded-2xl border border-primary/20 bg-primary/10 text-primary shadow-soft">
                      <Search className="size-5" />
                    </div>
                    <div className="min-w-0">
                      <Badge variant="soft" className="border-border/70 bg-muted/45 text-[11px] font-medium text-muted-foreground">
                        Top-K 排序为空
                      </Badge>
                      <div className="mt-3 text-base font-semibold text-foreground">没有召回到结果</div>
                      <p className="mt-2 max-w-2xl text-sm leading-6 text-muted-foreground">
                        当前 query 没有命中可展示的 chunk，可以先从关键词表达和数据集范围开始排查。
                      </p>
                    </div>
                  </div>

                  <div className="grid gap-3 sm:grid-cols-2">
                    <div className="rounded-2xl border border-border/60 bg-muted/20 p-4">
                      <div className="text-[11px] font-medium tracking-[0.16em] text-muted-foreground/80">检索 Query</div>
                      <div className="mt-2 line-clamp-2 break-all text-sm font-medium leading-6 text-foreground">
                        {noResultQuerySummary || '未填写'}
                      </div>
                    </div>
                    <div className="rounded-2xl border border-border/60 bg-muted/20 p-4">
                      <div className="text-[11px] font-medium tracking-[0.16em] text-muted-foreground/80">数据集范围</div>
                      <div className="mt-2 line-clamp-2 break-all font-mono text-sm leading-6 text-foreground">
                        {noResultDatasetSummary}
                      </div>
                    </div>
                  </div>

                  <div className="space-y-2">
                    <div className="text-xs font-medium text-muted-foreground">建议动作</div>
                    <div className="flex flex-wrap gap-2">
                      {noResultActionTips.map((label) => (
                        <span
                          key={label}
                          className="inline-flex items-center rounded-full border border-border/60 bg-muted/35 px-3 py-1.5 text-xs font-medium text-foreground/85"
                        >
                          {label}
                        </span>
                      ))}
                    </div>
                  </div>
                </div>

                <div className="border-t border-border/60 bg-muted/20 p-5 xl:border-l xl:border-t-0">
                  <div className="inline-flex items-center gap-2 rounded-full border border-warning/20 bg-warning/10 px-3 py-1 text-[11px] font-medium text-warning">
                    <Zap className="size-3.5" />
                    排查方向
                  </div>
                  <div className="mt-4 space-y-3">
                    {noResultDiagnosticTips.map((item) => (
                      <div key={item.title} className="rounded-2xl border border-border/60 bg-background/72 p-3.5">
                        <div className="text-sm font-medium text-foreground">{item.title}</div>
                        <p className="mt-1.5 text-xs leading-5 text-muted-foreground">{item.description}</p>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </Panel>
          ) : null}

          {hasResultList ? (
            <div className="space-y-4 animate-in fade-in slide-in-from-bottom-4 motion-reduce:animate-none motion-reduce:transition-none">
              <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
                <div className="space-y-2">
                  <h4 className="text-sm font-semibold text-foreground">召回结果</h4>
                  <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                    {searchQueryForRetrieval && searchQueryForRetrieval !== searchQuery.trim() ? (
                      <span className="inline-flex items-center rounded-full border border-border/60 bg-muted/40 px-2 py-1">
                        实际检索 Query：<span className="ml-1 font-mono text-foreground">{searchQueryForRetrieval}</span>
                      </span>
                    ) : null}
                    {searchHasEvidence !== null ? (
                      <span className="inline-flex items-center rounded-full border border-border/60 bg-muted/40 px-2 py-1 font-mono">
                        has_evidence={String(searchHasEvidence)}
                      </span>
                    ) : null}
                    {searchAbstainTriggered !== null ? (
                      <span className="inline-flex items-center rounded-full border border-border/60 bg-muted/40 px-2 py-1 font-mono">
                        abstain_triggered={String(searchAbstainTriggered)}
                      </span>
                    ) : null}
                    {searchAbstainReason ? (
                      <span className="inline-flex items-center rounded-full border border-border/60 bg-muted/40 px-2 py-1 font-mono">
                        abstain_reason={searchAbstainReason}
                      </span>
                    ) : null}
                  </div>
                </div>

                <div className="flex flex-wrap items-center gap-2">
                  <Button
                    type="button"
                    variant="outline"
                    className="h-8 rounded-full border-border/60 bg-background/60 px-3 text-xs text-muted-foreground hover:bg-background"
                    disabled={isCreatingRegressionCase || selectedEvidenceSet.size === 0 || !selectedDatasetId}
                    onClick={() => detachPromise(handleCreateRegressionCaseFromSelection())}
                    title={selectedDatasetId ? '用选中的证据创建回归用例' : '请先选择数据集'}
                  >
                    {isCreatingRegressionCase ? (
                      <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin motion-reduce:animate-none" />
                    ) : (
                      <TestTube2 className="mr-1.5 h-3.5 w-3.5" />
                    )}
                    创建回归用例
                  </Button>
                  <Button
                    type="button"
                    variant="outline"
                    className="h-8 rounded-full border-border/60 bg-background/60 px-3 text-xs text-muted-foreground hover:bg-background"
                    onClick={handleExportEvidencePack}
                  >
                    <FileStack className="mr-1.5 h-3.5 w-3.5" />
                    导出 Evidence Pack
                  </Button>
                  {selectedEvidenceSet.size > 0 ? (
                    <span className="inline-flex items-center rounded-full border border-border/60 bg-muted/40 px-2 py-1 text-xs tabular-nums text-muted-foreground">
                      已选 {selectedEvidenceSet.size}
                    </span>
                  ) : null}
                  <span className="inline-flex items-center rounded-full border border-border/60 bg-muted/40 px-2 py-1 text-xs tabular-nums text-muted-foreground">
                    Top {searchResults.length}
                  </span>
                </div>
              </div>

              <div className="grid gap-4 2xl:grid-cols-[minmax(0,1fr)_21rem]">
                <div className="space-y-4">
                  <div aria-label="检索结果排名列表" className="space-y-3">
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
                      const matchedTerms = (hit.matched_terms || []).filter(Boolean).slice(0, 4).map(String)
                      const isSelected = activeResult ? toHitKey(activeResult) === toHitKey(hit) : idx === 0
                      const snippet = previewChunkContent(hit.chunk_content)

                      return (
                        <article
                          key={`${String(hit.document_id || '')}:${chunkId}:${role}:${clause}:${pathStr}`}
                          role="listitem"
                          tabIndex={0}
                          className={cn(
                            'group rounded-[22px] border p-4 text-left transition-colors transition-shadow duration-200 motion-reduce:transition-none animate-in fade-in-0 slide-in-from-bottom-1 duration-300 motion-reduce:animate-none',
                            isSelected
                              ? 'border-primary/35 bg-primary/5 shadow-soft'
                              : 'border-border/60 bg-background/62 hover:border-border/80 hover:bg-background/78 hover:shadow-soft/70'
                          )}
                          style={{ animationDelay: `${staggerDelayMs}ms` }}
                          onClick={() => setActiveHit(hit)}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter' || e.key === ' ') {
                              e.preventDefault()
                              setActiveHit(hit)
                            }
                          }}
                        >
                          <div className="flex gap-4">
                            <div className="flex w-12 shrink-0 flex-col items-center gap-2 pt-1">
                              <input
                                type="checkbox"
                                className="h-4 w-4 rounded border-border"
                                aria-label={`Ground truth: #${idx + 1}`}
                                disabled={!chunkId}
                                checked={checked}
                                onClick={(e) => e.stopPropagation()}
                                onChange={() => toggleEvidenceSelection(chunkId)}
                              />
                              <div
                                className={cn(
                                  'grid h-10 w-10 place-items-center rounded-2xl border text-sm font-semibold tabular-nums',
                                  isSelected
                                    ? 'border-primary/30 bg-primary/10 text-primary'
                                    : 'border-border/60 bg-background/70 text-muted-foreground'
                                )}
                              >
                                {idx + 1}
                              </div>
                            </div>

                            <div className="min-w-0 flex-1 space-y-3">
                              <div className="flex items-start justify-between gap-3">
                                <div className="min-w-0">
                                  <div className="flex items-start gap-3">
                                    {hit.has_image && hit.img_url ? (
                                      (() => {
                                        const safeUrl = resolveSafeCitationImageUrl(hit.img_url)
                                        if (!safeUrl) return null
                                        return (
                                          <AuthImageLink
                                            src={safeUrl}
                                            className="relative hidden h-12 w-12 shrink-0 overflow-hidden rounded-xl border border-border/60 bg-muted/20 sm:block"
                                            title="Open image"
                                            onClick={(e) => e.stopPropagation()}
                                          >
                                            <AuthImage
                                              src={safeUrl}
                                              alt="citation thumbnail"
                                              fill
                                              unoptimized
                                              sizes="48px"
                                              className="object-cover"
                                            />
                                          </AuthImageLink>
                                        )
                                      })()
                                    ) : null}

                                    <div className="min-w-0">
                                      <div className="flex flex-wrap items-center gap-2">
                                        <span className="inline-flex items-center gap-1 text-sm font-semibold text-foreground">
                                          <FileIcon className="size-3.5 text-muted-foreground" />
                                          <span className="truncate max-w-[34rem]" title={docName}>
                                            {docName || 'Unknown'}
                                          </span>
                                        </span>
                                        {typeof hit.page_number === 'number' ? (
                                          <span className="rounded-full border border-border/60 bg-muted/30 px-2 py-0.5 text-[11px] tabular-nums text-muted-foreground">
                                            P{hit.page_number}
                                          </span>
                                        ) : null}
                                      </div>

                                      <div className="mt-2 flex flex-wrap items-center gap-1.5 text-[11px]">
                                        <span className="rounded-full border border-border/60 bg-muted/40 px-2 py-1 font-mono text-muted-foreground">
                                          {role}
                                        </span>
                                        {chunkRole ? (
                                          <span className="rounded-full border border-border/60 bg-muted/40 px-2 py-1 font-mono text-muted-foreground">
                                            {chunkRole}
                                          </span>
                                        ) : null}
                                        {clause ? (
                                          <span className="rounded-full border border-primary/20 bg-primary/10 px-2 py-1 font-mono text-primary">
                                            {clause}
                                          </span>
                                        ) : null}
                                        {isExpanded ? (
                                          <span className="rounded-full border border-sky-500/20 bg-sky-500/10 px-2 py-1 font-mono text-sky-700 dark:text-sky-300">
                                            expanded
                                          </span>
                                        ) : null}
                                        {familyHit ? (
                                          <span className="rounded-full bg-warning/10 text-warning border border-warning/20 px-2 py-1 font-mono">
                                            family_hit
                                          </span>
                                        ) : null}
                                      </div>
                                    </div>
                                  </div>
                                </div>

                                <div className="shrink-0 text-right">
                                  <div className="text-[10px] uppercase tracking-[0.18em] text-muted-foreground">final</div>
                                  <div className="mt-1 font-mono text-lg font-semibold tabular-nums text-primary">
                                    {formatScore(hit.relevance_score, 2)}
                                  </div>
                                </div>
                              </div>

                              <p className="line-clamp-4 text-sm leading-6 text-foreground/90">{snippet}</p>

                              <div className="flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
                                {pathStr ? (
                                  <span className="inline-flex max-w-full items-center rounded-full border border-border/60 bg-muted/35 px-2 py-1">
                                    <span className="truncate" title={pathStr}>{pathStr}</span>
                                  </span>
                                ) : null}
                                {chunkId ? (
                                  <span className="inline-flex items-center rounded-full border border-border/60 bg-muted/35 px-2 py-1 font-mono">
                                    {shortId(chunkId)}
                                  </span>
                                ) : null}
                                {matchedTerms.map((term) => (
                                  <span key={term} className="inline-flex items-center rounded-full border border-border/60 bg-background/80 px-2 py-1">
                                    {term}
                                  </span>
                                ))}
                              </div>

                              <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                                <div className="rounded-xl border border-border/60 bg-background/70 p-2.5">
                                  <div className="text-[10px] uppercase tracking-[0.14em] text-muted-foreground">final</div>
                                  <div className="mt-1 font-mono text-sm tabular-nums text-foreground">{formatScore(hit.relevance_score, 2)}</div>
                                </div>
                                <div className="rounded-xl border border-border/60 bg-background/70 p-2.5">
                                  <div className="text-[10px] uppercase tracking-[0.14em] text-muted-foreground">vec</div>
                                  <div className="mt-1 font-mono text-sm tabular-nums text-foreground">{formatScore(hit.vector_score)}</div>
                                </div>
                                <div className="rounded-xl border border-border/60 bg-background/70 p-2.5">
                                  <div className="text-[10px] uppercase tracking-[0.14em] text-muted-foreground">bm25</div>
                                  <div className="mt-1 font-mono text-sm tabular-nums text-foreground">{formatScore(hit.bm25_score)}</div>
                                </div>
                                <div className="rounded-xl border border-border/60 bg-background/70 p-2.5">
                                  <div className="text-[10px] uppercase tracking-[0.14em] text-muted-foreground">rerank</div>
                                  <div className="mt-1 font-mono text-sm tabular-nums text-foreground">{formatScore(hit.rerank_score)}</div>
                                </div>
                              </div>

                              <div className="flex flex-wrap items-center justify-between gap-3 pt-1">
                                <div className="text-[11px] text-muted-foreground">
                                  {isSelected ? '当前选中，右侧可查看摘要详情。' : '点击卡片可切换右侧详情。'}
                                </div>

                                <div className="inline-flex items-center gap-1">
                                  <IconButton
                                    label="在文档查看器中打开"
                                    variant="ghost"
                                    className="h-8 w-8 text-muted-foreground hover:text-primary hover:bg-muted"
                                    onClick={(e) => {
                                      e.stopPropagation()
                                      handleOpenHitInDocumentViewer(hit)
                                    }}
                                    onMouseEnter={() => handlePrefetchHitDocument(hit)}
                                    onFocus={() => handlePrefetchHitDocument(hit)}
                                    disabled={!documentId}
                                  >
                                    <ExternalLink className="size-4" />
                                  </IconButton>
                                  <IconButton
                                    label="复制 chunk_id"
                                    variant="ghost"
                                    className="h-8 w-8 text-muted-foreground hover:text-primary hover:bg-muted"
                                    onClick={(e) => {
                                      e.stopPropagation()
                                      detachPromise(copyToClipboard(chunkId, 'chunk_id'))
                                    }}
                                    disabled={!chunkId}
                                  >
                                    <Copy className="size-4" />
                                  </IconButton>
                                  <Button
                                    type="button"
                                    variant="outline"
                                    className="h-8 rounded-lg px-3"
                                    onClick={(e) => {
                                      e.stopPropagation()
                                      openDetails(hit)
                                    }}
                                  >
                                    详情
                                  </Button>
                                </div>
                              </div>
                            </div>
                          </div>
                        </article>
                      )
                    })}
                  </div>

                  <details className="rounded-2xl border border-border/60 bg-background/60 p-4">
                    <summary className="cursor-pointer select-none text-xs font-semibold text-foreground inline-flex items-center gap-2">
                      <Zap className="size-4 text-primary" />
                      检索 Debug（RRF / trimming / per-query metrics）
                    </summary>
                    <div className="mt-3 space-y-3">
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
                                {mainRetrieverDebug ? String(Boolean(mainRetrieverDebug.overfetch_enabled)) : '—'}
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
                                    <div className="mt-1 font-mono tabular-nums text-foreground/90">{formatCount(fusion.selected_prefix)}</div>
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

                            const enrich = isRecord(dbg.enrich_pass2)
                              ? dbg.enrich_pass2
                              : isRecord(dbg.enrich_pass1)
                                ? dbg.enrich_pass1
                                : null

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
                              (toInt(div?.max_chunks_per_doc) ?? 0) > 0 ||
                                (toInt(div?.max_chunks_per_page) ?? 0) > 0 ||
                                (toInt(div?.min_distinct_docs) ?? 0) > 0
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
                                <tr
                                  key={`${String(item.kind || 'query')}:${String(item.query_chars ?? '')}:${String(item.elapsed_sec ?? '')}`}
                                  className="border-b border-border/40 align-top"
                                >
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

                <aside className="hidden 2xl:block">
                  <div className="sticky top-4 space-y-4 rounded-[22px] border border-border/60 bg-background/70 p-4 shadow-soft">
                    <div className="border-b border-border/60 pb-3">
                      <div className="text-xs font-semibold uppercase tracking-[0.16em] text-muted-foreground">
                        Selected Hit
                      </div>
                      <div className="mt-2 text-base font-semibold text-foreground">
                        {activeResult?.document_name || '未选择结果'}
                      </div>
                      <div className="mt-1 text-xs text-muted-foreground">
                        这里展示当前命中的摘要、分数和关键元数据；完整深度信息仍可通过“详情”打开。
                      </div>
                    </div>

                    {activeResult ? (
                      <>
                        <div className="grid grid-cols-2 gap-2">
                          <div className="rounded-xl border border-border/60 bg-background/70 p-2.5">
                            <div className="text-[10px] uppercase tracking-[0.14em] text-muted-foreground">final</div>
                            <div className="mt-1 font-mono text-sm tabular-nums text-foreground">{formatScore(activeResult.relevance_score, 2)}</div>
                          </div>
                          <div className="rounded-xl border border-border/60 bg-background/70 p-2.5">
                            <div className="text-[10px] uppercase tracking-[0.14em] text-muted-foreground">page</div>
                            <div className="mt-1 font-mono text-sm tabular-nums text-foreground">
                              {typeof activeResult.page_number === 'number' ? activeResult.page_number : '—'}
                            </div>
                          </div>
                          <div className="rounded-xl border border-border/60 bg-background/70 p-2.5">
                            <div className="text-[10px] uppercase tracking-[0.14em] text-muted-foreground">vec</div>
                            <div className="mt-1 font-mono text-sm tabular-nums text-foreground">{formatScore(activeResult.vector_score)}</div>
                          </div>
                          <div className="rounded-xl border border-border/60 bg-background/70 p-2.5">
                            <div className="text-[10px] uppercase tracking-[0.14em] text-muted-foreground">rerank</div>
                            <div className="mt-1 font-mono text-sm tabular-nums text-foreground">{formatScore(activeResult.rerank_score)}</div>
                          </div>
                        </div>

                        <div className="space-y-2">
                          <div className="text-xs font-semibold text-foreground">Snippet</div>
                          <div className="rounded-xl border border-border/60 bg-background/70 p-3 text-sm leading-6 text-foreground/90">
                            {previewChunkContent(activeResult.chunk_content, 560)}
                          </div>
                        </div>

                        <div className="space-y-2">
                          <div className="text-xs font-semibold text-foreground">Metadata</div>
                          <div className="rounded-xl border border-border/60 bg-background/70 p-3 text-xs text-muted-foreground space-y-2">
                            <div>
                              role: <span className="font-mono text-foreground">{String(activeResult.retrieval_role || 'main')}</span>
                            </div>
                            <div>
                              chunk_id:{' '}
                              <span className="font-mono text-foreground">
                                {activeResult.chunk_id ? shortId(String(activeResult.chunk_id), { head: 12, tail: 6 }) : '—'}
                              </span>
                            </div>
                            <div>
                              path: <span className="text-foreground">{String(activeResult.policy_path_str || '—')}</span>
                            </div>
                          </div>
                        </div>

                        {activeResultMatchedTerms.length ? (
                          <div className="space-y-2">
                            <div className="text-xs font-semibold text-foreground">Matched Terms</div>
                            <div className="flex flex-wrap gap-2">
                              {activeResultMatchedTerms.slice(0, 8).map((term) => (
                                <span
                                  key={term}
                                  className="inline-flex items-center rounded-full border border-border/60 bg-background/80 px-2 py-1 text-[11px] text-muted-foreground"
                                >
                                  {term}
                                </span>
                              ))}
                            </div>
                          </div>
                        ) : null}

                        <div className="flex flex-wrap items-center gap-2">
                          <Button
                            type="button"
                            variant="outline"
                            className="h-8 rounded-full px-3 gap-2"
                            onClick={() => handleOpenHitInDocumentViewer(activeResult)}
                          >
                            <ExternalLink className="size-4" />
                            打开文档
                          </Button>
                          <Button
                            type="button"
                            variant="outline"
                            className="h-8 rounded-full px-3 gap-2"
                            onClick={() => openDetails(activeResult)}
                          >
                            <Copy className="size-4" />
                            深入详情
                          </Button>
                        </div>
                      </>
                    ) : (
                      <div className="rounded-xl border border-dashed border-border/60 bg-background/40 p-4 text-sm text-muted-foreground">
                        选择一条召回结果后，这里会展示摘要详情。
                      </div>
                    )}
                  </div>
                </aside>
              </div>
            </div>
          ) : null}
        </div>
      </div>

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
                      <Copy className="size-4" />
                      复制 chunk_id
                    </Button>
                    <Button
                      type="button"
                      variant="outline"
                      className="h-8 rounded-full px-3 gap-2"
                      onClick={() => detachPromise(copyToClipboard(String(activeHit.doc_pipeline_key || ''), 'doc_pipeline_key'))}
                      disabled={!activeHit.doc_pipeline_key}
                    >
                      <Copy className="size-4" />
                      复制 doc_pipeline_key
                    </Button>
                    <Button
                      type="button"
                      variant="outline"
                      className="h-8 rounded-full px-3 gap-2"
                      onClick={() => detachPromise(copyToClipboard((activeMatchedTerms || []).join(' '), 'matched_terms'))}
                      disabled={!activeMatchedTerms.length}
                    >
                      <Copy className="size-4" />
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
                          <Copy className="size-4" />
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
                          <Copy className="size-4" />
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
