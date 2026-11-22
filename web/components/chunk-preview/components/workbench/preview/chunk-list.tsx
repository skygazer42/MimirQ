/**
 * ChunkList - 切片列表
 */
'use client'

import { AnimatePresence, motion, useReducedMotion } from 'framer-motion'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useVirtualizer } from '@tanstack/react-virtual'
import {
  Chunking,
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
} from '@/components/icons'
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
import styles from '../compare.module.css'
import { ChunkCard } from '../../chunk-card'
import { ChunkInspectorDialog } from '../../chunk-inspector-dialog'
import {
  chunkIsReviewed,
  chunkNeedsReview,
  isChunkOverrideDisabled,
  isChunkOverrideEdited,
  isJsonObject,
} from '@/components/chunk-preview/utils/metadata'
import type { ChunkPreviewItem, ChunkPreviewResponse, ChunkPreviewReviewSignals, JsonObject } from '@/types'
import { computeRoleIndices } from '@/components/chunk-preview/utils/review-signals'
import { applyChunkEdits } from '@/components/chunk-preview/utils/chunk-edits'
import { getChunkSectionPath } from '@/components/chunk-preview/utils/sections'
import {
  buildChunkSearchIndex,
  searchChunkIndex,
  type ChunkSearchResult,
} from '@/components/chunk-preview/utils/retrieval-search'
import { rerankChunkSearchResults, type RerankedChunkSearchResult } from '@/components/chunk-preview/utils/reranker-sim'
import { writeClientStorage } from '@/lib/client-storage'
import { cn, detachPromise } from '@/lib/utils'
import {
  ORIGINAL_PREVIEW_MODE_STORAGE_KEY,
  getStoredOriginalPreviewMode,
  shouldRevealPdfPreviewOnChunkSelect,
  isPdfOriginalFile,
} from './pdf-dock'
import {
  buildChunkListRows,
  getApplicableReviewSignals,
  getSectionFilterValue,
  parseLengthBounds,
  SECTION_ALL_VALUE,
  SECTION_NONE_VALUE,
  type ChunkListEntry,
} from './chunk-list-model'

const QUERY_DEBOUNCE_MS = 150
type SortMode = 'index' | 'length_desc' | 'length_asc'
type ViewMode = 'flat' | 'hierarchy'
type GroupMode = 'none' | 'section'
type ChunkInspection = {
  preview: ChunkPreviewResponse
  fileId: string | undefined
  position: number
  open: boolean
}

const PAGE_ALL_VALUE = '__mimirq_page_all__'
const PAGE_UNKNOWN_VALUE = '__mimirq_page_unknown__'
function toSignalSet(values: readonly number[] | undefined): ReadonlySet<number> | undefined {
  return values === undefined ? undefined : new Set(values)
}

function toSignalMap(values: ChunkPreviewReviewSignals['gap_before_by_index']): Map<number, number> {
  const out = new Map<number, number>()
  if (values === undefined) return out
  for (const [key, value] of Object.entries(values)) out.set(Number(key), value)
  return out
}

