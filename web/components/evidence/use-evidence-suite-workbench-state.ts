'use client'

import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, useSyncExternalStore } from 'react'
import { toast } from 'sonner'
import { getAuthSessionKey, subscribeAuthSession } from '@/lib/auth-storage'

import type { Dataset, EvidenceItem, EvidenceItemCreate, EvidenceSuite } from '@/types'
import { datasetApi, evidenceApi, feedbackApi, ragApi } from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'
import { buildWhyMissedReport, parseReferenceDriftDetails, type ReferenceDriftDetail } from '@/lib/evidence-why-missed'
import { extractEvidenceNeedles, rankEvidenceCitations } from '@/lib/evidence-suggestions'
import type { EvidenceCitation } from '@/lib/evidence-citations'
import { parseSuiteDashboard, type SuiteDashboardSnapshot } from '@/lib/evidence-dashboard'
import { parseHardcaseDiscovery, type HardcaseSnapshot } from '@/lib/evidence-hardcases'
import { coerceOneOf } from '@/lib/one-of'
import { detachPromise } from '@/lib/utils'

import {
  EMPTY_CITATIONS,
  RETRIEVAL_PROFILE_VALUES,
  buildReferenceSources,
  downloadJson,
  evidenceStatusBadgeVariant,
  parseEvidenceImportPack,
  parseEvidenceRetrieveResult,
  safeIsoForFilename,
  type EvidenceImportPack,
  type EvidenceRetrieveResult,
  type RetrievalProfile,
} from './evidence-suite-workbench-utils'

function useRequestIntent(key: string | null, sessionKey: string) {
  const ref = useRef({ key, sessionKey, sequence: 0, pending: new Set<string>() })
  useLayoutEffect(() => {
    ref.current = { key, sessionKey, sequence: 0, pending: new Set<string>() }
    return () => {
      ref.current = { key: null, sessionKey, sequence: 0, pending: new Set<string>() }
    }
  }, [key, sessionKey])
  return useMemo(() => ({ key, sessionKey, ref }), [key, sessionKey])
}

function sameOwner(binding: ReturnType<typeof useRequestIntent>) {
  const intent = binding.ref.current
  return () =>
    intent.key !== null &&
    intent.key === binding.key &&
    intent.sessionKey === binding.sessionKey &&
    binding.ref.current === intent &&
    getAuthSessionKey() === intent.sessionKey
}

function latestRequest(binding: ReturnType<typeof useRequestIntent>) {
  const isCurrent = sameOwner(binding)
  if (!isCurrent()) return () => false
  const intent = binding.ref.current
  const sequence = ++intent.sequence
  return () => isCurrent() && intent.sequence === sequence
}

function startOperation(binding: ReturnType<typeof useRequestIntent>, name: string) {
  const isCurrent = sameOwner(binding)
  const intent = binding.ref.current
  if (!isCurrent() || intent.pending.has(name)) return null
  intent.pending.add(name)
  return { isCurrent, finish: () => intent.pending.delete(name) }
}

