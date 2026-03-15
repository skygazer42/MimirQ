'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { toast } from 'sonner'
import { BarChart3, Copy, Download, FileUp, Loader2, Plus, RefreshCw, Search, ShieldCheck, TestTube2, X } from 'lucide-react'

import type {
  Citation,
  Dataset,
  EvidenceHardcaseDiscovery,
  EvidenceItem,
  EvidenceItemCreate,
  EvidenceItemStatus,
  EvidenceSuite,
  EvidenceSuiteDashboard,
  ReferenceSource,
} from '@/types'
import { datasetApi, evidenceApi, feedbackApi, ragApi } from '@/lib/api-client'
import { formatApiError } from '@/lib/api-errors'
import { buildWhyMissedReport } from '@/lib/evidence-why-missed'
import { extractEvidenceNeedles, rankEvidenceCitations } from '@/lib/evidence-suggestions'
import { cn, detachPromise } from '@/lib/utils'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Panel } from '@/components/ui/panel'
import { ScrollArea } from '@/components/ui/scroll-area'
import { SearchInput } from '@/components/ui/search-input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Separator } from '@/components/ui/separator'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { TagInput } from '@/components/ui/tag-input'
import { Textarea } from '@/components/ui/textarea'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog'

type RetrievalProfile = 'recall50' | 'coverage80' | 'recall20'

type EvidenceRetrieveResult = {
  citations?: Citation[]
  has_evidence?: boolean | null
  abstain_triggered?: boolean | null
  abstain_reason?: string | null
  [key: string]: unknown
}

type EvidenceImportPack = {
  citations?: Citation[]
  selected_chunk_ids?: unknown[]
  retrieval_profile?: string | null
  version?: string | number | null
  [key: string]: unknown
}

function asDatasetId(raw: unknown): string | null {
  if (typeof raw === 'string' && raw.trim()) return raw
  return null
}