export function ChunkList({ mobileView }: Readonly<{ mobileView?: 'original' | 'chunks' }>) {
  const t = useTranslations('ChunkPreview')
  const {
    previewData,
    previewSourceFile,
    gapReviewRequest,
    chunkOverrides,
    currentFile,
    currentFileItem,
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
  const unit: 'chars' | 'tokens' = previewData?.params.unit === 'tokens' ? 'tokens' : 'chars'
  const [queryInput, setQueryInput] = useState('')
  const [query, setQuery] = useState('')
  const [sortMode, setSortMode] = useState<SortMode>('index')
  const [viewMode, setViewMode] = useState<ViewMode>('flat')
  const [groupMode, setGroupMode] = useState<GroupMode>('none')
  const [collapsedGroups, setCollapsedGroups] = useState<ReadonlySet<string>>(() => new Set<string>())
  const [pageFilter, setPageFilter] = useState<string>(PAGE_ALL_VALUE)
  const [sectionFilter, setSectionFilter] = useState<string>(SECTION_ALL_VALUE)
  const [filtersOpen, setFiltersOpen] = useState(false)
  const [retrieveOpen, setRetrieveOpen] = useState(false)
  const [retrieveQuery, setRetrieveQuery] = useState('')
  const [rerankEnabled, setRerankEnabled] = useState(false)
  const [rerankAlphaPct, setRerankAlphaPct] = useState(65)
  const [minimumLengthInput, setMinimumLengthInput] = useState('')
  const [maximumLengthInput, setMaximumLengthInput] = useState('')
  const [onlyShort, setOnlyShort] = useState(false)
  const [onlyDuplicate, setOnlyDuplicate] = useState(false)
  const [onlyEdited, setOnlyEdited] = useState(false)
  const [onlyDisabled, setOnlyDisabled] = useState(false)
  const [onlyGap, setOnlyGap] = useState(false)
  const [onlyOverlap, setOnlyOverlap] = useState(false)
  const [onlyNeedsReview, setOnlyNeedsReview] = useState(false)
  const [inspection, setInspection] = useState<ChunkInspection | null>(null)
  const scrollRef = useRef<HTMLDivElement>(null)
  const consumedGapRequest = useRef(gapReviewRequest)
  const queryTimerRef = useRef<number | null>(null)
  const commitListQuery = useCallback((value: string) => {
    if (queryTimerRef.current !== null) {
      globalThis.window.clearTimeout(queryTimerRef.current)
      queryTimerRef.current = null
    }
    setQueryInput(value)
    setQuery(value)
  }, [])
  const clearSignalFilters = useCallback(() => {
    setOnlyShort(false)
    setOnlyDuplicate(false)
    setOnlyGap(false)
    setOnlyOverlap(false)
  }, [])
  const clearDataFilters = useCallback(() => {
    clearSignalFilters()
    commitListQuery('')
    setPageFilter(PAGE_ALL_VALUE)
    setSectionFilter(SECTION_ALL_VALUE)
    setMinimumLengthInput('')
    setMaximumLengthInput('')
    setOnlyEdited(false)
    setOnlyDisabled(false)
    setOnlyNeedsReview(false)
  }, [clearSignalFilters, commitListQuery])

  const supportsPdfDocking = isPdfOriginalFile(previewData, previewSourceFile ?? currentFile)

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
      scrollRef.current?.focus({ preventScroll: true })
    },
    [setOriginalPanelVisible, setSelectedChunkIndex, showOriginalPanel, supportsPdfDocking],
  )

  const openDockedPdfPreview = useCallback(() => {
    writeClientStorage(ORIGINAL_PREVIEW_MODE_STORAGE_KEY, 'pdf')
    setOriginalPanelVisible(true)
    scrollRef.current?.focus({ preventScroll: true })
  }, [setOriginalPanelVisible])

  useEffect(() => {
    const timer = globalThis.window.setTimeout(() => {
      queryTimerRef.current = null
      setQuery(queryInput)
    }, QUERY_DEBOUNCE_MS)
    queryTimerRef.current = timer
    return () => {
      globalThis.window.clearTimeout(timer)
      queryTimerRef.current = null
    }
  }, [queryInput])

  useEffect(() => {
    const focusGaps = gapReviewRequest !== consumedGapRequest.current
    consumedGapRequest.current = gapReviewRequest
    clearDataFilters()
    setSortMode('index')
    setViewMode('flat')
    setGroupMode('none')
    setFiltersOpen(focusGaps)
    setRetrieveOpen(false)
    setRetrieveQuery('')
    setRerankEnabled(false)
    setRerankAlphaPct(65)
    setCollapsedGroups(new Set())
    setOnlyGap(focusGaps)
    setInspection(null)
    if (focusGaps) setSelectedChunkIndex(null)
    const container = scrollRef.current
    if (container !== null) container.scrollTop = 0
  }, [gapReviewRequest, previewData, currentFileItem?.id, setSelectedChunkIndex, clearDataFilters])

  const effectiveChunks = useMemo(() => {
    if (previewData === null) return []
    return previewData.chunks.map((chunk) => applyChunkEdits(chunk, chunkOverrides[chunk.index]))
  }, [previewData, chunkOverrides])

  const pageOptions = useMemo(() => {
    const pages = new Set<number>()
    let hasUnknown = false
    for (const c of effectiveChunks) {
      if (typeof c.page_number === 'number') pages.add(c.page_number)
      else hasUnknown = true
    }
    const list = Array.from(pages).sort((a, b) => a - b)
    return { list, hasUnknown }
  }, [effectiveChunks])

  const editedIndices = useMemo(
    () =>
      new Set(
        effectiveChunks
          .filter((chunk) => isChunkOverrideEdited(chunkOverrides[chunk.index]))
          .map((chunk) => chunk.index),
      ),
    [effectiveChunks, chunkOverrides],
  )
  const disabledIndices = useMemo(
    () =>
      new Set(
        effectiveChunks
          .filter((chunk) => isChunkOverrideDisabled(chunkOverrides[chunk.index]))
          .map((chunk) => chunk.index),
      ),
    [effectiveChunks, chunkOverrides],
  )

  const selectedChunk = selectedChunkIndex === null ? undefined : effectiveChunks[selectedChunkIndex]

  const copySelectedChunk = useCallback(async () => {
    if (selectedChunk === undefined) return
    if (!globalThis.navigator?.clipboard?.writeText) {
      toast.error(t('chunkList.toasts.clipboardUnsupported'))
      return
    }
    try {
      await globalThis.navigator.clipboard.writeText(selectedChunk.content)
      toast.success(t('chunkList.toasts.copiedSelected'))
    } catch {
      toast.error(t('chunkList.toasts.copyFailed'))
    }
  }, [selectedChunk, t])

  const sectionOptions = useMemo(() => {
    const seen = new Set<string>()
    const list: string[] = []
    let hasNone = false
    for (const c of effectiveChunks) {
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

  const hasRetrieveQuery = retrieveQuery.trim().length > 0
  const retrievalIndex = useMemo(() => {
    if (!hasRetrieveQuery) return null
    return buildChunkSearchIndex(effectiveChunks)
  }, [effectiveChunks, hasRetrieveQuery])

  const retrievalResults: ChunkSearchResult[] = useMemo(() => {
    if (retrievalIndex === null) return []
    const q = retrieveQuery.trim()
    if (!q) return []
    return searchChunkIndex(retrievalIndex, q, { limit: 10 })
  }, [retrieveQuery, retrievalIndex])

  const retrievalDisplayResults: Array<(ChunkSearchResult | RerankedChunkSearchResult) & { position: number }> =
    useMemo(() => {
      const results = rerankEnabled
        ? rerankChunkSearchResults(retrievalResults, retrieveQuery, effectiveChunks, { alpha: rerankAlphaPct / 100 })
        : retrievalResults
      return results.map((result) => {
        const position = effectiveChunks.findIndex((chunk) => chunk.index === result.index)
        if (position < 0) throw new Error(`Missing chunk ${result.index} for local search display`)
        return { ...result, position }
      })
    }, [rerankEnabled, retrievalResults, retrieveQuery, effectiveChunks, rerankAlphaPct])

  const reviewSignals = useMemo(
    () => getApplicableReviewSignals(previewData, chunkOverrides),
    [previewData, chunkOverrides],
  )
  const duplicateIndices = useMemo(
    () => toSignalSet(reviewSignals?.duplicate_indices),
    [reviewSignals?.duplicate_indices],
  )

  const shortIndices = useMemo(() => toSignalSet(reviewSignals?.short_indices), [reviewSignals?.short_indices])

  const roleIndices = useMemo(() => computeRoleIndices(effectiveChunks), [effectiveChunks])
  const hasHierarchy = roleIndices.parents.size > 0 || roleIndices.children.size > 0
  const isHierarchyView = hasHierarchy && viewMode === 'hierarchy'
  const isSectionView = groupMode === 'section' && !isHierarchyView
  const lengthBounds = useMemo(
    () => parseLengthBounds(minimumLengthInput, maximumLengthInput),
    [minimumLengthInput, maximumLengthInput],
  )

  const coverageSignals = useMemo(
    () => ({
      basis: reviewSignals?.basis,
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
    ],
  )
  const unavailableSignalFilter =
    (onlyShort && shortIndices === undefined) ||
    (onlyDuplicate && duplicateIndices === undefined) ||
    (onlyGap && coverageSignals.gapIndices === undefined) ||
    (onlyOverlap && coverageSignals.overlapIndices === undefined)

  const needsReviewIndices = useMemo(() => {
    const out = new Set<number>()
    for (const chunk of effectiveChunks) if (chunkNeedsReview(chunk)) out.add(chunk.index)
    return out
  }, [effectiveChunks])

  const setChunkReviewed = useCallback(
    (position: number, reviewed: boolean) => {
      const chunk = effectiveChunks[position]

      const metadata: JsonObject = { ...chunk.metadata }
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

      updateChunkOverride(chunk.index, { metadata })
      toast.success(reviewed ? t('chunkList.toasts.markedReviewed') : t('chunkList.toasts.restoredReview'))
    },
    [effectiveChunks, t, updateChunkOverride],
  )

  const currentInspection =
    inspection !== null && inspection.preview === previewData && inspection.fileId === currentFileItem?.id
      ? inspection
      : null
  const inspectorChunk = currentInspection === null ? undefined : effectiveChunks[currentInspection.position]

  const getFilteredChunks = useCallback(
    (text: string): ChunkListEntry[] => {
      if (!lengthBounds.valid || unavailableSignalFilter) return []
      const { minimum, maximum } = lengthBounds
      function getChunkLength(chunk: ChunkPreviewItem): number | undefined {
        if (unit === 'tokens') return typeof chunk.tokens_est === 'number' ? chunk.tokens_est : undefined
        return chunk.length
      }
      const q = text.trim().toLowerCase()
      const base = effectiveChunks
        .map((chunk, position) => ({ chunk, position }))
        .filter(({ chunk }) => {
          if (pageFilter === PAGE_ALL_VALUE) {
            // pass
          } else if (pageFilter === PAGE_UNKNOWN_VALUE) {
            if (typeof chunk.page_number === 'number') return false
          } else if (typeof chunk.page_number !== 'number' || String(chunk.page_number) !== pageFilter) return false

          const sectionPath = getChunkSectionPath(chunk)
          if (sectionFilter === SECTION_ALL_VALUE) {
            // pass
          } else if (sectionFilter === SECTION_NONE_VALUE) {
            if (sectionPath) return false
          } else if (getSectionFilterValue(sectionPath) !== sectionFilter) return false

          const contentOk = q ? chunk.content.toLowerCase().includes(q) : true
          if (!contentOk) return false

          const length = getChunkLength(chunk)
          if ((minimum !== undefined || maximum !== undefined) && length === undefined) return false
          if (length !== undefined && minimum !== undefined && length < minimum) return false
          if (length !== undefined && maximum !== undefined && length > maximum) return false

          if (onlyShort && shortIndices?.has(chunk.index) !== true) return false
          if (onlyDuplicate && duplicateIndices?.has(chunk.index) !== true) return false
          if (onlyEdited && !editedIndices.has(chunk.index)) return false
          if (onlyDisabled && !disabledIndices.has(chunk.index)) return false
          if (onlyGap && coverageSignals.gapIndices?.has(chunk.index) !== true) return false
          if (onlyOverlap && coverageSignals.overlapIndices?.has(chunk.index) !== true) return false
          if (onlyNeedsReview && !needsReviewIndices.has(chunk.index)) return false

          return true
        })

      if (sortMode !== 'index') {
        base.sort((a, b) => {
          const left = getChunkLength(a.chunk)
          const right = getChunkLength(b.chunk)
          if (left === undefined) return right === undefined ? 0 : 1
          if (right === undefined) return -1
          return sortMode === 'length_desc' ? right - left : left - right
        })
      }
      return base
    },
    [
      effectiveChunks,
      pageFilter,
      sectionFilter,
      sortMode,
      lengthBounds,
      unavailableSignalFilter,
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
    ],
  )
  const flatFilteredChunks = useMemo(() => getFilteredChunks(query), [getFilteredChunks, query])

  const matchCount = flatFilteredChunks.length
  const isQueryPending = queryInput !== query

  const hasOtherDataFilters =
    pageFilter !== PAGE_ALL_VALUE ||
    sectionFilter !== SECTION_ALL_VALUE ||
    minimumLengthInput.trim().length > 0 ||
    maximumLengthInput.trim().length > 0 ||
    onlyShort ||
    onlyDuplicate ||
    onlyEdited ||
    onlyDisabled ||
    onlyGap ||
    onlyOverlap ||
    onlyNeedsReview
  const hasDataFilters = query.trim().length > 0 || hasOtherDataFilters

  const displayRows = useMemo(
    () =>
      buildChunkListRows(effectiveChunks, flatFilteredChunks, {
        view: isHierarchyView ? 'hierarchy' : isSectionView ? 'section' : 'flat',
        collapsedGroups,
        forceExpand: hasDataFilters,
        noSectionLabel: t('chunkList.section.none'),
      }),
    [effectiveChunks, flatFilteredChunks, isHierarchyView, isSectionView, collapsedGroups, hasDataFilters, t],
  )

  const getRowKey = useCallback((rowIndex: number) => displayRows[rowIndex].key, [displayRows])

  function revealRetrievedChunk(position: number) {
    const pendingEntries = getFilteredChunks(queryInput)
    const pendingRows = buildChunkListRows(effectiveChunks, pendingEntries, {
      view: isHierarchyView ? 'hierarchy' : isSectionView ? 'section' : 'flat',
      collapsedGroups,
      forceExpand: queryInput.trim().length > 0 || hasOtherDataFilters,
      noSectionLabel: t('chunkList.section.none'),
    })
    const visible = pendingRows.some((row) => row.kind !== 'section' && row.position === position)
    if (!visible) {
      const matches = pendingEntries.some((entry) => entry.position === position)
      if (!matches) {
        clearDataFilters()
        toast.info(t('chunkList.toasts.filtersClearedForResult'))
      } else commitListQuery(queryInput)
      const entries = matches
        ? pendingEntries
        : effectiveChunks.map((chunk, sourcePosition) => ({ chunk, position: sourcePosition }))
      const expanded = buildChunkListRows(effectiveChunks, entries, {
        view: isHierarchyView ? 'hierarchy' : isSectionView ? 'section' : 'flat',
        collapsedGroups: new Set<string>(),
        forceExpand: false,
        noSectionLabel: t('chunkList.section.none'),
      })
      const target = expanded.find((row) => row.kind !== 'section' && row.position === position)
      if (target !== undefined && target.kind !== 'section' && target.groupKey !== undefined) {
        const groupKey = target.groupKey
        setCollapsedGroups((previous) => {
          const next = new Set(previous)
          next.delete(groupKey)
          return next
        })
      }
    } else commitListQuery(queryInput)
    selectChunkIndex(position)
  }

  // eslint-disable-next-line react-hooks/incompatible-library
  const rowVirtualizer = useVirtualizer({
    count: displayRows.length,
    getItemKey: getRowKey,
    getScrollElement: () => scrollRef.current,
    estimateSize: (idx) => (displayRows[idx].kind === 'section' ? 44 : 140),
    overscan: 8,
  })

  // Keep the selected chunk visible (best effort).
  useEffect(() => {
    if (selectedChunkIndex == null) return
    const pos = displayRows.findIndex((item) => item.kind !== 'section' && item.position === selectedChunkIndex)
    if (pos >= 0) {
      // Wait for the mobile pane to be visible and measured before restoring its selected row.
      const frame = requestAnimationFrame(() => {
        if (scrollRef.current?.clientHeight) rowVirtualizer.scrollToIndex(pos, { align: 'start' })
      })
      return () => cancelAnimationFrame(frame)
    }
  }, [displayRows, mobileView, rowVirtualizer, selectedChunkIndex])

  const matchesLabel =
    previewData !== null && hasDataFilters && lengthBounds.valid && !unavailableSignalFilter
      ? `${matchCount} / ${previewData.total_chunks}`
      : null

  const filterActiveCount = [
    query.trim().length > 0,
    hasHierarchy && viewMode !== 'flat',
    isSectionView,
    sortMode !== 'index',
    pageFilter !== PAGE_ALL_VALUE,
    sectionFilter !== SECTION_ALL_VALUE,
    minimumLengthInput.trim().length > 0 || maximumLengthInput.trim().length > 0,
    onlyShort,
    onlyDuplicate,
    onlyGap,
    onlyOverlap,
    onlyNeedsReview,
    onlyEdited,
    onlyDisabled,
  ].filter((active) => active).length

  function toggleGroup(key: string) {
    setCollapsedGroups((previous) => {
      const next = new Set(previous)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  const qualitySummaryItems = [
    {
      key: 'short',
      active: onlyShort,
      unavailable: shortIndices === undefined,
      label: t('chunkList.filters.shortLabel', { count: shortIndices === undefined ? '—' : shortIndices.size }),
      title: shortIndices === undefined ? t('chunkList.filters.unavailable') : t('chunkList.filters.onlyShortTitle'),
      icon: AlertCircle,
      toggle: () => setOnlyShort((v) => !v),
    },
    {
      key: 'duplicate',
      active: onlyDuplicate,
      unavailable: duplicateIndices === undefined,
      label: t('chunkList.filters.duplicateLabel', {
        count: duplicateIndices === undefined ? '—' : duplicateIndices.size,
      }),
      title:
        duplicateIndices === undefined ? t('chunkList.filters.unavailable') : t('chunkList.filters.onlyDuplicateTitle'),
      icon: Copy,
      toggle: () => setOnlyDuplicate((v) => !v),
    },
    {
      key: 'gap',
      active: onlyGap,
      unavailable: coverageSignals.gapIndices === undefined,
      label: t('chunkList.filters.gapLabel', {
        count: coverageSignals.gapIndices === undefined ? '—' : coverageSignals.gapIndices.size,
      }),
      title:
        coverageSignals.gapIndices === undefined
          ? t('chunkList.filters.unavailable')
          : coverageSignals.basis === 'child'
            ? t('chunkList.filters.onlyGapTitleChildCoverage')
            : t('chunkList.filters.onlyGapTitle'),
      toggle: () => setOnlyGap((v) => !v),
    },
    {
      key: 'overlap',
      active: onlyOverlap,
      unavailable: coverageSignals.overlapIndices === undefined,
      label: t('chunkList.filters.overlapLabel', {
        count: coverageSignals.overlapIndices === undefined ? '—' : coverageSignals.overlapIndices.size,
      }),
      title:
        coverageSignals.overlapIndices === undefined
          ? t('chunkList.filters.unavailable')
          : coverageSignals.basis === 'child'
            ? t('chunkList.filters.onlyOverlapTitleChildCoverage')
            : t('chunkList.filters.onlyOverlapTitle'),
      toggle: () => setOnlyOverlap((v) => !v),
    },
    {
      key: 'review',
      active: onlyNeedsReview,
      unavailable: false,
      label: t('chunkList.filters.reviewLabel', { count: needsReviewIndices.size }),
      title: t('chunkList.filters.onlyNeedsReviewTitle'),
      icon: Code2,
      toggle: () => setOnlyNeedsReview((v) => !v),
    },
    {
      key: 'edited',
      active: onlyEdited,
      unavailable: false,
      label: t('chunkList.filters.editedLabel', { count: editedIndices.size }),
      title: t('chunkList.filters.onlyEditedTitle'),
      icon: Pencil,
      toggle: () => setOnlyEdited((v) => !v),
    },
    {
      key: 'skipped',
      active: onlyDisabled,
      unavailable: false,
      label: t('chunkList.filters.skippedLabel', { count: disabledIndices.size }),
      title: t('chunkList.filters.onlySkippedTitle'),
      icon: EyeOff,
      toggle: () => setOnlyDisabled((v) => !v),
    },
  ]
  const noServerSignals =
    shortIndices === undefined &&
    duplicateIndices === undefined &&
    coverageSignals.gapIndices === undefined &&
    coverageSignals.overlapIndices === undefined

  const filterButtonLabel =
    filterActiveCount > 0
      ? t('chunkList.toolbar.filtersWithCount', { count: filterActiveCount })
      : t('chunkList.toolbar.filters')

  const showVirtualized = previewData !== null && displayRows.length > 0
  const listSurfaceKey = `chunk-list-surface:${viewMode}:${groupMode}`
  const surfaceTransition = useMemo(
    () => ({
      duration: reduceMotion ? 0 : 0.22,
      ease: [0.16, 1, 0.3, 1] as const,
    }),
    [reduceMotion],
  )

  const expandableGroupKeys = useMemo(() => {
    const out: string[] = []
    if (isHierarchyView) {
      for (const row of displayRows) {
        if (row.kind === 'parent' && !row.forceExpanded) out.push(row.groupKey)
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
    return expandableGroupKeys.every((key) => collapsedGroups.has(key))
  }, [collapsedGroups, expandableGroupKeys])

  const sortLengthDescLabel =
    unit === 'tokens' ? t('chunkList.sort.lengthDescTokens') : t('chunkList.sort.lengthDescChars')
  const sortLengthAscLabel =
    unit === 'tokens' ? t('chunkList.sort.lengthAscTokens') : t('chunkList.sort.lengthAscChars')
  const lengthFilterLabel =
    unit === 'tokens' ? t('chunkList.lengthFilter.labelTokens') : t('chunkList.lengthFilter.labelChars')
  const minLengthFilterAria =
    unit === 'tokens' ? t('chunkList.lengthFilter.minAriaTokens') : t('chunkList.lengthFilter.minAriaChars')
  const maxLengthFilterAria =
    unit === 'tokens' ? t('chunkList.lengthFilter.maxAriaTokens') : t('chunkList.lengthFilter.maxAriaChars')
  const allGroupsToggleTitle = allGroupsCollapsed
    ? t('chunkList.groupToggle.expandAllTitle')
    : t('chunkList.groupToggle.collapseAllTitle')
  const allGroupsToggleLabel = allGroupsCollapsed
    ? t('chunkList.groupToggle.expand')
    : t('chunkList.groupToggle.collapse')
  const chunkListToolbarButtonClass = styles.listButton
  const chunkListToolbarActiveButtonClass = `${styles.listButton} ${styles.listButtonActive}`

  return (
    <div className={styles.pane}>
      <div
        role="region"
        aria-label={t('chunkList.toolsLabel')}
        className="min-h-0 max-h-[50%] shrink-0 overflow-y-auto"
      >
        <div className="shrink-0 border-b border-border bg-card">
          <div className="flex flex-col">
            <div className={styles.paneHead}>
              <div className="flex min-w-0 items-center gap-1.5">
                <span className="flex min-w-0 items-center gap-1.5 whitespace-nowrap text-[13px] font-semibold text-foreground">
                  <span className="inline-flex items-center text-muted-foreground">
                    <Rows3 className="h-3.5 w-3.5" />
                  </span>
                  {t('chunkList.title')}
                </span>
                {previewData === null ? null : <span className={styles.metadata}>{previewData.total_chunks}</span>}
                {matchesLabel ? (
                  <span className="truncate font-mono text-[10.5px] text-muted-foreground">{matchesLabel}</span>
                ) : null}
              </div>
            </div>

            <div data-chunk-list-toolbar className={cn(styles.listToolRow, 'px-6 py-2.5')}>
              <div data-chunk-list-search className={cn(styles.listSearch, 'relative')}>
                <Search className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                <Input
                  value={queryInput}
                  onChange={(e) => setQueryInput(e.target.value)}
                  placeholder={t('chunkList.searchPlaceholder')}
                  className="h-full min-w-0 flex-1 border-0 bg-transparent px-0 pr-5 text-[13px] shadow-none focus-visible:ring-1 focus-visible:ring-ring"
                  aria-label="搜索切块内容"
                />
                {queryInput ? (
                  <button
                    type="button"
                    className="absolute right-2 top-1/2 -translate-y-1/2 rounded text-muted-foreground transition-colors hover:text-foreground focus-ring"
                    onClick={() => {
                      commitListQuery('')
                    }}
                    aria-label={t('chunkList.clearSearch')}
                    title={t('chunkList.clearSearch')}
                  >
                    <X className="w-3 h-3" />
                  </button>
                ) : null}
              </div>
              {selectedChunk === undefined ? null : (
                <>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    className={cn(chunkListToolbarButtonClass, styles.desktopListAction)}
                    onClick={() => detachPromise(copySelectedChunk())}
                  >
                    {t('chunkList.actions.copySelected')}
                  </Button>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    className={cn(chunkListToolbarButtonClass, styles.desktopListAction)}
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
                className={
                  retrieveOpen || retrieveQuery.trim() ? chunkListToolbarActiveButtonClass : chunkListToolbarButtonClass
                }
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
                className={
                  filtersOpen || filterActiveCount > 0 ? chunkListToolbarActiveButtonClass : chunkListToolbarButtonClass
                }
                onClick={() => setFiltersOpen((v) => !v)}
                aria-expanded={filtersOpen}
                aria-controls="chunk-list-filter-panel"
                title={filterButtonLabel}
              >
                <SlidersHorizontal className="h-3.5 w-3.5 mr-1" />
                {filterButtonLabel}
              </Button>
            </div>

            {filtersOpen ? (
              <div id="chunk-list-filter-panel" className={cn(styles.listFilters, 'px-6 pb-3')}>
                <div className={styles.qualityTools}>
                  <div className="flex min-w-0 flex-wrap items-center gap-1.5">
                    {effectiveChunks.length > 0 ? (
                      <>
                        {qualitySummaryItems.map((item) => {
                          const Icon = item.icon
                          return (
                            <Button
                              key={item.key}
                              type="button"
                              variant={item.active ? 'secondary' : 'ghost'}
                              size="sm"
                              className="h-8 rounded px-2 text-[13px]"
                              onClick={item.toggle}
                              aria-pressed={item.active}
                              disabled={item.unavailable && !item.active}
                              title={item.title}
                            >
                              {Icon ? <Icon className="mr-1 h-3 w-3" /> : null}
                              {item.label}
                            </Button>
                          )
                        })}
                        {noServerSignals ? (
                          <span role="status" className="text-[13px] text-muted-foreground">
                            {t('chunkList.toolbar.noQualitySignals')}
                          </span>
                        ) : null}
                      </>
                    ) : (
                      <span className="text-[13px] text-muted-foreground">
                        {t('chunkList.toolbar.noQualitySignals')}
                      </span>
                    )}
                  </div>
                </div>

                <div className="flex flex-wrap items-center gap-1.5">
                  {hasHierarchy ? (
                    <Select
                      value={viewMode}
                      onValueChange={(value) => {
                        const next = value as ViewMode
                        setViewMode(next)
                        if (next === 'hierarchy') {
                          setSortMode('index')
                          setGroupMode('none')
                        }
                        if (next !== 'hierarchy') setCollapsedGroups(new Set())
                      }}
                    >
                      <SelectTrigger
                        aria-label={t('chunkList.view.placeholder')}
                        className="h-[28px] w-[112px] rounded-lg border-border/60 bg-background text-[13px]"
                      >
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
                        setCollapsedGroups(new Set())
                        if (next === 'section') setSortMode('index')
                      }}
                    >
                      <SelectTrigger
                        aria-label={t('chunkList.group.placeholder')}
                        className="h-[28px] w-[112px] rounded-lg border-border/60 bg-background text-[13px]"
                      >
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
                      className="h-[28px] rounded-lg px-2 text-[13px]"
                      onClick={() => {
                        if (allGroupsCollapsed) {
                          setCollapsedGroups(new Set())
                          return
                        }
                        setCollapsedGroups(new Set(expandableGroupKeys))
                      }}
                      title={allGroupsToggleTitle}
                    >
                      {allGroupsToggleLabel}
                    </Button>
                  ) : null}
                  <Select
                    value={sortMode}
                    onValueChange={(value) => setSortMode(value as SortMode)}
                    disabled={isHierarchyView || isSectionView}
                  >
                    <SelectTrigger
                      aria-label={t('chunkList.sort.placeholder')}
                      className="h-[28px] w-[122px] rounded-lg border-border/60 bg-background text-[13px]"
                    >
                      <SelectValue placeholder={t('chunkList.sort.placeholder')} />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="index">{t('chunkList.sort.index')}</SelectItem>
                      <SelectItem value="length_desc">{sortLengthDescLabel}</SelectItem>
                      <SelectItem value="length_asc">{sortLengthAscLabel}</SelectItem>
                    </SelectContent>
                  </Select>
                  <Select value={pageFilter} onValueChange={(value) => setPageFilter(value)}>
                    <SelectTrigger
                      aria-label={t('chunkList.page.placeholder')}
                      className="h-[28px] w-[98px] rounded-lg border-border/60 bg-background text-[13px]"
                    >
                      <SelectValue placeholder={t('chunkList.page.placeholder')} />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value={PAGE_ALL_VALUE}>{t('chunkList.page.all')}</SelectItem>
                      {pageOptions.hasUnknown ? (
                        <SelectItem value={PAGE_UNKNOWN_VALUE}>{t('chunkList.page.unknown')}</SelectItem>
                      ) : null}
                      {pageOptions.list.map((p) => (
                        <SelectItem key={p} value={String(p)}>
                          P.{p}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  {sectionOptions.list.length > 0 || sectionOptions.hasNone ? (
                    <Select value={sectionFilter} onValueChange={(value) => setSectionFilter(value)}>
                      <SelectTrigger
                        aria-label={t('chunkList.section.placeholder')}
                        className="h-[28px] w-[138px] rounded-lg border-border/60 bg-background text-[13px]"
                      >
                        <SelectValue placeholder={t('chunkList.section.placeholder')} />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value={SECTION_ALL_VALUE}>{t('chunkList.section.all')}</SelectItem>
                        {sectionOptions.hasNone ? (
                          <SelectItem value={SECTION_NONE_VALUE}>{t('chunkList.section.none')}</SelectItem>
                        ) : null}
                        {sectionOptions.list.map((sec) => (
                          <SelectItem key={sec} value={getSectionFilterValue(sec)}>
                            <span className="block max-w-[520px] truncate" title={sec}>
                              {sec}
                            </span>
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  ) : null}
                  <div className="flex items-center gap-1 text-[13px] text-muted-foreground">
                    <span className="mr-1">{lengthFilterLabel}</span>
                    <Input
                      value={minimumLengthInput}
                      onChange={(event) => setMinimumLengthInput(event.target.value)}
                      aria-invalid={!lengthBounds.valid && lengthBounds.minimumInvalid}
                      aria-describedby={lengthBounds.valid ? undefined : 'chunk-list-length-error'}
                      placeholder={t('chunkList.lengthFilter.minPlaceholder')}
                      className="h-[28px] w-[58px] rounded-lg border-border/60 bg-background px-2 text-[13px] font-mono"
                      inputMode="numeric"
                      aria-label={minLengthFilterAria}
                    />
                    <span className="px-1 opacity-70">-</span>
                    <Input
                      value={maximumLengthInput}
                      onChange={(event) => setMaximumLengthInput(event.target.value)}
                      aria-invalid={!lengthBounds.valid && lengthBounds.maximumInvalid}
                      aria-describedby={lengthBounds.valid ? undefined : 'chunk-list-length-error'}
                      placeholder={t('chunkList.lengthFilter.maxPlaceholder')}
                      className="h-[28px] w-[58px] rounded-lg border-border/60 bg-background px-2 text-[13px] font-mono"
                      inputMode="numeric"
                      aria-label={maxLengthFilterAria}
                    />
                    {minimumLengthInput !== '' || maximumLengthInput !== '' ? (
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        className="h-[28px] rounded-lg px-2 text-[13px]"
                        onClick={() => {
                          setMinimumLengthInput('')
                          setMaximumLengthInput('')
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
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        className="h-[28px] rounded-lg px-2 text-[13px]"
                      >
                        {t('chunkList.batch.trigger')}
                      </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="start">
                      <DropdownMenuItem
                        disabled={isQueryPending || matchCount === 0}
                        onSelect={() => {
                          const targets = flatFilteredChunks.map(({ chunk }) => chunk.index)
                          const delta = targets.filter((i) => !disabledIndices.has(i)).length
                          setChunksDisabled(targets, true)
                          toast.success(t('chunkList.batch.skipFilteredSuccess', { count: delta }))
                        }}
                      >
                        {t('chunkList.batch.skipFiltered', { count: matchCount })}
                      </DropdownMenuItem>

                      <DropdownMenuSeparator />

                      <DropdownMenuItem
                        disabled={duplicateIndices === undefined || duplicateIndices.size === 0}
                        onSelect={() => {
                          if (duplicateIndices === undefined) return
                          const targets = Array.from(duplicateIndices)
                          const delta = targets.filter((i) => !disabledIndices.has(i)).length
                          setChunksDisabled(targets, true)
                          toast.success(t('chunkList.batch.skipDuplicatesSuccess', { count: delta }))
                        }}
                      >
                        {t('chunkList.batch.skipDuplicates', {
                          count: duplicateIndices === undefined ? '—' : duplicateIndices.size,
                        })}
                      </DropdownMenuItem>
                      <DropdownMenuItem
                        disabled={shortIndices === undefined || shortIndices.size === 0}
                        onSelect={() => {
                          if (shortIndices === undefined) return
                          const targets = Array.from(shortIndices)
                          const delta = targets.filter((i) => !disabledIndices.has(i)).length
                          setChunksDisabled(targets, true)
                          toast.success(t('chunkList.batch.skipShortSuccess', { count: delta }))
                        }}
                      >
                        {t('chunkList.batch.skipShort', {
                          count: shortIndices === undefined ? '—' : shortIndices.size,
                        })}
                      </DropdownMenuItem>

                      {hasHierarchy ? (
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
                        disabled={isQueryPending || matchCount === 0 || disabledIndices.size === 0}
                        onSelect={() => {
                          const targets = flatFilteredChunks.map(({ chunk }) => chunk.index)
                          const delta = targets.filter((i) => disabledIndices.has(i)).length
                          setChunksDisabled(targets, false)
                          toast.success(t('chunkList.batch.restoreFilteredSuccess', { count: delta }))
                        }}
                      >
                        {t('chunkList.batch.restoreFiltered')}
                      </DropdownMenuItem>
                    </DropdownMenuContent>
                  </DropdownMenu>
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
                aria-label={t('chunkList.retrieve.queryPlaceholder')}
                onChange={(event) => setRetrieveQuery(event.currentTarget.value)}
                placeholder={t('chunkList.retrieve.queryPlaceholder')}
                className="h-8 text-[13px] bg-background"
              />
              {retrieveQuery ? (
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="h-8 px-2 text-[13px]"
                  onClick={() => setRetrieveQuery('')}
                >
                  {t('chunkList.retrieve.clear')}
                </Button>
              ) : null}
              <Button
                type="button"
                variant={rerankEnabled ? 'secondary' : 'ghost'}
                size="sm"
                className="h-8 px-2 text-[13px]"
                onClick={() => setRerankEnabled((v) => !v)}
                title={t('chunkList.retrieve.rerankTitle')}
              >
                {t('chunkList.retrieve.rerank')}
              </Button>
              {rerankEnabled ? (
                <div className="flex items-center gap-2">
                  <span
                    className="text-[13px] text-muted-foreground font-mono"
                    title={t('chunkList.retrieve.alphaTitle')}
                  >
                    {rerankAlphaPct}%
                  </span>
                  <input
                    type="range"
                    min={0}
                    max={100}
                    value={rerankAlphaPct}
                    onChange={(e) => setRerankAlphaPct(Number(e.target.value))}
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
                      onClick={() => revealRetrievedChunk(r.position)}
                      title={r.section === null ? undefined : r.section}
                    >
                      <div className="flex items-center gap-2">
                        <span className="text-[13px] font-mono font-bold px-1.5 py-0.5 rounded bg-primary/10 text-primary border border-primary/20">
                          #{r.position + 1}
                        </span>
                        {disabledIndices.has(r.index) ? (
                          <span className="text-[13px] font-mono px-1.5 py-0.5 rounded bg-muted/60 text-muted-foreground border border-border/60">
                            {t('chunkList.retrieve.skippedBadge')}
                          </span>
                        ) : null}
                        {r.page_number == null ? null : (
                          <span className="text-[13px] text-muted-foreground">P.{r.page_number}</span>
                        )}
                        {r.section ? (
                          <span className="min-w-0 flex-1 text-[13px] text-muted-foreground truncate">{r.section}</span>
                        ) : (
                          <span className="min-w-0 flex-1" />
                        )}
                        {'combined_score' in r ? (
                          <span
                            className="text-[13px] text-muted-foreground font-mono"
                            title={t('chunkList.retrieve.combinedScoreTitle', {
                              retrieval: r.retrieval_score.toFixed(2),
                              rerank: Math.round(r.rerank_score * 100),
                              combined: r.combined_score.toFixed(2),
                            })}
                          >
                            {t('chunkList.retrieve.combinedScoreLabel', { score: r.combined_score.toFixed(2) })}
                          </span>
                        ) : (
                          <span className="text-[13px] text-muted-foreground font-mono">
                            {t('chunkList.retrieve.retrievalScoreLabel', { score: r.score.toFixed(2) })}
                          </span>
                        )}
                      </div>
                      <div className="mt-1 text-[13px] text-muted-foreground line-clamp-2">{r.snippet}</div>
                    </button>
                  ))
                ) : (
                  <div className="text-[13px] text-muted-foreground">{t('chunkList.retrieve.noResults')}</div>
                )}
              </div>
            ) : (
              <div className="mt-2 text-[13px] text-muted-foreground">{t('chunkList.retrieve.hint')}</div>
            )}
          </div>
        ) : null}
      </div>

      <section
        ref={scrollRef}
        tabIndex={0}
        data-page-scroll-container="true"
        aria-label={t('chunkList.ariaLabel')}
        className={styles.chunkScroll}
      >
        <AnimatePresence initial={false} mode="wait">
          <motion.div
            key={listSurfaceKey}
            layout={!reduceMotion}
            initial={reduceMotion ? false : { opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={reduceMotion ? undefined : { opacity: 0, y: -6 }}
            transition={surfaceTransition}
            className={styles.chunkSurface}
            style={{
              height: showVirtualized ? `${rowVirtualizer.getTotalSize()}px` : undefined,
              position: showVirtualized ? 'relative' : undefined,
            }}
          >
            {(() => {
              if (previewData !== null) {
                if (!lengthBounds.valid)
                  return (
                    <p id="chunk-list-length-error" role="alert" className="p-6 text-sm text-destructive">
                      {t('chunkList.lengthFilter.invalid')}
                    </p>
                  )
                if (unavailableSignalFilter)
                  return (
                    <div role="status" className="space-y-3 p-6 text-sm text-muted-foreground">
                      <p>{t('chunkList.states.unavailableSignals')}</p>
                      <Button type="button" variant="outline" onClick={clearSignalFilters}>
                        {t('chunkList.states.clearSignalFilters')}
                      </Button>
                    </div>
                  )
                return displayRows.length > 0 ? (
                  rowVirtualizer.getVirtualItems().map((virtualRow) => {
                    const item = displayRows[virtualRow.index]
                    if (item.kind === 'section') {
                      const groupKey = item.key
                      const isCollapsed = collapsedGroups.has(groupKey)
                      return (
                        <div
                          key={virtualRow.key}
                          data-index={virtualRow.index}
                          ref={rowVirtualizer.measureElement}
                          style={{
                            position: 'absolute',
                            top: 0,
                            left: 0,
                            width: '100%',
                            transform: `translateY(${virtualRow.start}px)`,
                          }}
                          className="pb-2"
                        >
                          <div className="flex items-center gap-2 px-2 py-1.5 rounded-xl border border-border/60 bg-muted/40">
                            <button
                              type="button"
                              className="h-6 w-6 inline-flex items-center justify-center rounded-md border border-border/60 bg-card text-muted-foreground hover:text-foreground hover:border-primary/30 hover:bg-muted transition-colors focus-ring"
                              onClick={() => toggleGroup(groupKey)}
                              aria-expanded={!isCollapsed}
                              aria-label={
                                isCollapsed
                                  ? t('chunkList.groupToggle.expandSection')
                                  : t('chunkList.groupToggle.collapseSection')
                              }
                              title={
                                isCollapsed
                                  ? t('chunkList.groupToggle.expandSection')
                                  : t('chunkList.groupToggle.collapseSection')
                              }
                            >
                              {isCollapsed ? <ChevronRight className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
                            </button>
                            <span className="min-w-0 flex-1 text-[13px] font-semibold truncate" title={item.label}>
                              {item.label}
                            </span>
                            <span className="text-[13px] text-muted-foreground font-mono">{item.count}</span>
                          </div>
                        </div>
                      )
                    }
                    const { chunk, position, indent } = item
                    const isHovered = hoveredChunkIndex === position
                    const isSelected = selectedChunkIndex === position
                    const isShort = shortIndices?.has(chunk.index) === true
                    const isDuplicate = duplicateIndices?.has(chunk.index) === true
                    const isEdited = editedIndices.has(chunk.index)
                    const gapBefore = coverageSignals.gapBeforeByIndex.get(chunk.index)
                    const overlapPrev = coverageSignals.overlapPrevByIndex.get(chunk.index)
                    const isGap = coverageSignals.gapIndices?.has(chunk.index) === true
                    const isOverlap = coverageSignals.overlapIndices?.has(chunk.index) === true
                    const dimContext = item.kind === 'parent' && item.isContext && !isHovered && !isSelected
                    const isCollapsed = item.kind === 'parent' && item.collapsed
                    return (
                      <div
                        key={virtualRow.key}
                        data-index={virtualRow.index}
                        ref={rowVirtualizer.measureElement}
                        style={{
                          position: 'absolute',
                          top: 0,
                          left: 0,
                          width: '100%',
                          transform: `translateY(${virtualRow.start}px)`,
                        }}
                        className={isHierarchyView ? 'flex gap-2 items-start' : ''}
                      >
                        {isHierarchyView ? (
                          <div className="w-6 shrink-0 pt-3 flex justify-center">
                            {(() => {
                              if (item.kind === 'parent') {
                                return (
                                  <button
                                    type="button"
                                    className="h-6 w-6 inline-flex items-center justify-center rounded-md border border-border/60 bg-card text-muted-foreground hover:text-foreground hover:border-primary/30 hover:bg-muted transition-colors focus-ring"
                                    disabled={item.forceExpanded}
                                    aria-expanded={!item.collapsed}
                                    onClick={(event) => {
                                      event.stopPropagation()
                                      toggleGroup(item.groupKey)
                                      if (!item.collapsed && selectedChunkIndex !== null) {
                                        const selected = displayRows.find(
                                          (row) => row.kind !== 'section' && row.position === selectedChunkIndex,
                                        )
                                        if (
                                          selected?.kind === 'chunk' &&
                                          selected.groupKey === item.groupKey &&
                                          selected.indent === 1
                                        ) {
                                          selectChunkIndex(position)
                                        }
                                      }
                                    }}
                                    aria-label={
                                      isCollapsed
                                        ? t('chunkList.groupToggle.expandGroup')
                                        : t('chunkList.groupToggle.collapseGroup')
                                    }
                                    title={
                                      item.forceExpanded
                                        ? t('chunkList.groupToggle.filterExpanded')
                                        : isCollapsed
                                          ? t('chunkList.groupToggle.expandChildren', {
                                              visible: item.childCountVisible,
                                              total: item.childCountTotal,
                                            })
                                          : t('chunkList.groupToggle.collapseChildren', {
                                              visible: item.childCountVisible,
                                              total: item.childCountTotal,
                                            })
                                    }
                                  >
                                    {isCollapsed ? (
                                      <ChevronRight className="h-4 w-4" />
                                    ) : (
                                      <ChevronDown className="h-4 w-4" />
                                    )}
                                  </button>
                                )
                              } else if (indent === 1) {
                                return <div className="mt-1 h-2 w-2 rounded-full bg-muted-foreground/40" />
                              } else {
                                return null
                              }
                            })()}
                          </div>
                        ) : null}
                        <div
                          className={[
                            'min-w-0 flex-1',
                            (isHierarchyView || isSectionView) && indent === 1 ? 'pl-3 border-l border-border/50' : '',
                            dimContext ? 'opacity-75' : '',
                          ]
                            .filter(Boolean)
                            .join(' ')}
                        >
                          <ChunkCard
                            chunk={chunk}
                            position={position}
                            unit={unit}
                            sourceFilename={previewData.filename}
                            isHovered={isHovered}
                            isSelected={isSelected}
                            isShort={isShort}
                            isDuplicate={isDuplicate}
                            isGap={isGap}
                            gapBefore={gapBefore}
                            isOverlap={isOverlap}
                            overlapPrev={overlapPrev}
                            isEdited={isEdited}
                            isDisabled={disabledIndices.has(chunk.index)}
                            onToggleDisabled={() => toggleChunkDisabled(chunk.index)}
                            onToggleReviewed={() => setChunkReviewed(position, !chunkIsReviewed(chunk))}
                            query={query}
                            onMouseEnter={() => setHoveredChunkIndex(position)}
                            onMouseLeave={() => setHoveredChunkIndex(null)}
                            onEdit={() => {
                              setInspection({
                                preview: previewData,
                                fileId: currentFileItem?.id,
                                position,
                                open: true,
                              })
                            }}
                            onToggleSelect={() => {
                              selectChunkIndex(selectedChunkIndex === position ? null : position)
                            }}
                          />
                        </div>
                      </div>
                    )
                  })
                ) : (
                  <div className="h-full flex flex-col items-center justify-center text-muted-foreground gap-2 py-12">
                    <Search className="w-10 h-10 opacity-20" />
                    <p className="text-[13px] text-muted-foreground">
                      {t(effectiveChunks.length === 0 ? 'chunkList.states.noChunks' : 'chunkList.states.noMatches')}
                    </p>
                  </div>
                )
              } else if (isLoading) {
                return (
                  <div className="h-full flex flex-col items-center justify-center text-muted-foreground gap-2 py-12">
                    <Loader2 className="w-8 h-8 animate-spin motion-reduce:animate-none opacity-20" />
                    <p className="text-[13px]">{t('chunkList.states.loading')}</p>
                  </div>
                )
              } else if (error) {
                return (
                  <div className="h-full flex flex-col items-center justify-center text-muted-foreground gap-3 px-5 py-12">
                    <div
                      role="alert"
                      aria-live="polite"
                      className="flex w-full max-w-[34rem] flex-col items-center rounded-2xl border border-destructive/20 bg-destructive/8 px-5 py-5 text-center shadow-[inset_0_1px_0_hsl(var(--background)/0.72)]"
                    >
                      <span className="grid size-11 place-items-center rounded-2xl bg-destructive/10 text-destructive">
                        <AlertCircle className="size-5" />
                      </span>
                      <p className="mt-3 text-sm font-semibold text-foreground">{t('chunkList.states.error')}</p>
                      <p className="mt-2 max-w-[30rem] break-words text-[13px] leading-5 text-muted-foreground">
                        {error}
                      </p>
                    </div>
                    <Button variant="outline" size="sm" className="h-8 px-3 text-[13px]" onClick={() => runPreview()}>
                      {t('chunkList.states.retry')}
                    </Button>
                  </div>
                )
              } else {
                return (
                  <div className="h-full flex flex-col items-center justify-center text-muted-foreground gap-2 py-12">
                    <Chunking appearance="color" className="size-12" />
                    <p className="text-[13px]">{t('chunkList.states.waiting')}</p>
                  </div>
                )
              }
            })()}
          </motion.div>
        </AnimatePresence>
      </section>

      {currentInspection !== null && inspectorChunk !== undefined ? (
        <ChunkInspectorDialog
          key={`${currentInspection.position}:${inspectorChunk.index}`}
          open={currentInspection.open}
          onOpenChange={(open) =>
            setInspection((current) => (current === currentInspection ? { ...current, open } : current))
          }
          chunk={inspectorChunk}
          position={currentInspection.position}
          sourceFilename={currentInspection.preview.filename}
          overrideUpdatedAt={chunkOverrides[inspectorChunk.index]?.updatedAt}
          onSave={({ content, metadata }) => {
            updateChunkOverride(inspectorChunk.index, { content, metadata })
            toast.success(t('chunkList.toasts.savedEdit'))
          }}
          onReset={() => {
            clearChunkOverride(inspectorChunk.index)
            toast.success(t('chunkList.toasts.resetEdit'))
          }}
        />
      ) : null}
    </div>
  )
}