export function useEvidenceSuiteWorkbenchState(datasetId: string, options?: { initialFeedbackId?: string }) {
  const sessionKey = useSyncExternalStore(subscribeAuthSession, getAuthSessionKey, getAuthSessionKey)
  const [datasetError, setDatasetError] = useState<string | null>(null)
  const [dataset, setDataset] = useState<Dataset | null>(null)
  const [datasetLoading, setDatasetLoading] = useState(false)

  const [suites, setSuites] = useState<EvidenceSuite[]>([])
  const [suitesLoading, setSuitesLoading] = useState(false)
  const [suitesError, setSuitesError] = useState<string | null>(null)
  const [suiteQuery, setSuiteQuery] = useState('')
  const [includeArchivedSuites, setIncludeArchivedSuites] = useState(false)

  const [selectedSuiteId, setSelectedSuiteId] = useState<string>('')
  const selectedSuite = useMemo(
    () => suites.find((suite) => suite.id === selectedSuiteId) ?? null,
    [selectedSuiteId, suites],
  )

  const [items, setItems] = useState<EvidenceItem[]>([])
  const [itemsLoading, setItemsLoading] = useState(false)
  const [itemsError, setItemsError] = useState<string | null>(null)
  const [itemQuery, setItemQuery] = useState('')
  const [statusFilter, setStatusFilter] = useState<string>('__all__')

  const [selectedItemId, setSelectedItemId] = useState<string>('')
  const selectedItem = useMemo(() => items.find((item) => item.id === selectedItemId) ?? null, [items, selectedItemId])

  const [whyMissedOpen, setWhyMissedOpen] = useState(false)
  const [whyMissedProfile, setWhyMissedProfile] = useState<RetrievalProfile>('recall50')
  const [whyMissedRanRetrieve, setWhyMissedRanRetrieve] = useState(false)
  const [whyMissedRetrieving, setWhyMissedRetrieving] = useState(false)
  const [whyMissedError, setWhyMissedError] = useState<string | null>(null)
  const [whyMissedCitations, setWhyMissedCitations] = useState<EvidenceCitation[]>([])
  const [whyMissedDriftLoading, setWhyMissedDriftLoading] = useState(false)
  const [whyMissedDriftError, setWhyMissedDriftError] = useState<string | null>(null)
  const [whyMissedDriftedRefs, setWhyMissedDriftedRefs] = useState<ReferenceDriftDetail[]>([])
  const [whyMissedDriftComplete, setWhyMissedDriftComplete] = useState(false)

  const [dashboardOpen, setDashboardOpen] = useState(false)
  const [dashboardLoading, setDashboardLoading] = useState(false)
  const [dashboardError, setDashboardError] = useState<string | null>(null)
  const [dashboardSnapshot, setDashboardSnapshot] = useState<SuiteDashboardSnapshot | null>(null)
  const [dashboardIncludeArchived, setDashboardIncludeArchived] = useState(false)

  const [hardcaseOpen, setHardcaseOpen] = useState(false)
  const [hardcaseLoading, setHardcaseLoading] = useState(false)
  const [hardcaseError, setHardcaseError] = useState<string | null>(null)
  const [hardcaseSnapshot, setHardcaseSnapshot] = useState<HardcaseSnapshot | null>(null)
  const [hardcaseMaxRating, setHardcaseMaxRating] = useState<number>(2)
  const [hardcaseIncludeExisting, setHardcaseIncludeExisting] = useState(false)
  const [hardcaseMaxCandidates, setHardcaseMaxCandidates] = useState<number>(50)
  const [hardcaseTags, setHardcaseTags] = useState<string[]>(['hardcase'])

  const [convertingFeedbackIds, setConvertingFeedbackIds] = useState<ReadonlySet<string>>(() => new Set())
  const [feedbackErrors, setFeedbackErrors] = useState<ReadonlyMap<string, string>>(() => new Map())
  const [pendingFeedbackId, setPendingFeedbackId] = useState<string>(() =>
    options?.initialFeedbackId === undefined ? '' : options.initialFeedbackId.trim(),
  )

  const [createSuiteOpen, setCreateSuiteOpen] = useState(false)
  const [suiteName, setSuiteName] = useState('')
  const [suiteDesc, setSuiteDesc] = useState('')
  const [suiteTags, setSuiteTags] = useState<string[]>([])
  const [creatingSuite, setCreatingSuite] = useState(false)
  const [createSuiteError, setCreateSuiteError] = useState<string | null>(null)

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
  const [importingPack, setImportingPack] = useState(false)
  const [importSelectedChunkIds, setImportSelectedChunkIds] = useState<string[]>([])
  const fileInputRef = useRef<HTMLInputElement | null>(null)

  const [importingQAFaq, setImportingQAFaq] = useState(false)
  const qaFaqInputRef = useRef<HTMLInputElement | null>(null)

  const [creatingItem, setCreatingItem] = useState(false)
  const [createItemError, setCreateItemError] = useState<string | null>(null)
  const [exportingSuite, setExportingSuite] = useState(false)
  const [syncingSuite, setSyncingSuite] = useState(false)
  const [syncNeedsRefresh, setSyncNeedsRefresh] = useState(false)
  const syncReceipt = useRef<Awaited<ReturnType<typeof evidenceApi.syncSuiteToRegression>> | null>(null)
  const [itemActions, setItemActions] = useState<ReadonlyMap<string, 'review' | 'approve' | 'archive'>>(() => new Map())
  const itemAction = itemActions.get(selectedItemId) ?? null

  const datasetOwner = useRequestIntent(datasetId, sessionKey)
  const suiteOwner = useRequestIntent(JSON.stringify([datasetId, selectedSuiteId]), sessionKey)
  const itemOwner = useRequestIntent(JSON.stringify([datasetId, selectedSuiteId, selectedItemId]), sessionKey)
  const createSuiteOwner = useRequestIntent(createSuiteOpen ? datasetId : null, sessionKey)
  const createItemOwner = useRequestIntent(
    createItemOpen ? JSON.stringify([datasetId, selectedSuiteId]) : null,
    sessionKey,
  )
  const datasetRead = useRequestIntent(datasetId, sessionKey)
  const suitesRead = useRequestIntent(JSON.stringify([datasetId, includeArchivedSuites]), sessionKey)
  const itemsRead = useRequestIntent(JSON.stringify([datasetId, selectedSuiteId]), sessionKey)
  const dashboardRead = useRequestIntent(
    dashboardOpen ? JSON.stringify([datasetId, selectedSuiteId, dashboardIncludeArchived]) : null,
    sessionKey,
  )
  const hardcaseRead = useRequestIntent(
    hardcaseOpen
      ? JSON.stringify([datasetId, selectedSuiteId, hardcaseMaxRating, hardcaseIncludeExisting, hardcaseMaxCandidates])
      : null,
    sessionKey,
  )
  const retrieveRead = useRequestIntent(
    createItemOpen ? JSON.stringify([datasetId, selectedSuiteId, newQuery, profile]) : null,
    sessionKey,
  )
  const importRead = useRequestIntent(createItemOpen ? JSON.stringify([datasetId, selectedSuiteId]) : null, sessionKey)
  const driftRead = useRequestIntent(
    whyMissedOpen
      ? JSON.stringify([
          datasetId,
          selectedSuiteId,
          selectedItemId,
          selectedItem?.updated_at,
          selectedItem?.status,
          items.length,
          itemsLoading,
          itemsError,
        ])
      : null,
    sessionKey,
  )
  const whyRetrieveRead = useRequestIntent(
    whyMissedOpen
      ? JSON.stringify([datasetId, selectedSuiteId, selectedItemId, selectedItem?.query, whyMissedProfile])
      : null,
    sessionKey,
  )
  useLayoutEffect(() => {
    setDataset(null)
    setDatasetError(null)
    setSuites([])
    setSelectedSuiteId('')
    setSuitesError(null)
    setDatasetLoading(false)
    setSuitesLoading(false)
    setCreatingSuite(false)
  }, [datasetId, sessionKey])
  useLayoutEffect(() => {
    setItems([])
    setItemsError(null)
    setItemsLoading(false)
    setSelectedItemId('')
    setCreatingItem(false)
    setImportingQAFaq(false)
    setConvertingFeedbackIds(new Set())
    setFeedbackErrors(new Map())
    setExportingSuite(false)
    setSyncingSuite(false)
    setSyncNeedsRefresh(false)
    syncReceipt.current = null
    setItemActions(new Map())
  }, [datasetId, selectedSuiteId, sessionKey])
  useLayoutEffect(() => {
    setCreatingSuite(false)
    setCreateSuiteError(null)
  }, [datasetId, sessionKey, createSuiteOpen])
  useLayoutEffect(() => {
    setCreatingItem(false)
    setCreateItemError(null)
    setImportPack(null)
    setImportError(null)
    setImportSelectedChunkIds([])
    setImportingPack(false)
  }, [datasetId, selectedSuiteId, createItemOpen, sessionKey])
  useLayoutEffect(() => {
    setRetrieveRes(null)
    setRetrieveError(null)
    setRetrieving(false)
    setSelectedChunkIds([])
  }, [datasetId, selectedSuiteId, newQuery, profile, createItemOpen, sessionKey])
  useLayoutEffect(() => {
    setWhyMissedCitations([])
    setWhyMissedError(null)
    setWhyMissedRanRetrieve(false)
    setWhyMissedRetrieving(false)
  }, [datasetId, selectedSuiteId, selectedItemId, selectedItem?.query, whyMissedProfile, whyMissedOpen, sessionKey])
  useLayoutEffect(() => {
    setWhyMissedDriftedRefs([])
    setWhyMissedDriftError(null)
    setWhyMissedDriftLoading(false)
    setWhyMissedDriftComplete(false)
  }, [
    datasetId,
    selectedSuiteId,
    selectedItemId,
    selectedItem?.updated_at,
    selectedItem?.status,
    items.length,
    itemsLoading,
    itemsError,
    whyMissedOpen,
    sessionKey,
  ])

  useLayoutEffect(() => {
    setDashboardSnapshot(null)
    setDashboardError(null)
    setDashboardLoading(dashboardOpen && selectedSuiteId.length > 0)
  }, [datasetId, selectedSuiteId, dashboardOpen, sessionKey])
  useLayoutEffect(() => {
    setHardcaseSnapshot(null)
    setHardcaseError(null)
    setHardcaseLoading(hardcaseOpen && selectedSuiteId.length > 0)
  }, [datasetId, selectedSuiteId, hardcaseOpen, sessionKey])
  const filteredSuites = useMemo(() => {
    const query = suiteQuery.trim().toLowerCase()
    if (!query) return suites
    return suites.filter((suite) => {
      const haystack = [suite.name, suite.description, suite.tags?.join(' ')].join(' ').toLowerCase()
      return haystack.includes(query)
    })
  }, [suiteQuery, suites])

  const filteredItems = useMemo(() => {
    const query = itemQuery.trim().toLowerCase()
    const filter = statusFilter
    return items
      .filter((item) => (filter === '__all__' ? true : item.status === filter))
      .filter((item) => {
        if (!query) return true
        const haystack = [item.query, item.notes]
          .filter((value) => value !== null)
          .join(' ')
          .toLowerCase()
        return haystack.includes(query)
      })
  }, [items, itemQuery, statusFilter])

  const loadDataset = useCallback(async () => {
    const isCurrent = latestRequest(datasetRead)
    if (!isCurrent()) return

    if (!datasetId) return
    setDatasetLoading(true)
    setDatasetError(null)
    try {
      const nextDataset = await datasetApi.get(datasetId)
      if (!isCurrent()) return

      setDataset(nextDataset)
    } catch (error: unknown) {
      if (!isCurrent()) return

      setDatasetError(formatApiError(error, '加载数据集失败'))
    } finally {
      if (isCurrent()) {
        setDatasetLoading(false)
      }
    }
  }, [datasetId, datasetRead])

  const loadSuites = useCallback(async (): Promise<boolean> => {
    const isCurrent = latestRequest(suitesRead)
    if (!isCurrent()) return false

    if (!datasetId) return false
    setSuitesLoading(true)
    setSuitesError(null)
    try {
      const next: EvidenceSuite[] = []
      let skip = 0
      while (true) {
        const page = await evidenceApi.listSuites({
          dataset_id: datasetId,
          include_archived: includeArchivedSuites,
          skip,
          limit: 200,
        })
        if (!isCurrent()) return false
        if (page.items === undefined) throw new Error('证据集响应缺少条目集合')
        next.push(...page.items)
        if (next.length >= page.total) break
        if (page.items.length === 0) throw new Error('证据集分页读取提前结束')
        skip += page.items.length
      }
      setSuites(next)
      setSelectedSuiteId((current) => (next.some((suite) => suite.id === current) ? current : (next[0]?.id ?? '')))
      return true
    } catch (error: unknown) {
      if (!isCurrent()) return false

      setSuitesError(formatApiError(error, '加载 Evidence Suites 失败'))
      return false
    } finally {
      if (isCurrent()) {
        setSuitesLoading(false)
      }
    }
  }, [datasetId, includeArchivedSuites, suitesRead])

  const loadItems = useCallback(async (): Promise<boolean> => {
    const isCurrent = latestRequest(itemsRead)
    if (!isCurrent()) return false

    if (!selectedSuiteId) {
      setItems([])
      setItemsError(null)
      return true
    }
    setItemsLoading(true)
    setItemsError(null)
    try {
      const next: EvidenceItem[] = []
      let skip = 0
      while (true) {
        const page = await evidenceApi.listItems(selectedSuiteId, { skip, limit: 200 })
        if (!isCurrent()) return false
        if (page.items === undefined) throw new Error('证据条目响应缺少条目集合')
        next.push(...page.items)
        if (next.length >= page.total) break
        if (page.items.length === 0) throw new Error('证据条目分页读取提前结束')
        skip += page.items.length
      }
      setItems(next)
      setSelectedItemId((current) => (current && !next.some((item) => item.id === current) ? '' : current))
      return true
    } catch (error: unknown) {
      if (!isCurrent()) return false

      setItemsError(formatApiError(error, '加载 Evidence Items 失败'))
      return false
    } finally {
      if (isCurrent()) {
        setItemsLoading(false)
      }
    }
  }, [selectedSuiteId, itemsRead])

  const loadDashboard = useCallback(async () => {
    const isCurrent = latestRequest(dashboardRead)
    if (!isCurrent()) return

    if (!selectedSuiteId) {
      setDashboardSnapshot(null)
      setDashboardError(null)
      return
    }
    setDashboardLoading(true)
    setDashboardError(null)
    try {
      const res = await evidenceApi.getSuiteDashboard(selectedSuiteId, {
        include_archived_items: dashboardIncludeArchived,
      })
      if (!isCurrent()) return

      setDashboardSnapshot({ data: parseSuiteDashboard(res), includeArchived: dashboardIncludeArchived })
    } catch (error: unknown) {
      if (!isCurrent()) return

      setDashboardError(formatApiError(error, '加载 Dashboard 失败'))
    } finally {
      if (isCurrent()) {
        setDashboardLoading(false)
      }
    }
  }, [dashboardIncludeArchived, selectedSuiteId, dashboardRead])

  const loadHardcases = useCallback(async () => {
    const isCurrent = latestRequest(hardcaseRead)
    if (!isCurrent()) return

    if (!selectedSuiteId) {
      setHardcaseSnapshot(null)
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
      if (!isCurrent()) return

      setHardcaseSnapshot({
        data: parseHardcaseDiscovery(res),
        maxRating: hardcaseMaxRating,
        includeExisting: hardcaseIncludeExisting,
        maxCandidates: hardcaseMaxCandidates,
      })
    } catch (error: unknown) {
      if (!isCurrent()) return

      setHardcaseError(formatApiError(error, '加载 Hardcase candidates 失败'))
    } finally {
      if (isCurrent()) {
        setHardcaseLoading(false)
      }
    }
  }, [hardcaseIncludeExisting, hardcaseMaxCandidates, hardcaseMaxRating, selectedSuiteId, hardcaseRead])

  const currentLoaders = useRef({
    suites: loadSuites,
    items: loadItems,
    dashboard: loadDashboard,
    hardcases: loadHardcases,
  })
  useLayoutEffect(() => {
    currentLoaders.current = {
      suites: loadSuites,
      items: loadItems,
      dashboard: loadDashboard,
      hardcases: loadHardcases,
    }
  }, [loadSuites, loadItems, loadDashboard, loadHardcases])
  const reloadSuites = useCallback(() => currentLoaders.current.suites(), [])
  const reloadItems = useCallback(() => currentLoaders.current.items(), [])
  const reloadDashboard = useCallback(() => currentLoaders.current.dashboard(), [])
  const reloadHardcases = useCallback(() => currentLoaders.current.hardcases(), [])

  const copyText = useCallback(
    async (label: string, text: string) => {
      const isCurrent = sameOwner(datasetOwner)
      try {
        if (navigator.clipboard === undefined) throw new Error('当前浏览器环境不支持剪贴板')
        await navigator.clipboard.writeText(text)
        if (isCurrent()) toast.success(`${label} 已复制`)
      } catch (error: unknown) {
        if (isCurrent()) toast.error(formatApiError(error, '复制失败'))
      }
    },
    [datasetOwner],
  )

  const handleConvertFeedbackToEvidence = useCallback(
    async (feedbackId: string, questionHash?: string, options?: { tags?: string[]; source?: string }) => {
      if (!selectedSuiteId || feedbackId.length === 0) return
      const operation = startOperation(suiteOwner, `convert-feedback:${feedbackId}`)
      if (operation === null) return
      const { isCurrent } = operation
      const sameItemSelection = sameOwner(itemOwner)
      setConvertingFeedbackIds((previous) => new Set(previous).add(feedbackId))
      setFeedbackErrors((previous) => {
        const next = new Map(previous)
        next.delete(feedbackId)
        return next
      })
      try {
        const created = await feedbackApi.toEvidenceItem(feedbackId, {
          suite_id: selectedSuiteId,
          tags: options?.tags ?? hardcaseTags,
          extra: { source: options?.source ?? 'hardcase_discovery', question_hash: questionHash },
        })
        if (!isCurrent()) return
        setItems((previous) => [created, ...previous.filter((item) => item.id !== created.id)])
        if (sameItemSelection()) setSelectedItemId(created.id)
        if (options?.source === 'chat_feedback_action') {
          setPendingFeedbackId((current) => (current === feedbackId ? '' : current))
        }
        toast.success('已创建证据条目（草稿）')
        if (statusFilter !== '__all__' && statusFilter !== created.status) setStatusFilter(created.status)
        detachPromise(currentLoaders.current.items())
        detachPromise(currentLoaders.current.suites())
        detachPromise(currentLoaders.current.hardcases())
      } catch (error: unknown) {
        if (!isCurrent()) return
        const message = formatApiError(error, '转为证据条目失败')
        setFeedbackErrors((previous) => new Map(previous).set(feedbackId, message))
      } finally {
        if (isCurrent())
          setConvertingFeedbackIds((previous) => {
            const next = new Set(previous)
            next.delete(feedbackId)
            return next
          })
        operation.finish()
      }
    },
    [hardcaseTags, selectedSuiteId, suiteOwner, itemOwner, statusFilter],
  )

  useEffect(() => {
    setPendingFeedbackId(options?.initialFeedbackId === undefined ? '' : options.initialFeedbackId.trim())
  }, [options?.initialFeedbackId])

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
    const operation = startOperation(createSuiteOwner, 'create-suite')
    if (operation === null) return
    const isCurrent = operation.isCurrent
    const sameSuiteSelection = sameOwner(suiteOwner)

    const name = suiteName.trim()
    if (!datasetId || name.length === 0) {
      operation.finish()
      return
    }
    setCreatingSuite(true)
    setCreateSuiteError(null)
    try {
      const suite = await evidenceApi.createSuite({
        dataset_id: datasetId,
        name,
        description: suiteDesc,
        tags: suiteTags,
        config: {},
      })
      if (!isCurrent()) return

      toast.success('已创建 Evidence Suite')
      setCreateSuiteOpen(false)
      setSuites((prev) => [suite, ...prev])
      if (sameSuiteSelection()) setSelectedSuiteId(suite.id)
      detachPromise(currentLoaders.current.suites())
    } catch (error: unknown) {
      if (!isCurrent()) return

      setCreateSuiteError(formatApiError(error, '创建证据集失败'))
    } finally {
      if (isCurrent()) {
        setCreatingSuite(false)
      }
      operation.finish()
    }
  }, [datasetId, suiteDesc, suiteName, suiteTags, createSuiteOwner, suiteOwner])

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
    const isCurrent = latestRequest(retrieveRead)
    if (!isCurrent()) return

    if (!datasetId) return
    const query = newQuery.trim()
    if (!query) return

    setRetrieving(true)
    setRetrieveError(null)
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
          answer_mode: 'llm',
        },
      })
      if (!isCurrent()) return

      const result = parseEvidenceRetrieveResult(res)
      setRetrieveRes(result)
      setSelectedChunkIds((selected) =>
        selected.filter((id) => result.citations.some((citation) => citation.chunk_id === id)),
      )
      if (res.has_evidence) toast.success('找到证据')
      else if (res.abstain_triggered)
        toast.warning(res.abstain_reason == null ? '检索已弃答' : `检索已弃答：${res.abstain_reason}`)
      else toast.message('未找到证据')
    } catch (error: unknown) {
      if (!isCurrent()) return

      setRetrieveError(formatApiError(error, '检索失败'))
    } finally {
      if (isCurrent()) {
        setRetrieving(false)
      }
    }
  }, [datasetId, newQuery, profile, retrieveRead])

  const toggleChunkSelection = useCallback((chunkId: string, mode: 'retrieve' | 'import') => {
    if (!chunkId) return
    if (mode === 'retrieve') {
      setSelectedChunkIds((prev) => {
        const next = new Set(prev)
        if (next.has(chunkId)) next.delete(chunkId)
        else next.add(chunkId)
        return Array.from(next)
      })
      return
    }
    setImportSelectedChunkIds((prev) => {
      const next = new Set(prev)
      if (next.has(chunkId)) next.delete(chunkId)
      else next.add(chunkId)
      return Array.from(next)
    })
  }, [])

  const handlePickPackFile = useCallback(
    async (file: File) => {
      const isCurrent = latestRequest(importRead)
      if (!isCurrent()) return

      setImportError(null)
      setImportingPack(true)
      try {
        const text = await file.text()
        if (!isCurrent()) return

        const parsed: unknown = JSON.parse(text)
        const payload = parseEvidenceImportPack(parsed)
        setImportPack(payload)
        setImportSelectedChunkIds(payload.selected_chunk_ids ?? [])
      } catch (error: unknown) {
        if (!isCurrent()) return

        setImportError(`解析失败：${formatApiError(error, '无法读取证据包')}`)
      } finally {
        if (isCurrent()) setImportingPack(false)
      }
    },
    [importRead],
  )

  const handleCreateItem = useCallback(async () => {
    if (!datasetId || !selectedSuiteId || !newQuery.trim()) return
    const operation = startOperation(createItemOwner, 'create-item')
    if (operation === null) return
    const { isCurrent } = operation
    const sameItemSelection = sameOwner(itemOwner)
    setCreatingItem(true)
    setCreateItemError(null)
    try {
      const source = createItemTab === 'retrieve' ? retrieveRes : importPack
      if (source === null) throw new Error('请先检索或导入证据')
      const selected = createItemTab === 'retrieve' ? selectedChunkIds : importSelectedChunkIds
      if (selected.length === 0) throw new Error('请至少选择 1 条引用')
      const references = buildReferenceSources(source.citations, new Set(selected))
      const createdFrom = createItemTab === 'retrieve' ? 'retrieve' : 'evidence_pack'
      const body: EvidenceItemCreate = {
        suite_id: selectedSuiteId,
        dataset_id: datasetId,
        query: newQuery.trim(),
        expected_answer: newExpected,
        notes: newNotes,
        reference_sources: references,
        retrieval_snapshot: { ...source, selected_chunk_ids: selected, created_from: createdFrom },
        rag_config_snapshot: {
          retrieval_profile: createItemTab === 'import' ? importPack?.retrieval_profile : profile,
          created_from: createdFrom,
        },
      }
      const created = await evidenceApi.createItem(selectedSuiteId, body)
      if (!isCurrent()) return
      setItems((previous) => [created, ...previous])
      if (sameItemSelection()) setSelectedItemId(created.id)
      if (statusFilter !== '__all__' && statusFilter !== created.status) setStatusFilter(created.status)
      setCreateItemOpen(false)
      toast.success('已创建证据条目（草稿）')
      detachPromise(currentLoaders.current.suites())
      detachPromise(currentLoaders.current.items())
    } catch (error: unknown) {
      if (isCurrent()) setCreateItemError(formatApiError(error, '创建证据条目失败'))
    } finally {
      if (isCurrent()) setCreatingItem(false)
      operation.finish()
    }
  }, [
    datasetId,
    selectedSuiteId,
    newQuery,
    createItemOwner,
    itemOwner,
    createItemTab,
    retrieveRes,
    importPack,
    selectedChunkIds,
    importSelectedChunkIds,
    newExpected,
    newNotes,
    profile,
    statusFilter,
  ])

  const handleImportQAFaq = useCallback(
    async (file: File) => {
      if (selectedSuite === null) return

      const name = file.name.toLowerCase()
      if (!name.endsWith('.csv') && !name.endsWith('.jsonl')) {
        toast.error('只支持导入 .csv / .jsonl')
        return
      }

      const operation = startOperation(suiteOwner, 'import-qa-faq')
      if (operation === null) return
      const { isCurrent } = operation
      setImportingQAFaq(true)
      try {
        const res = await evidenceApi.importItems(selectedSuite.id, file)
        if (!isCurrent()) return

        toast.success(
          `导入完成：解析 ${res.parsed}，新增 ${res.created}，跳过 ${res.skipped}，错误 ${res.errors.length}`,
        )
        detachPromise(currentLoaders.current.items())
        detachPromise(currentLoaders.current.suites())
      } catch (error: unknown) {
        if (!isCurrent()) return

        toast.error(formatApiError(error, '导入失败'))
      } finally {
        if (isCurrent()) {
          setImportingQAFaq(false)
        }
        operation.finish()
      }
    },
    [selectedSuite, suiteOwner],
  )

  const handleExportSuite = useCallback(async () => {
    if (selectedSuite === null) return
    const operation = startOperation(suiteOwner, 'export-suite')
    if (operation === null) return
    const { isCurrent } = operation
    setExportingSuite(true)
    try {
      const result = await evidenceApi.exportSuite(selectedSuite.id, { include_archived_items: false })
      if (!isCurrent()) return
      const name = selectedSuite.name.replaceAll(/[\\/:*?"<>|]+/g, '_').slice(0, 64)
      downloadJson(`${name}.${safeIsoForFilename(result.exported_at)}.json`, result)
      toast.success('已导出证据集')
    } catch (error: unknown) {
      if (isCurrent()) toast.error(formatApiError(error, '导出失败'))
    } finally {
      if (isCurrent()) setExportingSuite(false)
      operation.finish()
    }
  }, [selectedSuite, suiteOwner])

  const handleSyncSuite = useCallback(async () => {
    if (selectedSuite === null) return
    const operation = startOperation(suiteOwner, 'sync-suite')
    if (operation === null) return
    const { isCurrent } = operation
    setSyncingSuite(true)
    try {
      const result = syncReceipt.current ?? (await evidenceApi.syncSuiteToRegression(selectedSuite.id))
      if (!isCurrent()) return
      syncReceipt.current = result
      setSyncNeedsRefresh(true)
      const [suitesLoaded, itemsLoaded] = await Promise.all([
        currentLoaders.current.suites(),
        currentLoaders.current.items(),
      ])
      if (!isCurrent()) return
      if (!suitesLoaded || !itemsLoaded) throw new Error('同步已完成，列表刷新失败；重试将只刷新列表。')
      syncReceipt.current = null
      setSyncNeedsRefresh(false)
      const message = `同步完成：新增 ${result.created}，更新 ${result.updated}，跳过 ${result.skipped}`
      if (result.errors !== undefined && result.errors.length > 0)
        toast.warning(`${message}，错误 ${result.errors.length}`)
      else toast.success(message)
    } finally {
      if (isCurrent()) setSyncingSuite(false)
      operation.finish()
    }
  }, [selectedSuite, suiteOwner])

  const updateItemStatus = useCallback(
    async (itemId: string, action: 'review' | 'approve' | 'archive') => {
      const operation = startOperation(suiteOwner, `item-status:${itemId}`)
      if (operation === null) return
      const { isCurrent } = operation
      const sameItemSelection = sameOwner(itemOwner)
      setItemActions((previous) => new Map(previous).set(itemId, action))
      try {
        const request = {
          review: evidenceApi.reviewItem,
          approve: evidenceApi.approveItem,
          archive: evidenceApi.archiveItem,
        }[action]
        const updated = await request(itemId)
        if (!isCurrent()) return
        setItems((previous) => previous.map((item) => (item.id === itemId ? updated : item)))
        if (sameItemSelection()) toast.success({ review: '已提交复核', approve: '已通过', archive: '已归档' }[action])
        detachPromise(currentLoaders.current.suites())
        detachPromise(currentLoaders.current.items())
      } finally {
        if (isCurrent())
          setItemActions((previous) => {
            const next = new Map(previous)
            next.delete(itemId)
            return next
          })
        operation.finish()
      }
    },
    [suiteOwner, itemOwner],
  )

  const handleArchiveItem = useCallback((itemId: string) => updateItemStatus(itemId, 'archive'), [updateItemStatus])

  const handleReviewItem = useCallback(
    async (itemId: string) => {
      const sameItemSelection = sameOwner(itemOwner)
      try {
        await updateItemStatus(itemId, 'review')
      } catch (error: unknown) {
        if (sameItemSelection()) toast.error(formatApiError(error, '提交复核失败'))
      }
    },
    [updateItemStatus, itemOwner],
  )

  const handleApproveItem = useCallback(
    async (itemId: string) => {
      const sameItemSelection = sameOwner(itemOwner)
      try {
        await updateItemStatus(itemId, 'approve')
      } catch (error: unknown) {
        if (sameItemSelection()) toast.error(formatApiError(error, '通过失败'))
      }
    },
    [updateItemStatus, itemOwner],
  )

  const suiteCounts = selectedSuite?.item_counts

  const retrieveCitations = useMemo(() => retrieveRes?.citations ?? EMPTY_CITATIONS, [retrieveRes])
  const importCitations = useMemo(() => importPack?.citations ?? EMPTY_CITATIONS, [importPack])

  const expectedNeedles = useMemo(() => extractEvidenceNeedles(newExpected), [newExpected])
  const retrieveRanked = useMemo(
    () => rankEvidenceCitations(retrieveCitations, expectedNeedles),
    [expectedNeedles, retrieveCitations],
  )
  const suggestedRetrieveChunkIds = useMemo(() => {
    const out: string[] = []
    for (const ranked of retrieveRanked) {
      if (ranked.score <= 0) continue
      const chunkId = ranked.citation.chunk_id
      if (!chunkId || !ranked.citation.document_id) continue
      out.push(chunkId)
      if (out.length >= 8) break
    }
    return out
  }, [retrieveRanked])

  const applyRetrieveSuggestions = useCallback(() => {
    if (!suggestedRetrieveChunkIds.length) return
    setSelectedChunkIds((prev) => {
      const next = new Set(prev)
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
    const isCurrent = latestRequest(driftRead)
    if (!isCurrent()) return

    if (!selectedSuiteId) return
    if (!selectedItem?.id) return
    if (itemsLoading || itemsError !== null) return

    setWhyMissedDriftLoading(true)
    setWhyMissedDriftError(null)
    try {
      const audit = await evidenceApi.getSuiteDriftAudit(selectedSuiteId, {
        include_archived_items: true,
        include_details: true,
        details_limit: 2000,
        slice_top_n: 20,
      })
      if (!isCurrent()) return

      const details = parseReferenceDriftDetails(audit.drifted_references)
      const complete =
        audit.total_items === items.length &&
        audit.details_truncated === false &&
        audit.drift_references === details.length
      setWhyMissedDriftComplete(complete)
      if (!complete) setWhyMissedDriftError('漂移审计只覆盖部分条目或引用；未覆盖引用标记为待确认。')
      setWhyMissedDriftedRefs(details.filter((detail) => detail.item_id === selectedItem.id))
    } catch (error: unknown) {
      if (!isCurrent()) return

      setWhyMissedDriftError(formatApiError(error, '加载 Drift Audit 失败'))
    } finally {
      if (isCurrent()) {
        setWhyMissedDriftLoading(false)
      }
    }
  }, [selectedItem?.id, selectedSuiteId, driftRead, items.length, itemsLoading, itemsError])

  useEffect(() => {
    if (!whyMissedOpen) return
    detachPromise(loadWhyMissedDrift())
  }, [loadWhyMissedDrift, whyMissedOpen])

  const runWhyMissedRetrieve = useCallback(async () => {
    const isCurrent = latestRequest(whyRetrieveRead)
    if (!isCurrent()) return

    if (!datasetId) return
    if (!selectedItem?.query) return

    const query = selectedItem.query.trim()
    if (!query) return

    setWhyMissedRetrieving(true)
    setWhyMissedError(null)
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
          answer_mode: 'llm',
        },
      })
      if (!isCurrent()) return

      const nextCitations = parseEvidenceRetrieveResult(res).citations
      setWhyMissedCitations(nextCitations)
      setWhyMissedRanRetrieve(true)
      toast.success(`检索完成：citations=${nextCitations.length}`)
    } catch (error: unknown) {
      if (!isCurrent()) return

      setWhyMissedError(formatApiError(error, '检索失败'))
    } finally {
      if (isCurrent()) {
        setWhyMissedRetrieving(false)
      }
    }
  }, [datasetId, selectedItem?.query, whyMissedProfile, whyRetrieveRead])

  const whyMissedReport = useMemo(() => {
    if (!selectedItem) return null
    if (!whyMissedRanRetrieve) return null
    return buildWhyMissedReport({
      reference_sources: selectedItem.reference_sources ?? [],
      citations: whyMissedCitations,
      drifted_references: whyMissedDriftedRefs,
      drift_complete: whyMissedDriftComplete && !itemsLoading && itemsError === null,
    })
  }, [
    selectedItem,
    whyMissedCitations,
    whyMissedDriftedRefs,
    whyMissedRanRetrieve,
    whyMissedDriftComplete,
    itemsLoading,
    itemsError,
  ])

  const whyMissedRefDocIds = useMemo(() => {
    const ids = new Set<string>()
    for (const ref of selectedItem?.reference_sources ?? []) {
      ids.add(ref.document_id)
    }
    return ids
  }, [selectedItem?.reference_sources])

  const whyMissedRefChunkIds = useMemo(() => {
    const ids = new Set<string>()
    for (const ref of selectedItem?.reference_sources ?? []) {
      ids.add(ref.chunk_id)
    }
    return ids
  }, [selectedItem?.reference_sources])

  const exportWhyMissedReport = useCallback(() => {
    if (!selectedSuite?.id) return
    if (!selectedItem?.id) return
    if (!whyMissedReport) return

    const safeTs = safeIsoForFilename(new Date().toISOString())
    const suiteName = selectedSuite.name.replaceAll(/[\\/:*?"<>|]+/g, '_').slice(0, 64)
    const itemId = selectedItem.id.slice(0, 8)
    downloadJson(`${suiteName}.why-missed.${itemId}.${safeTs}.json`, {
      schema: 'mimirq.evidence_why_missed.v1',
      generated_at: new Date().toISOString(),
      suite_id: selectedSuite.id,
      item_id: selectedItem.id,
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
    createItemError,
    creatingSuite,
    createSuiteError,
    convertingFeedbackIds,
    feedbackErrors,
    copyText,
    dashboardSnapshot,
    dashboardError,
    dashboardIncludeArchived,
    dashboardLoading,
    dashboardOpen,
    dataset,
    datasetError,
    loadDataset,
    datasetId,
    datasetLoading,
    evidenceStatusBadgeVariant,
    expectedNeedles,
    exportWhyMissedReport,
    exportingSuite,
    syncingSuite,
    syncNeedsRefresh,
    itemAction,
    fileInputRef,
    filteredItems,
    filteredSuites,
    handleApproveItem,
    handleArchiveItem,
    handleConvertFeedbackToEvidence,
    handleCreateItem,
    handleCreateSuite,
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
    hardcaseSnapshot,
    hardcaseTags,
    importCitations,
    importError,
    importPack,
    importSelectedChunkIds,
    importingQAFaq,
    importingPack,
    includeArchivedSuites,
    itemQuery,
    itemsError,
    itemsLoading,
    loadDashboard: reloadDashboard,
    loadHardcases: reloadHardcases,
    loadItems: reloadItems,
    loadSuites: reloadSuites,
    loadWhyMissedDrift,
    newExpected,
    newNotes,
    newQuery,
    openCreateItem,
    openCreateSuite,
    pendingFeedbackId,
    openWhyMissed,
    profile,
    qaFaqInputRef,
    resetCreateSuiteForm,
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
    setIncludeArchivedSuites,
    setItemQuery,
    setNewExpected,
    setNewNotes,
    setNewQuery,
    setPendingFeedbackId,
    setProfile,
    setSelectedItemId,
    setSelectedSuiteId,
    setStatusFilter,
    setSuiteDesc,
    setSuiteName,
    setSuiteQuery,
    setSuiteTags,
    setWhyMissedOpen,
    setWhyMissedProfile,
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
