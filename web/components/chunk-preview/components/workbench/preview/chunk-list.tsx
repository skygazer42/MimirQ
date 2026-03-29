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
    if (unit === 'tokens') return `${tok ?? '-'} tok · ${selectedChunk.length} chars`
    return tok == null ? `${selectedChunk.length} chars` : `${selectedChunk.length} chars · ${tok} tok`
  }, [selectedChunk, unit])

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
        const label = sec || 'No section'
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
    toast.error('复制失败：浏览器不支持 Clipboard API')
  }

  return (
    <div className="flex-1 flex flex-col min-w-0 bg-background">
      <div className="h-12 border-b border-border/60 bg-card flex items-center justify-between px-4 shrink-0 gap-3">
        <span className="text-sm font-semibold text-foreground flex items-center gap-2 whitespace-nowrap shrink-0">
          <Layers className="w-4 h-4 text-muted-foreground" />
          切片列表
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
              placeholder="搜索切片内容..."
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
                aria-label="清除搜索"
                title="清除搜索"
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
                <SelectValue placeholder="View" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="flat">Flat</SelectItem>
                <SelectItem value="hierarchy">Hierarchy</SelectItem>
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
                <SelectValue placeholder="Group" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="none">No Group</SelectItem>
                <SelectItem value="section">Section</SelectItem>
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
              title={allGroupsCollapsed ? 'Expand all groups' : 'Collapse all groups'}
            >
              {allGroupsCollapsed ? 'Expand' : 'Collapse'}
            </Button>
          ) : null}
          <Select value={sortMode} onValueChange={(value) => setSortMode(value as SortMode)} disabled={isHierarchyView || isSectionView}>
            <SelectTrigger className="h-7 w-[140px] text-[11px] bg-background">
              <SelectValue placeholder="排序" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="index">原顺序</SelectItem>
              <SelectItem value="length_desc">{unit === 'tokens' ? 'Tokens：大到小' : '长度：大到小'}</SelectItem>
              <SelectItem value="length_asc">{unit === 'tokens' ? 'Tokens：小到大' : '长度：小到大'}</SelectItem>
            </SelectContent>
          </Select>
          <Select value={pageFilter} onValueChange={(value) => setPageFilter(value)}>
            <SelectTrigger className="h-7 w-[110px] text-[11px] bg-background">
              <SelectValue placeholder="页面" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={PAGE_ALL_VALUE}>全部页面</SelectItem>
              {pageOptions.hasUnknown ? <SelectItem value={PAGE_UNKNOWN_VALUE}>未知</SelectItem> : null}
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
                <SelectValue placeholder="Section" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={SECTION_ALL_VALUE}>All sections</SelectItem>
                {sectionOptions.hasNone ? <SelectItem value={SECTION_NONE_VALUE}>No section</SelectItem> : null}
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
            <span className="mr-1">{unit === 'tokens' ? 'Tokens:' : '长度:'}</span>
            <Input
              value={minLen > 0 ? String(minLen) : ''}
              onChange={(e) => {
                const raw = e.target.value.trim()
                const n = raw ? Number(raw) : 0
                if (raw) { if (Number.isFinite(n)) setMinLen(Math.max(0, Math.trunc(n))) } else { setMinLen(0) }
              }}
              placeholder="Min"
              className="h-7 w-[72px] text-[11px] font-mono bg-background"
              inputMode="numeric"
              aria-label={unit === 'tokens' ? '最小 token 过滤' : '最小长度过滤'}
            />
            <span className="px-1 opacity-70">-</span>
            <Input
              value={maxLen > 0 ? String(maxLen) : ''}
              onChange={(e) => {
                const raw = e.target.value.trim()
                const n = raw ? Number(raw) : 0
                if (raw) { if (Number.isFinite(n)) setMaxLen(Math.max(0, Math.trunc(n))) } else { setMaxLen(0) }
              }}
              placeholder="Max"
              className="h-7 w-[72px] text-[11px] font-mono bg-background"
              inputMode="numeric"
              aria-label={unit === 'tokens' ? '最大 token 过滤' : '最大长度过滤'}
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
                清除
              </Button>
            ) : null}
          </div>
          <div className="hidden xl:flex items-center gap-1">
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button type="button" variant="outline" size="sm" className="h-7 px-2 text-[11px]">
                  Batch
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem
                  disabled={matchCount === 0}
                  onSelect={() => {
                    const targets = Array.from(matchIndexSet)
                    const delta = targets.filter((i) => !disabledIndices.has(i)).length
                    setChunksDisabled(targets, true)
                    toast.success(`SKIP filtered: ${delta}`)
                  }}
                >
                  SKIP filtered ({matchCount})
                </DropdownMenuItem>

                <DropdownMenuSeparator />

                <DropdownMenuItem
                  disabled={duplicateIndices.size === 0}
                  onSelect={() => {
                    const targets = Array.from(duplicateIndices)
                    const delta = targets.filter((i) => !disabledIndices.has(i)).length
                    setChunksDisabled(targets, true)
                    toast.success(`SKIP DUP: ${delta}`)
                  }}
                >
                  SKIP DUP ({duplicateIndices.size})
                </DropdownMenuItem>
                <DropdownMenuItem
                  disabled={shortIndices.size === 0}
                  onSelect={() => {
                    const targets = Array.from(shortIndices)
                    const delta = targets.filter((i) => !disabledIndices.has(i)).length
                    setChunksDisabled(targets, true)
                    toast.success(`SKIP SHORT: ${delta}`)
                  }}
                >
                  SKIP SHORT ({shortIndices.size})
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
                        toast.success(`SKIP parents: ${delta}`)
                      }}
                    >
                      SKIP parents ({roleIndices.parents.size})
                    </DropdownMenuItem>
                    <DropdownMenuItem
                      disabled={roleIndices.children.size === 0}
                      onSelect={() => {
                        const targets = Array.from(roleIndices.children)
                        const delta = targets.filter((i) => !disabledIndices.has(i)).length
                        setChunksDisabled(targets, true)
                        toast.success(`SKIP children: ${delta}`)
                      }}
                    >
                      SKIP children ({roleIndices.children.size})
                    </DropdownMenuItem>
                  </>
                ) : null}

                <DropdownMenuSeparator />

                <DropdownMenuItem
                  disabled={disabledIndices.size === 0}
                  onSelect={() => {
                    const targets = Array.from(disabledIndices)
                    setChunksDisabled(targets, false)
                    toast.success(`RESTORE all: ${targets.length}`)
                  }}
                >
                  RESTORE all ({disabledIndices.size})
                </DropdownMenuItem>
                <DropdownMenuItem
                  disabled={disabledIndices.size === 0 || matchCount === 0}
                  onSelect={() => {
                    const targets = Array.from(matchIndexSet)
                    const delta = targets.filter((i) => disabledIndices.has(i)).length
                    setChunksDisabled(targets, false)
                    toast.success(`RESTORE filtered: ${delta}`)
                  }}
                >
                  RESTORE filtered
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
              title="Only SHORT"
            >
              <AlertCircle className="h-3.5 w-3.5 mr-1" />
              SHORT {shortIndices.size}
            </Button>
            <Button
              type="button"
              variant={onlyDuplicate ? 'secondary' : 'ghost'}
              size="sm"
              className="h-7 px-2 text-[11px]"
              onClick={() => setOnlyDuplicate((v) => !v)}
              title="Only DUP"
            >
              <Copy className="h-3.5 w-3.5 mr-1" />
              DUP {duplicateIndices.size}
            </Button>
            <Button
              type="button"
              variant={onlyGap ? 'secondary' : 'ghost'}
              size="sm"
              className="h-7 px-2 text-[11px]"
              onClick={() => setOnlyGap((v) => !v)}
              title={coverageSignals.basis === 'child' ? 'Only GAP (child coverage)' : 'Only GAP'}
            >
              GAP {coverageSignals.gapIndices.size}
            </Button>
            <Button
              type="button"
              variant={onlyOverlap ? 'secondary' : 'ghost'}
              size="sm"
              className="h-7 px-2 text-[11px]"
              onClick={() => setOnlyOverlap((v) => !v)}
              title={coverageSignals.basis === 'child' ? 'Only OVR (child coverage)' : 'Only OVR'}
            >
              OVR {coverageSignals.overlapIndices.size}
            </Button>
            <Button
              type="button"
              variant={onlyNeedsReview ? 'secondary' : 'ghost'}
              size="sm"
              className="h-7 px-2 text-[11px]"
              onClick={() => setOnlyNeedsReview((v) => !v)}
              title="Only needs_review (semantic heuristics)"
            >
              <Code2 className="h-3.5 w-3.5 mr-1" />
              REVIEW {needsReviewIndices.size}
            </Button>
            <Button
              type="button"
              variant={onlyEdited ? 'secondary' : 'ghost'}
              size="sm"
              className="h-7 px-2 text-[11px]"
              onClick={() => setOnlyEdited((v) => !v)}
              title="Only EDIT"
            >
              <Pencil className="h-3.5 w-3.5 mr-1" />
              EDIT {editedIndices.size}
            </Button>
            <Button
              type="button"
              variant={onlyDisabled ? 'secondary' : 'ghost'}
              size="sm"
              className="h-7 px-2 text-[11px]"
              onClick={() => setOnlyDisabled((v) => !v)}
              title="Only SKIP"
            >
              <EyeOff className="h-3.5 w-3.5 mr-1" />
              SKIP {disabledIndices.size}
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
              清除锁定
            </Button>
          )}
          {!showOriginalPanel && supportsPdfDocking ? (
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="h-7 px-2 text-[11px]"
              onClick={openDockedPdfPreview}
              title="显示右侧 PDF 原文，并保持后续切片选择联动定位"
            >
              恢复 PDF 联动
            </Button>
          ) : null}
          <Button
            type="button"
            variant={retrieveOpen ? 'secondary' : 'ghost'}
            size="sm"
            className="h-7 px-2 text-[11px]"
            onClick={() => setRetrieveOpen((v) => !v)}
            title="Retrieve (ranked local search)"
          >
            <Search className="h-3.5 w-3.5 mr-1" />
            Retrieve{retrieveQuery.trim() ? ` ${retrievalDisplayResults.length}` : ''}
          </Button>
          {matchesLabel ? <span className="text-[10px] text-muted-foreground font-mono">{matchesLabel}</span> : null}
          <div className="hidden lg:flex items-center gap-2 text-[10px] text-muted-foreground">
            <MousePointer2 className="w-3 h-3" />
            {showOriginalPanel
              ? '悬停定位 · 点击锁定 · ↑↓/J K 导航 · / 搜索'
              : supportsPdfDocking
                ? '点击锁定 · ↑↓/J K 导航（原文已隐藏，可恢复 PDF 联动） · / 搜索'
                : '点击锁定 · ↑↓/J K 导航（原文已隐藏） · / 搜索'}
            <CornerDownLeft className="w-3 h-3 opacity-70" />
            Esc 取消 · G 首尾
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
              placeholder="Retrieval query (ranked)…"
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
                Clear
              </Button>
            ) : null}
            <Button
              type="button"
              variant={rerankEnabled ? 'secondary' : 'ghost'}
              size="sm"
              className="h-8 px-2 text-[11px]"
              onClick={() => setRerankEnabled((v) => !v)}
              title="Rerank (local sim; best-effort)"
            >
              Rerank
            </Button>
            {rerankEnabled ? (
              <div className="flex items-center gap-2">
                <span className="text-[10px] text-muted-foreground font-mono" title="alpha (retrieval weight)">
                  {rerankAlphaPct}%
                </span>
                <input
                  type="range"
                  min={0}
                  max={100}
                  value={rerankAlphaPct}
                  onChange={(e) => setRerankAlphaPct(Number(e.target.value) || 0)}
                  aria-label="Rerank alpha (retrieval weight)"
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
                          SKIP
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
                          title={`retrieve=${r.retrieval_score.toFixed(2)} · rerank=${Math.round(r.rerank_score * 100)}% · combined=${r.combined_score.toFixed(2)}`}
                        >
                          C {r.combined_score.toFixed(2)}
                        </span>
                      ) : (
                        <span className="text-[10px] text-muted-foreground font-mono">R {r.score.toFixed(2)}</span>
                      )}
                    </div>
                    <div className="mt-1 text-[11px] text-muted-foreground line-clamp-2">{r.snippet}</div>
                  </button>
                ))
              ) : (
                <div className="text-[11px] text-muted-foreground">No results.</div>
              )}
            </div>
          ) : (
            <div className="mt-2 text-[11px] text-muted-foreground">
              Type a query to simulate retrieval ranking (local MiniSearch). Enable Rerank to simulate a reranker pass (best-effort).
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
                aria-label="编辑切片"
                title="编辑切片"
              >
                <Pencil className="h-4 w-4" />
              </Button>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="h-8 w-8"
                onClick={() => detachPromise(copyText(selectedChunk.content || '', '已复制切片内容'))}
                aria-label="复制切片内容"
                title="复制切片内容"
              >
                <Copy className="h-4 w-4" />
              </Button>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="h-8 w-8"
                onClick={() => detachPromise(copyText(JSON.stringify(selectedChunk, null, 2), '已复制切片 JSON'))}
                aria-label="复制切片 JSON"
                title="复制切片 JSON"
              >
                <Braces className="h-4 w-4" />
              </Button>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="h-8 w-8"
                onClick={() => {
                  const name = (previewData?.filename || '').trim() || 'document'
                  const pageLabel = selectedChunk.page_number == null ? '' : ` · P.${selectedChunk.page_number}`
                  const tok = typeof selectedChunk.tokens_est === 'number' ? ` · ${selectedChunk.tokens_est} tok` : ''
                  const fence = '````'
                  const raw = String(selectedChunk.content || '').trim()
                  const excerpt = raw.length > 2000 ? `${raw.slice(0, 2000)}…` : raw
                  const text = [
                    `【${name} · chunk #${(selectedChunkIndex ?? 0) + 1}${pageLabel}${tok} · ${selectedChunk.start_index}-${selectedChunk.end_index}】`,
                    `${fence}text`,
                    excerpt,
                    fence,
                  ].join('\n')
                  detachPromise(copyText(text, '已复制引用'))
                }}
                aria-label="复制引用"
                title="复制引用"
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
                    '已复制 Markdown 代码块'
                  ))
                }
                aria-label="复制为 Markdown 代码块"
                title="复制为 Markdown 代码块"
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
                取消锁定
              </Button>
            </div>
          </div>
        </div>
      ) : null}

      <div
        ref={scrollRef}
        data-page-scroll-container="true"
        role="listbox"
        aria-label="Chunk list"
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
                        <button type="button" className="h-6 w-6 inline-flex items-center justify-center rounded-md border border-border/60 bg-card text-muted-foreground hover:text-foreground hover:border-primary/30 hover:bg-muted transition-colors focus-ring" onClick={() => setCollapsedGroups((prev) => ({ ...prev, [groupKey]: !Boolean(prev[groupKey]) }))} aria-label={isCollapsed ? 'Expand section' : 'Collapse section'} title={isCollapsed ? 'Expand section' : 'Collapse section'}>
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
                                }} aria-label={isCollapsed ? 'Expand group' : 'Collapse group'} title={isCollapsed
                                    ? `Expand (${item.childCountVisible ?? 0}/${item.childCountTotal ?? 0} children)`
                                    : `Collapse (${item.childCountVisible ?? 0}/${item.childCountTotal ?? 0} children)`}>
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
                <p className="text-xs text-muted-foreground">未找到匹配切片</p>
              </div>));
    }
    else if (isLoading) {
            return (<div className="h-full flex flex-col items-center justify-center text-muted-foreground gap-2 py-12">
              <Loader2 className="w-8 h-8 animate-spin motion-reduce:animate-none opacity-20"/>
              <p className="text-xs">生成中...</p>
            </div>);
        }
        else if (error) {
                return (<div className="h-full flex flex-col items-center justify-center text-muted-foreground gap-2 py-12">
              <AlertCircle className="w-10 h-10 opacity-20"/>
              <p className="text-xs text-muted-foreground">生成预览失败</p>
              <p className="text-[10px] text-muted-foreground max-w-xs text-center">{error}</p>
              <Button variant="outline" size="sm" className="mt-2 h-8 px-3 text-[11px]" onClick={() => runPreview()}>
                重试
              </Button>
            </div>);
            }
            else {
                return (<div className="h-full flex flex-col items-center justify-center text-muted-foreground gap-2 py-12">
              <Layers className="w-12 h-12 opacity-10"/>
              <p className="text-xs">等待生成预览</p>
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
          toast.success('已保存编辑')
        }}
        onReset={() => {
          if (inspectorIndex == null) return
          clearChunkOverride(inspectorIndex)
          toast.success('已重置编辑')
        }}
      />
    </div>
  )
}