function downloadJson(filename: string, data: any) {
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

function citationScoreLabel(c: Citation): string {
  const raw = (c.retrieval_score ?? c.rerank_score ?? c.relevance_score ?? c.vector_score ?? c.bm25_score ?? 0) as any
  const n = Number(raw)
  if (Number.isFinite(n)) return n.toFixed(4)
  return '0.0000'
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

function formatDurationSec(sec: unknown): string {
  const n = Number(sec)
  if (!Number.isFinite(n) || n <= 0) return '-'
  const mins = n / 60
  if (mins < 60) return `${Math.round(mins)}m`
  const hours = mins / 60
  if (hours < 48) return `${hours.toFixed(1)}h`
  const days = hours / 24
  return `${days.toFixed(1)}d`
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
  const [whyMissedDriftedRefs, setWhyMissedDriftedRefs] = useState<any[]>([])

  // Suite dashboard
  const [dashboardOpen, setDashboardOpen] = useState(false)
  const [dashboardLoading, setDashboardLoading] = useState(false)
  const [dashboardError, setDashboardError] = useState<string | null>(null)
  const [dashboard, setDashboard] = useState<EvidenceSuiteDashboard | null>(null)
  const [dashboardIncludeArchived, setDashboardIncludeArchived] = useState(false)
  const dashboardThroughput = dashboard?.throughput
  const dashboardCoverage = dashboard?.coverage

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
    } catch (e: any) {
      toast.error(formatApiError(e, '加载数据集失败'))
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
    } catch (e: any) {
      setSuitesError(formatApiError(e, '加载 Evidence Suites 失败'))
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
    } catch (e: any) {
      setItemsError(formatApiError(e, '加载 Evidence Items 失败'))
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
    } catch (e: any) {
      setDashboardError(formatApiError(e, '加载 Dashboard 失败'))
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
    } catch (e: any) {
      setHardcaseError(formatApiError(e, '加载 Hardcase candidates 失败'))
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
    } catch (e: any) {
      toast.error(formatApiError(e, '复制失败'))
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
    } catch (e: any) {
      toast.error(formatApiError(e, '转为 EvidenceItem 失败'))
    } finally {
      setConvertingFeedbackId('')
    }
  }, [hardcaseTags, loadHardcases, loadItems, selectedSuiteId])

  useEffect(() => {
    detachPromise(loadDataset())
  }, [datasetId])

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
    } catch (e: any) {
      toast.error(formatApiError(e, '创建 Suite 失败'))
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
      setRetrieveRes(res || null)
      if (res?.has_evidence) toast.success('找到证据')
      else if (res?.abstain_triggered) toast.warning(`已触发 abstain：${res?.abstain_reason || 'unknown'}`)
      else toast.message('未找到证据')
    } catch (e: any) {
      setRetrieveError(formatApiError(e, '检索失败'))
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
      const payload = JSON.parse(text)
      setImportPack(payload)
      const selectedFromFile = Array.isArray(payload?.selected_chunk_ids) ? payload.selected_chunk_ids.map(String) : []
      setImportSelectedChunkIds(selectedFromFile)
    } catch (e: any) {
      setImportError(`解析失败：${String(e?.message || e)}`)
    }
  }, [])

  const handleCreateItem = useCallback(async () => {
    if (!datasetId) return
    if (!selectedSuiteId) return
    const suite = selectedSuite
    if (!suite?.id) return

    const query = newQuery.trim()
    if (!query) return

    let citations: Citation[] = []
    let selected: string[] = []
    let retrievalSnapshot: any = null
    let ragSnapshot: any = { retrieval_profile: profile }

    if (createItemTab === 'retrieve') {
      citations = retrieveRes?.citations || []
      selected = selectedChunkIds || []
      retrievalSnapshot = {
        ...retrieveRes,
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
    } catch (e: any) {
      toast.error(formatApiError(e, '创建 Evidence Item 失败'))
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
      } catch (e: any) {
        toast.error(formatApiError(e, '导入失败'))
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
    } catch (e: any) {
      toast.error(formatApiError(e, '导出失败'))
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
    } catch (e: any) {
      toast.error(formatApiError(e, '导出 LTR 训练数据失败'))
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
    } catch (e: any) {
      toast.error(formatApiError(e, '同步失败'))
    }
  }, [loadItems, loadSuites, selectedSuite])

  const handleArchiveItem = useCallback(async (itemId: string) => {
    if (!itemId) return
    try {
      const updated = await evidenceApi.archiveItem(itemId)
      setItems((prev) => (prev || []).map((it) => (it.id === itemId ? updated : it)))
      toast.success('已归档')
      detachPromise(loadSuites())
    } catch (e: any) {
      toast.error(formatApiError(e, '归档失败'))
    }
  }, [loadSuites])

  const handleReviewItem = useCallback(async (itemId: string) => {
    if (!itemId) return
    try {
      const updated = await evidenceApi.reviewItem(itemId)
      setItems((prev) => (prev || []).map((it) => (it.id === itemId ? updated : it)))
      toast.success('已提交 Review')
      detachPromise(loadSuites())
    } catch (e: any) {
      toast.error(formatApiError(e, '提交 Review 失败'))
    }
  }, [loadSuites])

  const handleApproveItem = useCallback(async (itemId: string) => {
    if (!itemId) return
    try {
      const updated = await evidenceApi.approveItem(itemId)
      setItems((prev) => (prev || []).map((it) => (it.id === itemId ? updated : it)))
      toast.success('已批准（approved）')
      detachPromise(loadSuites())
    } catch (e: any) {
      toast.error(formatApiError(e, '批准失败'))
    }
  }, [loadSuites])

  const suiteCounts = useMemo(() => {
    const c = selectedSuite?.item_counts || null
    if (!c) return null
    return {
      total: Number((c as any)?.total || 0),
      draft: Number((c as any)?.draft || 0),
      reviewed: Number((c as any)?.reviewed || 0),
      approved: Number((c as any)?.approved || 0),
      archived: Number((c as any)?.archived || 0),
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

    const snapProfile = String((selectedItem as any)?.rag_config_snapshot?.retrieval_profile || '').trim()
    if (snapProfile === 'recall50' || snapProfile === 'coverage80' || snapProfile === 'recall20') {
      setWhyMissedProfile(snapProfile as RetrievalProfile)
    } else {
      setWhyMissedProfile('recall50')
    }

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
      const details = Array.isArray((audit as any)?.drifted_references) ? ((audit as any).drifted_references as any[]) : []
      const itemId = String(selectedItem.id)
      setWhyMissedDriftedRefs(details.filter((d) => String(d?.item_id || '') === itemId))
    } catch (e: any) {
      setWhyMissedDriftError(formatApiError(e, '加载 Drift Audit 失败'))
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
      const nextCitations = (res?.citations || []) as unknown as Citation[]
      setWhyMissedCitations(nextCitations)
      setWhyMissedRanRetrieve(true)
      toast.success(`检索完成：citations=${nextCitations.length}`)
    } catch (e: any) {
      setWhyMissedError(formatApiError(e, '检索失败'))
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
      const did = String((r as any)?.document_id || '').trim()
      if (did) ids.add(did)
    }
    return ids
  }, [selectedItem?.reference_sources])

  const whyMissedRefChunkIds = useMemo(() => {
    const ids = new Set<string>()
    for (const r of selectedItem?.reference_sources || []) {
      const cid = String((r as any)?.chunk_id || '').trim()
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
        {/* Suites */}
        <Panel className="lg:col-span-3 p-4">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <div className="text-sm font-semibold text-foreground flex items-center gap-2">
                <ShieldCheck className="size-4 text-muted-foreground" aria-hidden="true" />
                Evidence Suites
              </div>
              <div className="text-xs text-muted-foreground mt-1 text-pretty">
                数据集：{datasetLoading ? '加载中…' : (dataset?.name || datasetId || '-')}
              </div>
            </div>
            <Button size="sm" className="gap-2" onClick={openCreateSuite}>
              <Plus className="size-4" aria-hidden="true" />
              新建
            </Button>
          </div>

          <div className="mt-3 flex items-center gap-2">
            <SearchInput value={suiteQuery} onValueChange={setSuiteQuery} placeholder="搜索 Suite…" />
            <Button
              variant="outline"
              size="icon"
              aria-label="刷新 Suites"
              className="size-9"
              onClick={() => detachPromise(loadSuites())}
              disabled={suitesLoading}
            >
              <RefreshCw className={cn('size-4', suitesLoading ? 'animate-spin motion-reduce:animate-none' : '')} aria-hidden="true" />
            </Button>
          </div>

          <div className="mt-3 flex items-center justify-between gap-3 text-xs text-muted-foreground">
            <div className="inline-flex items-center gap-2 select-none">
              <Checkbox
                checked={includeArchivedSuites}
                onCheckedChange={(v) => setIncludeArchivedSuites(Boolean(v))}
                aria-label="包含已归档 suites"
              />
              包含已归档
            </div>
            <span className="font-mono tabular-nums">{filteredSuites.length}</span>
          </div>

          {suitesError ? (
            <div className="mt-3 text-xs text-destructive text-pretty">{suitesError}</div>
          ) : null}

          <div className="mt-3">
            <ScrollArea className="h-[420px] pr-2">
              <div className="space-y-2">
                {(() => {
    if (suitesLoading) {
        return (<div className="text-xs text-muted-foreground">加载中…</div>);
    }
    else {
        if (filteredSuites.length) {
            return (filteredSuites.map((s) => {
                const active = s.id === selectedSuiteId;
                const counts = (s as any)?.item_counts || {};
                const total = Number(counts?.total || 0);
                const approved = Number(counts?.approved || 0);
                return (<button key={s.id} type="button" className={cn('w-full text-left rounded-lg border px-3 py-2 transition-colors', active ? 'border-primary/40 bg-primary/5' : 'border-border hover:bg-muted/30')} onClick={() => {
                        setSelectedSuiteId(String(s.id));
                        setSelectedItemId('');
                    }}>
                        <div className="flex items-start justify-between gap-3">
                          <div className="min-w-0">
                            <div className="text-sm font-medium text-foreground truncate">{s.name}</div>
                            {s.description ? (<div className="mt-0.5 text-xs text-muted-foreground line-clamp-2 text-pretty">
                                {s.description}
                              </div>) : null}
                          </div>
                          <div className="flex flex-col items-end gap-1 flex-shrink-0">
                            <Badge variant="outline" className="font-mono tabular-nums">
                              {total}
                            </Badge>
                            {approved ? (<Badge variant="soft" className="font-mono tabular-nums">
                                approved {approved}
                              </Badge>) : null}
                          </div>
                        </div>
                        {Array.isArray(s.tags) && s.tags.length ? (<div className="mt-2 flex flex-wrap gap-1">
                            {(s.tags || []).slice(0, 3).map((t) => (<Badge key={t} variant="secondary" className="text-[10px] font-mono">
                                {t}
                              </Badge>))}
                            {s.tags.length > 3 ? (<span className="text-[10px] text-muted-foreground font-mono">+{s.tags.length - 3}</span>) : null}
                          </div>) : null}
                      </button>);
            }));
        }
        else {
            return (<div className="text-xs text-muted-foreground text-pretty">
                    暂无 Suite。点击「新建」创建一个 Evidence Suite。
                  </div>);
        }
    }
})()}
              </div>
            </ScrollArea>
          </div>
        </Panel>

        {/* Items */}
        <Panel className="lg:col-span-4 p-4">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <div className="text-sm font-semibold text-foreground">Evidence Items</div>
              <div className="text-xs text-muted-foreground mt-1 text-pretty">
                {selectedSuite ? (
                  <>
                    Suite：<span className="font-mono">{String(selectedSuite.id).slice(0, 8)}</span> ·{' '}
                    <span className="font-medium">{selectedSuite.name}</span>
                  </>
                ) : (
                  '请选择一个 Suite'
                )}
              </div>
            </div>
            <div className="flex items-center gap-2">
              <Button size="sm" className="gap-2" onClick={openCreateItem} disabled={!selectedSuiteId}>
                <Plus className="size-4" aria-hidden="true" />
                新建 Item
              </Button>
            </div>
          </div>

          <div className="mt-3 grid grid-cols-1 gap-2">
            <SearchInput value={itemQuery} onValueChange={setItemQuery} placeholder="搜索 Item…" />
            <div className="flex items-center gap-2">
              <Select value={statusFilter} onValueChange={(v) => setStatusFilter(String(v))} disabled={!selectedSuiteId}>
                <SelectTrigger className="h-9">
                  <SelectValue placeholder="状态筛选" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="__all__">全部状态</SelectItem>
                  <SelectItem value="draft">draft</SelectItem>
                  <SelectItem value="reviewed">reviewed</SelectItem>
                  <SelectItem value="approved">approved</SelectItem>
                  <SelectItem value="archived">archived</SelectItem>
                </SelectContent>
              </Select>
              <Button
                variant="outline"
                size="icon"
                aria-label="刷新 Items"
                className="size-9"
                onClick={() => detachPromise(loadItems())}
                disabled={!selectedSuiteId || itemsLoading}
              >
                <RefreshCw className={cn('size-4', itemsLoading ? 'animate-spin motion-reduce:animate-none' : '')} aria-hidden="true" />
              </Button>
              <div className="ml-auto text-xs text-muted-foreground font-mono tabular-nums">
                {filteredItems.length}
              </div>
            </div>
          </div>

          {itemsError ? <div className="mt-3 text-xs text-destructive text-pretty">{itemsError}</div> : null}

          <div className="mt-3">
            <ScrollArea className="h-[420px] pr-2">
              <div className="space-y-2">
                {(() => {
    if (selectedSuiteId) {
        if (itemsLoading) {
            return (<div className="text-xs text-muted-foreground">加载中…</div>);
        }
        else {
            if (filteredItems.length) {
                return (filteredItems.map((it) => {
                    const active = it.id === selectedItemId;
                    return (<button key={it.id} type="button" className={cn('w-full text-left rounded-lg border px-3 py-2 transition-colors', active ? 'border-primary/40 bg-primary/5' : 'border-border hover:bg-muted/30')} onClick={() => setSelectedItemId(String(it.id))}>
                        <div className="flex items-start justify-between gap-3">
                          <div className="min-w-0">
                            <div className="text-sm font-medium text-foreground line-clamp-2 text-pretty">
                              {it.query}
                            </div>
                            {it.notes ? (<div className="mt-1 text-xs text-muted-foreground line-clamp-2 text-pretty">{it.notes}</div>) : null}
                          </div>
                          <Badge variant={evidenceStatusBadgeVariant(it.status)} className="font-mono text-[10px] uppercase">
                            {it.status}
                          </Badge>
                        </div>
                        <div className="mt-2 flex items-center justify-between gap-3 text-[11px] text-muted-foreground font-mono tabular-nums">
                          <span>refs: {Array.isArray(it.reference_sources) ? it.reference_sources.length : 0}</span>
                          <span>{String(it.updated_at || '').slice(0, 19).replaceAll('T', ' ')}</span>
                        </div>
                      </button>);
                }));
            }
            else {
                return (<div className="text-xs text-muted-foreground text-pretty">暂无 Items。点击「新建 Item」创建。</div>);
            }
        }
    }
    else {
        return (<div className="text-xs text-muted-foreground text-pretty">选择一个 Suite 后即可查看/创建 Items。</div>);
    }
})()}
              </div>
            </ScrollArea>
          </div>
        </Panel>

        {/* Detail */}
        <Panel className="lg:col-span-5 p-4">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <div className="text-sm font-semibold text-foreground">Detail</div>
              <div className="text-xs text-muted-foreground mt-1 text-pretty">
                {selectedItem ? (
                  <>
                    Item：<span className="font-mono">{String(selectedItem.id).slice(0, 8)}</span>
                  </>
                ) : (
                  '请选择一个 Item'
                )}
              </div>
            </div>
            <div className="flex items-center gap-2">
              <input
                ref={qaFaqInputRef}
                type="file"
                accept=".csv,.jsonl,text/csv,application/x-ndjson"
                className="hidden"
                onChange={(e) => {
                  const f = e.target.files?.[0]
                  if (f) detachPromise(handleImportQAFaq(f))
                }}
              />
              <Button
                variant="outline"
                size="sm"
                className="gap-2"
                onClick={() => setHardcaseOpen(true)}
                disabled={!selectedSuite?.id}
              >
                <TestTube2 className="size-4" aria-hidden="true" />
                Hardcases
              </Button>
              <Button
                variant="outline"
                size="sm"
                className="gap-2"
                onClick={() => setDashboardOpen(true)}
                disabled={!selectedSuite?.id}
              >
                <BarChart3 className="size-4" aria-hidden="true" />
                Dashboard
              </Button>
              <Button
                variant="outline"
                size="sm"
                className="gap-2"
                onClick={handleExportSuite}
                disabled={!selectedSuite?.id}
              >
                <Download className="size-4" aria-hidden="true" />
                导出 Suite
              </Button>

              <Button
                variant="outline"
                size="sm"
                className="gap-2"
                onClick={handleExportLtrTraining}
                disabled={!selectedSuite?.id}
                title="Export LTR training rows + hard negatives (ZIP)"
              >
                <Download className="size-4" aria-hidden="true" />
                导出 LTR
              </Button>

              <Button
                variant="outline"
                size="sm"
                className="gap-2"
                onClick={() => qaFaqInputRef.current?.click()}
                disabled={!selectedSuite?.id || importingQAFaq}
              >
                {importingQAFaq ? (
                  <Loader2 className="size-4 animate-spin motion-reduce:animate-none" aria-hidden="true" />
                ) : (
                  <FileUp className="size-4" aria-hidden="true" />
                )}
                导入 QA/FAQ
              </Button>

              <AlertDialog>
                <AlertDialogTrigger asChild>
                  <Button size="sm" className="gap-2" disabled={!selectedSuite?.id}>
                    <RefreshCw className="size-4" aria-hidden="true" />
                    Sync 回归
                  </Button>
                </AlertDialogTrigger>
                <AlertDialogContent>
                  <AlertDialogHeader>
                    <AlertDialogTitle>同步到回归用例库？</AlertDialogTitle>
                    <AlertDialogDescription className="text-pretty">
                      将该 Suite 中 <span className="font-mono">approved</span> 状态的 Items upsert 到回归用例库（question + reference_sources）。
                      如果已有绑定的 case，会更新它。
                    </AlertDialogDescription>
                  </AlertDialogHeader>
                  <AlertDialogFooter>
                    <AlertDialogCancel>取消</AlertDialogCancel>
                    <AlertDialogAction onClick={() => detachPromise(handleSyncSuite())} disabled={!selectedSuite?.id}>
                      同步
                    </AlertDialogAction>
                  </AlertDialogFooter>
                </AlertDialogContent>
              </AlertDialog>
            </div>
          </div>

          {suiteCounts ? (
            <div className="mt-3 flex flex-wrap gap-2 text-xs">
              <Badge variant="outline" className="font-mono tabular-nums">
                total {suiteCounts.total}
              </Badge>
              <Badge variant="outline" className="font-mono tabular-nums">
                draft {suiteCounts.draft}
              </Badge>
              <Badge variant="secondary" className="font-mono tabular-nums">
                reviewed {suiteCounts.reviewed}
              </Badge>
              <Badge variant="soft" className="font-mono tabular-nums">
                approved {suiteCounts.approved}
              </Badge>
              <Badge variant="outline" className="font-mono tabular-nums">
                archived {suiteCounts.archived}
              </Badge>
            </div>
          ) : null}

          <Separator className="my-4" />

          {selectedItem ? (
            <div className="space-y-4">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="text-sm font-semibold text-foreground text-pretty">{selectedItem.query}</div>
                  <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-muted-foreground font-mono">
                    <Badge variant={evidenceStatusBadgeVariant(selectedItem.status)} className="uppercase">
                      {selectedItem.status}
                    </Badge>
                    {selectedItem.regression_case_id ? (
                      <Badge variant="outline" className="truncate max-w-[220px]">
                        case {String(selectedItem.regression_case_id).slice(0, 8)}
                      </Badge>
                    ) : null}
                  </div>
                </div>

                <div className="flex flex-wrap items-center gap-2">
                  {selectedItem.status === 'draft' ? (
                    <Button size="sm" variant="outline" className="gap-2" onClick={() => detachPromise(handleReviewItem(String(selectedItem.id)))}>
                      <Search className="size-4" aria-hidden="true" />
                      Review
                    </Button>
                  ) : null}

                  {selectedItem.status === 'reviewed' ? (
                    <Button size="sm" className="gap-2" onClick={() => detachPromise(handleApproveItem(String(selectedItem.id)))}>
                      <ShieldCheck className="size-4" aria-hidden="true" />
                      Approve
                    </Button>
                  ) : null}

                  <Button size="sm" variant="outline" className="gap-2" onClick={openWhyMissed}>
                    <BarChart3 className="size-4" aria-hidden="true" />
                    Why missed?
                  </Button>

                  <AlertDialog>
                    <AlertDialogTrigger asChild>
                      <Button size="sm" variant="destructive" className="gap-2" disabled={selectedItem.status === 'archived'}>
                        <X className="size-4" aria-hidden="true" />
                        归档
                      </Button>
                    </AlertDialogTrigger>
                    <AlertDialogContent>
                      <AlertDialogHeader>
                        <AlertDialogTitle>归档该 Item？</AlertDialogTitle>
                        <AlertDialogDescription className="text-pretty">
                          归档后不会从数据库删除，但默认列表会隐藏。该操作可用于标记“已废弃/不再维护”的证据。
                        </AlertDialogDescription>
                      </AlertDialogHeader>
                      <AlertDialogFooter>
                        <AlertDialogCancel>取消</AlertDialogCancel>
                        <AlertDialogAction onClick={() => detachPromise(handleArchiveItem(String(selectedItem.id)))}>归档</AlertDialogAction>
                      </AlertDialogFooter>
                    </AlertDialogContent>
                  </AlertDialog>
                </div>
              </div>

              {selectedItem.expected_answer ? (
                <div>
                  <div className="text-xs font-medium text-muted-foreground mb-1">Expected Answer (optional)</div>
                  <Panel className="p-3">
                    <div className="text-sm whitespace-pre-wrap text-pretty">{selectedItem.expected_answer}</div>
                  </Panel>
                </div>
              ) : null}

              {Array.isArray((selectedItem as any).tags) && (selectedItem as any).tags.length ? (
                <div>
                  <div className="text-xs font-medium text-muted-foreground mb-1">Tags</div>
                  <div className="flex flex-wrap gap-2">
                    {((selectedItem as any).tags as string[]).map((t) => (
                      <Badge key={t} variant="outline" className="font-mono text-[10px]">
                        {t}
                      </Badge>
                    ))}
                  </div>
                </div>
              ) : null}

              {selectedItem && selectedItem.source_metadata && Object.keys(selectedItem.source_metadata).length ? (
                <div>
                  <div className="text-xs font-medium text-muted-foreground mb-1">Source Metadata</div>
                  <Panel className="p-3">
                    <ScrollArea className="h-[180px] pr-2">
                      <pre className="text-xs font-mono whitespace-pre-wrap break-words text-muted-foreground">
                        {JSON.stringify(selectedItem.source_metadata, null, 2)}
                      </pre>
                    </ScrollArea>
                  </Panel>
                </div>
              ) : null}

              <div>
                <div className="text-xs font-medium text-muted-foreground mb-1">Reference Sources</div>
                <Panel className="p-3">
                  <div className="space-y-2">
                    {(selectedItem.reference_sources || []).length ? (
                      (selectedItem.reference_sources || []).map((r) => (
                        <div key={`${String(r.document_id)}:${String(r.chunk_id)}`} className="rounded-md border border-border/60 p-2">
                          <div className="flex items-start justify-between gap-2">
                            <div className="min-w-0">
                              <div className="text-xs font-mono text-foreground truncate">
                                {String(r.document_id).slice(0, 8)}:{String(r.chunk_id).slice(0, 8)}
                              </div>
                              {r.label ? (
                                <div className="mt-1 text-xs text-muted-foreground line-clamp-1 text-pretty">{r.label}</div>
                              ) : null}
                            </div>
                            <div className="text-[11px] text-muted-foreground font-mono tabular-nums flex-shrink-0">
                              {typeof r.page_number === 'number' ? `P.${r.page_number}` : null}
                              {typeof r.chunk_index === 'number' ? ` · #${r.chunk_index}` : null}
                            </div>
                          </div>
                          {r.quote ? (
                            <div className="mt-2 text-xs text-muted-foreground line-clamp-3 text-pretty">{r.quote}</div>
                          ) : null}
                        </div>
                      ))
                    ) : (
                      <div className="text-sm text-muted-foreground text-pretty">暂无 reference_sources。</div>
                    )}
                  </div>
                </Panel>
              </div>

              {selectedItem.notes ? (
                <div>
                  <div className="text-xs font-medium text-muted-foreground mb-1">Notes</div>
                  <Panel className="p-3">
                    <div className="text-sm whitespace-pre-wrap text-pretty">{selectedItem.notes}</div>
                  </Panel>
                </div>
              ) : null}
            </div>
          ) : (
            <div className="text-sm text-muted-foreground text-pretty">
              选择一个 Item 查看详情。你可以在 draft 状态下修改内容，然后提交 review → approve → sync。
            </div>
          )}
        </Panel>
      </div>

      {/* Hardcase candidates dialog */}
      <Dialog
        open={hardcaseOpen}
        onOpenChange={(open) => {
          setHardcaseOpen(open)
          if (!open) {
            setHardcaseError(null)
            setConvertingFeedbackId('')
          }
        }}
      >
        <DialogContent className="max-w-4xl overflow-hidden">
          <DialogHeader>
            <DialogTitle>Hardcase Candidates</DialogTitle>
            <DialogDescription className="text-pretty">
              从低分反馈 + rag_trace 聚类得到的候选（PII-safe）。选择一个 <span className="font-mono">feedback_id</span> 转为 draft EvidenceItem。
            </DialogDescription>
          </DialogHeader>

          <div className="flex flex-col sm:flex-row sm:items-center gap-3">
            <div className="flex flex-wrap items-center gap-3">
              <div className="flex items-center gap-2 text-xs">
                <span className="text-muted-foreground">max rating</span>
                <Select value={String(hardcaseMaxRating)} onValueChange={(v) => setHardcaseMaxRating(Number(v) || 2)}>
                  <SelectTrigger className="h-8 w-24">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="1">{'<= 1'}</SelectItem>
                    <SelectItem value="2">{'<= 2'}</SelectItem>
                    <SelectItem value="3">{'<= 3'}</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              <div className="inline-flex items-center gap-2 select-none text-xs text-muted-foreground">
                <Checkbox
                  checked={hardcaseIncludeExisting}
                  onCheckedChange={(v) => setHardcaseIncludeExisting(Boolean(v))}
                  aria-label="Include existing items"
                />
                include existing
              </div>

              <div className="flex items-center gap-2 text-xs">
                <span className="text-muted-foreground">max candidates</span>
                <Input
                  value={String(hardcaseMaxCandidates)}
                  onChange={(e) => {
                    const n = Number(e.target.value || 0) || 0
                    setHardcaseMaxCandidates(Math.max(0, Math.min(200, Math.floor(n))))
                  }}
                  className="h-8 w-24 font-mono tabular-nums"
                  inputMode="numeric"
                />
              </div>
            </div>

            <div className="sm:ml-auto flex items-center gap-2">
              {hardcaseRes ? (
                <div className="text-xs text-muted-foreground font-mono tabular-nums">
                  scanned {hardcaseRes.feedback_scanned} · candidates {hardcaseRes.candidates?.length ?? 0}
                  {hardcaseRes.truncated ? ' · truncated' : ''}
                </div>
              ) : null}

              <Button
                variant="outline"
                size="sm"
                className="gap-2"
                onClick={() => detachPromise(loadHardcases())}
                disabled={!selectedSuiteId || hardcaseLoading}
              >
                <RefreshCw className={cn('size-4', hardcaseLoading ? 'animate-spin motion-reduce:animate-none' : '')} aria-hidden="true" />
                refresh
              </Button>
            </div>
          </div>

          <div className="space-y-1">
            <Label>Convert tags</Label>
            <TagInput value={hardcaseTags} onValueChange={setHardcaseTags} placeholder="回车添加 tag…" />
          </div>

          {hardcaseError ? <div className="text-xs text-destructive text-pretty">{hardcaseError}</div> : null}

          <ScrollArea className="max-h-[70vh] pr-3">
            {(() => {
    if (hardcaseLoading) {
        return (<div className="text-sm text-muted-foreground flex items-center gap-2 py-4">
                <Loader2 className="size-4 animate-spin motion-reduce:animate-none" aria-hidden="true"/>
                loading…
              </div>);
    }
    else {
        if (hardcaseRes) {
            return (<div className="space-y-3 py-1">
                {(() => {
                    if (hardcaseRes.enabled) {
                        if ((hardcaseRes.candidates || []).length) {
                            return ((hardcaseRes.candidates || []).map((cand) => {
                                const qh = String(cand.question_hash || '').trim();
                                const fbIds = Array.isArray(cand.feedback_ids) ? cand.feedback_ids : [];
                                const reqIds = Array.isArray(cand.request_ids) ? cand.request_ids : [];
                                const errKinds = (cand.retrieval_error_kinds || {}) as Record<string, number>;
                                const errBadges = Object.entries(errKinds)
                                    .filter(([k, v]) => k && Number(v) > 0)
                                    .sort((a, b) => Number(b[1]) - Number(a[1]) || String(a[0]).localeCompare(String(b[0])))
                                    .slice(0, 4);
                                const tmpl = (cand as any)?.rag_config_template || null;
                                const tmplKey = tmpl ? String(tmpl?.template_key || '').trim() : '';
                                const tmplVer = tmpl && Number.isFinite(Number(tmpl?.version)) ? Number(tmpl.version) : null;
                                const tmplPatch = tmpl ? String(tmpl?.patch_hash || '').trim() : '';
                                const tmplLabel = tmplKey ? `${tmplKey}${tmplVer === null ? '' : `@${tmplVer}`}` : '';
                                return (<Panel key={qh || JSON.stringify(cand)} className="p-3">
                        <div className="flex items-start justify-between gap-3">
                          <div className="min-w-0">
                            <div className="text-[11px] text-muted-foreground">question_hash</div>
                            <div className="mt-0.5 font-mono text-sm break-all">{qh || '(missing)'}</div>
                          </div>
                          <div className="flex items-center gap-2 flex-shrink-0">
                            <Badge variant="outline" className="font-mono tabular-nums">
                              cluster {cand.cluster_size ?? 0}
                            </Badge>
                            <Button variant="outline" size="icon" className="size-8" aria-label="复制 question_hash" onClick={() => detachPromise(copyText('question_hash', qh))} disabled={!qh}>
                              <Copy className="size-4" aria-hidden="true"/>
                            </Button>
                          </div>
                        </div>

                        <div className="mt-2 flex flex-wrap gap-2 text-[11px] text-muted-foreground font-mono tabular-nums">
                          {cand.retrieval_config_hash ? (<Badge variant="secondary" className="font-mono">
                              cfg {String(cand.retrieval_config_hash).slice(0, 16)}
                            </Badge>) : (<Badge variant="outline" className="font-mono">
                              cfg -
                            </Badge>)}

                          {typeof cand.citations_count === 'number' ? (<Badge variant="outline" className="font-mono">
                              cites {cand.citations_count}
                            </Badge>) : null}

                          {errBadges.length ? (errBadges.map(([k, v]) => (<Badge key={k} variant="outline" className="font-mono">
                                {k}:{v}
                              </Badge>))) : (<Badge variant="outline" className="font-mono">
                              errors 0
                            </Badge>)}

                          {tmplLabel ? (<Badge variant="outline" className="font-mono">
                              tmpl {tmplLabel}
                            </Badge>) : null}
                          {tmplPatch ? (<Badge variant="outline" className="font-mono">
                              patch {tmplPatch.slice(0, 10)}
                            </Badge>) : null}

                          {hardcaseRes.truncated ? (<Badge variant="destructive" className="font-mono">
                              truncated
                            </Badge>) : null}
                        </div>

                        <div className="mt-3 grid grid-cols-1 md:grid-cols-2 gap-3">
                          <div>
                            <div className="text-[11px] text-muted-foreground mb-1">feedback_ids (sample)</div>
                            <div className="flex flex-wrap gap-2">
                              {fbIds.length ? (fbIds.slice(0, 8).map((fid) => (<div key={fid} className="inline-flex items-center gap-1.5">
                                    <Badge variant="outline" className="font-mono text-[10px]">
                                      {String(fid).slice(0, 8)}
                                    </Badge>
                                    <Button variant="outline" size="icon" className="size-7" aria-label="复制 feedback_id" onClick={() => detachPromise(copyText('feedback_id', String(fid)))}>
                                      <Copy className="size-3.5" aria-hidden="true"/>
                                    </Button>
                                    <Button size="sm" className="h-7 px-2 text-xs" onClick={() => detachPromise(handleConvertFeedbackToEvidence(String(fid), qh))} disabled={!selectedSuiteId || Boolean(convertingFeedbackId)}>
                                      {convertingFeedbackId === String(fid) ? (<Loader2 className="size-3.5 animate-spin motion-reduce:animate-none mr-1.5" aria-hidden="true"/>) : null}
                                      转为 draft
                                    </Button>
                                  </div>))) : (<div className="text-xs text-muted-foreground">-</div>)}
                            </div>
                          </div>

                          <div>
                            <div className="text-[11px] text-muted-foreground mb-1">request_ids (sample)</div>
                            <div className="flex flex-wrap gap-2">
                              {reqIds.length ? (reqIds.slice(0, 6).map((rid) => (<div key={rid} className="inline-flex items-center gap-1.5">
                                    <Badge variant="secondary" className="font-mono text-[10px]">
                                      {String(rid).slice(0, 10)}
                                    </Badge>
                                    <Button variant="outline" size="icon" className="size-7" aria-label="复制 request_id" onClick={() => detachPromise(copyText('request_id', String(rid)))}>
                                      <Copy className="size-3.5" aria-hidden="true"/>
                                    </Button>
                                  </div>))) : (<div className="text-xs text-muted-foreground">-</div>)}
                            </div>
                          </div>
                        </div>
                      </Panel>);
                            }));
                        }
                        else {
                            return (<Panel className="p-3">
                    <div className="text-sm font-medium text-foreground">暂无候选</div>
                    <div className="mt-1 text-xs text-muted-foreground text-pretty">
                      你可以尝试提高 <span className="font-mono">max rating</span> 或增大窗口（后端默认 7 天）。
                    </div>
                  </Panel>);
                        }
                    }
                    else {
                        return (<Panel className="p-3">
                    <div className="text-sm font-medium text-foreground">Metrics log disabled</div>
                    <div className="mt-1 text-xs text-muted-foreground text-pretty">
                      需要开启 <span className="font-mono">ENABLE_METRICS_LOG=true</span> 才能从 traces 中发现 hardcases。
                    </div>
                  </Panel>);
                    }
                })()}

                <div className="text-[11px] text-muted-foreground font-mono tabular-nums">
                  window {hardcaseRes.window_minutes}m · max_bytes {hardcaseRes.max_bytes} · trace_index {hardcaseRes.trace_index_size}
                </div>
              </div>);
        }
        else {
            return (<div className="text-sm text-muted-foreground py-4">点击 refresh 加载候选。</div>);
        }
    }
})()}
          </ScrollArea>
        </DialogContent>
      </Dialog>

      {/* Suite dashboard dialog */}
      <Dialog
        open={dashboardOpen}
        onOpenChange={(open) => {
          setDashboardOpen(open)
          if (!open) {
            setDashboardError(null)
          }
        }}
      >
        <DialogContent className="max-w-4xl overflow-hidden">
          <DialogHeader>
            <DialogTitle>Suite Dashboard</DialogTitle>
            <DialogDescription className="text-pretty">
              {selectedSuite ? (
                <>
                  Suite <span className="font-mono">{String(selectedSuite.id).slice(0, 8)}</span> 路{' '}
                  <span className="font-medium">{selectedSuite.name}</span>
                </>
              ) : (
                '请选择一个 Suite'
              )}
            </DialogDescription>
          </DialogHeader>

          <div className="flex flex-col sm:flex-row sm:items-center gap-3">
            <div className="inline-flex items-center gap-2 select-none text-xs text-muted-foreground">
              <Checkbox
                checked={dashboardIncludeArchived}
                onCheckedChange={(v) => setDashboardIncludeArchived(Boolean(v))}
                aria-label="Include archived items"
              />
              include archived items
            </div>

            <div className="sm:ml-auto flex items-center gap-2">
              {dashboard ? (
                <div className="text-xs text-muted-foreground font-mono tabular-nums">
                  generated {String(dashboard.generated_at || '').slice(0, 19).replaceAll('T', ' ')}
                </div>
              ) : null}
              <Button
                variant="outline"
                size="sm"
                className="gap-2"
                onClick={() => detachPromise(loadDashboard())}
                disabled={!selectedSuiteId || dashboardLoading}
              >
                <RefreshCw className={cn('size-4', dashboardLoading ? 'animate-spin motion-reduce:animate-none' : '')} aria-hidden="true" />
                refresh
              </Button>
            </div>
          </div>

          {dashboardError ? <div className="text-xs text-destructive text-pretty">{dashboardError}</div> : null}

          <ScrollArea className="max-h-[70vh] pr-3">
            <div className="space-y-4">
              {(() => {
    if (dashboardLoading) {
        return (<div className="text-sm text-muted-foreground flex items-center gap-2">
                  <Loader2 className="size-4 animate-spin motion-reduce:animate-none" aria-hidden="true"/>
                  loading…
                </div>);
    }
    else {
        if (dashboard) {
            return (<>
                  {dashboardThroughput ? (<div>
                      <div className="text-xs font-medium text-muted-foreground mb-2">
                        Throughput (last {dashboardThroughput.window_days}d)
                      </div>
                      <div className="flex flex-wrap gap-2 text-xs">
                        <Badge variant="outline" className="font-mono tabular-nums">
                          created {dashboardThroughput.last_window?.created ?? 0}
                        </Badge>
                        <Badge variant="secondary" className="font-mono tabular-nums">
                          reviewed {dashboardThroughput.last_window?.reviewed ?? 0}
                        </Badge>
                        <Badge variant="soft" className="font-mono tabular-nums">
                          approved {dashboardThroughput.last_window?.approved ?? 0}
                        </Badge>
                      </div>

                      <div className="mt-3 grid grid-cols-1 md:grid-cols-3 gap-3">
                        <Panel className="p-3">
                          <div className="text-xs font-medium text-muted-foreground mb-1">draft → reviewed</div>
                          <div className="text-xs text-muted-foreground font-mono tabular-nums">
                            n {dashboardThroughput.draft_to_reviewed?.count ?? 0}
                          </div>
                          <div className="mt-1 text-xs font-mono tabular-nums">
                            p50 {formatDurationSec(dashboardThroughput.draft_to_reviewed?.p50_sec ?? 0)} · p90{' '}
                            {formatDurationSec(dashboardThroughput.draft_to_reviewed?.p90_sec ?? 0)} · mean{' '}
                            {formatDurationSec(dashboardThroughput.draft_to_reviewed?.mean_sec ?? 0)}
                          </div>
                        </Panel>

                        <Panel className="p-3">
                          <div className="text-xs font-medium text-muted-foreground mb-1">reviewed → approved</div>
                          <div className="text-xs text-muted-foreground font-mono tabular-nums">
                            n {dashboardThroughput.reviewed_to_approved?.count ?? 0}
                          </div>
                          <div className="mt-1 text-xs font-mono tabular-nums">
                            p50 {formatDurationSec(dashboardThroughput.reviewed_to_approved?.p50_sec ?? 0)} · p90{' '}
                            {formatDurationSec(dashboardThroughput.reviewed_to_approved?.p90_sec ?? 0)} · mean{' '}
                            {formatDurationSec(dashboardThroughput.reviewed_to_approved?.mean_sec ?? 0)}
                          </div>
                        </Panel>

                        <Panel className="p-3">
                          <div className="text-xs font-medium text-muted-foreground mb-1">draft → approved</div>
                          <div className="text-xs text-muted-foreground font-mono tabular-nums">
                            n {dashboardThroughput.draft_to_approved?.count ?? 0}
                          </div>
                          <div className="mt-1 text-xs font-mono tabular-nums">
                            p50 {formatDurationSec(dashboardThroughput.draft_to_approved?.p50_sec ?? 0)} · p90{' '}
                            {formatDurationSec(dashboardThroughput.draft_to_approved?.p90_sec ?? 0)} · mean{' '}
                            {formatDurationSec(dashboardThroughput.draft_to_approved?.mean_sec ?? 0)}
                          </div>
                        </Panel>
                      </div>
                    </div>) : (<div className="text-sm text-muted-foreground text-pretty">No throughput data.</div>)}

                  <Separator />

                  {dashboardCoverage ? (<>
                      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                        <Panel className="p-3">
                          <div className="text-xs font-medium text-muted-foreground mb-2">Language coverage</div>
                          <div className="space-y-1">
                            {(dashboardCoverage.language || []).map((b) => (<div key={`lang:${b.key}`} className="flex items-center justify-between gap-3 text-xs">
                                <div className="min-w-0 truncate font-mono">{b.key}</div>
                                <div className="flex items-center gap-3 font-mono tabular-nums text-muted-foreground">
                                  <span>refs {b.references}</span>
                                  <span>items {b.items}</span>
                                </div>
                              </div>))}
                          </div>
                        </Panel>

                        <Panel className="p-3">
                          <div className="text-xs font-medium text-muted-foreground mb-2">File type coverage</div>
                          <div className="space-y-1">
                            {(dashboardCoverage.file_type || []).map((b) => (<div key={`ft:${b.key}`} className="flex items-center justify-between gap-3 text-xs">
                                <div className="min-w-0 truncate font-mono">{b.key}</div>
                                <div className="flex items-center gap-3 font-mono tabular-nums text-muted-foreground">
                                  <span>refs {b.references}</span>
                                  <span>items {b.items}</span>
                                </div>
                              </div>))}
                          </div>
                        </Panel>

                        <Panel className="p-3">
                          <div className="text-xs font-medium text-muted-foreground mb-2">Quality bucket coverage</div>
                          <div className="space-y-1">
                            {(dashboardCoverage.quality_bucket || []).map((b) => (<div key={`qb:${b.key}`} className="flex items-center justify-between gap-3 text-xs">
                                <div className="min-w-0 truncate font-mono">{b.key}</div>
                                <div className="flex items-center gap-3 font-mono tabular-nums text-muted-foreground">
                                  <span>refs {b.references}</span>
                                  <span>items {b.items}</span>
                                </div>
                              </div>))}
                          </div>
                        </Panel>

                        <Panel className="p-3">
                          <div className="text-xs font-medium text-muted-foreground mb-2">Channel (hit_type) coverage</div>
                          <div className="space-y-1">
                            {(dashboardCoverage.channel || []).map((b) => (<div key={`ch:${b.key}`} className="flex items-center justify-between gap-3 text-xs">
                                <div className="min-w-0 truncate font-mono">{b.key}</div>
                                <div className="flex items-center gap-3 font-mono tabular-nums text-muted-foreground">
                                  <span>refs {b.references}</span>
                                  <span>items {b.items}</span>
                                </div>
                              </div>))}
                          </div>
                        </Panel>
                      </div>

                      <Panel className="p-3">
                        <div className="text-xs font-medium text-muted-foreground mb-2">
                          Heatmap: language × file_type (unique items)
                        </div>
                        {dashboardCoverage.heatmaps?.['language_x_file_type'] ? (<div className="overflow-x-auto">
                            {(() => {
                            const hm = dashboardCoverage.heatmaps['language_x_file_type'];
                            const x = hm?.x || [];
                            const y = hm?.y || [];
                            const z = hm?.z || [];
                            let max = 0;
                            for (const row of z) {
                                for (const v of row) {
                                    const n = Number(v) || 0;
                                    if (n > max)
                                        max = n;
                                }
                            }
                            const cols = x.length;
                            return (<div className="grid gap-px rounded-lg overflow-hidden border border-border/60 bg-border/60" style={{ gridTemplateColumns: `120px repeat(${cols}, minmax(72px, 1fr))` }}>
                                  <div className="bg-muted/40 px-2 py-1 text-[11px] font-mono text-muted-foreground">
                                    lang \\ ft
                                  </div>
                                  {x.map((ft) => (<div key={`hm-x:${ft}`} className="bg-muted/40 px-2 py-1 text-[11px] font-mono truncate">
                                      {ft}
                                    </div>))}
                                  {y.map((lang, rowIdx) => (<div key={`hm-row:${lang}`} className="contents">
                                      <div className="bg-muted/30 px-2 py-1 text-[11px] font-mono text-muted-foreground truncate">
                                        {lang}
                                      </div>
                                      {x.map((ft, colIdx) => {
                                        const v = Number(z?.[rowIdx]?.[colIdx] ?? 0) || 0;
                                        const ratio = max > 0 ? v / max : 0;
                                        const cellBg = (() => {
                                            if (v === 0) {
                                                return 'bg-muted/20';
                                            }
                                            else {
                                                if (ratio >= 0.75) {
                                                    return 'bg-primary/30';
                                                }
                                                else {
                                                    if (ratio >= 0.5) {
                                                        return 'bg-primary/20';
                                                    }
                                                    else {
                                                        if (ratio >= 0.25) {
                                                            return 'bg-primary/10';
                                                        }
                                                        else {
                                                            return 'bg-primary/5';
                                                        }
                                                    }
                                                }
                                            }
                                        })();
                                        return (<div key={`hm-cell:${lang}:${ft}`} className={cn('px-2 py-1 text-[11px] font-mono tabular-nums text-center', cellBg)}>
                                            {v}
                                          </div>);
                                    })}
                                </div>))}
                            </div>);
                        })()}
                      </div>) : (<div className="text-xs text-muted-foreground">No heatmap data.</div>)}
                  </Panel>
                    </>) : (<div className="text-sm text-muted-foreground text-pretty">No coverage data.</div>)}
                </>);
        }
        else {
            return (<div className="text-sm text-muted-foreground text-pretty">No dashboard data.</div>);
        }
    }
})()}
            </div>
          </ScrollArea>
        </DialogContent>
      </Dialog>

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

      {/* Create item dialog */}
      <Dialog open={createItemOpen} onOpenChange={(open) => setCreateItemOpen(open)}>
        <DialogContent className="max-w-3xl">
          <DialogHeader>
            <DialogTitle>新建 Evidence Item</DialogTitle>
            <DialogDescription className="text-pretty">
              先用检索找到证据切片，再将选中的引用保存为 <span className="font-mono">reference_sources</span>。
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <div className="space-y-1">
                <Label htmlFor="item-query">Query</Label>
                <Input
                  id="item-query"
                  value={newQuery}
                  onChange={(e) => setNewQuery(e.target.value)}
                  placeholder="输入要标注/回归的查询…"
                />
              </div>
              <div className="space-y-1">
                <Label htmlFor="item-expected">Expected Answer（可选）</Label>
                <Input
                  id="item-expected"
                  value={newExpected}
                  onChange={(e) => setNewExpected(e.target.value)}
                  placeholder="用于人工对照（可留空）"
                />
              </div>
            </div>

            <div className="space-y-1">
              <Label htmlFor="item-notes">Notes（可选）</Label>
              <Textarea
                id="item-notes"
                value={newNotes}
                onChange={(e) => setNewNotes(e.target.value)}
                placeholder="记录为什么这些引用是 Ground Truth / 边界条件 / 预期召回方式…"
                rows={2}
              />
            </div>

            <Tabs value={createItemTab} onValueChange={(v) => setCreateItemTab(v as any)}>
              <TabsList>
                <TabsTrigger value="retrieve">检索选择</TabsTrigger>
                <TabsTrigger value="import">导入 Evidence Pack</TabsTrigger>
              </TabsList>

              <TabsContent value="retrieve" className="mt-3 space-y-3">
                <div className="flex flex-col md:flex-row gap-3 md:items-end">
                  <div className="w-full md:w-[220px]">
                    <div className="text-xs text-muted-foreground mb-1">Retrieval Profile</div>
                    <Select value={profile} onValueChange={(v) => setProfile(v as RetrievalProfile)}>
                      <SelectTrigger className="h-9">
                        <SelectValue placeholder="选择 profile" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="recall50">recall50 (默认)</SelectItem>
                        <SelectItem value="coverage80">coverage80</SelectItem>
                        <SelectItem value="recall20">recall20</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>

                  <Button className="gap-2" onClick={() => detachPromise(runRetrieve())} disabled={retrieving || !newQuery.trim() || !datasetId}>
                    {retrieving ? <Loader2 className="size-4 animate-spin motion-reduce:animate-none" aria-hidden="true" /> : <Search className="size-4" aria-hidden="true" />}
                    运行检索
                  </Button>

                  <Button
                    variant="outline"
                    className="gap-2"
                    onClick={applyRetrieveSuggestions}
                    disabled={retrieving || !retrieveRes || suggestedRetrieveChunkIds.length === 0}
                  >
                    Suggest ({suggestedRetrieveChunkIds.length})
                  </Button>

                  <div className="ml-auto text-xs text-muted-foreground font-mono tabular-nums">
                    已选 {selectedChunkIds.length}
                  </div>
                </div>

                {retrieveError ? <div className="text-xs text-destructive text-pretty">{retrieveError}</div> : null}

                {expectedNeedles.length ? (
                  <div className="flex flex-wrap items-center gap-1 text-xs text-muted-foreground">
                    <span className="font-mono">needles:</span>
                    {expectedNeedles.slice(0, 10).map((n) => (
                      <Badge key={`needle:${n}`} variant="secondary" className="text-[10px] font-mono">
                        {n}
                      </Badge>
                    ))}
                  </div>
                ) : null}

                <Panel className="p-3">
                  <ScrollArea className="h-[320px] pr-2">
                    <div className="space-y-2">
                      {/* eslint-disable-next-line no-nested-ternary */}
                      {retrieveRes ? (
                        retrieveRanked.length ? (
                          retrieveRanked.map((r) => {
                            const c = r.citation
                            const assistScore = r.score
                            const hits = r.hits || []
                            const chunkId = String(c.chunk_id || '')
                            const checked = !!chunkId && selectedChunkIds.includes(chunkId)
                            return (
                              <div key={chunkId || `${c.document_id}:${c.chunk_index}`} className="rounded-lg border border-border/60 p-2">
                                <div className="flex items-start gap-2">
                                  <Checkbox
                                    checked={checked}
                                    onCheckedChange={() => toggleChunkSelection(chunkId, 'retrieve')}
                                    aria-label="选择该引用"
                                    disabled={!chunkId}
                                  />
                                  <div className="min-w-0 flex-1">
                                    <div className="flex items-start justify-between gap-3">
                                      <div className="min-w-0">
                                        <div className="text-xs font-mono text-foreground truncate">
                                          {c.document_name || String(c.document_id).slice(0, 8)}
                                        </div>
                                        <div className="mt-1 text-xs text-muted-foreground font-mono tabular-nums">
                                          score {citationScoreLabel(c)}
                                          {typeof c.page_number === 'number' ? ` · P.${c.page_number}` : null}
                                          {typeof c.chunk_index === 'number' ? ` · #${c.chunk_index}` : null}
                                        </div>
                                      </div>
                                      <div className="flex items-center gap-2">
                                        {assistScore > 0 ? (
                                          <Badge variant="secondary" className="font-mono text-[10px] tabular-nums">
                                            hit {assistScore}
                                          </Badge>
                                        ) : null}
                                        {chunkId ? (
                                          <Badge variant="outline" className="font-mono text-[10px]">
                                            {chunkId.slice(0, 8)}
                                          </Badge>
                                        ) : (
                                          <Badge variant="destructive" className="font-mono text-[10px]">
                                            missing chunk_id
                                          </Badge>
                                        )}
                                      </div>
                                    </div>
                                    <div className="mt-2 text-xs text-muted-foreground line-clamp-3 text-pretty">
                                      {c.chunk_content}
                                    </div>
                                    {hits.length ? (
                                      <div className="mt-2 flex flex-wrap gap-1">
                                        {hits.slice(0, 4).map((h) => (
                                          <Badge key={`hit:${chunkId || String(c.document_id)}:${h}`} variant="outline" className="text-[10px] font-mono">
                                            {h}
                                          </Badge>
                                        ))}
                                      </div>
                                    ) : null}
                                  </div>
                                </div>
                              </div>
                            )
                          })
                        ) : (
                          <div className="text-sm text-muted-foreground text-pretty">无 citations。</div>
                        )
                      ) : (
                        <div className="text-sm text-muted-foreground text-pretty">运行检索后在此勾选 Ground Truth 引用。</div>
                      )}
                    </div>
                  </ScrollArea>
                </Panel>
              </TabsContent>

              <TabsContent value="import" className="mt-3 space-y-3">
                <div className="flex items-center gap-2">
                  <input
                    ref={fileInputRef}
                    type="file"
                    accept="application/json,.json"
                    className="hidden"
                    onChange={(e) => {
                      const file = e.target.files?.[0]
                      if (file) detachPromise(handlePickPackFile(file))
                    }}
                  />
                  <Button
                    variant="outline"
                    className="gap-2"
                    onClick={() => fileInputRef.current?.click()}
                  >
                    <FileUp className="size-4" aria-hidden="true" />
                    选择 JSON
                  </Button>
                  {importPack ? (
                    <div className="text-xs text-muted-foreground font-mono truncate">
                      pack version {String(importPack?.version ?? '?')} · citations {Array.isArray(importCitations) ? importCitations.length : 0}
                    </div>
                  ) : (
                    <div className="text-xs text-muted-foreground text-pretty">上传 Evidence Pack（来自检索预览导出）。</div>
                  )}

                  <div className="ml-auto text-xs text-muted-foreground font-mono tabular-nums">
                    已选 {importSelectedChunkIds.length}
                  </div>
                </div>

                {importError ? <div className="text-xs text-destructive text-pretty">{importError}</div> : null}

                <Panel className="p-3">
                  <ScrollArea className="h-[320px] pr-2">
                    <div className="space-y-2">
                      {/* eslint-disable-next-line no-nested-ternary */}
                      {importPack ? (
                        importCitations.length ? (
                          importCitations.map((c) => {
                            const chunkId = String(c.chunk_id || '')
                            const checked = !!chunkId && importSelectedChunkIds.includes(chunkId)
                            return (
                              <div key={chunkId || `${c.document_id}:${c.chunk_index}`} className="rounded-lg border border-border/60 p-2">
                                <div className="flex items-start gap-2">
                                  <Checkbox
                                    checked={checked}
                                    onCheckedChange={() => toggleChunkSelection(chunkId, 'import')}
                                    aria-label="选择该引用"
                                    disabled={!chunkId}
                                  />
                                  <div className="min-w-0 flex-1">
                                    <div className="flex items-start justify-between gap-3">
                                      <div className="min-w-0">
                                        <div className="text-xs font-mono text-foreground truncate">
                                          {c.document_name || String(c.document_id).slice(0, 8)}
                                        </div>
                                        <div className="mt-1 text-xs text-muted-foreground font-mono tabular-nums">
                                          score {citationScoreLabel(c)}
                                          {typeof c.page_number === 'number' ? ` · P.${c.page_number}` : null}
                                          {typeof c.chunk_index === 'number' ? ` · #${c.chunk_index}` : null}
                                        </div>
                                      </div>
                                      {chunkId ? (
                                        <Badge variant="outline" className="font-mono text-[10px]">
                                          {chunkId.slice(0, 8)}
                                        </Badge>
                                      ) : (
                                        <Badge variant="destructive" className="font-mono text-[10px]">
                                          missing chunk_id
                                        </Badge>
                                      )}
                                    </div>
                                    <div className="mt-2 text-xs text-muted-foreground line-clamp-3 text-pretty">
                                      {c.chunk_content}
                                    </div>
                                  </div>
                                </div>
                              </div>
                            )
                          })
                        ) : (
                          <div className="text-sm text-muted-foreground text-pretty">pack 中没有 citations。</div>
                        )
                      ) : (
                        <div className="text-sm text-muted-foreground text-pretty">导入后在此勾选 Ground Truth 引用。</div>
                      )}
                    </div>
                  </ScrollArea>
                </Panel>
              </TabsContent>
            </Tabs>
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setCreateItemOpen(false)}>
              取消
            </Button>
            <Button
              onClick={() => detachPromise(handleCreateItem())}
              disabled={creatingItem || !selectedSuiteId || !newQuery.trim()}
            >
              {creatingItem ? <Loader2 className="size-4 animate-spin motion-reduce:animate-none mr-2" aria-hidden="true" /> : null}
              创建 Item（draft）
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Why missed? dialog (per EvidenceItem) */}
      <Dialog
        open={whyMissedOpen}
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
      >
        <DialogContent className="max-w-5xl overflow-hidden">
          <DialogHeader>
            <DialogTitle>Why missed?</DialogTitle>
            <DialogDescription className="text-pretty">
              对比 <span className="font-mono">reference_sources</span>（Ground Truth）与“当前检索结果”，并附带 Drift Audit（引用指针是否已漂移）。
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4">
            <div className="flex flex-col md:flex-row md:items-end gap-3">
              <div className="w-full md:w-[220px]">
                <div className="text-xs text-muted-foreground mb-1">Retrieval Profile</div>
                <Select value={whyMissedProfile} onValueChange={(v) => setWhyMissedProfile(v as RetrievalProfile)}>
                  <SelectTrigger className="h-9">
                    <SelectValue placeholder="选择 profile" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="recall50">recall50 (默认)</SelectItem>
                    <SelectItem value="coverage80">coverage80</SelectItem>
                    <SelectItem value="recall20">recall20</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              <Button
                className="gap-2"
                onClick={() => detachPromise(runWhyMissedRetrieve())}
                disabled={whyMissedRetrieving || !datasetId || !selectedItem?.query}
              >
                {whyMissedRetrieving ? (
                  <Loader2 className="size-4 animate-spin motion-reduce:animate-none" aria-hidden="true" />
                ) : (
                  <Search className="size-4" aria-hidden="true" />
                )}
                运行检索
              </Button>

              <Button
                variant="outline"
                className="gap-2"
                onClick={() => detachPromise(loadWhyMissedDrift())}
                disabled={whyMissedDriftLoading || !selectedSuiteId || !selectedItem?.id}
                title="Load drift audit details for this suite and filter to the selected item"
              >
                {whyMissedDriftLoading ? (
                  <Loader2 className="size-4 animate-spin motion-reduce:animate-none" aria-hidden="true" />
                ) : (
                  <RefreshCw className="size-4" aria-hidden="true" />
                )}
                Drift Audit
              </Button>

              <Button
                variant="outline"
                className="gap-2"
                onClick={exportWhyMissedReport}
                disabled={!whyMissedReport}
                title="Export a JSON report (PII-minimized except for query text)."
              >
                <Download className="size-4" aria-hidden="true" />
                导出 JSON
              </Button>

              <div className="ml-auto text-xs text-muted-foreground font-mono tabular-nums">
                {selectedItem?.id ? `item ${String(selectedItem.id).slice(0, 8)}` : null}
                {whyMissedRanRetrieve ? ` · citations ${whyMissedCitations.length}` : null}
              </div>
            </div>

            {whyMissedError ? <div className="text-xs text-destructive text-pretty">{whyMissedError}</div> : null}
            {whyMissedDriftError ? <div className="text-xs text-destructive text-pretty">{whyMissedDriftError}</div> : null}

            {whyMissedReport ? (
              <div className="flex flex-wrap gap-2 text-xs">
                <Badge variant="outline" className="font-mono tabular-nums">
                  refs {whyMissedReport.summary.total_references}
                </Badge>
                <Badge variant="soft" className="font-mono tabular-nums">
                  retrieved {whyMissedReport.summary.retrieved_references}
                </Badge>
                <Badge variant="destructive" className="font-mono tabular-nums">
                  missed {whyMissedReport.summary.missing_references}
                </Badge>
                <Badge variant="secondary" className="font-mono tabular-nums">
                  drifted {whyMissedReport.summary.drifted_references}
                </Badge>
              </div>
            ) : (
              <div className="text-xs text-muted-foreground text-pretty">先运行检索，再查看 “missed / drifted / retrieved” 解释。</div>
            )}

            <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
              <Panel className="p-3">
                <div className="text-xs font-medium text-muted-foreground mb-2">Ground Truth（reference_sources）</div>
                <ScrollArea className="h-[420px] pr-2">
                  <div className="space-y-2">
                    {(() => {
    if (selectedItem) {
        if (whyMissedReport) {
            return (whyMissedReport.references.map((r) => {
                const status = r.status;
                const statusLabel = (() => {
                    if (status === 'retrieved') {
                        return `hit #${r.retrieval?.rank ?? '?'}`;
                    }
                    else {
                        if (status === 'drifted') {
                            return `drift:${String(r.drift?.reason || 'unknown')}`;
                        }
                        else {
                            if (status === 'missing') {
                                return 'missed';
                            }
                            else {
                                return 'unknown';
                            }
                        }
                    }
                })();
                const statusVariant = (() => {
                    if (status === 'retrieved') {
                        return 'soft';
                    }
                    else {
                        if (status === 'missing') {
                            return 'destructive';
                        }
                        else {
                            if (status === 'drifted') {
                                return 'secondary';
                            }
                            else {
                                return 'outline';
                            }
                        }
                    }
                })();
                return (<div key={r.chunk_id} className="rounded-lg border border-border/60 p-2">
                            <div className="flex items-start justify-between gap-3">
                              <div className="min-w-0">
                                <div className="flex flex-wrap items-center gap-2">
                                  <Badge variant={statusVariant as any} className="font-mono text-[10px]">
                                    {statusLabel}
                                  </Badge>
                                  <div className="text-xs font-mono text-foreground truncate">
                                    {String(r.document_id || '').slice(0, 8)}:{String(r.chunk_id || '').slice(0, 8)}
                                  </div>
                                </div>
                                {r.label ? <div className="mt-1 text-xs text-muted-foreground line-clamp-1 text-pretty">{r.label}</div> : null}
                                {r.retrieval ? (<div className="mt-1 text-[11px] text-muted-foreground font-mono tabular-nums">
                                    {r.retrieval.hit_type ? `${r.retrieval.hit_type}` : 'hit'} · rank {r.retrieval.rank}
                                    {typeof r.retrieval.score === 'number' ? ` · score ${r.retrieval.score.toFixed(4)}` : null}
                                  </div>) : null}
                                {r.hints?.document_hit_rank || r.hints?.chunk_index_hit_rank ? (<div className="mt-2 flex flex-wrap gap-1">
                                    {r.hints?.document_hit_rank ? (<Badge variant="outline" className="font-mono text-[10px]">
                                        doc@{r.hints.document_hit_rank}
                                      </Badge>) : null}
                                    {r.hints?.chunk_index_hit_rank ? (<Badge variant="outline" className="font-mono text-[10px]">
                                        idx@{r.hints.chunk_index_hit_rank}
                                      </Badge>) : null}
                                  </div>) : null}
                              </div>
                              {typeof r.chunk_index === 'number' ? (<div className="text-[11px] text-muted-foreground font-mono tabular-nums flex-shrink-0">
                                  #{r.chunk_index}
                                </div>) : null}
                            </div>
                          </div>);
            }));
        }
        else {
            return (<div className="text-sm text-muted-foreground text-pretty">运行检索后展示对照结果。</div>);
        }
    }
    else {
        return (<div className="text-sm text-muted-foreground text-pretty">未选择 Item。</div>);
    }
})()}
                  </div>
                </ScrollArea>
              </Panel>

              <Panel className="p-3">
                <div className="text-xs font-medium text-muted-foreground mb-2">Retrieved Citations（当前检索结果）</div>
                <ScrollArea className="h-[420px] pr-2">
                  <div className="space-y-2">
                    {(() => {
    if (whyMissedRanRetrieve) {
        if (whyMissedCitations.length) {
            return (whyMissedCitations.slice(0, 80).map((c, idx) => {
                const docId = String((c as any)?.document_id || '').trim();
                const chunkId = String((c as any)?.chunk_id || '').trim();
                const isRefDoc = !!docId && whyMissedRefDocIds.has(docId);
                const isRefChunk = !!chunkId && whyMissedRefChunkIds.has(chunkId);
                const score = (c.retrieval_score ?? c.rerank_score ?? c.relevance_score ?? c.vector_score ?? c.bm25_score) as any;
                return (<div key={chunkId || `${docId}:${idx}`} className={cn('rounded-lg border p-2', (() => {
                        if (isRefChunk) {
                            return 'border-primary/50 bg-primary/5';
                        }
                        else {
                            if (isRefDoc) {
                                return 'border-border/60 bg-muted/20';
                            }
                            else {
                                return 'border-border/60';
                            }
                        }
                    })())}>
                            <div className="flex items-start justify-between gap-3">
                              <div className="min-w-0">
                                <div className="flex flex-wrap items-center gap-2">
                                  <div className="text-xs font-mono text-foreground truncate">
                                    #{idx + 1} {c.document_name || docId.slice(0, 8)}
                                  </div>
                                  {isRefChunk ? (<Badge variant="soft" className="font-mono text-[10px]">
                                      ref_chunk
                                    </Badge>) : null}
                                  {isRefDoc && !isRefChunk ? (<Badge variant="outline" className="font-mono text-[10px]">
                                      ref_doc
                                    </Badge>) : null}
                                </div>
                                <div className="mt-1 text-[11px] text-muted-foreground font-mono tabular-nums">
                                  {String((c as any)?.hit_type || 'hit')} · score {Number(score || 0).toFixed(4)}
                                  {typeof (c as any)?.page_number === 'number' ? ` · P.${(c as any).page_number}` : null}
                                  {typeof (c as any)?.chunk_index === 'number' ? ` · #${(c as any).chunk_index}` : null}
                                </div>
                              </div>
                              {chunkId ? (<Badge variant="outline" className="font-mono text-[10px]">
                                  {chunkId.slice(0, 8)}
                                </Badge>) : null}
                            </div>
                            {c.chunk_content ? (<div className="mt-2 text-xs text-muted-foreground line-clamp-3 text-pretty">
                                {c.chunk_content}
                              </div>) : null}
                          </div>);
            }));
        }
        else {
            return (<div className="text-sm text-muted-foreground text-pretty">无 citations。</div>);
        }
    }
    else {
        return (<div className="text-sm text-muted-foreground text-pretty">先点击“运行检索”。</div>);
    }
})()}
                  </div>
                </ScrollArea>
                {whyMissedRanRetrieve && whyMissedCitations.length > 80 ? (
                  <div className="mt-2 text-xs text-muted-foreground font-mono">
                    showing first 80 of {whyMissedCitations.length}
                  </div>
                ) : null}
              </Panel>
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  )
}
