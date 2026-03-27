'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { toast } from 'sonner'

import type {
  Citation,
  Dataset,
  EvidenceHardcaseDiscovery,
  EvidenceItem,
  EvidenceItemCreate,
  EvidenceReferenceDriftDetail,
  EvidenceSuite,
  EvidenceSuiteDashboard,
  JsonObject,
} from '@/types'
import { datasetApi, evidenceApi, feedbackApi, ragApi } from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'
import { buildWhyMissedReport } from '@/lib/evidence-why-missed'
import { extractEvidenceNeedles, rankEvidenceCitations } from '@/lib/evidence-suggestions'
import { coerceOneOf } from '@/lib/one-of'
import { detachPromise } from '@/lib/utils'

import {
  EMPTY_CITATIONS,
  RETRIEVAL_PROFILE_VALUES,
  asDatasetId,
  buildReferenceSources,
  downloadBlob,
  downloadJson,
  evidenceStatusBadgeVariant,
  getErrorMessage,
  normalizeImportPack,
  normalizeRetrieveResult,
  safeIsoForFilename,
  type EvidenceImportPack,
  type EvidenceRetrieveResult,
  type RetrievalProfile,
} from './evidence-suite-workbench-utils'

export function useEvidenceSuiteWorkbenchState(datasetIdRaw: string) {
  const datasetId = asDatasetId(datasetIdRaw)

  const [dataset, setDataset] = useState<Dataset | null>(null)
  const [datasetLoading, setDatasetLoading] = useState(false)

  const [suites, setSuites] = useState<EvidenceSuite[]>([])
  const [suitesLoading, setSuitesLoading] = useState(false)
  const [suitesError, setSuitesError] = useState<string | null>(null)
  const [suiteQuery, setSuiteQuery] = useState('')
  const [includeArchivedSuites, setIncludeArchivedSuites] = useState(false)

  const [selectedSuiteId, setSelectedSuiteId] = useState<string>('')
  const selectedSuite = useMemo(() => suites.find((suite) => suite.id === selectedSuiteId) || null, [selectedSuiteId, suites])

  const [items, setItems] = useState<EvidenceItem[]>([])
  const [itemsLoading, setItemsLoading] = useState(false)
  const [itemsError, setItemsError] = useState<string | null>(null)
  const [itemQuery, setItemQuery] = useState('')
  const [statusFilter, setStatusFilter] = useState<string>('__all__')

  const [selectedItemId, setSelectedItemId] = useState<string>('')
  const selectedItem = useMemo(() => items.find((item) => item.id === selectedItemId) || null, [items, selectedItemId])

  const [whyMissedOpen, setWhyMissedOpen] = useState(false)
  const [whyMissedProfile, setWhyMissedProfile] = useState<RetrievalProfile>('recall50')
  const [whyMissedRanRetrieve, setWhyMissedRanRetrieve] = useState(false)
  const [whyMissedRetrieving, setWhyMissedRetrieving] = useState(false)
  const [whyMissedError, setWhyMissedError] = useState<string | null>(null)
  const [whyMissedCitations, setWhyMissedCitations] = useState<Citation[]>([])
  const [whyMissedDriftLoading, setWhyMissedDriftLoading] = useState(false)
  const [whyMissedDriftError, setWhyMissedDriftError] = useState<string | null>(null)
  const [whyMissedDriftedRefs, setWhyMissedDriftedRefs] = useState<EvidenceReferenceDriftDetail[]>([])

  const [dashboardOpen, setDashboardOpen] = useState(false)
  const [dashboardLoading, setDashboardLoading] = useState(false)
  const [dashboardError, setDashboardError] = useState<string | null>(null)
  const [dashboard, setDashboard] = useState<EvidenceSuiteDashboard | null>(null)
  const [dashboardIncludeArchived, setDashboardIncludeArchived] = useState(false)

  const [hardcaseOpen, setHardcaseOpen] = useState(false)
  const [hardcaseLoading, setHardcaseLoading] = useState(false)
  const [hardcaseError, setHardcaseError] = useState<string | null>(null)
  const [hardcaseRes, setHardcaseRes] = useState<EvidenceHardcaseDiscovery | null>(null)
  const [hardcaseMaxRating, setHardcaseMaxRating] = useState<number>(2)
  const [hardcaseIncludeExisting, setHardcaseIncludeExisting] = useState(false)
  const [hardcaseMaxCandidates, setHardcaseMaxCandidates] = useState<number>(50)
  const [hardcaseTags, setHardcaseTags] = useState<string[]>(['hardcase'])

  const [convertingFeedbackId, setConvertingFeedbackId] = useState<string>('')

  const [createSuiteOpen, setCreateSuiteOpen] = useState(false)
  const [suiteName, setSuiteName] = useState('')
  const [suiteDesc, setSuiteDesc] = useState('')
  const [suiteTags, setSuiteTags] = useState<string[]>([])
  const [creatingSuite, setCreatingSuite] = useState(false)

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
    const query = suiteQuery.trim().toLowerCase()
    const base = suites || []
    if (!query) return base
    return base.filter((suite) => {
      const haystack = `${suite.name || ''} ${(suite.description || '')} ${(suite.tags || []).join(' ')}`.toLowerCase()
      return haystack.includes(query)
    })
  }, [suiteQuery, suites])

  const filteredItems = useMemo(() => {
    const query = itemQuery.trim().toLowerCase()
    const filter = statusFilter
    return (items || [])
      .filter((item) => (filter === '__all__' ? true : String(item.status || '').toLowerCase() === filter))
      .filter((item) => {
        if (!query) return true
        const haystack = `${item.query || ''} ${(item.notes || '')}`.toLowerCase()
        return haystack.includes(query)
      })
  }, [items, itemQuery, statusFilter])

  const loadDataset = useCallback(async () => {
    if (!datasetId) return
    setDatasetLoading(true)
    try {
      const nextDataset = await datasetApi.get(datasetId)
      setDataset(nextDataset)
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
      } else if (selectedSuiteId && !next.some((suite) => suite.id === selectedSuiteId)) {
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
      if (selectedItemId && !next.some((item) => item.id === selectedItemId)) {
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

  const handleConvertFeedbackToEvidence = useCallback(
    async (feedbackId: string, questionHash?: string) => {
      if (!selectedSuiteId) return
      const id = String(feedbackId || '').trim()
      if (!id) return
      setConvertingFeedbackId(id)
      try {
        const created = await feedbackApi.toEvidenceItem(id, {
          suite_id: selectedSuiteId,
          tags: hardcaseTags,
          extra: { source: 'hardcase_discovery', question_hash: questionHash || undefined },
        })
        const createdId = String(created?.id || '').trim()
        toast.success('已创建 draft EvidenceItem')
        await loadItems()
        await loadHardcases()
        if (createdId) setSelectedItemId(createdId)
      } catch (error: unknown) {
        toast.error(formatApiError(error, '转为 EvidenceItem 失败'))
      } finally {
        setConvertingFeedbackId('')
      }
    },
    [hardcaseTags, loadHardcases, loadItems, selectedSuiteId]
  )

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
    const query = newQuery.trim()
    if (!query) return

    setRetrieving(true)
    setRetrieveError(null)
    setRetrieveRes(null)
    setSelectedChunkIds([])
    try {
      const res = await ragApi.retrieveEvidence({
        query,
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
        const next = new Set(prev || [])
        if (next.has(chunkId)) next.delete(chunkId)
        else next.add(chunkId)
        return Array.from(next)
      })
      return
    }
    setImportSelectedChunkIds((prev) => {
      const next = new Set(prev || [])
      if (next.has(chunkId)) next.delete(chunkId)
      else next.add(chunkId)
      return Array.from(next)
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
      retrievalSnapshot = retrieveRes
        ? {
            ...retrieveRes,
            selected_chunk_ids: selected,
            created_from: 'retrieve',
          }
        : {
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
        retrieval_profile: typeof importPack?.retrieval_profile === 'string' ? importPack.retrieval_profile : profile,
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
      setItems((prev) => (prev || []).map((item) => (item.id === itemId ? updated : item)))
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
      setItems((prev) => (prev || []).map((item) => (item.id === itemId ? updated : item)))
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
      setItems((prev) => (prev || []).map((item) => (item.id === itemId ? updated : item)))
      toast.success('已批准（approved）')
      detachPromise(loadSuites())
    } catch (error: unknown) {
      toast.error(formatApiError(error, '批准失败'))
    }
  }, [loadSuites])

  const suiteCounts = useMemo(() => {
    const counts = selectedSuite?.item_counts || null
    if (!counts) return null
    return {
      total: Number(counts.total || 0),
      draft: Number(counts.draft || 0),
      reviewed: Number(counts.reviewed || 0),
      approved: Number(counts.approved || 0),
      archived: Number(counts.archived || 0),
    }
  }, [selectedSuite?.item_counts])

  const retrieveCitations = useMemo(() => retrieveRes?.citations ?? EMPTY_CITATIONS, [retrieveRes])
  const importCitations = useMemo(() => importPack?.citations ?? EMPTY_CITATIONS, [importPack])

  const expectedNeedles = useMemo(() => extractEvidenceNeedles(newExpected), [newExpected])
  const retrieveRanked = useMemo(() => rankEvidenceCitations(retrieveCitations, expectedNeedles), [expectedNeedles, retrieveCitations])
  const suggestedRetrieveChunkIds = useMemo(() => {
    const out: string[] = []
    for (const ranked of retrieveRanked || []) {
      if (ranked.score <= 0) continue
      const chunkId = String(ranked.citation.chunk_id || '')
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
      for (const chunkId of suggestedRetrieveChunkIds) next.add(chunkId)
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

    const snapshotProfile = selectedItem?.rag_config_snapshot?.retrieval_profile
    const snapProfile = typeof snapshotProfile === 'string' ? snapshotProfile.trim() : ''
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
      setWhyMissedDriftedRefs(details.filter((detail) => String(detail?.item_id || '') === itemId))
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

    const query = String(selectedItem.query || '').trim()
    if (!query) return

    setWhyMissedRetrieving(true)
    setWhyMissedError(null)
    setWhyMissedRanRetrieve(false)
    setWhyMissedCitations([])
    try {
      const res = await ragApi.retrieveEvidence({
        query,
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
    for (const ref of selectedItem?.reference_sources || []) {
      const docId = String(ref.document_id || '').trim()
      if (docId) ids.add(docId)
    }
    return ids
  }, [selectedItem?.reference_sources])

  const whyMissedRefChunkIds = useMemo(() => {
    const ids = new Set<string>()
    for (const ref of selectedItem?.reference_sources || []) {
      const chunkId = String(ref.chunk_id || '').trim()
      if (chunkId) ids.add(chunkId)
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

  return {
    applyRetrieveSuggestions,
    createItemOpen,
    createItemTab,
    createSuiteOpen,
    creatingItem,
    creatingSuite,
    convertingFeedbackId,
    copyText,
    dashboard,
    dashboardError,
    dashboardIncludeArchived,
    dashboardLoading,
    dashboardOpen,
    dataset,
    datasetId,
    datasetLoading,
    evidenceStatusBadgeVariant,
    expectedNeedles,
    exportWhyMissedReport,
    fileInputRef,
    filteredItems,
    filteredSuites,
    handleApproveItem,
    handleArchiveItem,
    handleConvertFeedbackToEvidence,
    handleCreateItem,
    handleCreateSuite,
    handleExportLtrTraining,
    handleExportSuite,
    handleImportQAFaq,
    handlePickPackFile,
    handleReviewItem,
    handleSyncSuite,
    hardcaseError,
    hardcaseIncludeExisting,
    hardcaseLoading,
    hardcaseMaxCandidates,
    hardcaseMaxRating,
    hardcaseOpen,
    hardcaseRes,
    hardcaseTags,
    importCitations,
    importError,
    importPack,
    importSelectedChunkIds,
    importingQAFaq,
    includeArchivedSuites,
    itemQuery,
    itemsError,
    itemsLoading,
    loadDashboard,
    loadHardcases,
    loadItems,
    loadSuites,
    loadWhyMissedDrift,
    newExpected,
    newNotes,
    newQuery,
    openCreateItem,
    openCreateSuite,
    openWhyMissed,
    profile,
    qaFaqInputRef,
    resetCreateSuiteForm,
    retrieveCitations,
    retrieveError,
    retrieveRanked,
    retrieveRes,
    retrieving,
    runRetrieve,
    runWhyMissedRetrieve,
    selectedChunkIds,
    selectedItem,
    selectedItemId,
    selectedSuite,
    selectedSuiteId,
    setCreateItemOpen,
    setCreateItemTab,
    setCreateSuiteOpen,
    setDashboardError,
    setDashboardIncludeArchived,
    setDashboardOpen,
    setHardcaseError,
    setHardcaseIncludeExisting,
    setHardcaseMaxCandidates,
    setHardcaseMaxRating,
    setHardcaseOpen,
    setHardcaseTags,
    setImportSelectedChunkIds,
    setIncludeArchivedSuites,
    setItemQuery,
    setNewExpected,
    setNewNotes,
    setNewQuery,
    setProfile,
    setSelectedItemId,
    setSelectedSuiteId,
    setStatusFilter,
    setSuiteDesc,
    setSuiteName,
    setSuiteQuery,
    setSuiteTags,
    setWhyMissedCitations,
    setWhyMissedDriftError,
    setWhyMissedDriftedRefs,
    setWhyMissedOpen,
    setWhyMissedProfile,
    setWhyMissedRanRetrieve,
    setWhyMissedError,
    statusFilter,
    suggestedRetrieveChunkIds,
    suiteCounts,
    suiteDesc,
    suiteName,
    suiteQuery,
    suiteTags,
    suitesError,
    suitesLoading,
    toggleChunkSelection,
    whyMissedCitations,
    whyMissedDriftError,
    whyMissedDriftLoading,
    whyMissedOpen,
    whyMissedProfile,
    whyMissedRanRetrieve,
    whyMissedRefChunkIds,
    whyMissedRefDocIds,
    whyMissedReport,
    whyMissedRetrieving,
    whyMissedError,
  }
}

export type EvidenceSuiteWorkbenchState = ReturnType<typeof useEvidenceSuiteWorkbenchState>
