/**
 * ChunkList - 切片列表
 */
'use client'

import { AnimatePresence, motion, useReducedMotion } from 'framer-motion'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useVirtualizer } from '@tanstack/react-virtual'
import {
  Layers,
  Rows3,
  Loader2,
  AlertCircle,
  Search,
  Copy,
  Code2,
  X,
  Pencil,
  ChevronDown,
  ChevronRight,
  EyeOff,
  SlidersHorizontal,
} from 'lucide-react'
import { useTranslations } from 'next-intl'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { useChunkPreview } from '@/components/chunk-preview/context'
import { ChunkCard } from '../../chunk-card'
import { ChunkInspectorDialog } from '../../chunk-inspector-dialog'
import { chunkIsReviewed, chunkNeedsReview, isChunkOverrideDisabled, isChunkOverrideEdited, isJsonObject } from '@/components/chunk-preview/utils/metadata'
import type { ChunkPreviewItem, ChunkPreviewReviewSignals, JsonObject } from '@/types'
import { computeRoleIndices, roughEstimateTokens } from '@/components/chunk-preview/utils/review-signals'
import { getChunkSectionPath } from '@/components/chunk-preview/utils/sections'
import { buildChunkSearchIndex, searchChunkIndex, type ChunkSearchResult } from '@/components/chunk-preview/utils/retrieval-search'
import { rerankChunkSearchResults, type RerankedChunkSearchResult } from '@/components/chunk-preview/utils/reranker-sim'
import { writeClientStorage } from '@/lib/client-storage'
import { detachPromise } from '@/lib/utils'
import {
  ORIGINAL_PREVIEW_MODE_STORAGE_KEY,
  getStoredOriginalPreviewMode,
  shouldRevealPdfPreviewOnChunkSelect,
} from './pdf-dock'


const QUERY_DEBOUNCE_MS = 150
type SortMode = 'index' | 'length_desc' | 'length_asc'
type ViewMode = 'flat' | 'hierarchy'
type GroupMode = 'none' | 'section'
const PAGE_ALL_VALUE = '__mimirq_page_all__'
const PAGE_UNKNOWN_VALUE = '__mimirq_page_unknown__'
const SECTION_ALL_VALUE = '__mimirq_section_all__'
const SECTION_NONE_VALUE = '__mimirq_section_none__'

type DisplayRow =
  | {
      kind: 'chunk'
      chunk: ChunkPreviewItem
      index: number
      indent: 0 | 1
      groupKey?: string
      role?: 'parent' | 'child' | 'solo'
      childCountTotal?: number
      childCountVisible?: number
      isContext?: boolean
    }
  | {
      kind: 'section'
      key: string
      label: string
      count: number
    }

function toSignalSet(values: readonly number[] | undefined): Set<number> {
  const out = new Set<number>()
  for (const value of values || []) {
    const idx = Number(value)
    if (Number.isFinite(idx)) out.add(idx)
  }
  return out
}

function toSignalMap(values: ChunkPreviewReviewSignals['gap_before_by_index']): Map<number, number> {
  const out = new Map<number, number>()
  for (const [key, value] of Object.entries(values || {})) {
    const idx = Number(key)
    const n = Number(value)
    if (Number.isFinite(idx) && Number.isFinite(n)) out.set(idx, n)
  }
  return out
}

