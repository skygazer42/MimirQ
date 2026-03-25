'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { toast } from 'sonner'
import { Loader2, Plus } from 'lucide-react'

import type {
  Citation,
  Dataset,
  EvidenceHardcaseDiscovery,
  EvidenceItem,
  EvidenceItemCreate,
  EvidenceItemStatus,
  EvidenceReferenceDriftDetail,
  EvidenceRetrieveResponse,
  EvidenceSuite,
  EvidenceSuiteDashboard,
  JsonObject,
  ReferenceSource,
} from '@/types'
import { datasetApi, evidenceApi, feedbackApi, ragApi } from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'
import { buildWhyMissedReport } from '@/lib/evidence-why-missed'
import { extractEvidenceNeedles, rankEvidenceCitations } from '@/lib/evidence-suggestions'
import { coerceOneOf } from '@/lib/one-of'
import { detachPromise } from '@/lib/utils'

import { Button } from '@/components/ui/button'
import { CreateItemDialog } from '@/components/evidence/create-item-dialog'
import { HardcaseCandidatesDialog } from '@/components/evidence/hardcase-candidates-dialog'
import { ItemDetailPanel } from '@/components/evidence/item-detail-panel'
import { ItemListPanel } from '@/components/evidence/item-list-panel'
import { SuiteListPanel } from '@/components/evidence/suite-list-panel'
import { SuiteDashboardDialog } from '@/components/evidence/suite-dashboard-dialog'
import { WhyMissedDialog } from '@/components/evidence/why-missed-dialog'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { TagInput } from '@/components/ui/tag-input'
import { Textarea } from '@/components/ui/textarea'

type RetrievalProfile = 'recall50' | 'coverage80' | 'recall20'

type JsonRecord = JsonObject

type EvidenceRetrieveResult = Omit<EvidenceRetrieveResponse, 'citations'> & {
  citations?: Citation[]
}

type EvidenceImportPack = JsonObject & {
  citations?: Citation[]
  selected_chunk_ids?: string[]
  retrieval_profile?: string | null
  version?: string | number | null
}

const RETRIEVAL_PROFILE_VALUES = ['recall50', 'coverage80', 'recall20'] as const

