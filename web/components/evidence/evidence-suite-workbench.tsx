'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { toast } from 'sonner'
import { BarChart3, Download, FileUp, Loader2, Plus, RefreshCw, Search, ShieldCheck, X } from 'lucide-react'

import type { Citation, Dataset, EvidenceItem, EvidenceItemCreate, EvidenceItemStatus, EvidenceSuite, EvidenceSuiteDashboard, ReferenceSource } from '@/types'
import { datasetApi, evidenceApi, ragApi } from '@/lib/api-client'
import { formatApiError } from '@/lib/api-errors'
import { extractEvidenceNeedles, rankEvidenceCitations } from '@/lib/evidence-suggestions'
import { cn } from '@/lib/utils'

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
  return (ts || new Date().toISOString()).replace(/[:.]/g, '-')
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

export function EvidenceSuiteWorkbench({ datasetId: datasetIdRaw }: { datasetId: string }) {
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

  // Suite dashboard
  const [dashboardOpen, setDashboardOpen] = useState(false)
  const [dashboardLoading, setDashboardLoading] = useState(false)
  const [dashboardError, setDashboardError] = useState<string | null>(null)
  const [dashboard, setDashboard] = useState<EvidenceSuiteDashboard | null>(null)
  const [dashboardIncludeArchived, setDashboardIncludeArchived] = useState(false)
  const dashboardThroughput = dashboard?.throughput
  const dashboardCoverage = dashboard?.coverage

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
  const [retrieveRes, setRetrieveRes] = useState<any | null>(null)
  const [selectedChunkIds, setSelectedChunkIds] = useState<string[]>([])

  const [importPack, setImportPack] = useState<any | null>(null)
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

  useEffect(() => {
    void loadDataset()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [datasetId])

  useEffect(() => {
    void loadSuites()
  }, [loadSuites])

  useEffect(() => {
    void loadItems()
  }, [loadItems])

  useEffect(() => {
    if (!dashboardOpen) return
    void loadDashboard()
  }, [dashboardOpen, loadDashboard])

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
      citations = (retrieveRes?.citations || []) as Citation[]
      selected = selectedChunkIds || []
      retrievalSnapshot = {
        ...retrieveRes,
        selected_chunk_ids: selected,
        created_from: 'retrieve',
      }
      ragSnapshot = { retrieval_profile: profile, created_from: 'retrieve' }
    } else {
      citations = (importPack?.citations || []) as Citation[]
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
      void loadSuites()
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
        void loadItems()
        void loadSuites()
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
      const name = (selectedSuite.name || 'evidence-suite').replace(/[\\/:*?"<>|]+/g, '_').slice(0, 64)
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
      const name = (selectedSuite.name || 'evidence-suite').replace(/[\\/:*?"<>|]+/g, '_').slice(0, 64)
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
      void loadItems()
      void loadSuites()
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
      void loadSuites()
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
      void loadSuites()
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
      void loadSuites()
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

  const retrieveCitations = useMemo(() => ((retrieveRes?.citations as Citation[] | undefined) ?? EMPTY_CITATIONS), [retrieveRes])
  const importCitations = useMemo(() => ((importPack?.citations as Citation[] | undefined) ?? EMPTY_CITATIONS), [importPack])

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
              onClick={() => void loadSuites()}
              disabled={suitesLoading}
            >
              <RefreshCw className={cn('size-4', suitesLoading ? 'animate-spin motion-reduce:animate-none' : '')} aria-hidden="true" />
            </Button>
          </div>

          <div className="mt-3 flex items-center justify-between gap-3 text-xs text-muted-foreground">
            <label className="inline-flex items-center gap-2 select-none">
              <Checkbox
                checked={includeArchivedSuites}
                onCheckedChange={(v) => setIncludeArchivedSuites(Boolean(v))}
                aria-label="包含已归档 suites"
              />
              包含已归档
            </label>
            <span className="font-mono tabular-nums">{filteredSuites.length}</span>
          </div>

          {suitesError ? (
            <div className="mt-3 text-xs text-destructive text-pretty">{suitesError}</div>
          ) : null}

          <div className="mt-3">
            <ScrollArea className="h-[420px] pr-2">
              <div className="space-y-2">
                {suitesLoading ? (
                  <div className="text-xs text-muted-foreground">加载中…</div>
                ) : filteredSuites.length ? (
                  filteredSuites.map((s) => {
                    const active = s.id === selectedSuiteId
                    const counts = (s as any)?.item_counts || {}
                    const total = Number(counts?.total || 0)
                    const approved = Number(counts?.approved || 0)
                    return (
                      <button
                        key={s.id}
                        type="button"
                        className={cn(
                          'w-full text-left rounded-lg border px-3 py-2 transition-colors',
                          active ? 'border-primary/40 bg-primary/5' : 'border-border hover:bg-muted/30'
                        )}
                        onClick={() => {
                          setSelectedSuiteId(String(s.id))
                          setSelectedItemId('')
                        }}
                      >
                        <div className="flex items-start justify-between gap-3">
                          <div className="min-w-0">
                            <div className="text-sm font-medium text-foreground truncate">{s.name}</div>
                            {s.description ? (
                              <div className="mt-0.5 text-xs text-muted-foreground line-clamp-2 text-pretty">
                                {s.description}
                              </div>
                            ) : null}
                          </div>
                          <div className="flex flex-col items-end gap-1 flex-shrink-0">
                            <Badge variant="outline" className="font-mono tabular-nums">
                              {total}
                            </Badge>
                            {approved ? (
                              <Badge variant="soft" className="font-mono tabular-nums">
                                approved {approved}
                              </Badge>
                            ) : null}
                          </div>
                        </div>
                        {Array.isArray(s.tags) && s.tags.length ? (
                          <div className="mt-2 flex flex-wrap gap-1">
                            {(s.tags || []).slice(0, 3).map((t) => (
                              <Badge key={t} variant="secondary" className="text-[10px] font-mono">
                                {t}
                              </Badge>
                            ))}
                            {s.tags.length > 3 ? (
                              <span className="text-[10px] text-muted-foreground font-mono">+{s.tags.length - 3}</span>
                            ) : null}
                          </div>
                        ) : null}
                      </button>
                    )
                  })
                ) : (
                  <div className="text-xs text-muted-foreground text-pretty">
                    暂无 Suite。点击「新建」创建一个 Evidence Suite。
                  </div>
                )}
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
                onClick={() => void loadItems()}
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
                {!selectedSuiteId ? (
                  <div className="text-xs text-muted-foreground text-pretty">选择一个 Suite 后即可查看/创建 Items。</div>
                ) : itemsLoading ? (
                  <div className="text-xs text-muted-foreground">加载中…</div>
                ) : filteredItems.length ? (
                  filteredItems.map((it) => {
                    const active = it.id === selectedItemId
                    return (
                      <button
                        key={it.id}
                        type="button"
                        className={cn(
                          'w-full text-left rounded-lg border px-3 py-2 transition-colors',
                          active ? 'border-primary/40 bg-primary/5' : 'border-border hover:bg-muted/30'
                        )}
                        onClick={() => setSelectedItemId(String(it.id))}
                      >
                        <div className="flex items-start justify-between gap-3">
                          <div className="min-w-0">
                            <div className="text-sm font-medium text-foreground line-clamp-2 text-pretty">
                              {it.query}
                            </div>
                            {it.notes ? (
                              <div className="mt-1 text-xs text-muted-foreground line-clamp-2 text-pretty">{it.notes}</div>
                            ) : null}
                          </div>
                          <Badge variant={evidenceStatusBadgeVariant(it.status)} className="font-mono text-[10px] uppercase">
                            {it.status}
                          </Badge>
                        </div>
                        <div className="mt-2 flex items-center justify-between gap-3 text-[11px] text-muted-foreground font-mono tabular-nums">
                          <span>refs: {Array.isArray(it.reference_sources) ? it.reference_sources.length : 0}</span>
                          <span>{String(it.updated_at || '').slice(0, 19).replace('T', ' ')}</span>
                        </div>
                      </button>
                    )
                  })
                ) : (
                  <div className="text-xs text-muted-foreground text-pretty">暂无 Items。点击「新建 Item」创建。</div>
                )}
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
                  if (f) void handleImportQAFaq(f)
                }}
              />
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
                    <AlertDialogAction onClick={() => void handleSyncSuite()} disabled={!selectedSuite?.id}>
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

          {!selectedItem ? (
            <div className="text-sm text-muted-foreground text-pretty">
              选择一个 Item 查看详情。你可以在 draft 状态下修改内容，然后提交 review → approve → sync。
            </div>
          ) : (
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
                    <Button size="sm" variant="outline" className="gap-2" onClick={() => void handleReviewItem(String(selectedItem.id))}>
                      <Search className="size-4" aria-hidden="true" />
                      Review
                    </Button>
                  ) : null}

                  {selectedItem.status === 'reviewed' ? (
                    <Button size="sm" className="gap-2" onClick={() => void handleApproveItem(String(selectedItem.id))}>
                      <ShieldCheck className="size-4" aria-hidden="true" />
                      Approve
                    </Button>
                  ) : null}

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
                        <AlertDialogAction onClick={() => void handleArchiveItem(String(selectedItem.id))}>归档</AlertDialogAction>
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
                      (selectedItem.reference_sources || []).map((r, idx) => (
                        <div key={`${r.chunk_id}:${idx}`} className="rounded-md border border-border/60 p-2">
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
          )}
        </Panel>
      </div>

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
            <label className="inline-flex items-center gap-2 select-none text-xs text-muted-foreground">
              <Checkbox
                checked={dashboardIncludeArchived}
                onCheckedChange={(v) => setDashboardIncludeArchived(Boolean(v))}
                aria-label="Include archived items"
              />
              include archived items
            </label>

            <div className="sm:ml-auto flex items-center gap-2">
              {dashboard ? (
                <div className="text-xs text-muted-foreground font-mono tabular-nums">
                  generated {String(dashboard.generated_at || '').slice(0, 19).replace('T', ' ')}
                </div>
              ) : null}
              <Button
                variant="outline"
                size="sm"
                className="gap-2"
                onClick={() => void loadDashboard()}
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
              {dashboardLoading ? (
                <div className="text-sm text-muted-foreground flex items-center gap-2">
                  <Loader2 className="size-4 animate-spin motion-reduce:animate-none" aria-hidden="true" />
                  loading…
                </div>
              ) : dashboard ? (
                <>
                  {dashboardThroughput ? (
                    <div>
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
                    </div>
                  ) : (
                    <div className="text-sm text-muted-foreground text-pretty">No throughput data.</div>
                  )}

                  <Separator />

                  {dashboardCoverage ? (
                    <>
                      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                        <Panel className="p-3">
                          <div className="text-xs font-medium text-muted-foreground mb-2">Language coverage</div>
                          <div className="space-y-1">
                            {(dashboardCoverage.language || []).map((b) => (
                              <div key={`lang:${b.key}`} className="flex items-center justify-between gap-3 text-xs">
                                <div className="min-w-0 truncate font-mono">{b.key}</div>
                                <div className="flex items-center gap-3 font-mono tabular-nums text-muted-foreground">
                                  <span>refs {b.references}</span>
                                  <span>items {b.items}</span>
                                </div>
                              </div>
                            ))}
                          </div>
                        </Panel>

                        <Panel className="p-3">
                          <div className="text-xs font-medium text-muted-foreground mb-2">File type coverage</div>
                          <div className="space-y-1">
                            {(dashboardCoverage.file_type || []).map((b) => (
                              <div key={`ft:${b.key}`} className="flex items-center justify-between gap-3 text-xs">
                                <div className="min-w-0 truncate font-mono">{b.key}</div>
                                <div className="flex items-center gap-3 font-mono tabular-nums text-muted-foreground">
                                  <span>refs {b.references}</span>
                                  <span>items {b.items}</span>
                                </div>
                              </div>
                            ))}
                          </div>
                        </Panel>

                        <Panel className="p-3">
                          <div className="text-xs font-medium text-muted-foreground mb-2">Quality bucket coverage</div>
                          <div className="space-y-1">
                            {(dashboardCoverage.quality_bucket || []).map((b) => (
                              <div key={`qb:${b.key}`} className="flex items-center justify-between gap-3 text-xs">
                                <div className="min-w-0 truncate font-mono">{b.key}</div>
                                <div className="flex items-center gap-3 font-mono tabular-nums text-muted-foreground">
                                  <span>refs {b.references}</span>
                                  <span>items {b.items}</span>
                                </div>
                              </div>
                            ))}
                          </div>
                        </Panel>

                        <Panel className="p-3">
                          <div className="text-xs font-medium text-muted-foreground mb-2">Channel (hit_type) coverage</div>
                          <div className="space-y-1">
                            {(dashboardCoverage.channel || []).map((b) => (
                              <div key={`ch:${b.key}`} className="flex items-center justify-between gap-3 text-xs">
                                <div className="min-w-0 truncate font-mono">{b.key}</div>
                                <div className="flex items-center gap-3 font-mono tabular-nums text-muted-foreground">
                                  <span>refs {b.references}</span>
                                  <span>items {b.items}</span>
                                </div>
                              </div>
                            ))}
                          </div>
                        </Panel>
                      </div>

                      <Panel className="p-3">
                        <div className="text-xs font-medium text-muted-foreground mb-2">
                          Heatmap: language × file_type (unique items)
                        </div>
                        {dashboardCoverage.heatmaps?.['language_x_file_type'] ? (
                          <div className="overflow-x-auto">
                            {(() => {
                              const hm = dashboardCoverage.heatmaps['language_x_file_type']
                              const x = hm?.x || []
                              const y = hm?.y || []
                              const z = hm?.z || []
                              let max = 0
                              for (const row of z) {
                                for (const v of row) {
                                  const n = Number(v) || 0
                                  if (n > max) max = n
                                }
                              }
                              const cols = x.length
                              return (
                                <div
                                  className="grid gap-px rounded-lg overflow-hidden border border-border/60 bg-border/60"
                                  style={{ gridTemplateColumns: `120px repeat(${cols}, minmax(72px, 1fr))` }}
                                >
                                  <div className="bg-muted/40 px-2 py-1 text-[11px] font-mono text-muted-foreground">
                                    lang \\ ft
                                  </div>
                                  {x.map((ft) => (
                                    <div
                                      key={`hm-x:${ft}`}
                                      className="bg-muted/40 px-2 py-1 text-[11px] font-mono truncate"
                                    >
                                      {ft}
                                    </div>
                                  ))}
                                  {y.map((lang, rowIdx) => (
                                    <div key={`hm-row:${lang}`} className="contents">
                                      <div className="bg-muted/30 px-2 py-1 text-[11px] font-mono text-muted-foreground truncate">
                                        {lang}
                                      </div>
                                      {x.map((ft, colIdx) => {
                                        const v = Number(z?.[rowIdx]?.[colIdx] ?? 0) || 0
                                        const ratio = max > 0 ? v / max : 0
                                        const cellBg =
                                          v === 0
                                            ? 'bg-muted/20'
                                            : ratio >= 0.75
                                              ? 'bg-primary/30'
                                              : ratio >= 0.5
                                                ? 'bg-primary/20'
                                                : ratio >= 0.25
                                                  ? 'bg-primary/10'
                                                  : 'bg-primary/5'
                                        return (
                                          <div
                                            key={`hm-cell:${lang}:${ft}`}
                                            className={cn('px-2 py-1 text-[11px] font-mono tabular-nums text-center', cellBg)}
                                          >
                                            {v}
                                          </div>
                                        )
                                  })}
                                </div>
                              ))}
                            </div>
                          )
                        })()}
                      </div>
                    ) : (
                      <div className="text-xs text-muted-foreground">No heatmap data.</div>
                    )}
                  </Panel>
                    </>
                  ) : (
                    <div className="text-sm text-muted-foreground text-pretty">No coverage data.</div>
                  )}
                </>
              ) : (
                <div className="text-sm text-muted-foreground text-pretty">No dashboard data.</div>
              )}
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
            <Button onClick={() => void handleCreateSuite()} disabled={creatingSuite || !suiteName.trim()}>
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

                  <Button className="gap-2" onClick={() => void runRetrieve()} disabled={retrieving || !newQuery.trim() || !datasetId}>
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
                      if (file) void handlePickPackFile(file)
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
              onClick={() => void handleCreateItem()}
              disabled={creatingItem || !selectedSuiteId || !newQuery.trim()}
            >
              {creatingItem ? <Loader2 className="size-4 animate-spin motion-reduce:animate-none mr-2" aria-hidden="true" /> : null}
              创建 Item（draft）
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