export function ChunkList() {
  const t = useTranslations('ChunkPreview')
  const {
    previewData,
    chunkOverrides,
    currentFile,
    hoveredChunkIndex,
    selectedChunkIndex,
    setHoveredChunkIndex,
    setSelectedChunkIndex,
    updateChunkOverride,
    toggleChunkDisabled,
    setChunksDisabled,
    clearChunkOverride,
    showOriginalPanel,
    setOriginalPanelVisible,
    isLoading,
    error,
    runPreview,
  } = useChunkPreview()
  const reduceMotion = useReducedMotion()
  const unit: 'chars' | 'tokens' = previewData?.params?.unit === 'tokens' ? 'tokens' : 'chars'
  const [queryInput, setQueryInput] = useState('')
  const [query, setQuery] = useState('')
  const [sortMode, setSortMode] = useState<SortMode>('index')
  const [viewMode, setViewMode] = useState<ViewMode>('flat')
  const [groupMode, setGroupMode] = useState<GroupMode>('none')
  const [collapsedGroups, setCollapsedGroups] = useState<Record<string, boolean>>({})
  const [pageFilter, setPageFilter] = useState<string>(PAGE_ALL_VALUE)
  const [sectionFilter, setSectionFilter] = useState<string>(SECTION_ALL_VALUE)
  const [filtersOpen, setFiltersOpen] = useState(false)
  const [retrieveOpen, setRetrieveOpen] = useState(false)
  const [retrieveQuery, setRetrieveQuery] = useState('')
  const [rerankEnabled, setRerankEnabled] = useState(false)
  const [rerankAlphaPct, setRerankAlphaPct] = useState(65)
  const [minLen, setMinLen] = useState<number>(0)
  const [maxLen, setMaxLen] = useState<number>(0)
  const [onlyShort, setOnlyShort] = useState(false)
  const [onlyDuplicate, setOnlyDuplicate] = useState(false)
  const [onlyEdited, setOnlyEdited] = useState(false)
  const [onlyDisabled, setOnlyDisabled] = useState(false)
  const [onlyGap, setOnlyGap] = useState(false)
  const [onlyOverlap, setOnlyOverlap] = useState(false)
  const [onlyNeedsReview, setOnlyNeedsReview] = useState(false)
  const [inspectorOpen, setInspectorOpen] = useState(false)
  const [inspectorIndex, setInspectorIndex] = useState<number | null>(null)
  const scrollRef = useRef<HTMLDivElement>(null)
  const searchRef = useRef<HTMLInputElement>(null)

  const isParentChildStrategy = previewData?.chunk_strategy === 'parent_child'
  const isHierarchyView = isParentChildStrategy && viewMode === 'hierarchy'
  const isSectionView = groupMode === 'section' && !isHierarchyView
  const supportsPdfDocking = useMemo(() => {
    const fileType = String(previewData?.file_type || '').toLowerCase()
    if (fileType === 'pdf') return true
    const name = String(currentFile?.name || '').toLowerCase()
    return name.endsWith('.pdf')
  }, [currentFile?.name, previewData?.file_type])

  const selectChunkIndex = useCallback(
    (nextIndex: number | null) => {
      if (
        shouldRevealPdfPreviewOnChunkSelect({
          nextIndex,
          showOriginalPanel,
          isPdf: supportsPdfDocking,
          preferredPreviewMode: getStoredOriginalPreviewMode(),
        })
      ) {
        setOriginalPanelVisible(true)
      }
      setSelectedChunkIndex(nextIndex)
      scrollRef.current?.focus()
    },
    [setOriginalPanelVisible, setSelectedChunkIndex, showOriginalPanel, supportsPdfDocking]
  )

  const openDockedPdfPreview = useCallback(() => {
    if (globalThis.window !== undefined) {
      writeClientStorage(ORIGINAL_PREVIEW_MODE_STORAGE_KEY, 'pdf')
    }
    setOriginalPanelVisible(true)
    scrollRef.current?.focus()
  }, [setOriginalPanelVisible])

  useEffect(() => {
    const t = globalThis.window.setTimeout(() => setQuery(queryInput), QUERY_DEBOUNCE_MS)
    return () => globalThis.window.clearTimeout(t)
  }, [queryInput])

  useEffect(() => {
    setPageFilter(PAGE_ALL_VALUE)
    setSectionFilter(SECTION_ALL_VALUE)
    setQueryInput('')
    setQuery('')
    setSortMode('index')
    setViewMode('flat')
    setGroupMode('none')
    setFiltersOpen(false)
    setRetrieveOpen(false)
    setRetrieveQuery('')
    setRerankEnabled(false)
    setRerankAlphaPct(65)
    setCollapsedGroups({})
    setMinLen(0)
    setMaxLen(0)
    setOnlyShort(false)
    setOnlyDuplicate(false)
    setOnlyEdited(false)
    setOnlyDisabled(false)
    setOnlyGap(false)
    setOnlyOverlap(false)
    setOnlyNeedsReview(false)
    setInspectorOpen(false)
    setInspectorIndex(null)
  }, [previewData?.filename])

  const pageOptions = useMemo(() => {
    const chunks = previewData?.chunks || []
    const pages = new Set<number>()
    let hasUnknown = false
    for (const c of chunks) {
      if (typeof c.page_number === 'number') pages.add(c.page_number)
      else hasUnknown = true
    }
    const list = Array.from(pages).sort((a, b) => a - b)
    return { list, hasUnknown }
  }, [previewData?.chunks])

  const editedIndices = useMemo(() => {
    const out = new Set<number>()
    for (const [k, override] of Object.entries(chunkOverrides)) {
      const n = Number(k)
      if (!Number.isFinite(n)) continue
      if (isChunkOverrideEdited(override)) out.add(n)
    }
    return out
  }, [chunkOverrides])

  const disabledIndices = useMemo(() => {
    const out = new Set<number>()
    for (const [k, override] of Object.entries(chunkOverrides)) {
      const idx = Number(k)
      if (!Number.isFinite(idx)) continue
      if (isChunkOverrideDisabled(override)) out.add(idx)
    }
    return out
  }, [chunkOverrides])

  const effectiveChunks = useMemo(() => {

    const raw = previewData?.chunks || []
    if (!raw.length) return []
    return raw.map((chunk) => {
      const idx = typeof chunk.index === 'number' ? chunk.index : raw.indexOf(chunk)
      const override = chunkOverrides?.[idx]
      if (!override) return chunk
      const content = String(override.content ?? chunk.content ?? '')
      const metadata = (override.metadata ?? chunk.metadata ?? {})
      return {
        ...chunk,
        content,
        metadata,
        length: content.length,
        tokens_est: roughEstimateTokens(content),
      }
    })
  }, [previewData?.chunks, chunkOverrides])

  const copySelectedChunk = useCallback(async () => {
    if (selectedChunkIndex == null) return
    const chunk = effectiveChunks[selectedChunkIndex]
    const text = String(chunk?.content || '').trim()
    if (!text) return
    if (!globalThis.navigator?.clipboard?.writeText) {
      toast.error(t('chunkList.toasts.clipboardUnsupported'))
      return
    }
    await globalThis.navigator.clipboard.writeText(text)
    toast.success(t('chunkList.toasts.copiedSelected'))
  }, [effectiveChunks, selectedChunkIndex, t])

  const sectionOptions = useMemo(() => {
    const chunks = effectiveChunks || []
    const seen = new Set<string>()
    const list: string[] = []
    let hasNone = false
    for (const c of chunks) {
      const sec = getChunkSectionPath(c)
      if (!sec) {
        hasNone = true
        continue
      }
      if (seen.has(sec)) continue
      seen.add(sec)
      list.push(sec)
    }
    return { list, hasNone }
  }, [effectiveChunks])

  const retrievalIndex = useMemo(() => {
    if (!retrieveOpen) return null
    return buildChunkSearchIndex(effectiveChunks)
  }, [effectiveChunks, retrieveOpen])

  const retrievalResults: ChunkSearchResult[] = useMemo(() => {
    if (!retrieveOpen || !retrievalIndex) return []
    const q = retrieveQuery.trim()
    if (!q) return []
    return searchChunkIndex(retrievalIndex, q, { limit: 10 })
  }, [retrieveOpen, retrieveQuery, retrievalIndex])

  const retrievalDisplayResults: Array<ChunkSearchResult | RerankedChunkSearchResult> = useMemo(() => {
    if (!rerankEnabled) return retrievalResults
    return rerankChunkSearchResults(retrievalResults, retrieveQuery, effectiveChunks, { alpha: rerankAlphaPct / 100 })
  }, [rerankEnabled, retrievalResults, retrieveQuery, effectiveChunks, rerankAlphaPct])

  const reviewSignals = previewData?.review_signals ?? null
  const duplicateIndices = useMemo(
    () => toSignalSet(reviewSignals?.duplicate_indices),
    [reviewSignals?.duplicate_indices]
  )

  const shortIndices = useMemo(
    () => toSignalSet(reviewSignals?.short_indices),
    [reviewSignals?.short_indices]
  )

  const roleIndices = useMemo(() => computeRoleIndices(effectiveChunks), [effectiveChunks])

  const coverageSignals = useMemo(
    () => ({
      basis: reviewSignals?.basis === 'child' ? 'child' as const : 'all' as const,
      gapIndices: toSignalSet(reviewSignals?.gap_indices),
      overlapIndices: toSignalSet(reviewSignals?.overlap_indices),
      gapBeforeByIndex: toSignalMap(reviewSignals?.gap_before_by_index),
      overlapPrevByIndex: toSignalMap(reviewSignals?.overlap_prev_by_index),
    }),
    [
      reviewSignals?.basis,
      reviewSignals?.gap_indices,
      reviewSignals?.overlap_indices,
      reviewSignals?.gap_before_by_index,
      reviewSignals?.overlap_prev_by_index,
    ]
  )

  const needsReviewIndices = useMemo(() => {
    const out = new Set<number>()
    for (const c of effectiveChunks || []) {
      const idx = Number(c.index)
      if (!Number.isFinite(idx)) continue
      if (chunkNeedsReview(c)) out.add(idx)
    }
    return out
  }, [effectiveChunks])

  const setChunkReviewed = useCallback(
    (index: number, reviewed: boolean) => {
      const chunk = effectiveChunks[index]
      if (!chunk) return

      const metadata: JsonObject = { ...(isJsonObject(chunk.metadata) ? chunk.metadata : {}) }
      const semanticQuality = isJsonObject(metadata.semantic_quality) ? { ...metadata.semantic_quality } : null

      metadata.needs_review = !reviewed
      metadata.reviewed = reviewed
      metadata.review_status = reviewed ? 'approved' : 'pending'

      if (reviewed) metadata.reviewed_at = new Date().toISOString()
      else delete metadata.reviewed_at

      if (semanticQuality) {
        metadata.semantic_quality = {
          ...semanticQuality,
          needs_review: !reviewed,
        }
      }

      updateChunkOverride(index, { metadata })
      toast.success(reviewed ? t('chunkList.toasts.markedReviewed') : t('chunkList.toasts.restoredReview'))
    },
    [effectiveChunks, t, updateChunkOverride]
  )

  const inspectorChunk = useMemo(() => {
    if (inspectorIndex == null) return null
    return effectiveChunks[inspectorIndex] || null
  }, [effectiveChunks, inspectorIndex])

  const inspectorOverrideUpdatedAt = useMemo(() => {
    if (inspectorIndex == null) return undefined
    return chunkOverrides?.[inspectorIndex]?.updatedAt
  }, [chunkOverrides, inspectorIndex])

  const flatFilteredChunks = useMemo(() => {
    if (!effectiveChunks.length) return []
    const readLen = (chunk: ChunkPreviewItem) => {
      if (unit === 'tokens') return Number(chunk.tokens_est || 0)
      return Number(chunk.length || 0)
    }
    const q = query.trim().toLowerCase()
    const base = effectiveChunks
      .map((chunk: ChunkPreviewItem, index: number) => ({ chunk, index }))
      .filter(({ chunk }: { chunk: ChunkPreviewItem }) => {
        if (pageFilter === PAGE_ALL_VALUE) {
          // pass
        } else if (pageFilter === PAGE_UNKNOWN_VALUE) {
          if (typeof chunk.page_number === 'number') return false
        } else if (String(chunk.page_number ?? '') !== pageFilter) return false

        const sectionPath = getChunkSectionPath(chunk)
        if (sectionFilter === SECTION_ALL_VALUE) {
          // pass
        } else if (sectionFilter === SECTION_NONE_VALUE) {
          if (sectionPath) return false
        } else if (!sectionPath || sectionPath !== sectionFilter) return false

        const contentOk = q ? (chunk.content || '').toLowerCase().includes(q) : true
        if (!contentOk) return false

        const len = readLen(chunk)
        if (minLen > 0 && len < minLen) return false
        if (maxLen > 0 && len > maxLen) return false

        if (onlyShort && !shortIndices.has(Number(chunk.index))) return false
        if (onlyDuplicate && !duplicateIndices.has(Number(chunk.index))) return false
        if (onlyEdited && !editedIndices.has(Number(chunk.index))) return false
        if (onlyDisabled && !disabledIndices.has(Number(chunk.index))) return false
        if (onlyGap && !coverageSignals.gapIndices.has(Number(chunk.index))) return false
        if (onlyOverlap && !coverageSignals.overlapIndices.has(Number(chunk.index))) return false
        if (onlyNeedsReview && !needsReviewIndices.has(Number(chunk.index))) return false

        return true
      })

    if (sortMode === 'length_desc') {
      base.sort((a, b) => readLen(b.chunk) - readLen(a.chunk))
    } else if (sortMode === 'length_asc') {
      base.sort((a, b) => readLen(a.chunk) - readLen(b.chunk))
    }
    return base
  }, [
    effectiveChunks,
    pageFilter,
    sectionFilter,
    query,
    sortMode,
    minLen,
    maxLen,
    unit,
    onlyShort,
    onlyDuplicate,
    onlyEdited,
    onlyDisabled,
    onlyGap,
    onlyOverlap,
    onlyNeedsReview,
    shortIndices,
    duplicateIndices,
    editedIndices,
    disabledIndices,
    coverageSignals,
    needsReviewIndices,
  ])

  const matchCount = flatFilteredChunks.length
  const matchIndexSet = useMemo(() => new Set(flatFilteredChunks.map((item) => item.index)), [flatFilteredChunks])

  const displayRows: DisplayRow[] = useMemo(() => {
    if (!effectiveChunks.length) return []
    if (!isHierarchyView) {
      if (groupMode !== 'section') {
        return flatFilteredChunks.map(({ chunk, index }) => ({
          kind: 'chunk',
          chunk,
          index,
          indent: 0,
          role: 'solo',
        }))
      }

      const groupsInOrder: string[] = []
      const groups = new Map<
        string,
        {
          label: string
          items: Array<{ chunk: ChunkPreviewItem; index: number }>
        }
      >()

       for (const item of flatFilteredChunks) {
         const sec = getChunkSectionPath(item.chunk)
         const label = sec || t('chunkList.section.none')
         const key = sec ? `sec:${sec}` : `sec:${SECTION_NONE_VALUE}`
        let g = groups.get(key)
        if (!g) {
          g = { label, items: [] }
          groups.set(key, g)
          groupsInOrder.push(key)
        }
        g.items.push(item)
      }

      const rows: DisplayRow[] = []
      for (const key of groupsInOrder) {
        const g = groups.get(key)
        if (!g) continue
        rows.push({ kind: 'section', key, label: g.label, count: g.items.length })
        if (collapsedGroups[key]) continue
        for (const it of g.items) {
          rows.push({
            kind: 'chunk',
            chunk: it.chunk,
            index: it.index,
            indent: 1,
            role: 'solo',
          })
        }
      }

      return rows
    }

    const hasActiveFilters =
      Boolean(query.trim()) ||
      pageFilter !== PAGE_ALL_VALUE ||
      sectionFilter !== SECTION_ALL_VALUE ||
      minLen > 0 ||
      maxLen > 0 ||
      onlyShort ||
      onlyDuplicate ||
      onlyEdited ||
      onlyDisabled ||
      onlyGap ||
      onlyOverlap ||
      onlyNeedsReview

    type Group = {
      key: string
      parentIndex: number | null
      childIndices: number[]
      indices: number[]
    }

    const groupsInOrder: string[] = []
    const groups = new Map<string, Group>()

    for (let idx = 0; idx < effectiveChunks.length; idx += 1) {
      const chunk = effectiveChunks[idx]
      const meta = (chunk.metadata || {})
      const role = typeof meta.chunk_role === 'string' ? meta.chunk_role : undefined
      const parentIdRaw = meta.parent_id ?? meta.parent_node_id
      const parentId = typeof parentIdRaw === 'string' && parentIdRaw.trim() ? parentIdRaw.trim() : null

      if (!parentId) {
        const key = `__solo__${idx}`
        groupsInOrder.push(key)
        groups.set(key, { key, parentIndex: idx, childIndices: [], indices: [idx] })
        continue
      }

      let g = groups.get(parentId)
      if (!g) {
        g = { key: parentId, parentIndex: null, childIndices: [], indices: [] }
        groups.set(parentId, g)
        groupsInOrder.push(parentId)
      }
      g.indices.push(idx)
      if (role === 'parent' && g.parentIndex == null) g.parentIndex = idx
      if (role === 'child') g.childIndices.push(idx)
    }

    const rows: DisplayRow[] = []

    for (const key of groupsInOrder) {
      const g = groups.get(key)
      if (!g) continue

      const parentIdx = g.parentIndex ?? g.indices[0]
      const childIdxs =
        g.childIndices.length > 0 ? g.childIndices : g.indices.filter((i) => i !== parentIdx)

      const hasVisibleChild = childIdxs.some((i) => matchIndexSet.has(i))
      const groupHasAnyVisible = matchIndexSet.has(parentIdx) || hasVisibleChild
      if (!groupHasAnyVisible) continue

      const isCollapsed = Boolean(collapsedGroups[key])
      const forceExpand = hasActiveFilters && hasVisibleChild

      const visibleChildCount = childIdxs.reduce((acc, i) => acc + (matchIndexSet.has(i) ? 1 : 0), 0)
      const totalChildCount = childIdxs.length

      rows.push({
        kind: 'chunk',
        chunk: effectiveChunks[parentIdx],
        index: parentIdx,
        indent: 0,
        groupKey: key,
        role: 'parent',
        childCountTotal: totalChildCount,
        childCountVisible: visibleChildCount,
        isContext: !matchIndexSet.has(parentIdx) && hasVisibleChild,
      })

      if (isCollapsed && !forceExpand) continue

      for (const childIdx of childIdxs) {
        if (!matchIndexSet.has(childIdx)) continue
        rows.push({
          kind: 'chunk',
          chunk: effectiveChunks[childIdx],
          index: childIdx,
          indent: 1,
          groupKey: key,
          role: 'child',
        })
      }
    }

    return rows
  }, [
    effectiveChunks,
    flatFilteredChunks,
    isHierarchyView,
    groupMode,
    query,
    pageFilter,
    sectionFilter,
    minLen,
    maxLen,
    onlyShort,
    onlyDuplicate,
    onlyEdited,
    onlyDisabled,
    onlyGap,
    onlyOverlap,
    onlyNeedsReview,
    matchIndexSet,
    collapsedGroups,
    t,
  ])

  // eslint-disable-next-line react-hooks/incompatible-library
  const rowVirtualizer = useVirtualizer({
    count: displayRows.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: (idx) => (displayRows[idx]?.kind === 'section' ? 44 : 140),
    overscan: 8,
  })

  // Keep the selected chunk visible (best effort).
  useEffect(() => {
    if (selectedChunkIndex == null) return
    const pos = displayRows.findIndex((item) => item.kind === 'chunk' && item.index === selectedChunkIndex)
    if (pos >= 0) {
      rowVirtualizer.scrollToIndex(pos, { align: 'center' })
    }
  }, [displayRows, rowVirtualizer, selectedChunkIndex])

  const matchesLabel = useMemo(() => {
    const hasFilter =
      Boolean(query.trim()) ||
      pageFilter !== PAGE_ALL_VALUE ||
      sectionFilter !== SECTION_ALL_VALUE ||
      minLen > 0 ||
      maxLen > 0 ||
      onlyShort ||
      onlyDuplicate ||
      onlyEdited ||
      onlyDisabled ||
      onlyGap ||
      onlyOverlap ||
      onlyNeedsReview
    if (!hasFilter) return null
    return `${matchCount} / ${previewData?.total_chunks || 0}`
  }, [
    matchCount,
    previewData?.total_chunks,
    query,
    pageFilter,
    sectionFilter,
    minLen,
    maxLen,
    onlyShort,
    onlyDuplicate,
    onlyEdited,
    onlyDisabled,
    onlyGap,
    onlyOverlap,
    onlyNeedsReview,
  ])

  const filterActiveCount = useMemo(() => {
    let count = 0
    if (query.trim()) count += 1
    if (isParentChildStrategy && viewMode !== 'flat') count += 1
    if (!isHierarchyView && groupMode !== 'none') count += 1
    if (sortMode !== 'index') count += 1
    if (pageFilter !== PAGE_ALL_VALUE) count += 1
    if (sectionFilter !== SECTION_ALL_VALUE) count += 1
    if (minLen > 0 || maxLen > 0) count += 1
    if (onlyShort) count += 1
    if (onlyDuplicate) count += 1
    if (onlyGap) count += 1
    if (onlyOverlap) count += 1
    if (onlyNeedsReview) count += 1
    if (onlyEdited) count += 1
    if (onlyDisabled) count += 1
    return count
  }, [
    groupMode,
    isHierarchyView,
    isParentChildStrategy,
    maxLen,
    minLen,
    onlyDisabled,
    onlyDuplicate,
    onlyEdited,
    onlyGap,
    onlyNeedsReview,
    onlyOverlap,
    onlyShort,
    pageFilter,
    query,
    sectionFilter,
    sortMode,
    viewMode,
  ])

  const qualitySummaryItems = [
    {
      key: 'short',
      count: shortIndices.size,
      active: onlyShort,
      label: t('chunkList.filters.shortLabel', { count: shortIndices.size }),
      title: t('chunkList.filters.onlyShortTitle'),
      icon: AlertCircle,
      toggle: () => setOnlyShort((v) => !v),
    },
    {
      key: 'duplicate',
      count: duplicateIndices.size,
      active: onlyDuplicate,
      label: t('chunkList.filters.duplicateLabel', { count: duplicateIndices.size }),
      title: t('chunkList.filters.onlyDuplicateTitle'),
      icon: Copy,
      toggle: () => setOnlyDuplicate((v) => !v),
    },
    {
      key: 'gap',
      count: coverageSignals.gapIndices.size,
      active: onlyGap,
      label: t('chunkList.filters.gapLabel', { count: coverageSignals.gapIndices.size }),
      title: coverageSignals.basis === 'child'
        ? t('chunkList.filters.onlyGapTitleChildCoverage')
        : t('chunkList.filters.onlyGapTitle'),
      toggle: () => setOnlyGap((v) => !v),
    },
    {
      key: 'overlap',
      count: coverageSignals.overlapIndices.size,
      active: onlyOverlap,
      label: t('chunkList.filters.overlapLabel', { count: coverageSignals.overlapIndices.size }),
      title: coverageSignals.basis === 'child'
        ? t('chunkList.filters.onlyOverlapTitleChildCoverage')
        : t('chunkList.filters.onlyOverlapTitle'),
      toggle: () => setOnlyOverlap((v) => !v),
    },
    {
      key: 'review',
      count: needsReviewIndices.size,
      active: onlyNeedsReview,
      label: t('chunkList.filters.reviewLabel', { count: needsReviewIndices.size }),
      title: t('chunkList.filters.onlyNeedsReviewTitle'),
      icon: Code2,
      toggle: () => setOnlyNeedsReview((v) => !v),
    },
    {
      key: 'edited',
      count: editedIndices.size,
      active: onlyEdited,
      label: t('chunkList.filters.editedLabel', { count: editedIndices.size }),
      title: t('chunkList.filters.onlyEditedTitle'),
      icon: Pencil,
      toggle: () => setOnlyEdited((v) => !v),
    },
    {
      key: 'skipped',
      count: disabledIndices.size,
      active: onlyDisabled,
      label: t('chunkList.filters.skippedLabel', { count: disabledIndices.size }),
      title: t('chunkList.filters.onlySkippedTitle'),
      icon: EyeOff,
      toggle: () => setOnlyDisabled((v) => !v),
    },
  ]
  const activeQualitySummaryItems = qualitySummaryItems.filter((item) => item.count > 0 || item.active)
  const healthyQualitySummaryCount = Math.max(0, qualitySummaryItems.length - activeQualitySummaryItems.length)

  const filterButtonLabel = filterActiveCount > 0
    ? t('chunkList.toolbar.filtersWithCount', { count: filterActiveCount })
    : t('chunkList.toolbar.filters')

  const showVirtualized = Boolean(previewData?.chunks && displayRows.length > 0)
  const listSurfaceKey = `chunk-list-surface:${viewMode}:${groupMode}`
  const surfaceTransition = useMemo(
    () => ({
      duration: reduceMotion ? 0 : 0.22,
      ease: [0.16, 1, 0.3, 1] as const,
    }),
    [reduceMotion]
  )

  const expandableGroupKeys = useMemo(() => {
    const out: string[] = []
    if (isHierarchyView) {
      for (const row of displayRows) {
        if (row.kind !== 'chunk') continue
        if (row.indent === 0 && row.groupKey && (row.childCountTotal || 0) > 0) out.push(row.groupKey)
      }
      return out
    }
    if (groupMode === 'section') {
      for (const row of displayRows) {
        if (row.kind === 'section' && row.count > 0) out.push(row.key)
      }
      return out
    }
    return out
  }, [displayRows, groupMode, isHierarchyView])

  const allGroupsCollapsed = useMemo(() => {
    if (!expandableGroupKeys.length) return false
    return expandableGroupKeys.every((k) => Boolean(collapsedGroups[k]))
  }, [collapsedGroups, expandableGroupKeys])

  const sortLengthDescLabel = unit === 'tokens'
    ? t('chunkList.sort.lengthDescTokens')
    : t('chunkList.sort.lengthDescChars')
  const sortLengthAscLabel = unit === 'tokens'
    ? t('chunkList.sort.lengthAscTokens')
    : t('chunkList.sort.lengthAscChars')
  const lengthFilterLabel = unit === 'tokens'
    ? t('chunkList.lengthFilter.labelTokens')
    : t('chunkList.lengthFilter.labelChars')
  const minLengthFilterAria = unit === 'tokens'
    ? t('chunkList.lengthFilter.minAriaTokens')
    : t('chunkList.lengthFilter.minAriaChars')
  const maxLengthFilterAria = unit === 'tokens'
    ? t('chunkList.lengthFilter.maxAriaTokens')
    : t('chunkList.lengthFilter.maxAriaChars')
  const allGroupsToggleTitle = allGroupsCollapsed
    ? t('chunkList.groupToggle.expandAllTitle')
    : t('chunkList.groupToggle.collapseAllTitle')
  const allGroupsToggleLabel = allGroupsCollapsed
    ? t('chunkList.groupToggle.expand')
    : t('chunkList.groupToggle.collapse')
  const navigationHint = showOriginalPanel
    ? t('chunkList.keyboardHints.withOriginalPanel')
    : supportsPdfDocking
      ? t('chunkList.keyboardHints.withPdfDocking')
      : t('chunkList.keyboardHints.hiddenOriginal')
  const chunkListToolbarButtonClass =
    'h-7 rounded-full border-border/45 px-2 text-[10.5px] font-medium text-muted-foreground shadow-none transition-colors hover:border-primary/30 hover:bg-primary/10 hover:text-primary'
  const chunkListToolbarActiveButtonClass =
    'h-7 rounded-full border-primary/20 bg-primary/10 px-2 text-[10.5px] font-semibold text-primary shadow-none transition-colors hover:bg-primary/20'

  return (
    <div className="flex-1 flex flex-col min-w-0 bg-background">
      <div className="border-b border-border/55 bg-card px-3 py-2 shrink-0">
        <div className="flex flex-col gap-1.5">
          <div className="flex min-w-0 items-center justify-between gap-2">
            <div className="flex min-w-0 items-center gap-1.5">
              <span className="flex min-w-0 items-center gap-1.5 whitespace-nowrap text-[13px] font-semibold text-foreground">
                <span className="flex h-6 w-6 items-center justify-center rounded-full border border-primary/20 bg-primary/10 text-primary">
                  <Rows3 className="h-3.5 w-3.5" />
                </span>
                {t('chunkList.title')}
              </span>
              {previewData?.total_chunks ? (
                <span className="rounded-full border border-primary/20 bg-primary/10 px-1.5 py-0.5 font-mono text-[10px] font-semibold text-primary">
                  {previewData.total_chunks}
                </span>
              ) : null}
              {matchesLabel ? <span className="truncate font-mono text-[10.5px] text-muted-foreground">{matchesLabel}</span> : null}
            </div>
          </div>

          <div
            data-chunk-list-toolbar
            className="flex min-w-0 flex-wrap items-center gap-1 rounded-[18px] border border-border/45 bg-muted/20 p-1 shadow-[inset_0_1px_0_rgba(255,255,255,0.55)]"
          >
            <div
              data-chunk-list-search
              className="relative flex h-7 min-w-[150px] flex-1 items-center rounded-full border border-border/40 bg-background/90 px-2 shadow-sm"
            >
                <Search className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                <Input
                  ref={searchRef}
                  value={queryInput}
                  onChange={(e) => setQueryInput(e.target.value)}
                  placeholder={t('chunkList.searchPlaceholder')}
                  className="h-full min-w-0 flex-1 border-0 bg-transparent px-1.5 pr-5 text-[11px] shadow-none placeholder:text-muted-foreground/65 focus-visible:ring-1 focus-visible:ring-primary/30"
                />
                {queryInput ? (
                  <button
                    type="button"
                    className="absolute right-2 top-1/2 -translate-y-1/2 rounded text-muted-foreground transition-colors hover:text-foreground focus-ring"
                    onClick={() => {
                      setQueryInput('')
                      setQuery('')
                    }}
                    aria-label={t('chunkList.clearSearch')}
                    title={t('chunkList.clearSearch')}
                  >
                    <X className="w-3 h-3" />
                  </button>
                ) : null}
              </div>
              {selectedChunkIndex == null ? null : (
                <>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    className={chunkListToolbarButtonClass}
                    onClick={() => detachPromise(copySelectedChunk())}
                  >
                    {t('chunkList.actions.copySelected')}
                  </Button>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    className={chunkListToolbarButtonClass}
                    onClick={() => selectChunkIndex(null)}
                  >
                    {t('chunkList.actions.clearSelection')}
                  </Button>
                </>
              )}
              {!showOriginalPanel && supportsPdfDocking ? (
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className={chunkListToolbarButtonClass}
                  onClick={openDockedPdfPreview}
                  title={t('chunkList.actions.restorePdfDockTitle')}
                >
                  {t('chunkList.actions.restorePdfDock')}
                </Button>
              ) : null}
              <Button
                type="button"
                variant={retrieveOpen ? 'secondary' : 'outline'}
                size="sm"
                className={retrieveOpen || retrieveQuery.trim() ? chunkListToolbarActiveButtonClass : chunkListToolbarButtonClass}
                onClick={() => setRetrieveOpen((v) => !v)}
                title={t('chunkList.retrieve.triggerTitle')}
              >
                <Search className="h-3.5 w-3.5 mr-1" />
                {t('chunkList.retrieve.trigger')}
                {retrieveQuery.trim() ? ` ${retrievalDisplayResults.length}` : ''}
              </Button>
              <Button
                type="button"
                variant={filtersOpen || filterActiveCount > 0 ? 'secondary' : 'outline'}
                size="sm"
                className={filtersOpen || filterActiveCount > 0 ? chunkListToolbarActiveButtonClass : chunkListToolbarButtonClass}
                onClick={() => setFiltersOpen((v) => !v)}
                aria-expanded={filtersOpen}
                aria-controls="chunk-list-filter-panel"
                title={filterButtonLabel}
              >
                <SlidersHorizontal className="h-3.5 w-3.5 mr-1" />
                {filterButtonLabel}
              </Button>
          </div>

          <div className="flex flex-wrap items-center justify-between gap-1.5 rounded-2xl border border-border/40 bg-background/70 px-2 py-1">
            <div className="flex min-w-0 flex-wrap items-center gap-1.5">
              {effectiveChunks.length > 0 ? (
                <>
                  {activeQualitySummaryItems.map((item) => {
                  const Icon = item.icon
                  return (
                    <Button
                      key={item.key}
                      type="button"
                      variant={item.active ? 'secondary' : 'ghost'}
                      size="sm"
                      className="h-6 rounded-md px-1.5 text-[10px]"
                      onClick={item.toggle}
                      title={item.title}
                    >
                      {Icon ? <Icon className="mr-1 h-3 w-3" /> : null}
                      {item.label}
                    </Button>
                  )
                  })}
                  {healthyQualitySummaryCount > 0 ? (
                    <span className="inline-flex h-6 items-center rounded-md border border-emerald-500/15 bg-emerald-500/8 px-1.5 text-[10px] text-emerald-700 dark:text-emerald-300">
                      {t('chunkList.filters.healthySummary', { count: healthyQualitySummaryCount })}
                    </span>
                  ) : null}
                </>
              ) : (
                <span className="text-[11px] text-muted-foreground">{t('chunkList.toolbar.noQualitySignals')}</span>
              )}
            </div>
            <span className="sr-only">
              {navigationHint} · {t('chunkList.keyboardHints.footer')}
            </span>
          </div>

          {filtersOpen ? (
            <div
              id="chunk-list-filter-panel"
              className="rounded-lg border border-border/50 bg-[linear-gradient(180deg,hsl(var(--background)),hsl(var(--muted)/0.18))] p-2"
            >
              <div className="flex flex-wrap items-center gap-1.5">
            {isParentChildStrategy ? (
              <Select
                value={viewMode}
                onValueChange={(value) => {
                  const next = value as ViewMode
                  setViewMode(next)
                  if (next === 'hierarchy') {
                    setSortMode('index')
                    setGroupMode('none')
                  }
                  if (next !== 'hierarchy') setCollapsedGroups({})
                }}
              >
                <SelectTrigger className="h-[28px] w-[112px] rounded-lg border-border/60 bg-background text-[11px]">
                  <SelectValue placeholder={t('chunkList.view.placeholder')} />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="flat">{t('chunkList.view.flat')}</SelectItem>
                  <SelectItem value="hierarchy">{t('chunkList.view.hierarchy')}</SelectItem>
                </SelectContent>
              </Select>
            ) : null}
            {!isHierarchyView && (sectionOptions.list.length > 0 || sectionOptions.hasNone) ? (
              <Select
                value={groupMode}
                onValueChange={(value) => {
                  const next = value as GroupMode
                  setGroupMode(next)
                  setCollapsedGroups({})
                  if (next === 'section') setSortMode('index')
                }}
              >
                <SelectTrigger className="h-[28px] w-[112px] rounded-lg border-border/60 bg-background text-[11px]">
                  <SelectValue placeholder={t('chunkList.group.placeholder')} />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="none">{t('chunkList.group.none')}</SelectItem>
                  <SelectItem value="section">{t('chunkList.group.section')}</SelectItem>
                </SelectContent>
              </Select>
            ) : null}
            {(isHierarchyView || isSectionView) && expandableGroupKeys.length > 0 ? (
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="h-[28px] rounded-lg px-2 text-[11px]"
                onClick={() => {
                  if (allGroupsCollapsed) {
                    setCollapsedGroups({})
                    return
                  }
                  const next: Record<string, boolean> = {}
                  for (const k of expandableGroupKeys) next[k] = true
                  setCollapsedGroups(next)
                }}
                title={allGroupsToggleTitle}
              >
                {allGroupsToggleLabel}
              </Button>
            ) : null}
            <Select value={sortMode} onValueChange={(value) => setSortMode(value as SortMode)} disabled={isHierarchyView || isSectionView}>
              <SelectTrigger className="h-[28px] w-[122px] rounded-lg border-border/60 bg-background text-[11px]">
                <SelectValue placeholder={t('chunkList.sort.placeholder')} />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="index">{t('chunkList.sort.index')}</SelectItem>
                <SelectItem value="length_desc">{sortLengthDescLabel}</SelectItem>
                <SelectItem value="length_asc">{sortLengthAscLabel}</SelectItem>
              </SelectContent>
            </Select>
            <Select value={pageFilter} onValueChange={(value) => setPageFilter(value)}>
              <SelectTrigger className="h-[28px] w-[98px] rounded-lg border-border/60 bg-background text-[11px]">
                <SelectValue placeholder={t('chunkList.page.placeholder')} />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={PAGE_ALL_VALUE}>{t('chunkList.page.all')}</SelectItem>
                {pageOptions.hasUnknown ? <SelectItem value={PAGE_UNKNOWN_VALUE}>{t('chunkList.page.unknown')}</SelectItem> : null}
                {pageOptions.list.map((p) => (
                  <SelectItem key={p} value={String(p)}>
                    P.{p}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {sectionOptions.list.length > 0 || sectionOptions.hasNone ? (
              <Select value={sectionFilter} onValueChange={(value) => setSectionFilter(value)}>
                <SelectTrigger className="h-[28px] w-[138px] rounded-lg border-border/60 bg-background text-[11px]">
                  <SelectValue placeholder={t('chunkList.section.placeholder')} />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={SECTION_ALL_VALUE}>{t('chunkList.section.all')}</SelectItem>
                  {sectionOptions.hasNone ? <SelectItem value={SECTION_NONE_VALUE}>{t('chunkList.section.none')}</SelectItem> : null}
                  {sectionOptions.list.map((sec) => (
                    <SelectItem key={sec} value={sec}>
                      <span className="block max-w-[520px] truncate" title={sec}>
                        {sec}
                      </span>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            ) : null}
            <div className="flex items-center gap-1 text-[11px] text-muted-foreground">
              <span className="mr-1">{lengthFilterLabel}</span>
              <Input
                value={minLen > 0 ? String(minLen) : ''}
                onChange={(e) => {
                  const raw = e.target.value.trim()
                  const n = raw ? Number(raw) : 0
                  if (raw) { if (Number.isFinite(n)) setMinLen(Math.max(0, Math.trunc(n))) } else { setMinLen(0) }
                }}
                placeholder={t('chunkList.lengthFilter.minPlaceholder')}
                className="h-[28px] w-[58px] rounded-lg border-border/60 bg-background px-2 text-[11px] font-mono"
                inputMode="numeric"
                aria-label={minLengthFilterAria}
              />
              <span className="px-1 opacity-70">-</span>
              <Input
                value={maxLen > 0 ? String(maxLen) : ''}
                onChange={(e) => {
                  const raw = e.target.value.trim()
                  const n = raw ? Number(raw) : 0
                  if (raw) { if (Number.isFinite(n)) setMaxLen(Math.max(0, Math.trunc(n))) } else { setMaxLen(0) }
                }}
                placeholder={t('chunkList.lengthFilter.maxPlaceholder')}
                className="h-[28px] w-[58px] rounded-lg border-border/60 bg-background px-2 text-[11px] font-mono"
                inputMode="numeric"
                aria-label={maxLengthFilterAria}
              />
              {(minLen > 0 || maxLen > 0) ? (
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="h-[28px] rounded-lg px-2 text-[11px]"
                  onClick={() => {
                    setMinLen(0)
                    setMaxLen(0)
                  }}
                >
                  {t('chunkList.lengthFilter.clear')}
                </Button>
              ) : null}
            </div>
              </div>

              <div className="mt-2 flex flex-wrap items-center gap-1.5 border-t border-border/45 pt-2">
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button type="button" variant="outline" size="sm" className="h-[28px] rounded-lg px-2 text-[11px]">
                    {t('chunkList.batch.trigger')}
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="start">
                  <DropdownMenuItem
                    disabled={matchCount === 0}
                    onSelect={() => {
                      const targets = Array.from(matchIndexSet)
                      const delta = targets.filter((i) => !disabledIndices.has(i)).length
                      setChunksDisabled(targets, true)
                      toast.success(t('chunkList.batch.skipFilteredSuccess', { count: delta }))
                    }}
                  >
                    {t('chunkList.batch.skipFiltered', { count: matchCount })}
                  </DropdownMenuItem>

                  <DropdownMenuSeparator />

                  <DropdownMenuItem
                    disabled={duplicateIndices.size === 0}
                    onSelect={() => {
                      const targets = Array.from(duplicateIndices)
                      const delta = targets.filter((i) => !disabledIndices.has(i)).length
                      setChunksDisabled(targets, true)
                      toast.success(t('chunkList.batch.skipDuplicatesSuccess', { count: delta }))
                    }}
                  >
                    {t('chunkList.batch.skipDuplicates', { count: duplicateIndices.size })}
                  </DropdownMenuItem>
                  <DropdownMenuItem
                    disabled={shortIndices.size === 0}
                    onSelect={() => {
                      const targets = Array.from(shortIndices)
                      const delta = targets.filter((i) => !disabledIndices.has(i)).length
                      setChunksDisabled(targets, true)
                      toast.success(t('chunkList.batch.skipShortSuccess', { count: delta }))
                    }}
                  >
                    {t('chunkList.batch.skipShort', { count: shortIndices.size })}
                  </DropdownMenuItem>

                  {isParentChildStrategy ? (
                    <>
                      <DropdownMenuSeparator />
                      <DropdownMenuItem
                        disabled={roleIndices.parents.size === 0}
                        onSelect={() => {
                          const targets = Array.from(roleIndices.parents)
                          const delta = targets.filter((i) => !disabledIndices.has(i)).length
                          setChunksDisabled(targets, true)
                          toast.success(t('chunkList.batch.skipParentsSuccess', { count: delta }))
                        }}
                      >
                        {t('chunkList.batch.skipParents', { count: roleIndices.parents.size })}
                      </DropdownMenuItem>
                      <DropdownMenuItem
                        disabled={roleIndices.children.size === 0}
                        onSelect={() => {
                          const targets = Array.from(roleIndices.children)
                          const delta = targets.filter((i) => !disabledIndices.has(i)).length
                          setChunksDisabled(targets, true)
                          toast.success(t('chunkList.batch.skipChildrenSuccess', { count: delta }))
                        }}
                      >
                        {t('chunkList.batch.skipChildren', { count: roleIndices.children.size })}
                      </DropdownMenuItem>
                    </>
                  ) : null}

                  <DropdownMenuSeparator />

                  <DropdownMenuItem
                    disabled={disabledIndices.size === 0}
                    onSelect={() => {
                      const targets = Array.from(disabledIndices)
                      setChunksDisabled(targets, false)
                      toast.success(t('chunkList.batch.restoreAllSuccess', { count: targets.length }))
                    }}
                  >
                    {t('chunkList.batch.restoreAll', { count: disabledIndices.size })}
                  </DropdownMenuItem>
                  <DropdownMenuItem
                    disabled={disabledIndices.size === 0 || matchCount === 0}
                    onSelect={() => {
                      const targets = Array.from(matchIndexSet)
                      const delta = targets.filter((i) => disabledIndices.has(i)).length
                      setChunksDisabled(targets, false)
                      toast.success(t('chunkList.batch.restoreFilteredSuccess', { count: delta }))
                    }}
                  >
                    {t('chunkList.batch.restoreFiltered')}
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>

              <Button
                type="button"
                variant={onlyShort ? 'secondary' : 'ghost'}
                size="sm"
                className="h-[28px] rounded-lg px-2 text-[11px]"
                onClick={() => setOnlyShort((v) => !v)}
                title={t('chunkList.filters.onlyShortTitle')}
              >
                <AlertCircle className="h-3.5 w-3.5 mr-1" />
                {t('chunkList.filters.shortLabel', { count: shortIndices.size })}
              </Button>
              <Button
                type="button"
                variant={onlyDuplicate ? 'secondary' : 'ghost'}
                size="sm"
                className="h-[28px] rounded-lg px-2 text-[11px]"
                onClick={() => setOnlyDuplicate((v) => !v)}
                title={t('chunkList.filters.onlyDuplicateTitle')}
              >
                <Copy className="h-3.5 w-3.5 mr-1" />
                {t('chunkList.filters.duplicateLabel', { count: duplicateIndices.size })}
              </Button>
              <Button
                type="button"
                variant={onlyGap ? 'secondary' : 'ghost'}
                size="sm"
                className="h-[28px] rounded-lg px-2 text-[11px]"
                onClick={() => setOnlyGap((v) => !v)}
                title={coverageSignals.basis === 'child'
                  ? t('chunkList.filters.onlyGapTitleChildCoverage')
                  : t('chunkList.filters.onlyGapTitle')}
              >
                {t('chunkList.filters.gapLabel', { count: coverageSignals.gapIndices.size })}
              </Button>
              <Button
                type="button"
                variant={onlyOverlap ? 'secondary' : 'ghost'}
                size="sm"
                className="h-[28px] rounded-lg px-2 text-[11px]"
                onClick={() => setOnlyOverlap((v) => !v)}
                title={coverageSignals.basis === 'child'
                  ? t('chunkList.filters.onlyOverlapTitleChildCoverage')
                  : t('chunkList.filters.onlyOverlapTitle')}
              >
                {t('chunkList.filters.overlapLabel', { count: coverageSignals.overlapIndices.size })}
              </Button>
              <Button
                type="button"
                variant={onlyNeedsReview ? 'secondary' : 'ghost'}
                size="sm"
                className="h-[28px] rounded-lg px-2 text-[11px]"
                onClick={() => setOnlyNeedsReview((v) => !v)}
                title={t('chunkList.filters.onlyNeedsReviewTitle')}
              >
                <Code2 className="h-3.5 w-3.5 mr-1" />
                {t('chunkList.filters.reviewLabel', { count: needsReviewIndices.size })}
              </Button>
              <Button
                type="button"
                variant={onlyEdited ? 'secondary' : 'ghost'}
                size="sm"
                className="h-[28px] rounded-lg px-2 text-[11px]"
                onClick={() => setOnlyEdited((v) => !v)}
                title={t('chunkList.filters.onlyEditedTitle')}
              >
                <Pencil className="h-3.5 w-3.5 mr-1" />
                {t('chunkList.filters.editedLabel', { count: editedIndices.size })}
              </Button>
              <Button
                type="button"
                variant={onlyDisabled ? 'secondary' : 'ghost'}
                size="sm"
                className="h-[28px] rounded-lg px-2 text-[11px]"
                onClick={() => setOnlyDisabled((v) => !v)}
                title={t('chunkList.filters.onlySkippedTitle')}
              >
                <EyeOff className="h-3.5 w-3.5 mr-1" />
                {t('chunkList.filters.skippedLabel', { count: disabledIndices.size })}
              </Button>
            </div>
            </div>
          ) : null}
        </div>
      </div>

      {retrieveOpen ? (
        <div className="border-b border-border/60 bg-card px-4 py-3">
          <div className="flex flex-wrap items-center gap-2">
            <Search className="w-4 h-4 text-muted-foreground" />
            <Input
              value={retrieveQuery}
              onChange={(e) => {
                const v = e.target.value
                setRetrieveQuery(v)
                if (v.trim()) setRetrieveOpen(true)
              }}
              placeholder={t('chunkList.retrieve.queryPlaceholder')}
              className="h-8 text-[11px] bg-background"
            />
            {retrieveQuery ? (
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="h-8 px-2 text-[11px]"
                onClick={() => setRetrieveQuery('')}
              >
                {t('chunkList.retrieve.clear')}
              </Button>
            ) : null}
            <Button
              type="button"
              variant={rerankEnabled ? 'secondary' : 'ghost'}
              size="sm"
              className="h-8 px-2 text-[11px]"
              onClick={() => setRerankEnabled((v) => !v)}
              title={t('chunkList.retrieve.rerankTitle')}
            >
              {t('chunkList.retrieve.rerank')}
            </Button>
            {rerankEnabled ? (
              <div className="flex items-center gap-2">
                <span className="text-[11px] text-muted-foreground font-mono" title={t('chunkList.retrieve.alphaTitle')}>
                  {rerankAlphaPct}%
                </span>
                <input
                  type="range"
                  min={0}
                  max={100}
                  value={rerankAlphaPct}
                  onChange={(e) => setRerankAlphaPct(Number(e.target.value) || 0)}
                  aria-label={t('chunkList.retrieve.alphaAria')}
                  className="w-28 h-2 bg-muted rounded-lg appearance-none cursor-pointer accent-primary"
                />
              </div>
            ) : null}
          </div>

          {retrieveQuery.trim() ? (
            <div className="mt-2 space-y-2">
              {retrievalDisplayResults.length > 0 ? (
                retrievalDisplayResults.map((r) => (
                  <button
                    key={r.index}
                    type="button"
                    className="w-full text-left rounded-xl border border-border/60 bg-background hover:bg-muted px-3 py-2 transition-colors focus-ring"
                    onClick={() => selectChunkIndex(r.index)}
                    title={r.section}
                  >
                    <div className="flex items-center gap-2">
                      <span className="text-[11px] font-mono font-bold px-1.5 py-0.5 rounded bg-primary/10 text-primary border border-primary/20">
                        #{r.index + 1}
                      </span>
                      {disabledIndices.has(r.index) ? (
                        <span className="text-[11px] font-mono px-1.5 py-0.5 rounded bg-muted/60 text-muted-foreground border border-border/60">
                          {t('chunkList.retrieve.skippedBadge')}
                        </span>
                      ) : null}
                      {r.page_number == null ? null : (
                        <span className="text-[11px] text-muted-foreground">P.{r.page_number}</span>
                      )}
                      {r.section ? (
                        <span className="min-w-0 flex-1 text-[11px] text-muted-foreground truncate">{r.section}</span>
                      ) : (
                        <span className="min-w-0 flex-1" />
                      )}
                      {'combined_score' in r ? (
                        <span
                          className="text-[11px] text-muted-foreground font-mono"
                          title={t('chunkList.retrieve.combinedScoreTitle', {
                            retrieval: r.retrieval_score.toFixed(2),
                            rerank: Math.round(r.rerank_score * 100),
                            combined: r.combined_score.toFixed(2),
                          })}
                        >
                          {t('chunkList.retrieve.combinedScoreLabel', { score: r.combined_score.toFixed(2) })}
                        </span>
                      ) : (
                        <span className="text-[11px] text-muted-foreground font-mono">
                          {t('chunkList.retrieve.retrievalScoreLabel', { score: r.score.toFixed(2) })}
                        </span>
                      )}
                    </div>
                    <div className="mt-1 text-[11px] text-muted-foreground line-clamp-2">{r.snippet}</div>
                  </button>
                ))
              ) : (
                <div className="text-[11px] text-muted-foreground">{t('chunkList.retrieve.noResults')}</div>
              )}
            </div>
          ) : (
            <div className="mt-2 text-[11px] text-muted-foreground">
              {t('chunkList.retrieve.hint')}
            </div>
          )}
        </div>
      ) : null}

      <section
        ref={scrollRef}
        data-page-scroll-container="true"
        aria-label={t('chunkList.ariaLabel')}
        className="flex-1 overflow-y-auto overscroll-contain no-scrollbar p-4"
      >
        <AnimatePresence initial={false} mode="wait">
          <motion.div
            key={listSurfaceKey}
            layout={!reduceMotion}
            initial={reduceMotion ? false : { opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={reduceMotion ? undefined : { opacity: 0, y: -6 }}
            transition={surfaceTransition}
            className="min-h-full rounded-2xl border border-border/60 bg-card p-3 shadow-sm ring-1 ring-border/40"
            style={{
              height: showVirtualized ? `${rowVirtualizer.getTotalSize()}px` : undefined,
              position: showVirtualized ? 'relative' : undefined,
            }}
          >
          {(() => {
    if (previewData?.chunks) {
        return (displayRows.length > 0 ? (rowVirtualizer.getVirtualItems().map((virtualRow) => {
            const item = displayRows[virtualRow.index];
            if (!item)
                return null;
            if (item.kind === 'section') {
                const groupKey = item.key;
                const isCollapsed = Boolean(collapsedGroups[groupKey]);
                return (<div key={virtualRow.key} data-index={virtualRow.index} ref={rowVirtualizer.measureElement} style={{
                        position: 'absolute',
                        top: 0,
                        left: 0,
                        width: '100%',
                        transform: `translateY(${virtualRow.start}px)`,
                    }} className="pb-2">
                      <div className="flex items-center gap-2 px-2 py-1.5 rounded-xl border border-border/60 bg-muted/40">
                        <button
                          type="button"
                          className="h-6 w-6 inline-flex items-center justify-center rounded-md border border-border/60 bg-card text-muted-foreground hover:text-foreground hover:border-primary/30 hover:bg-muted transition-colors focus-ring"
                          onClick={() => setCollapsedGroups((prev) => ({ ...prev, [groupKey]: !prev[groupKey] }))}
                          aria-label={isCollapsed ? t('chunkList.groupToggle.expandSection') : t('chunkList.groupToggle.collapseSection')}
                          title={isCollapsed ? t('chunkList.groupToggle.expandSection') : t('chunkList.groupToggle.collapseSection')}
                        >
                          {isCollapsed ? <ChevronRight className="h-4 w-4"/> : <ChevronDown className="h-4 w-4"/>}
                        </button>
                        <span className="min-w-0 flex-1 text-[11px] font-semibold truncate" title={item.label}>
                          {item.label}
                        </span>
                        <span className="text-[11px] text-muted-foreground font-mono">{item.count}</span>
                      </div>
                    </div>);
            }
            const { chunk, index, indent } = item;
            const isHovered = hoveredChunkIndex === index;
            const isSelected = selectedChunkIndex === index;
            const isShort = shortIndices.has(index);
            const isDuplicate = duplicateIndices.has(index);
            const isEdited = editedIndices.has(index);
            const gapBefore = coverageSignals.gapBeforeByIndex.get(index);
            const overlapPrev = coverageSignals.overlapPrevByIndex.get(index);
            const isGap = coverageSignals.gapIndices.has(index);
            const isOverlap = coverageSignals.overlapIndices.has(index);
            const dimContext = Boolean(item.isContext) && !isHovered && !isSelected;
            const canCollapse = isHierarchyView &&
                indent === 0 &&
                Boolean(item.groupKey) &&
                (item.childCountTotal || 0) > 0;
            const groupKey = item.groupKey || '';
            const isCollapsed = canCollapse ? Boolean(collapsedGroups[groupKey]) : false;
            return (<div key={virtualRow.key} data-index={virtualRow.index} ref={rowVirtualizer.measureElement} style={{
                    position: 'absolute',
                    top: 0,
                    left: 0,
                    width: '100%',
                    transform: `translateY(${virtualRow.start}px)`,
                }} className={isHierarchyView ? 'pb-3 flex gap-2 items-start' : 'pb-3'}>
                    {isHierarchyView ? (<div className="w-6 shrink-0 pt-3 flex justify-center">
                        {(() => {
                        if (canCollapse) {
                            return (<button type="button" className="h-6 w-6 inline-flex items-center justify-center rounded-md border border-border/60 bg-card text-muted-foreground hover:text-foreground hover:border-primary/30 hover:bg-muted transition-colors focus-ring" onClick={(e) => {
                                    e.stopPropagation();
                                    const nextCollapsed = !collapsedGroups[groupKey];
                                    setCollapsedGroups((prev) => ({ ...prev, [groupKey]: nextCollapsed }));
                                    // Keep selection visible when collapsing a group.
                                    if (nextCollapsed && selectedChunkIndex != null) {
                                        const selMeta = (effectiveChunks[selectedChunkIndex]?.metadata || {});
                                        const selParentRaw = selMeta.parent_id ?? selMeta.parent_node_id;
                                        const selParent = typeof selParentRaw === 'string' && selParentRaw.trim() ? selParentRaw.trim() : null;
                                        if (selParent && selParent === groupKey && selectedChunkIndex !== index) {
                                            selectChunkIndex(index);
                                        }
                                    }
                                }} aria-label={isCollapsed ? t('chunkList.groupToggle.expandGroup') : t('chunkList.groupToggle.collapseGroup')} title={isCollapsed
                                    ? t('chunkList.groupToggle.expandChildren', {
                                      visible: item.childCountVisible ?? 0,
                                      total: item.childCountTotal ?? 0,
                                    })
                                    : t('chunkList.groupToggle.collapseChildren', {
                                      visible: item.childCountVisible ?? 0,
                                      total: item.childCountTotal ?? 0,
                                    })}>
                            {isCollapsed ? (<ChevronRight className="h-4 w-4"/>) : (<ChevronDown className="h-4 w-4"/>)}
                          </button>);
                        }
                        else if (indent === 1) {
                                return (<div className="mt-1 h-2 w-2 rounded-full bg-muted-foreground/40"/>);
                            }
                            else {
                                return null;
                            }
                    })()}
                      </div>) : null}
                    <div className={[
                    'min-w-0 flex-1',
                    (isHierarchyView || isSectionView) && indent === 1 ? 'pl-3 border-l border-border/50' : '',
                    dimContext ? 'opacity-75' : '',
                ]
                    .filter(Boolean)
                    .join(' ')}>
                      <ChunkCard chunk={chunk} index={index} unit={unit} sourceFilename={previewData?.filename} isHovered={isHovered} isSelected={isSelected} isShort={isShort} isDuplicate={isDuplicate} isGap={isGap} gapBefore={gapBefore} isOverlap={isOverlap} overlapPrev={overlapPrev} isEdited={isEdited} isDisabled={disabledIndices.has(index)} isReviewed={chunkIsReviewed(chunk)} onToggleDisabled={() => toggleChunkDisabled(index)} onToggleReviewed={() => setChunkReviewed(index, !chunkIsReviewed(chunk))} query={query} onMouseEnter={() => setHoveredChunkIndex(index)} onMouseLeave={() => setHoveredChunkIndex(null)} onEdit={() => {
                    setInspectorIndex(index);
                    setInspectorOpen(true);
                }} onToggleSelect={() => {
                    selectChunkIndex(selectedChunkIndex === index ? null : index);
                }}/>
                    </div>
                  </div>);
        })) : (<div className="h-full flex flex-col items-center justify-center text-muted-foreground gap-2 py-12">
                <Search className="w-10 h-10 opacity-20"/>
                <p className="text-xs text-muted-foreground">{t('chunkList.states.noMatches')}</p>
              </div>));
    }
    else if (isLoading) {
            return (<div className="h-full flex flex-col items-center justify-center text-muted-foreground gap-2 py-12">
              <Loader2 className="w-8 h-8 animate-spin motion-reduce:animate-none opacity-20"/>
              <p className="text-xs">{t('chunkList.states.loading')}</p>
            </div>);
        }
        else if (error) {
                return (<div className="h-full flex flex-col items-center justify-center text-muted-foreground gap-3 px-5 py-12">
              <div role="alert" aria-live="polite" className="flex w-full max-w-[34rem] flex-col items-center rounded-2xl border border-destructive/20 bg-destructive/8 px-5 py-5 text-center shadow-[inset_0_1px_0_hsl(var(--background)/0.72)]">
                <span className="grid size-11 place-items-center rounded-2xl bg-destructive/10 text-destructive">
                  <AlertCircle className="size-5"/>
                </span>
                <p className="mt-3 text-sm font-semibold text-foreground">{t('chunkList.states.error')}</p>
                <p className="mt-2 max-w-[30rem] break-words text-xs leading-5 text-muted-foreground">{error}</p>
              </div>
              <Button variant="outline" size="sm" className="h-8 px-3 text-[11px]" onClick={() => runPreview()}>
                {t('chunkList.states.retry')}
              </Button>
            </div>);
            }
            else {
                return (<div className="h-full flex flex-col items-center justify-center text-muted-foreground gap-2 py-12">
              <Layers className="w-12 h-12 opacity-10"/>
              <p className="text-xs">{t('chunkList.states.waiting')}</p>
            </div>);
            }
})()}
          </motion.div>
        </AnimatePresence>
      </section>

      <ChunkInspectorDialog
        open={inspectorOpen}
        onOpenChange={(open) => {
          setInspectorOpen(open)
          if (!open) setInspectorIndex(null)
        }}
        chunk={inspectorChunk}
        index={inspectorIndex}
        sourceFilename={previewData?.filename}
        overrideUpdatedAt={inspectorOverrideUpdatedAt}
        onSave={({ content, metadata }) => {
          if (inspectorIndex == null) return
          updateChunkOverride(inspectorIndex, { content, metadata })
          toast.success(t('chunkList.toasts.savedEdit'))
        }}
        onReset={() => {
          if (inspectorIndex == null) return
          clearChunkOverride(inspectorIndex)
          toast.success(t('chunkList.toasts.resetEdit'))
        }}
      />
    </div>
  )
}