function isRecord(value: unknown): value is JsonRecord {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

function toOptionalString(value: unknown): string | undefined {
  return typeof value === 'string' && value.trim() ? value : undefined
}

function toOptionalNumber(value: unknown): number | undefined {
  const next = typeof value === 'number' ? value : Number(value)
  return Number.isFinite(next) ? next : undefined
}

function toStringList(value: unknown): string[] | undefined {
  if (!Array.isArray(value)) return undefined
  const items = value.map((item) => String(item || '').trim()).filter(Boolean)
  return items.length ? items : undefined
}

function toCitation(value: unknown): Citation | null {
  if (!isRecord(value)) return null
  const document_id = toOptionalString(value.document_id) ?? ''
  const document_name = toOptionalString(value.document_name) ?? ''
  const chunk_content = typeof value.chunk_content === 'string' ? value.chunk_content : ''
  const relevance_score = toOptionalNumber(value.relevance_score) ?? 0

  if (!document_id || !document_name) return null

  const citation: Citation = {
    document_id,
    document_name,
    chunk_content,
    relevance_score,
  }

  citation.chunk_id = toOptionalString(value.chunk_id)
  citation.page_number = toOptionalNumber(value.page_number)
  citation.chunk_index = toOptionalNumber(value.chunk_index)
  citation.start_char = toOptionalNumber(value.start_char)
  citation.end_char = toOptionalNumber(value.end_char)
  citation.header_path = toOptionalString(value.header_path)
  citation.doc_pipeline_key = toOptionalString(value.doc_pipeline_key)
  citation.pipeline_hash = toOptionalString(value.pipeline_hash)
  citation.hit_type = toOptionalString(value.hit_type)
  citation.retrieval_score = toOptionalNumber(value.retrieval_score)
  citation.rerank_score = toOptionalNumber(value.rerank_score)
  citation.vector_score = toOptionalNumber(value.vector_score)
  citation.bm25_score = toOptionalNumber(value.bm25_score)
  citation.keyword_score = toOptionalNumber(value.keyword_score)
  citation.matched_terms = toStringList(value.matched_terms)

  return citation
}

function normalizeCitations(value: unknown): Citation[] {
  if (!Array.isArray(value)) return EMPTY_CITATIONS
  const citations = value.map(toCitation).filter((citation): citation is Citation => citation !== null)
  return citations.length ? citations : EMPTY_CITATIONS
}

function normalizeRetrieveResult(value: EvidenceRetrieveResponse | null | undefined): EvidenceRetrieveResult | null {
  if (!value) return null
  return {
    ...value,
    citations: normalizeCitations(value.citations),
  }
}

function normalizeImportPack(value: unknown): EvidenceImportPack | null {
  if (!isRecord(value)) return null
  return {
    ...value,
    citations: normalizeCitations(value.citations),
    selected_chunk_ids: toStringList(value.selected_chunk_ids),
    retrieval_profile: typeof value.retrieval_profile === 'string' ? value.retrieval_profile : null,
    version: typeof value.version === 'string' || typeof value.version === 'number' ? value.version : null,
  }
}

function getErrorMessage(error: unknown): string {
  if (error instanceof Error && error.message) return error.message
  const text = String(error || '').trim()
  return text || 'unknown'
}

function asDatasetId(raw: unknown): string | null {
  if (typeof raw === 'string' && raw.trim()) return raw
  return null
}

function downloadJson(filename: string, data: unknown) {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  try {
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    a.click()
  } finally {
    URL.revokeObjectURL(url)
  }
}

function downloadBlob(filename: string, blob: Blob) {
  const url = URL.createObjectURL(blob)
  try {
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    a.click()
  } finally {
    URL.revokeObjectURL(url)
  }
}

function evidenceStatusBadgeVariant(st: EvidenceItemStatus): 'outline' | 'secondary' | 'soft' | 'destructive' {
  if (st === 'approved') return 'soft'
  if (st === 'reviewed') return 'secondary'
  if (st === 'archived') return 'outline'
  return 'outline'
}

function buildReferenceSources(citations: Citation[], selectedChunkIds: Set<string>): ReferenceSource[] {
  const out: ReferenceSource[] = []
  for (const c of citations || []) {
    const chunkId = String(c.chunk_id || '')
    if (!chunkId || !selectedChunkIds.has(chunkId)) continue
    const docId = String(c.document_id || '')
    if (!docId) continue
    out.push({
      document_id: docId,
      chunk_id: chunkId,
      chunk_index: typeof c.chunk_index === 'number' ? c.chunk_index : undefined,
      page_number: typeof c.page_number === 'number' ? c.page_number : undefined,
      start_char: typeof c.start_char === 'number' ? c.start_char : undefined,
      end_char: typeof c.end_char === 'number' ? c.end_char : undefined,
      doc_pipeline_key: c.doc_pipeline_key || undefined,
      pipeline_hash: c.pipeline_hash || undefined,
      quote: (c.chunk_content || '').slice(0, 2000) || undefined,
      label: c.header_path || c.document_name || undefined,
    })
  }
  return out
}

function safeIsoForFilename(ts: string) {
  return (ts || new Date().toISOString()).replaceAll(/[:.]/g, '-')
}

const EMPTY_CITATIONS: Citation[] = []

export function EvidenceSuiteWorkbench({ datasetId: datasetIdRaw }: Readonly<{ datasetId: string }>) {
  const datasetId = asDatasetId(datasetIdRaw)

  const [dataset, setDataset] = useState<Dataset | null>(null)
  const [datasetLoading, setDatasetLoading] = useState(false)

  const [suites, setSuites] = useState<EvidenceSuite[]>([])
  const [suitesLoading, setSuitesLoading] = useState(false)
  const [suitesError, setSuitesError] = useState<string | null>(null)
  const [suiteQuery, setSuiteQuery] = useState('')
  const [includeArchivedSuites, setIncludeArchivedSuites] = useState(false)

  const [selectedSuiteId, setSelectedSuiteId] = useState<string>('')
  const selectedSuite = useMemo(() => suites.find((s) => s.id === selectedSuiteId) || null, [selectedSuiteId, suites])

  const [items, setItems] = useState<EvidenceItem[]>([])
  const [itemsLoading, setItemsLoading] = useState(false)
  const [itemsError, setItemsError] = useState<string | null>(null)
  const [itemQuery, setItemQuery] = useState('')
  const [statusFilter, setStatusFilter] = useState<string>('__all__')

  const [selectedItemId, setSelectedItemId] = useState<string>('')
  const selectedItem = useMemo(() => items.find((it) => it.id === selectedItemId) || null, [items, selectedItemId])

  // "Why missed?" workbench (per EvidenceItem) - drift + live retrieval comparison.
  const [whyMissedOpen, setWhyMissedOpen] = useState(false)
  const [whyMissedProfile, setWhyMissedProfile] = useState<RetrievalProfile>('recall50')
  const [whyMissedRanRetrieve, setWhyMissedRanRetrieve] = useState(false)
  const [whyMissedRetrieving, setWhyMissedRetrieving] = useState(false)
  const [whyMissedError, setWhyMissedError] = useState<string | null>(null)
  const [whyMissedCitations, setWhyMissedCitations] = useState<Citation[]>([])
  const [whyMissedDriftLoading, setWhyMissedDriftLoading] = useState(false)
  const [whyMissedDriftError, setWhyMissedDriftError] = useState<string | null>(null)
  const [whyMissedDriftedRefs, setWhyMissedDriftedRefs] = useState<EvidenceReferenceDriftDetail[]>([])

  // Suite dashboard
  const [dashboardOpen, setDashboardOpen] = useState(false)
  const [dashboardLoading, setDashboardLoading] = useState(false)
  const [dashboardError, setDashboardError] = useState<string | null>(null)
  const [dashboard, setDashboard] = useState<EvidenceSuiteDashboard | null>(null)
  const [dashboardIncludeArchived, setDashboardIncludeArchived] = useState(false)

  // Hardcase discovery (suite-level; PII-safe)
  const [hardcaseOpen, setHardcaseOpen] = useState(false)
  const [hardcaseLoading, setHardcaseLoading] = useState(false)
  const [hardcaseError, setHardcaseError] = useState<string | null>(null)
  const [hardcaseRes, setHardcaseRes] = useState<EvidenceHardcaseDiscovery | null>(null)
  const [hardcaseMaxRating, setHardcaseMaxRating] = useState<number>(2)
  const [hardcaseIncludeExisting, setHardcaseIncludeExisting] = useState(false)
  const [hardcaseMaxCandidates, setHardcaseMaxCandidates] = useState<number>(50)
  const [hardcaseTags, setHardcaseTags] = useState<string[]>(['hardcase'])
  const [convertingFeedbackId, setConvertingFeedbackId] = useState<string>('')

  // Create suite dialog
  const [createSuiteOpen, setCreateSuiteOpen] = useState(false)
  const [suiteName, setSuiteName] = useState('')
  const [suiteDesc, setSuiteDesc] = useState('')
  const [suiteTags, setSuiteTags] = useState<string[]>([])
  const [creatingSuite, setCreatingSuite] = useState(false)

  // Create item dialog
  const [createItemOpen, setCreateItemOpen] = useState(false)
  const [createItemTab, setCreateItemTab] = useState<'retrieve' | 'import'>('retrieve')

  const [newQuery, setNewQuery] = useState('')
  const [newExpected, setNewExpected] = useState('')
  const [newNotes, setNewNotes] = useState('')
  const [profile, setProfile] = useState<RetrievalProfile>('recall50')

  const [retrieving, setRetrieving] = useState(false)
  const [retrieveError, setRetrieveError] = useState<string | null>(null)
  const [retrieveRes, setRetrieveRes] = useState<EvidenceRetrieveResult | null>(null)
  const [selectedChunkIds, setSelectedChunkIds] = useState<string[]>([])

  const [importPack, setImportPack] = useState<EvidenceImportPack | null>(null)
  const [importError, setImportError] = useState<string | null>(null)
  const [importSelectedChunkIds, setImportSelectedChunkIds] = useState<string[]>([])
  const fileInputRef = useRef<HTMLInputElement | null>(null)

  const [importingQAFaq, setImportingQAFaq] = useState(false)
  const qaFaqInputRef = useRef<HTMLInputElement | null>(null)

  const [creatingItem, setCreatingItem] = useState(false)

  const filteredSuites = useMemo(() => {
    const q = suiteQuery.trim().toLowerCase()
    const base = suites || []
    if (!q) return base
    return base.filter((s) => {
      const hay = `${s.name || ''} ${(s.description || '')} ${(s.tags || []).join(' ')}`.toLowerCase()
      return hay.includes(q)
    })
  }, [suiteQuery, suites])

  const filteredItems = useMemo(() => {
    const q = itemQuery.trim().toLowerCase()
    const st = statusFilter
    return (items || [])
      .filter((it) => (st === '__all__' ? true : String(it.status || '').toLowerCase() === st))
      .filter((it) => {
        if (!q) return true
        const hay = `${it.query || ''} ${(it.notes || '')}`.toLowerCase()
        return hay.includes(q)
      })
  }, [items, itemQuery, statusFilter])

  const loadDataset = useCallback(async () => {
    if (!datasetId) return
    setDatasetLoading(true)
    try {
      const ds = await datasetApi.get(datasetId)
      setDataset(ds)
    } catch (error: unknown) {
      toast.error(formatApiError(error, '加载数据集失败'))
    } finally {
      setDatasetLoading(false)
    }
  }, [datasetId])

  const loadSuites = useCallback(async () => {
    if (!datasetId) return
    setSuitesLoading(true)
    setSuitesError(null)
    try {
      const res = await evidenceApi.listSuites({
        dataset_id: datasetId,
        include_archived: includeArchivedSuites,
        limit: 200,
      })
      const next = res.items || []
      setSuites(next)
      if (!selectedSuiteId && next[0]?.id) {
        setSelectedSuiteId(String(next[0].id))
      } else if (selectedSuiteId && !next.some((s) => s.id === selectedSuiteId)) {
        setSelectedSuiteId(next[0]?.id ? String(next[0].id) : '')
      }
    } catch (error: unknown) {
      setSuitesError(formatApiError(error, '加载 Evidence Suites 失败'))
    } finally {
      setSuitesLoading(false)
    }
  }, [datasetId, includeArchivedSuites, selectedSuiteId])

  const loadItems = useCallback(async () => {
    if (!selectedSuiteId) {
      setItems([])
      setItemsError(null)
      return
    }
    setItemsLoading(true)
    setItemsError(null)
    try {
      const res = await evidenceApi.listItems(selectedSuiteId, {
        limit: 200,
        status: statusFilter === '__all__' ? undefined : statusFilter,
      })
      const next = res.items || []
      setItems(next)
      if (selectedItemId && !next.some((it) => it.id === selectedItemId)) {
        setSelectedItemId('')
      }
    } catch (error: unknown) {
      setItemsError(formatApiError(error, '加载 Evidence Items 失败'))
    } finally {
      setItemsLoading(false)
    }
  }, [selectedItemId, selectedSuiteId, statusFilter])

  const loadDashboard = useCallback(async () => {
    if (!selectedSuiteId) {
      setDashboard(null)
      setDashboardError(null)
      return
    }
    setDashboardLoading(true)
    setDashboardError(null)
    try {
      const res = await evidenceApi.getSuiteDashboard(selectedSuiteId, {
        include_archived_items: dashboardIncludeArchived,
      })
      setDashboard(res)
    } catch (error: unknown) {
      setDashboardError(formatApiError(error, '加载 Dashboard 失败'))
    } finally {
      setDashboardLoading(false)
    }
  }, [dashboardIncludeArchived, selectedSuiteId])

  const loadHardcases = useCallback(async () => {
    if (!selectedSuiteId) {
      setHardcaseRes(null)
      setHardcaseError(null)
      return
    }
    setHardcaseLoading(true)
    setHardcaseError(null)
    try {
      const res = await evidenceApi.getSuiteHardcaseCandidates(selectedSuiteId, {
        max_rating: hardcaseMaxRating,
        include_existing: hardcaseIncludeExisting,
        max_candidates: hardcaseMaxCandidates,
      })
      setHardcaseRes(res)
    } catch (error: unknown) {
      setHardcaseError(formatApiError(error, '加载 Hardcase candidates 失败'))
      setHardcaseRes(null)
    } finally {
      setHardcaseLoading(false)
    }
  }, [hardcaseIncludeExisting, hardcaseMaxCandidates, hardcaseMaxRating, selectedSuiteId])

  const copyText = useCallback(async (label: string, text: string) => {
    const value = String(text || '').trim()
    if (!value) return
    try {
      await navigator.clipboard.writeText(value)
      toast.success(`${label} 已复制`)
    } catch (error: unknown) {
      toast.error(formatApiError(error, '复制失败'))
    }
  }, [])

  const handleConvertFeedbackToEvidence = useCallback(async (feedbackId: string, questionHash?: string) => {
    if (!selectedSuiteId) return
    const fid = String(feedbackId || '').trim()
    if (!fid) return
    setConvertingFeedbackId(fid)
    try {
      const created = await feedbackApi.toEvidenceItem(fid, {
        suite_id: selectedSuiteId,
        tags: hardcaseTags,
        extra: { source: 'hardcase_discovery', question_hash: questionHash || undefined },
      })
      const createdId = String(created?.id || '').trim()
      toast.success('已创建 draft EvidenceItem')
      await loadItems()
      await loadHardcases()
      if (createdId) {
        setSelectedItemId(createdId)
      }
    } catch (error: unknown) {
      toast.error(formatApiError(error, '转为 EvidenceItem 失败'))
    } finally {
      setConvertingFeedbackId('')
    }
  }, [hardcaseTags, loadHardcases, loadItems, selectedSuiteId])

  useEffect(() => {
    detachPromise(loadDataset())
  }, [loadDataset])

  useEffect(() => {
    detachPromise(loadSuites())
  }, [loadSuites])

  useEffect(() => {
    detachPromise(loadItems())
  }, [loadItems])

  useEffect(() => {
    if (!dashboardOpen) return
    detachPromise(loadDashboard())
  }, [dashboardOpen, loadDashboard])

  useEffect(() => {
    if (!hardcaseOpen) return
    detachPromise(loadHardcases())
  }, [hardcaseOpen, loadHardcases])

  const resetCreateSuiteForm = useCallback(() => {
    setSuiteName('')
    setSuiteDesc('')
    setSuiteTags([])
  }, [])

  const openCreateSuite = useCallback(() => {
    resetCreateSuiteForm()
    setCreateSuiteOpen(true)
  }, [resetCreateSuiteForm])

  const handleCreateSuite = useCallback(async () => {
    if (!datasetId) return
    const name = suiteName.trim()
    if (!name) return
    setCreatingSuite(true)
    try {
      const suite = await evidenceApi.createSuite({
        dataset_id: datasetId,
        name,
        description: suiteDesc.trim() || null,
        tags: suiteTags || [],
        config: {},
      })
      toast.success('已创建 Evidence Suite')
      setCreateSuiteOpen(false)
      setSuites((prev) => [suite, ...(prev || [])])
      setSelectedSuiteId(String(suite.id))
    } catch (error: unknown) {
      toast.error(formatApiError(error, '创建 Suite 失败'))
    } finally {
      setCreatingSuite(false)
    }
  }, [datasetId, suiteDesc, suiteName, suiteTags])

  const openCreateItem = useCallback(() => {
    setCreateItemTab('retrieve')
    setNewQuery('')
    setNewExpected('')
    setNewNotes('')
    setProfile('recall50')
    setRetrieveError(null)
    setRetrieveRes(null)
    setSelectedChunkIds([])
    setImportPack(null)
    setImportError(null)
    setImportSelectedChunkIds([])
    setCreateItemOpen(true)
  }, [])

  const runRetrieve = useCallback(async () => {
    if (!datasetId) return
    const q = newQuery.trim()
    if (!q) return

    setRetrieving(true)
    setRetrieveError(null)
    setRetrieveRes(null)
    setSelectedChunkIds([])
    try {
      const res = await ragApi.retrieveEvidence({
        query: q,
        history: [],
        dataset_id: datasetId,
        document_ids: [],
        rag_config: {
          retrieval_profile: profile,
          max_tokens: 2000,
          retrieval_mode: 'hybrid',
          alpha: 0.6,
          enable_weight_rerank: true,
          vector_weight: 0.6,
          keyword_weight: 0.4,
          use_graph: false,
          visible_evidence_only: false,
        },
      })
      const normalized = normalizeRetrieveResult(res)
      setRetrieveRes(normalized)
      if (res?.has_evidence) toast.success('找到证据')
      else if (res?.abstain_triggered) toast.warning(`已触发 abstain：${res?.abstain_reason || 'unknown'}`)
      else toast.message('未找到证据')
    } catch (error: unknown) {
      setRetrieveError(formatApiError(error, '检索失败'))
    } finally {
      setRetrieving(false)
    }
  }, [datasetId, newQuery, profile])

  const toggleChunkSelection = useCallback((chunkId: string, mode: 'retrieve' | 'import') => {
    if (!chunkId) return
    if (mode === 'retrieve') {
      setSelectedChunkIds((prev) => {
        const set = new Set(prev || [])
        if (set.has(chunkId)) set.delete(chunkId)
        else set.add(chunkId)
        return Array.from(set)
      })
      return
    }
    setImportSelectedChunkIds((prev) => {
      const set = new Set(prev || [])
      if (set.has(chunkId)) set.delete(chunkId)
      else set.add(chunkId)
      return Array.from(set)
    })
  }, [])

  const handlePickPackFile = useCallback(async (file: File) => {
    setImportError(null)
    setImportPack(null)
    setImportSelectedChunkIds([])
    try {
      const text = await file.text()
      const parsed = JSON.parse(text) as unknown
      const payload = normalizeImportPack(parsed)
      if (!payload) {
        throw new Error('invalid evidence pack')
      }
      setImportPack(payload)
      setImportSelectedChunkIds(payload.selected_chunk_ids ?? [])
    } catch (error: unknown) {
      setImportError(`解析失败：${getErrorMessage(error)}`)
    }
  }, [])

  const handleCreateItem = useCallback(async () => {
    if (!datasetId) return
    if (!selectedSuiteId) return
    const suite = selectedSuite
    if (!suite?.id) return

    const query = newQuery.trim()
    if (!query) {
      return
    }

    let citations: Citation[] = []
    let selected: string[] = []
    let retrievalSnapshot: JsonObject | null = null
    let ragSnapshot: JsonObject | null = null

    if (createItemTab === 'retrieve') {
      citations = retrieveRes?.citations || []
      selected = selectedChunkIds || []
      retrievalSnapshot = {
        ...(retrieveRes ?? {}),
        selected_chunk_ids: selected,
        created_from: 'retrieve',
      }
      ragSnapshot = { retrieval_profile: profile, created_from: 'retrieve' }
    } else {
      citations = importPack?.citations || []
      selected = importSelectedChunkIds || []
      retrievalSnapshot = {
        ...importPack,
        selected_chunk_ids: selected,
        created_from: 'evidence_pack',
      }
      ragSnapshot = {
        retrieval_profile: String(importPack?.retrieval_profile || profile || ''),
        created_from: 'evidence_pack',
      }
    }

    const refs = buildReferenceSources(citations, new Set(selected))
    if (!refs.length) {
      toast.error('请至少选择 1 条引用（chunk）')
      return
    }

    const body: EvidenceItemCreate = {
      suite_id: String(suite.id),
      dataset_id: datasetId,
      query,
      expected_answer: newExpected.trim() || null,
      reference_sources: refs,
      retrieval_snapshot: retrievalSnapshot || {},
      rag_config_snapshot: ragSnapshot || {},
      notes: newNotes.trim() || null,
    }

    setCreatingItem(true)
    try {
      const created = await evidenceApi.createItem(String(suite.id), body)
      toast.success('已创建 Evidence Item（draft）')
      setCreateItemOpen(false)
      setItems((prev) => [created, ...(prev || [])])
      setSelectedItemId(String(created.id))
      // Refresh suite counts (best-effort)
      detachPromise(loadSuites())
    } catch (error: unknown) {
      toast.error(formatApiError(error, '创建 Evidence Item 失败'))
    } finally {
      setCreatingItem(false)
    }
  }, [
    createItemTab,
    datasetId,
    importPack,
    importSelectedChunkIds,
    loadSuites,
    newExpected,
    newNotes,
    newQuery,
    profile,
    retrieveRes,
    selectedChunkIds,
    selectedSuite,
    selectedSuiteId,
  ])

  const handleImportQAFaq = useCallback(
    async (file: File) => {
      if (!selectedSuite?.id) return

      const name = String(file?.name || '').toLowerCase()
      if (!name.endsWith('.csv') && !name.endsWith('.jsonl')) {
        toast.error('只支持导入 .csv / .jsonl')
        return
      }

      setImportingQAFaq(true)
      try {
        const res = await evidenceApi.importItems(String(selectedSuite.id), file)
        toast.success(
          `导入完成：parsed=${res.parsed} created=${res.created} skipped=${res.skipped} errors=${(res.errors || []).length}`
        )
        detachPromise(loadItems())
        detachPromise(loadSuites())
      } catch (error: unknown) {
        toast.error(formatApiError(error, '导入失败'))
      } finally {
        setImportingQAFaq(false)
        if (qaFaqInputRef.current) qaFaqInputRef.current.value = ''
      }
    },
    [loadItems, loadSuites, selectedSuite]
  )

  const handleExportSuite = useCallback(async () => {
    if (!selectedSuite?.id) return
    try {
      const res = await evidenceApi.exportSuite(String(selectedSuite.id), { include_archived_items: false })
      const safeTs = safeIsoForFilename(res?.exported_at)
      const name = (selectedSuite.name || 'evidence-suite').replaceAll(/[\\/:*?"<>|]+/g, '_').slice(0, 64)
      downloadJson(`${name}.${safeTs}.json`, res)
      toast.success('已导出 Evidence Suite')
    } catch (error: unknown) {
      toast.error(formatApiError(error, '导出失败'))
    }
  }, [selectedSuite])

  const handleExportLtrTraining = useCallback(async () => {
    if (!selectedSuite?.id) return
    try {
      const blob = await evidenceApi.exportSuiteLtrTrainingBundleZip(String(selectedSuite.id), {
        include_archived_items: false,
        max_items: 2000,
      })
      const safeTs = safeIsoForFilename(new Date().toISOString())
      const name = (selectedSuite.name || 'evidence-suite').replaceAll(/[\\/:*?"<>|]+/g, '_').slice(0, 64)
      downloadBlob(`${name}.${safeTs}.ltr_training.zip`, blob)
      toast.success('已导出 LTR 训练数据')
    } catch (error: unknown) {
      toast.error(formatApiError(error, '导出 LTR 训练数据失败'))
    }
  }, [selectedSuite])

  const handleSyncSuite = useCallback(async () => {
    if (!selectedSuite?.id) return
    try {
      const res = await evidenceApi.syncSuiteToRegression(String(selectedSuite.id))
      const errors = Array.isArray(res?.errors) ? res.errors : []
      if (errors.length) {
        toast.warning(`同步完成：created=${res.created} updated=${res.updated} skipped=${res.skipped} errors=${errors.length}`)
      } else {
        toast.success(`同步完成：created=${res.created} updated=${res.updated} skipped=${res.skipped}`)
      }
      detachPromise(loadItems())
      detachPromise(loadSuites())
    } catch (error: unknown) {
      toast.error(formatApiError(error, '同步失败'))
    }
  }, [loadItems, loadSuites, selectedSuite])

  const handleArchiveItem = useCallback(async (itemId: string) => {
    if (!itemId) return
    try {
      const updated = await evidenceApi.archiveItem(itemId)
      setItems((prev) => (prev || []).map((it) => (it.id === itemId ? updated : it)))
      toast.success('已归档')
      detachPromise(loadSuites())
    } catch (error: unknown) {
      toast.error(formatApiError(error, '归档失败'))
    }
  }, [loadSuites])

  const handleReviewItem = useCallback(async (itemId: string) => {
    if (!itemId) return
    try {
      const updated = await evidenceApi.reviewItem(itemId)
      setItems((prev) => (prev || []).map((it) => (it.id === itemId ? updated : it)))
      toast.success('已提交 Review')
      detachPromise(loadSuites())
    } catch (error: unknown) {
      toast.error(formatApiError(error, '提交 Review 失败'))
    }
  }, [loadSuites])

  const handleApproveItem = useCallback(async (itemId: string) => {
    if (!itemId) return
    try {
      const updated = await evidenceApi.approveItem(itemId)
      setItems((prev) => (prev || []).map((it) => (it.id === itemId ? updated : it)))
      toast.success('已批准（approved）')
      detachPromise(loadSuites())
    } catch (error: unknown) {
      toast.error(formatApiError(error, '批准失败'))
    }
  }, [loadSuites])

  const suiteCounts = useMemo(() => {
    const c = selectedSuite?.item_counts || null
    if (!c) return null
    return {
      total: Number(c.total || 0),
      draft: Number(c.draft || 0),
      reviewed: Number(c.reviewed || 0),
      approved: Number(c.approved || 0),
      archived: Number(c.archived || 0),
    }
  }, [selectedSuite?.item_counts])

  const retrieveCitations = useMemo(() => retrieveRes?.citations ?? EMPTY_CITATIONS, [retrieveRes])
  const importCitations = useMemo(() => importPack?.citations ?? EMPTY_CITATIONS, [importPack])

  const expectedNeedles = useMemo(() => extractEvidenceNeedles(newExpected), [newExpected])
  const retrieveRanked = useMemo(() => rankEvidenceCitations(retrieveCitations, expectedNeedles), [expectedNeedles, retrieveCitations])
  const suggestedRetrieveChunkIds = useMemo(() => {
    const out: string[] = []
    for (const r of retrieveRanked || []) {
      if (r.score <= 0) continue
      const chunkId = String(r.citation.chunk_id || '')
      if (!chunkId) continue
      out.push(chunkId)
      if (out.length >= 8) break
    }
    return out
  }, [retrieveRanked])

  const applyRetrieveSuggestions = useCallback(() => {
    if (!suggestedRetrieveChunkIds.length) return
    setSelectedChunkIds((prev) => {
      const next = new Set(prev || [])
      for (const cid of suggestedRetrieveChunkIds) next.add(cid)
      return Array.from(next)
    })
    toast.success(`selected ${suggestedRetrieveChunkIds.length} suggested chunks`)
  }, [suggestedRetrieveChunkIds])

  const openWhyMissed = useCallback(() => {
    if (!selectedItem) return

    setWhyMissedError(null)
    setWhyMissedRanRetrieve(false)
    setWhyMissedCitations([])
    setWhyMissedDriftError(null)
    setWhyMissedDriftedRefs([])

    const snapProfile = String(selectedItem?.rag_config_snapshot?.retrieval_profile || '').trim()
    setWhyMissedProfile(coerceOneOf(RETRIEVAL_PROFILE_VALUES, snapProfile, 'recall50'))

    setWhyMissedOpen(true)
  }, [selectedItem])

  const loadWhyMissedDrift = useCallback(async () => {
    if (!selectedSuiteId) return
    if (!selectedItem?.id) return

    setWhyMissedDriftLoading(true)
    setWhyMissedDriftError(null)
    try {
      const audit = await evidenceApi.getSuiteDriftAudit(selectedSuiteId, {
        include_archived_items: false,
        include_details: true,
        details_limit: 2000,
        slice_top_n: 20,
      })
      const details = audit.drifted_references ?? []
      const itemId = String(selectedItem.id)
      setWhyMissedDriftedRefs(details.filter((d) => String(d?.item_id || '') === itemId))
    } catch (error: unknown) {
      setWhyMissedDriftError(formatApiError(error, '加载 Drift Audit 失败'))
    } finally {
      setWhyMissedDriftLoading(false)
    }
  }, [selectedItem?.id, selectedSuiteId])

  useEffect(() => {
    if (!whyMissedOpen) return
    detachPromise(loadWhyMissedDrift())
  }, [loadWhyMissedDrift, whyMissedOpen])

  const runWhyMissedRetrieve = useCallback(async () => {
    if (!datasetId) return
    if (!selectedItem?.query) return

    const q = String(selectedItem.query || '').trim()
    if (!q) return

    setWhyMissedRetrieving(true)
    setWhyMissedError(null)
    setWhyMissedRanRetrieve(false)
    setWhyMissedCitations([])
    try {
      const res = await ragApi.retrieveEvidence({
        query: q,
        history: [],
        dataset_id: datasetId,
        document_ids: [],
        rag_config: {
          retrieval_profile: whyMissedProfile,
          max_tokens: 2000,
          retrieval_mode: 'hybrid',
          alpha: 0.6,
          enable_weight_rerank: true,
          vector_weight: 0.6,
          keyword_weight: 0.4,
          use_graph: false,
          visible_evidence_only: false,
        },
      })
      const nextCitations = normalizeRetrieveResult(res)?.citations ?? EMPTY_CITATIONS
      setWhyMissedCitations(nextCitations)
      setWhyMissedRanRetrieve(true)
      toast.success(`检索完成：citations=${nextCitations.length}`)
    } catch (error: unknown) {
      setWhyMissedError(formatApiError(error, '检索失败'))
    } finally {
      setWhyMissedRetrieving(false)
    }
  }, [datasetId, selectedItem?.query, whyMissedProfile])

  const whyMissedReport = useMemo(() => {
    if (!selectedItem) return null
    if (!whyMissedRanRetrieve) return null
    return buildWhyMissedReport({
      reference_sources: selectedItem.reference_sources || [],
      citations: whyMissedCitations || [],
      drifted_references: whyMissedDriftedRefs || [],
    })
  }, [selectedItem, whyMissedCitations, whyMissedDriftedRefs, whyMissedRanRetrieve])

  const whyMissedRefDocIds = useMemo(() => {
    const ids = new Set<string>()
    for (const r of selectedItem?.reference_sources || []) {
      const did = String(r.document_id || '').trim()
      if (did) ids.add(did)
    }
    return ids
  }, [selectedItem?.reference_sources])

  const whyMissedRefChunkIds = useMemo(() => {
    const ids = new Set<string>()
    for (const r of selectedItem?.reference_sources || []) {
      const cid = String(r.chunk_id || '').trim()
      if (cid) ids.add(cid)
    }
    return ids
  }, [selectedItem?.reference_sources])

  const exportWhyMissedReport = useCallback(() => {
    if (!selectedSuite?.id) return
    if (!selectedItem?.id) return
    if (!whyMissedReport) return

    const safeTs = safeIsoForFilename(new Date().toISOString())
    const suiteName = (selectedSuite.name || 'evidence-suite').replaceAll(/[\\/:*?"<>|]+/g, '_').slice(0, 64)
    const itemId = String(selectedItem.id).slice(0, 8)
    downloadJson(`${suiteName}.why-missed.${itemId}.${safeTs}.json`, {
      schema: 'mimirq.evidence_why_missed.v1',
      generated_at: new Date().toISOString(),
      suite_id: String(selectedSuite.id),
      item_id: String(selectedItem.id),
      dataset_id: datasetId,
      retrieval_profile: whyMissedProfile,
      drifted_references: whyMissedDriftedRefs,
      citations: whyMissedCitations,
      report: whyMissedReport,
    })
    toast.success('已导出 Why-missed 报告')
  }, [
    datasetId,
    selectedItem?.id,
    selectedSuite?.id,
    selectedSuite?.name,
    whyMissedCitations,
    whyMissedDriftedRefs,
    whyMissedProfile,
    whyMissedReport,
  ])

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
        <SuiteListPanel
          datasetLabel={datasetLoading ? '加载中…' : (dataset?.name || datasetId || '-')}
          suiteQuery={suiteQuery}
          onSuiteQueryChange={setSuiteQuery}
          onRefresh={() => detachPromise(loadSuites())}
          suitesLoading={suitesLoading}
          includeArchivedSuites={includeArchivedSuites}
          onIncludeArchivedSuitesChange={setIncludeArchivedSuites}
          suitesError={suitesError}
          filteredSuites={filteredSuites}
          selectedSuiteId={selectedSuiteId}
          onCreateSuite={openCreateSuite}
          onSelectSuite={(suiteId) => {
            setSelectedSuiteId(suiteId)
            setSelectedItemId('')
          }}
        />

        <ItemListPanel
          selectedSuite={selectedSuite}
          selectedSuiteId={selectedSuiteId}
          itemQuery={itemQuery}
          onItemQueryChange={setItemQuery}
          statusFilter={statusFilter}
          onStatusFilterChange={setStatusFilter}
          onRefresh={() => detachPromise(loadItems())}
          itemsLoading={itemsLoading}
          filteredItems={filteredItems}
          itemsError={itemsError}
          selectedItemId={selectedItemId}
          onCreateItem={openCreateItem}
          onSelectItem={setSelectedItemId}
          statusBadgeVariant={evidenceStatusBadgeVariant}
        />

        <ItemDetailPanel
          selectedItem={selectedItem}
          selectedSuite={selectedSuite}
          suiteCounts={suiteCounts}
          importingQAFaq={importingQAFaq}
          qaFaqInputRef={qaFaqInputRef}
          statusBadgeVariant={evidenceStatusBadgeVariant}
          onImportQAFaqFile={(file) => detachPromise(handleImportQAFaq(file))}
          onOpenHardcases={() => setHardcaseOpen(true)}
          onOpenDashboard={() => setDashboardOpen(true)}
          onExportSuite={handleExportSuite}
          onExportLtrTraining={handleExportLtrTraining}
          onSyncSuite={() => detachPromise(handleSyncSuite())}
          onReviewItem={(itemId) => detachPromise(handleReviewItem(itemId))}
          onApproveItem={(itemId) => detachPromise(handleApproveItem(itemId))}
          onOpenWhyMissed={openWhyMissed}
          onArchiveItem={(itemId) => detachPromise(handleArchiveItem(itemId))}
        />
      </div>

      <HardcaseCandidatesDialog
        open={hardcaseOpen}
        selectedSuiteId={selectedSuiteId}
        loading={hardcaseLoading}
        error={hardcaseError}
        hardcaseRes={hardcaseRes}
        maxRating={hardcaseMaxRating}
        includeExisting={hardcaseIncludeExisting}
        maxCandidates={hardcaseMaxCandidates}
        tags={hardcaseTags}
        convertingFeedbackId={convertingFeedbackId}
        onOpenChange={(open) => {
          setHardcaseOpen(open)
          if (!open) {
            setHardcaseError(null)
            setConvertingFeedbackId('')
          }
        }}
        onMaxRatingChange={setHardcaseMaxRating}
        onIncludeExistingChange={setHardcaseIncludeExisting}
        onMaxCandidatesChange={setHardcaseMaxCandidates}
        onTagsChange={setHardcaseTags}
        onRefresh={() => detachPromise(loadHardcases())}
        onCopyText={(label, text) => {
          detachPromise(copyText(label, text))
        }}
        onConvertFeedback={(feedbackId, questionHash) => {
          detachPromise(handleConvertFeedbackToEvidence(feedbackId, questionHash))
        }}
      />

      <SuiteDashboardDialog
        open={dashboardOpen}
        selectedSuite={selectedSuite}
        selectedSuiteId={selectedSuiteId}
        includeArchived={dashboardIncludeArchived}
        loading={dashboardLoading}
        error={dashboardError}
        dashboard={dashboard}
        onOpenChange={(open) => {
          setDashboardOpen(open)
          if (!open) {
            setDashboardError(null)
          }
        }}
        onIncludeArchivedChange={setDashboardIncludeArchived}
        onRefresh={() => detachPromise(loadDashboard())}
      />

      {/* Create suite dialog */}
      <Dialog
        open={createSuiteOpen}
        onOpenChange={(open) => {
          setCreateSuiteOpen(open)
          if (!open) resetCreateSuiteForm()
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>新建 Evidence Suite</DialogTitle>
            <DialogDescription className="text-pretty">Suite 用于组织证据 Items，并作为“同步到回归”的单位。</DialogDescription>
          </DialogHeader>

          <div className="space-y-3">
            <div className="space-y-1">
              <Label htmlFor="suite-name">名称</Label>
              <Input
                id="suite-name"
                value={suiteName}
                onChange={(e) => setSuiteName(e.target.value)}
                placeholder="例如：Refund Policy v1"
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="suite-desc">描述（可选）</Label>
              <Textarea
                id="suite-desc"
                value={suiteDesc}
                onChange={(e) => setSuiteDesc(e.target.value)}
                placeholder="该 Suite 的范围 / 目标 / 约定…"
                rows={3}
              />
            </div>
            <div className="space-y-1">
              <Label>Tags（可选）</Label>
              <TagInput value={suiteTags} onValueChange={setSuiteTags} placeholder="回车添加 tag…" />
            </div>
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setCreateSuiteOpen(false)}>
              取消
            </Button>
            <Button onClick={() => detachPromise(handleCreateSuite())} disabled={creatingSuite || !suiteName.trim()}>
              {creatingSuite ? <Loader2 className="size-4 animate-spin motion-reduce:animate-none mr-2" aria-hidden="true" /> : null}
              创建
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <CreateItemDialog
        open={createItemOpen}
        newQuery={newQuery}
        newExpected={newExpected}
        newNotes={newNotes}
        createItemTab={createItemTab}
        profile={profile}
        retrieving={retrieving}
        datasetId={datasetId}
        suggestedRetrieveChunkIds={suggestedRetrieveChunkIds}
        selectedChunkIds={selectedChunkIds}
        retrieveError={retrieveError}
        expectedNeedles={expectedNeedles}
        hasRetrieveResult={Boolean(retrieveRes)}
        retrieveRanked={retrieveRanked}
        fileInputRef={fileInputRef}
        hasImportPack={Boolean(importPack)}
        importPackVersionLabel={String(importPack?.version ?? '?')}
        importCitations={importCitations}
        importError={importError}
        importSelectedChunkIds={importSelectedChunkIds}
        creatingItem={creatingItem}
        selectedSuiteId={selectedSuiteId}
        onOpenChange={setCreateItemOpen}
        onNewQueryChange={setNewQuery}
        onNewExpectedChange={setNewExpected}
        onNewNotesChange={setNewNotes}
        onCreateItemTabChange={setCreateItemTab}
        onProfileChange={setProfile}
        onRunRetrieve={() => detachPromise(runRetrieve())}
        onApplyRetrieveSuggestions={applyRetrieveSuggestions}
        onToggleRetrieveChunk={(chunkId) => toggleChunkSelection(chunkId, 'retrieve')}
        onPickPackFile={(file) => {
          detachPromise(handlePickPackFile(file))
        }}
        onToggleImportChunk={(chunkId) => toggleChunkSelection(chunkId, 'import')}
        onCreateItem={() => detachPromise(handleCreateItem())}
      />

      <WhyMissedDialog
        open={whyMissedOpen}
        datasetId={datasetId}
        selectedSuiteId={selectedSuiteId}
        selectedItem={selectedItem}
        whyMissedProfile={whyMissedProfile}
        whyMissedRetrieving={whyMissedRetrieving}
        whyMissedDriftLoading={whyMissedDriftLoading}
        whyMissedReport={whyMissedReport}
        whyMissedError={whyMissedError}
        whyMissedDriftError={whyMissedDriftError}
        whyMissedRanRetrieve={whyMissedRanRetrieve}
        whyMissedCitations={whyMissedCitations}
        whyMissedRefDocIds={whyMissedRefDocIds}
        whyMissedRefChunkIds={whyMissedRefChunkIds}
        onOpenChange={(open) => {
          setWhyMissedOpen(open)
          if (!open) {
            setWhyMissedError(null)
            setWhyMissedRanRetrieve(false)
            setWhyMissedCitations([])
            setWhyMissedDriftError(null)
            setWhyMissedDriftedRefs([])
          }
        }}
        onWhyMissedProfileChange={setWhyMissedProfile}
        onRunRetrieve={() => detachPromise(runWhyMissedRetrieve())}
        onLoadDrift={() => detachPromise(loadWhyMissedDrift())}
        onExportReport={exportWhyMissedReport}
      />
    </div>
  )
}
