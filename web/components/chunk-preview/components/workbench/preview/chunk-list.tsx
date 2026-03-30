/**
 * ChunkList - 切片列表
 */
'use client'

import { AnimatePresence, motion, useReducedMotion } from 'framer-motion'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useVirtualizer } from '@tanstack/react-virtual'
import {
  Layers,
  MousePointer2,
  Loader2,
  AlertCircle,
  Search,
  CornerDownLeft,
  Copy,
  Braces,
  Code2,
  Quote,
  X,
  Pencil,
  ChevronDown,
  ChevronRight,
  EyeOff,
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
import { chunkNeedsReview, isChunkOverrideDisabled, isChunkOverrideEdited } from '@/components/chunk-preview/utils/metadata'
import { SemanticQualityHeatmapMini } from './semantic-quality-heatmap-mini'
import type { ChunkPreviewItem } from '@/types'
import { computeCoverageSignals, computeRoleIndices, fnv1a32, roughEstimateTokens } from '@/components/chunk-preview/utils/review-signals'
import { getChunkSectionPath } from '@/components/chunk-preview/utils/sections'
import { buildChunkSearchIndex, searchChunkIndex, type ChunkSearchResult } from '@/components/chunk-preview/utils/retrieval-search'
import { rerankChunkSearchResults, type RerankedChunkSearchResult } from '@/components/chunk-preview/utils/reranker-sim'
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

function isEditableTarget(target: EventTarget | null) {
  const el = target as HTMLElement | null
  if (!el) return false
  const tag = (el.tagName || '').toLowerCase()
  if (tag === 'input' || tag === 'textarea' || tag === 'select') return true
  return el.isContentEditable
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
      globalThis.window.localStorage.setItem(ORIGINAL_PREVIEW_MODE_STORAGE_KEY, 'pdf')
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

  const duplicateIndices = useMemo(() => {
    const dups = new Set<number>()
    const seen = new Map<string, number>()
    for (const c of effectiveChunks) {
      const trimmed = String(c?.content ?? '').trim()
      if (!trimmed) continue
      const key = fnv1a32(trimmed)
      const prev = seen.get(key)
      if (prev == null) {
        seen.set(key, Number(c.index))
      } else {
        dups.add(prev)
        dups.add(Number(c.index))
      }
    }
    return dups
  }, [effectiveChunks])

  const shortIndices = useMemo(() => {
    const threshold = unit === 'tokens' ? 40 : 120
    const out = new Set<number>()
    for (const c of effectiveChunks) {
      const len = unit === 'tokens' ? Number(c.tokens_est || 0) : Number(c.length || 0)
      if (len > 0 && len < threshold) out.add(Number(c.index))
    }
    return out
  }, [effectiveChunks, unit])

  const roleIndices = useMemo(() => computeRoleIndices(effectiveChunks), [effectiveChunks])

  const coverageSignals = useMemo(
    () => computeCoverageSignals(effectiveChunks, { strategy: previewData?.chunk_strategy }),
    [effectiveChunks, previewData?.chunk_strategy]
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

  const selectedChunk = useMemo(() => {
    if (!effectiveChunks.length || selectedChunkIndex == null) return null
    return effectiveChunks[selectedChunkIndex] || null
  }, [effectiveChunks, selectedChunkIndex])

  const selectedChunkLenLabel = useMemo(() => {
    if (!selectedChunk) return null
    const tok = typeof selectedChunk.tokens_est === 'number' ? selectedChunk.tokens_est : null
    if (unit === 'tokens') {
      return t('chunkList.selectedChunk.lengthWithTokens', {
        tokens: tok ?? '-',
        chars: selectedChunk.length,
      })
    }
    if (tok == null) {
      return t('chunkList.selectedChunk.lengthCharsOnly', {
        chars: selectedChunk.length,
      })
    }
    return t('chunkList.selectedChunk.lengthCharsWithTokens', {
      chars: selectedChunk.length,
      tokens: tok,
    })
  }, [selectedChunk, t, unit])

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
        if (Boolean(collapsedGroups[key])) continue
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

  const navigableIndices = useMemo(() => {
    const out: number[] = []
    for (const row of displayRows) {
      if (row.kind !== 'chunk') continue
      out.push(row.index)
    }
    return out
  }, [displayRows])

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

  const copyText = async (value: string, okMessage: string) => {
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(value)
        toast.success(okMessage)
        return
      }
    } catch {
      // ignore
    }
    toast.error(t('chunkList.toasts.clipboardUnsupported'))
  }

  return (
    <div className="flex-1 flex flex-col min-w-0 bg-background">
      <div className="h-12 border-b border-border/60 bg-card flex items-center justify-between px-4 shrink-0 gap-3">
        <span className="text-sm font-semibold text-foreground flex items-center gap-2 whitespace-nowrap shrink-0">
          <Layers className="w-4 h-4 text-muted-foreground" />
          {t('chunkList.title')}
          {previewData?.total_chunks ? (
            <span className="text-[10px] text-primary bg-primary/10 border border-primary/20 px-2 py-0.5 rounded-full">
              {previewData.total_chunks}
            </span>
          ) : null}
        </span>
        <div className="flex items-center gap-2 flex-1 justify-end">
          <div className="relative w-48">
            <Search className="w-3.5 h-3.5 text-muted-foreground absolute left-2 top-1/2 -translate-y-1/2" />
            <Input
              ref={searchRef}
              value={queryInput}
              onChange={(e) => setQueryInput(e.target.value)}
              placeholder={t('chunkList.searchPlaceholder')}
              className="h-7 pl-7 pr-7 text-xs bg-background"
            />
            {queryInput ? (
              <button
                type="button"
                className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground transition-colors focus-ring rounded"
                onClick={() => {
                  setQueryInput('')
                  setQuery('')
                }}
                aria-label={t('chunkList.clearSearch')}
                title={t('chunkList.clearSearch')}
              >
                <X className="w-3.5 h-3.5" />
              </button>
            ) : null}
          </div>
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
              <SelectTrigger className="h-7 w-[120px] text-[11px] bg-background">
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
              <SelectTrigger className="h-7 w-[120px] text-[11px] bg-background">
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
              className="h-7 px-2 text-[11px]"
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
            <SelectTrigger className="h-7 w-[140px] text-[11px] bg-background">
              <SelectValue placeholder={t('chunkList.sort.placeholder')} />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="index">{t('chunkList.sort.index')}</SelectItem>
              <SelectItem value="length_desc">{sortLengthDescLabel}</SelectItem>
              <SelectItem value="length_asc">{sortLengthAscLabel}</SelectItem>
            </SelectContent>
          </Select>
          <Select value={pageFilter} onValueChange={(value) => setPageFilter(value)}>
            <SelectTrigger className="h-7 w-[110px] text-[11px] bg-background">
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
              <SelectTrigger className="h-7 w-[160px] text-[11px] bg-background">
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
          <div className="hidden xl:flex items-center gap-1 text-[10px] text-muted-foreground">
            <span className="mr-1">{lengthFilterLabel}</span>
            <Input
              value={minLen > 0 ? String(minLen) : ''}
              onChange={(e) => {
                const raw = e.target.value.trim()
                const n = raw ? Number(raw) : 0
                if (raw) { if (Number.isFinite(n)) setMinLen(Math.max(0, Math.trunc(n))) } else { setMinLen(0) }
              }}
              placeholder={t('chunkList.lengthFilter.minPlaceholder')}
              className="h-7 w-[72px] text-[11px] font-mono bg-background"
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
              className="h-7 w-[72px] text-[11px] font-mono bg-background"
              inputMode="numeric"
              aria-label={maxLengthFilterAria}
            />
            {(minLen > 0 || maxLen > 0) ? (
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="h-7 px-2 text-[11px]"
                onClick={() => {
                  setMinLen(0)
                  setMaxLen(0)
                }}
              >
                {t('chunkList.lengthFilter.clear')}
              </Button>
            ) : null}
          </div>
          <div className="hidden xl:flex items-center gap-1">
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button type="button" variant="outline" size="sm" className="h-7 px-2 text-[11px]">
                  {t('chunkList.batch.trigger')}
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
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

            <SemanticQualityHeatmapMini chunks={effectiveChunks} />

            <Button
              type="button"
              variant={onlyShort ? 'secondary' : 'ghost'}
              size="sm"
              className="h-7 px-2 text-[11px]"
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
              className="h-7 px-2 text-[11px]"
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
              className="h-7 px-2 text-[11px]"
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
              className="h-7 px-2 text-[11px]"
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
              className="h-7 px-2 text-[11px]"
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
              className="h-7 px-2 text-[11px]"
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
              className="h-7 px-2 text-[11px]"
              onClick={() => setOnlyDisabled((v) => !v)}
              title={t('chunkList.filters.onlySkippedTitle')}
            >
              <EyeOff className="h-3.5 w-3.5 mr-1" />
              {t('chunkList.filters.skippedLabel', { count: disabledIndices.size })}
            </Button>
          </div>
          {selectedChunkIndex == null ? null : (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="h-7 px-2 text-[11px]"
              onClick={() => selectChunkIndex(null)}
            >
              {t('chunkList.actions.clearSelection')}
            </Button>
          )}
          {!showOriginalPanel && supportsPdfDocking ? (
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="h-7 px-2 text-[11px]"
              onClick={openDockedPdfPreview}
              title={t('chunkList.actions.restorePdfDockTitle')}
            >
              {t('chunkList.actions.restorePdfDock')}
            </Button>
          ) : null}
          <Button
            type="button"
            variant={retrieveOpen ? 'secondary' : 'ghost'}
            size="sm"
            className="h-7 px-2 text-[11px]"
            onClick={() => setRetrieveOpen((v) => !v)}
            title={t('chunkList.retrieve.triggerTitle')}
          >
            <Search className="h-3.5 w-3.5 mr-1" />
            {t('chunkList.retrieve.trigger')}
            {retrieveQuery.trim() ? ` ${retrievalDisplayResults.length}` : ''}
          </Button>
          {matchesLabel ? <span className="text-[10px] text-muted-foreground font-mono">{matchesLabel}</span> : null}
          <div className="hidden lg:flex items-center gap-2 text-[10px] text-muted-foreground">
            <MousePointer2 className="w-3 h-3" />
            {navigationHint}
            <CornerDownLeft className="w-3 h-3 opacity-70" />
            {t('chunkList.keyboardHints.footer')}
          </div>
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
                <span className="text-[10px] text-muted-foreground font-mono" title={t('chunkList.retrieve.alphaTitle')}>
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
                      <span className="text-[10px] font-mono font-bold px-1.5 py-0.5 rounded bg-primary/10 text-primary border border-primary/20">
                        #{r.index + 1}
                      </span>
                      {disabledIndices.has(r.index) ? (
                        <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-muted/60 text-muted-foreground border border-border/60">
                          {t('chunkList.retrieve.skippedBadge')}
                        </span>
                      ) : null}
                      {r.page_number == null ? null : (
                        <span className="text-[10px] text-muted-foreground">P.{r.page_number}</span>
                      )}
                      {r.section ? (
                        <span className="min-w-0 flex-1 text-[10px] text-muted-foreground truncate">{r.section}</span>
                      ) : (
                        <span className="min-w-0 flex-1" />
                      )}
                      {'combined_score' in r ? (
                        <span
                          className="text-[10px] text-muted-foreground font-mono"
                          title={t('chunkList.retrieve.combinedScoreTitle', {
                            retrieval: r.retrieval_score.toFixed(2),
                            rerank: Math.round(r.rerank_score * 100),
                            combined: r.combined_score.toFixed(2),
                          })}
                        >
                          {t('chunkList.retrieve.combinedScoreLabel', { score: r.combined_score.toFixed(2) })}
                        </span>
                      ) : (
                        <span className="text-[10px] text-muted-foreground font-mono">
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

      {selectedChunk ? (
        <div className="border-b border-border/60 bg-card px-4 py-3">
          <div className="flex items-center justify-between gap-3">
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <span className="text-xs font-mono font-medium text-muted-foreground bg-muted px-1.5 py-0.5 rounded">
                  #{selectedChunkIndex == null ? '-' : selectedChunkIndex + 1}
                </span>
                {selectedChunk.page_number == null ? null : (
                  <span className="text-xs text-muted-foreground">P.{selectedChunk.page_number}</span>
                )}
                <span className="text-[10px] text-muted-foreground font-mono">
                  {selectedChunk.start_index}-{selectedChunk.end_index} · {selectedChunkLenLabel}
                </span>
              </div>
              <div className="mt-1 text-[11px] text-muted-foreground line-clamp-2">
                {(selectedChunk.content || '').slice(0, 260)}
                {(selectedChunk.content || '').length > 260 ? '…' : ''}
              </div>
            </div>
            <div className="flex items-center gap-1">
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="h-8 w-8"
                onClick={() => {
                  if (selectedChunkIndex == null) return
                  setInspectorIndex(selectedChunkIndex)
                  setInspectorOpen(true)
                }}
                aria-label={t('chunkList.selectedChunk.edit')}
                title={t('chunkList.selectedChunk.edit')}
              >
                <Pencil className="h-4 w-4" />
              </Button>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="h-8 w-8"
                onClick={() => detachPromise(copyText(selectedChunk.content || '', t('chunkList.selectedChunk.copyContentSuccess')))}
                aria-label={t('chunkList.selectedChunk.copyContent')}
                title={t('chunkList.selectedChunk.copyContent')}
              >
                <Copy className="h-4 w-4" />
              </Button>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="h-8 w-8"
                onClick={() => detachPromise(copyText(JSON.stringify(selectedChunk, null, 2), t('chunkList.selectedChunk.copyJsonSuccess')))}
                aria-label={t('chunkList.selectedChunk.copyJson')}
                title={t('chunkList.selectedChunk.copyJson')}
              >
                <Braces className="h-4 w-4" />
              </Button>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="h-8 w-8"
                onClick={() => {
                  const name = (previewData?.filename || '').trim() || t('chunkCard.documentFallback')
                  const pageLabel = selectedChunk.page_number == null
                    ? ''
                    : t('chunkList.selectedChunk.pageLabel', { page: selectedChunk.page_number })
                  const tok = typeof selectedChunk.tokens_est === 'number'
                    ? t('chunkList.selectedChunk.tokenLabel', { count: selectedChunk.tokens_est })
                    : ''
                  const fence = '````'
                  const raw = String(selectedChunk.content || '').trim()
                  const excerpt = raw.length > 2000 ? `${raw.slice(0, 2000)}…` : raw
                  const text = [
                    t('chunkList.selectedChunk.citationLine', {
                      name,
                      index: (selectedChunkIndex ?? 0) + 1,
                      pageLabel,
                      tokenLabel: tok,
                      start: selectedChunk.start_index,
                      end: selectedChunk.end_index,
                    }),
                    `${fence}text`,
                    excerpt,
                    fence,
                  ].join('\n')
                  detachPromise(copyText(text, t('chunkList.selectedChunk.copyCitationSuccess')))
                }}
                aria-label={t('chunkList.selectedChunk.copyCitation')}
                title={t('chunkList.selectedChunk.copyCitation')}
              >
                <Quote className="h-4 w-4" />
              </Button>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="h-8 w-8"
                onClick={() =>
                  detachPromise(copyText(
                    '```text\n' + (selectedChunk.content || '') + '\n```\n',
                    t('chunkList.selectedChunk.copyMarkdownSuccess')
                  ))
                }
                aria-label={t('chunkList.selectedChunk.copyMarkdown')}
                title={t('chunkList.selectedChunk.copyMarkdown')}
              >
                <Code2 className="h-4 w-4" />
              </Button>
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="h-8 px-3 text-[11px]"
                onClick={() => selectChunkIndex(null)}
              >
                {t('chunkList.selectedChunk.unlock')}
              </Button>
            </div>
          </div>
        </div>
      ) : null}

      <div
        ref={scrollRef}
        data-page-scroll-container="true"
        role="listbox"
        aria-label={t('chunkList.ariaLabel')}
        tabIndex={0}
        onKeyDown={(e) => {
          if (!previewData?.chunks?.length) return
          if (isEditableTarget(e.target)) return
          if (navigableIndices.length === 0) return

          const currentPos =
            selectedChunkIndex == null
              ? -1
              : navigableIndices.indexOf(selectedChunkIndex)

          const clamp = (n: number) => Math.max(0, Math.min(navigableIndices.length - 1, n))

          if (e.key === '/') {
            e.preventDefault()
            searchRef.current?.focus()
            return
          }
          if (e.key === 'Home' || (e.key.toLowerCase() === 'g' && !e.shiftKey)) {
            e.preventDefault()
            selectChunkIndex(navigableIndices[0] ?? null)
            return
          }
          if (e.key === 'End' || (e.key.toLowerCase() === 'g' && e.shiftKey)) {
            e.preventDefault()
            selectChunkIndex(navigableIndices[navigableIndices.length - 1] ?? null)
            return
          }

          if (e.key === 'ArrowDown' || e.key.toLowerCase() === 'j') {
            e.preventDefault()
            const nextPos = clamp(currentPos < 0 ? 0 : currentPos + 1)
            selectChunkIndex(navigableIndices[nextPos] ?? null)
            return
          }
          if (e.key === 'ArrowUp' || e.key.toLowerCase() === 'k') {
            e.preventDefault()
            const nextPos = clamp(currentPos < 0 ? 0 : currentPos - 1)
            selectChunkIndex(navigableIndices[nextPos] ?? null)
            return
          }
          if (e.key === 'Escape') {
            e.preventDefault()
            selectChunkIndex(null)
            return
          }
        }}
        className="flex-1 overflow-y-auto overscroll-contain no-scrollbar p-4 focus-ring"
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
                          onClick={() => setCollapsedGroups((prev) => ({ ...prev, [groupKey]: !Boolean(prev[groupKey]) }))}
                          aria-label={isCollapsed ? t('chunkList.groupToggle.expandSection') : t('chunkList.groupToggle.collapseSection')}
                          title={isCollapsed ? t('chunkList.groupToggle.expandSection') : t('chunkList.groupToggle.collapseSection')}
                        >
                          {isCollapsed ? <ChevronRight className="h-4 w-4"/> : <ChevronDown className="h-4 w-4"/>}
                        </button>
                        <span className="min-w-0 flex-1 text-[11px] font-semibold truncate" title={item.label}>
                          {item.label}
                        </span>
                        <span className="text-[10px] text-muted-foreground font-mono">{item.count}</span>
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
                                    const nextCollapsed = !Boolean(collapsedGroups[groupKey]);
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
                      <ChunkCard chunk={chunk} index={index} unit={unit} sourceFilename={previewData?.filename} isHovered={isHovered} isSelected={isSelected} isShort={isShort} isDuplicate={isDuplicate} isGap={isGap} gapBefore={gapBefore} isOverlap={isOverlap} overlapPrev={overlapPrev} isEdited={isEdited} isDisabled={disabledIndices.has(index)} onToggleDisabled={() => toggleChunkDisabled(index)} query={query} onMouseEnter={() => setHoveredChunkIndex(index)} onMouseLeave={() => setHoveredChunkIndex(null)} onEdit={() => {
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
                return (<div className="h-full flex flex-col items-center justify-center text-muted-foreground gap-2 py-12">
              <AlertCircle className="w-10 h-10 opacity-20"/>
              <p className="text-xs text-muted-foreground">{t('chunkList.states.error')}</p>
              <p className="text-[10px] text-muted-foreground max-w-xs text-center">{error}</p>
              <Button variant="outline" size="sm" className="mt-2 h-8 px-3 text-[11px]" onClick={() => runPreview()}>
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
      </div>

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
