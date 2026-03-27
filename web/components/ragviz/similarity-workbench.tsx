'use client'

import type { MouseEvent as ReactMouseEvent, ReactNode } from 'react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ragvizApi } from '@/lib/api'
import type {
  RagvizSimilarityCollection,
  RagvizSimilarityCalculateResponse,
  RagvizSimilarityCollectionsResponse,
  RagvizSimilarityMatrixResult,
  RagvizSimilarityRequest,
} from '@/types'
import { Button } from '@/components/ui/button'
import { PageLoading } from '@/components/ui/page-loading'
import { cn, detachPromise } from '@/lib/utils'
import {
  BarChart3,
  Database,
  Download,
  Eye,
  Filter,
  Grid3X3,
  Lock,
  RefreshCw,
} from 'lucide-react'
import { toast } from 'sonner'

type LeftTopPanel = 'dataSource' | 'operations'
type RightTopPanel = 'statistics' | null
type RightBottomPanel = 'filters' | null
type JsonRecord = Record<string, unknown>

type PlotlyTrace = {
  type: 'heatmap'
  z: Array<Array<number | null>>
  x: string[]
  y: string[]
  colorscale: string
  zmin: number
  zmax: number
  hovertemplate: string
}

type PlotlyLayout = {
  margin: { l: number; r: number; t: number; b: number }
  xaxis: { automargin: boolean; tickangle: number }
  yaxis: { automargin: boolean; autorange: 'reversed' }
  paper_bgcolor: string
  plot_bgcolor: string
}

type PlotlyConfig = {
  responsive: boolean
  displaylogo: boolean
}

type PlotlyLike = {
  react: (element: HTMLDivElement, data: PlotlyTrace[], layout: PlotlyLayout, config: PlotlyConfig) => void
  purge: (element: HTMLDivElement) => void
}

function isRecord(value: unknown): value is JsonRecord {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

function isPlotlyLike(value: unknown): value is PlotlyLike {
  if (!value || (typeof value !== 'object' && typeof value !== 'function')) return false
  const maybe = value as { react?: unknown; purge?: unknown }
  return typeof maybe.react === 'function' && typeof maybe.purge === 'function'
}

function isSimilarityMatrixResult(value: unknown): value is RagvizSimilarityMatrixResult {
  return (
    isRecord(value) &&
    Array.isArray(value.matrix) &&
    Array.isArray(value.x_data) &&
    Array.isArray(value.y_data) &&
    Array.isArray(value.x_available_fields) &&
    Array.isArray(value.y_available_fields) &&
    isRecord(value.metadata)
  )
}

function isVisualConfig(value: unknown): value is VisualConfig {
  return (
    isRecord(value) &&
    isRecord(value.displayFields) &&
    typeof value.displayFields.xField === 'string' &&
    typeof value.displayFields.yField === 'string' &&
    isRecord(value.similarityRange) &&
    typeof value.similarityRange.min === 'number' &&
    typeof value.similarityRange.max === 'number' &&
    isRecord(value.filters) &&
    isRecord(value.filters.topK) &&
    typeof value.filters.topK.value === 'number' &&
    (value.filters.topK.axis === 'x' || value.filters.topK.axis === 'y') &&
    isRecord(value.sorting) &&
    typeof value.sorting.order === 'string'
  )
}

function getErrorMessage(error: unknown, fallback = '操作失败'): string {
  if (error instanceof Error && error.message.trim()) return error.message.trim()
  const text = String(error || '').trim()
  return text || fallback
}

export function RagvizSimilarityWorkbench() {
  const [collections, setCollections] = useState<RagvizSimilarityCollection[]>([])
  const [collectionsLoading, setCollectionsLoading] = useState(false)
  const [collectionsError, setCollectionsError] = useState<string>('')

  const [xSelections, setXSelections] = useState<string[]>([''])
  const [ySelections, setYSelections] = useState<string[]>([''])
  const [xMaxItems, setXMaxItems] = useState<number>(30)
  const [yMaxItems, setYMaxItems] = useState<number>(30)
  const [isCalculating, setIsCalculating] = useState(false)
  const [calcProgress, setCalcProgress] = useState<{ done: number; total: number } | null>(null)
  const [colorScheme, setColorScheme] = useState<ColorSchemeKey>('viridis')
  const [tempSimilarityRange, setTempSimilarityRange] = useState<{ min: number; max: number }>({ min: 0, max: 1 })
  const [tempTopK, setTempTopK] = useState<{ value: number; axis: 'x' | 'y' }>({ value: 0, axis: 'x' })

  const [leftTopPanel, setLeftTopPanel] = useState<LeftTopPanel>('dataSource')
  const [rightTopPanel, setRightTopPanel] = useState<RightTopPanel>('statistics')
  const [rightBottomPanel, setRightBottomPanel] = useState<RightBottomPanel>('filters')

  const [leftWidth, setLeftWidth] = useState<number>(320)
  const [rightWidth, setRightWidth] = useState<number>(320)
  const [leftTopHeight, setLeftTopHeight] = useState<number | null>(null)
  const [rightTopHeight, setRightTopHeight] = useState<number | null>(null)

  const leftSidebarRef = useRef<HTMLDivElement>(null)
  const rightSidebarRef = useRef<HTMLDivElement>(null)
  const importInputRef = useRef<HTMLInputElement>(null)

  const [results, setResults] = useState<SimilarityMatrixEntry[]>([])
  const [matrixButtons, setMatrixButtons] = useState<MatrixButtonState[]>([])
  const [primaryIndex, setPrimaryIndex] = useState<number | null>(null)
  const [subtractIndex, setSubtractIndex] = useState<number | null>(null)
  const [activeFilterIndices, setActiveFilterIndices] = useState<number[]>([])
  const [exclusiveIndex, setExclusiveIndex] = useState<number | null>(null)
  const [exportIndex, setExportIndex] = useState<number>(0)

  const loadCollections = useCallback(async () => {
    setCollectionsError('')
    setCollectionsLoading(true)
    try {
      const res: RagvizSimilarityCollectionsResponse = await ragvizApi.listSimilarityCollections()
      setCollections(res.collections || [])
    } catch (error: unknown) {
      setCollectionsError(getErrorMessage(error, '加载 collections 失败'))
    } finally {
      setCollectionsLoading(false)
    }
  }, [])

  useEffect(() => {
    detachPromise(loadCollections())
  }, [loadCollections])

  const availableCollectionOptions = useMemo(() => {
    return collections.map((c) => ({ value: c.id, label: c.label, kind: c.kind, count: c.count }))
  }, [collections])

  const resolveCollectionLabel = (id: string) => {
    const found = collections.find((c) => c.id === id)
    return found?.label || id
  }

  const calculateSimilarity = async () => {
    const xs = xSelections.map((x) => x.trim()).filter(Boolean)
    const ys = ySelections.map((y) => y.trim()).filter(Boolean)

    if (xs.length === 0) {
      toast.error('请至少选择一个横坐标 Collection')
      return
    }
    if (ys.length === 0) {
      toast.error('请至少选择一个纵坐标 Collection')
      return
    }

    const total = xs.length * ys.length
    setIsCalculating(true)
    setCalcProgress({ done: 0, total })
    setResults([])
    setMatrixButtons([])
    setPrimaryIndex(null)
    setSubtractIndex(null)
    setActiveFilterIndices([])
    setExclusiveIndex(null)
    setExportIndex(0)

    const nextResults: SimilarityMatrixEntry[] = []
    let done = 0

    for (const x of xs) {
      for (const y of ys) {
        const payload: RagvizSimilarityRequest = {
          x_collection: x,
          y_collection: y,
          x_max_items: xMaxItems,
          y_max_items: yMaxItems,
        }

        try {
          const res: RagvizSimilarityCalculateResponse = await ragvizApi.calculateSimilarityMatrix(payload)
          if (!res.success || !res.result) {
            throw new Error(res.error || '计算失败')
          }

          const visualConfig = createDefaultVisualConfig(res.result.x_available_fields, res.result.y_available_fields)
          nextResults.push({
            xCollectionId: x,
            yCollectionId: y,
            xCollectionLabel: resolveCollectionLabel(x),
            yCollectionLabel: resolveCollectionLabel(y),
            result: res.result,
            visualConfig,
          })
        } catch (error: unknown) {
          const msg = getErrorMessage(error, '计算失败')
          toast.error(`${resolveCollectionLabel(x)} vs ${resolveCollectionLabel(y)}：${msg}`)
        } finally {
          done += 1
          setCalcProgress({ done, total })
        }
      }
    }

    setResults(nextResults)
    initializeMatrixState(nextResults)
    setIsCalculating(false)
    setCalcProgress(null)
    if (nextResults.length > 0) {
      toast.success(`成功计算 ${nextResults.length} 个相似度矩阵`)
    }
  }

  const initializeMatrixState = (entries: SimilarityMatrixEntry[]) => {
    if (entries.length === 0) {
      setMatrixButtons([])
      setPrimaryIndex(null)
      setSubtractIndex(null)
      setActiveFilterIndices([])
      setExclusiveIndex(null)
      setExportIndex(0)
      return
    }

    const init: MatrixButtonState[] = entries.map(() => ({ applyData: false, applyFilter: false, exclusive: false }))
    init[0] = { applyData: true, applyFilter: true, exclusive: true }
    setMatrixButtons(init)
    setPrimaryIndex(0)
    setSubtractIndex(null)
    setActiveFilterIndices([0])
    setExclusiveIndex(0)
    setExportIndex(0)
  }

  const downloadJson = (filename: string, data: unknown) => {
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    a.click()
    URL.revokeObjectURL(url)
  }

  const exportOne = () => {
    if (results.length === 0) return
    const idx = Math.max(0, Math.min(exportIndex, results.length - 1))
    const entry = results[idx]
    const payload = { version: 1, entries: [entry] }
    const safe = `matrix_${idx + 1}`.replaceAll(/[^\w.-]+/g, '_')
    downloadJson(`${safe}.json`, payload)
  }

  const exportAll = () => {
    if (results.length === 0) return
    const payload = { version: 1, entries: results }
    downloadJson(`matrices_all.json`, payload)
  }

  const parseImportedPayload = (raw: unknown): SimilarityMatrixEntry[] => {
    if (!raw) return []
    const entries = Array.isArray(raw) ? raw : isRecord(raw) && Array.isArray(raw.entries) ? raw.entries : [raw]
    const out: SimilarityMatrixEntry[] = []
    for (const entry of entries) {
      if (!isRecord(entry)) continue
      const result = entry.result
      if (!isSimilarityMatrixResult(result)) continue
      const metadata = isRecord(result.metadata) ? result.metadata : null
      const xCollectionId = String(entry.xCollectionId || entry.xCollection || metadata?.x_collection || '')
      const yCollectionId = String(entry.yCollectionId || entry.yCollection || metadata?.y_collection || '')
      const xCollectionLabel = String(entry.xCollectionLabel || xCollectionId || 'X')
      const yCollectionLabel = String(entry.yCollectionLabel || yCollectionId || 'Y')
      const visualConfig: VisualConfig =
        isVisualConfig(entry.visualConfig)
          ? entry.visualConfig
          : createDefaultVisualConfig(result.x_available_fields || [], result.y_available_fields || [])

      out.push({
        xCollectionId,
        yCollectionId,
        xCollectionLabel,
        yCollectionLabel,
        result,
        visualConfig,
      })
    }
    return out
  }

  const importFiles = async (files: FileList | null) => {
    if (!files || files.length === 0) return
    const imported: SimilarityMatrixEntry[] = []
    for (const file of Array.from(files)) {
      try {
        const text = await file.text()
        const json: unknown = JSON.parse(text)
        imported.push(...parseImportedPayload(json))
      } catch (error: unknown) {
        toast.error(`导入失败：${file.name}（${getErrorMessage(error, 'JSON 解析错误')}）`)
      }
    }

    if (imported.length === 0) {
      toast.warning('未找到可导入的矩阵数据')
      return
    }

    setResults((prev) => {
      if (prev.length === 0) return imported
      return [...prev, ...imported]
    })
    setMatrixButtons((prev) => {
      const appended = imported.map(() => ({ applyData: false, applyFilter: false, exclusive: false }))
      return prev.length === 0 ? appended : [...prev, ...appended]
    })
    if (results.length === 0) {
      initializeMatrixState(imported)
    }

    toast.success(`已导入 ${imported.length} 个矩阵`)
  }

  const primaryEntry = primaryIndex === null ? null : results[primaryIndex]
  const subtractEntry = subtractIndex === null ? null : results[subtractIndex]
  const isDifferenceMode = Boolean(primaryEntry && subtractEntry)
  const rangeBounds = useMemo(() => (isDifferenceMode ? { min: -1, max: 1 } : { min: 0, max: 1 }), [isDifferenceMode])

  useEffect(() => {
    // Match Kumi: entering difference mode resets sliders to [-1, 1].
    if (isDifferenceMode) {
      setTempSimilarityRange({ min: -1, max: 1 })
      setTempTopK({ value: 0, axis: 'x' })
    } else {
      setTempSimilarityRange({ min: 0, max: 1 })
      setTempTopK({ value: 0, axis: 'x' })
    }
  }, [isDifferenceMode])

  const displayMatrix = useMemo(() => {
    if (!primaryEntry) return null
    const a = primaryEntry.result.matrix
    if (!subtractEntry) return a
    const b = subtractEntry.result.matrix
    if (a.length !== b.length || (a[0]?.length || 0) !== (b[0]?.length || 0)) return a
    return a.map((row, i) => row.map((val, j) => val - b[i][j]))
  }, [primaryEntry, subtractEntry])

  const displayLabels = useMemo(() => {
    if (!primaryEntry) return null
    const xField = primaryEntry.visualConfig.displayFields.xField
    const yField = primaryEntry.visualConfig.displayFields.yField
    const xLabels = generateUniqueLabels(primaryEntry.result.x_data, xField)
    const yLabels = generateUniqueLabels(primaryEntry.result.y_data, yField)
    return { xLabels, yLabels }
  }, [primaryEntry])

  const activeVisualConfig: VisualConfig | null = useMemo(() => {
    if (exclusiveIndex === null) return null
    return results[exclusiveIndex]?.visualConfig || null
  }, [exclusiveIndex, results])

  const uiSimilarityRange = exclusiveIndex !== null && activeVisualConfig ? activeVisualConfig.similarityRange : tempSimilarityRange
  const uiTopK = exclusiveIndex !== null && activeVisualConfig ? activeVisualConfig.filters.topK : tempTopK

  const effectiveMask = useMemo(() => {
    if (!displayMatrix || !primaryEntry) return null

    // Exclusive mode: only use the editing matrix config.
    if (exclusiveIndex !== null && activeVisualConfig) {
      return computeFinalMask(displayMatrix, activeVisualConfig.similarityRange, activeVisualConfig.filters.topK)
    }

    // Apply-filter mode: OR masks of selected matrices (based on their own configs),
    // then AND with temporary filter (applied on the displayed matrix).
    let mask: boolean[][] | null = null
    const primaryShape = matrixShape(primaryEntry)

    const filterMasks = activeFilterIndices
      .map((idx) => {
        const entry = results[idx]
        if (!entry) return null
        const shape = matrixShape(entry)
        if (shape.rows !== primaryShape.rows || shape.cols !== primaryShape.cols) return null
        return computeFinalMask(entry.result.matrix, entry.visualConfig.similarityRange, entry.visualConfig.filters.topK)
      })
      .filter(Boolean) as boolean[][][]

    if (filterMasks.length > 0) {
      mask = combineWithOR(filterMasks)
    }

    const tempMask = computeFinalMask(displayMatrix, tempSimilarityRange, tempTopK)
    return mask ? combineWithAND(mask, tempMask) : tempMask
  }, [
    activeFilterIndices,
    activeVisualConfig,
    displayMatrix,
    exclusiveIndex,
    primaryEntry,
    results,
    tempSimilarityRange,
    tempTopK,
  ])

  const maskedMatrix = useMemo(() => {
    if (!displayMatrix) return null
    if (!effectiveMask) return displayMatrix as Array<Array<number | null>>
    return applyMask(displayMatrix, effectiveMask)
  }, [displayMatrix, effectiveMask])

  const topKAxisForStats: 'x' | 'y' | 'none' = useMemo(() => {
    const topK = uiTopK
    if (!topK || !topK.value) return 'none'
    return topK.axis
  }, [uiTopK])

  const normalStats = useMemo(() => {
    if (!effectiveMask) return null
    return calculateNormalModeStatistics(effectiveMask, topKAxisForStats)
  }, [effectiveMask, topKAxisForStats])

  const differenceStats = useMemo(() => {
    if (!primaryEntry || !subtractEntry) return null

    const groundTruthMask = computeFinalMask(
      primaryEntry.result.matrix,
      primaryEntry.visualConfig.similarityRange,
      primaryEntry.visualConfig.filters.topK
    )

    const subtractMask = computeFinalMask(
      subtractEntry.result.matrix,
      subtractEntry.visualConfig.similarityRange,
      subtractEntry.visualConfig.filters.topK
    )

    if (!displayMatrix) return null
    const tempMask = computeFinalMask(displayMatrix, tempSimilarityRange, tempTopK)
    const isTempDefault = tempSimilarityRange.min === -1 && tempSimilarityRange.max === 1 && tempTopK.value === 0
    const currentMask = isTempDefault ? subtractMask : tempMask

    return calculateDifferenceModeStatistics(groundTruthMask, currentMask)
  }, [displayMatrix, primaryEntry, subtractEntry, tempSimilarityRange, tempTopK])

  const updateDisplayFields = (xField: string, yField: string) => {
    if (primaryIndex === null) return
    const target = exclusiveIndex === null ? primaryIndex : exclusiveIndex
    setResults((prev) =>
      prev.map((entry, idx) => {
        if (idx !== target) return entry
        return {
          ...entry,
          visualConfig: {
            ...entry.visualConfig,
            displayFields: { xField, yField },
          },
        }
      })
    )
  }

  const updateSimilarityRange = (range: { min: number; max: number }) => {
    const clamp = (v: number) => Math.max(rangeBounds.min, Math.min(rangeBounds.max, v))
    const min = clamp(range.min)
    const max = clamp(range.max)
    const next = { min: Math.min(min, max), max: Math.max(min, max) }

    if (exclusiveIndex !== null) {
      setResults((prev) =>
        prev.map((entry, idx) => {
          if (idx !== exclusiveIndex) return entry
          return { ...entry, visualConfig: { ...entry.visualConfig, similarityRange: next } }
        })
      )
      return
    }
    setTempSimilarityRange(next)
  }

  const updateTopK = (nextTopK: { value: number; axis: 'x' | 'y' }) => {
    const shape = primaryEntry ? matrixShape(primaryEntry) : { rows: 0, cols: 0 }
    const max = nextTopK.axis === 'x' ? shape.cols : shape.rows
    const clamped = { ...nextTopK, value: Math.max(0, Math.min(Number(nextTopK.value) || 0, max)) }
    if (exclusiveIndex !== null) {
      setResults((prev) =>
        prev.map((entry, idx) => {
          if (idx !== exclusiveIndex) return entry
          return { ...entry, visualConfig: { ...entry.visualConfig, filters: { topK: clamped } } }
        })
      )
      return
    }
    setTempTopK(clamped)
  }

  const matrixShape = (entry: SimilarityMatrixEntry | null) => {
    const m = entry?.result?.matrix || []
    const rows = m.length
    const cols = rows > 0 ? (m[0]?.length || 0) : 0
    return { rows, cols }
  }

  const sameShape = (a: SimilarityMatrixEntry | null, b: SimilarityMatrixEntry | null) => {
    const sa = matrixShape(a)
    const sb = matrixShape(b)
    return sa.rows === sb.rows && sa.cols === sb.cols
  }

  const enterExclusiveMode = (index: number) => {
    setExclusiveIndex(index)
    setPrimaryIndex(index)
    setSubtractIndex(null)
    setActiveFilterIndices([index])

    setMatrixButtons((prev) =>
      prev.map((s, i) => ({
        applyData: i === index,
        applyFilter: i === index,
        exclusive: i === index,
      }))
    )
  }

  const exitExclusiveMode = () => {
    setExclusiveIndex(null)
    setMatrixButtons((prev) => prev.map((s) => ({ ...s, exclusive: false })))
  }

  const toggleApplyData = (index: number) => {
    if (index < 0 || index >= results.length) return

    // If enabling data on a different matrix while exclusive is active, exit exclusive first.
    if (exclusiveIndex !== null && exclusiveIndex !== index) {
      exitExclusiveMode()
    }

    setMatrixButtons((prev) => {
      const next = [...prev]
      const current = next[index]
      if (!current) return prev

      if (current.applyData) {
        // Turning off.
        if (index === subtractIndex) {
          next[index] = { ...current, applyData: false }
          setSubtractIndex(null)
        } else if (index === primaryIndex) {
          next[index] = { ...current, applyData: false }
          setPrimaryIndex(null)
          setSubtractIndex(null)
        } else {
          next[index] = { ...current, applyData: false }
        }
        return next
      }

      // Turning on: ensure shape consistency.
      if (primaryIndex !== null) {
        const primary = results[primaryIndex]
        const candidate = results[index]
        if (!sameShape(primary, candidate)) {
          toast.warning('矩阵大小不一致，无法用于差值/展示')
          return prev
        }
      }

      if (primaryIndex === null) {
        // No primary -> set as primary.
        setPrimaryIndex(index)
        setSubtractIndex(null)
        return next.map((s, i) => ({ ...s, applyData: i === index }))
      }

      if (primaryIndex === index) {
        return prev
      }

      if (subtractIndex === null) {
        setSubtractIndex(index)
        return next.map((s, i) => ({ ...s, applyData: i === primaryIndex || i === index }))
      }

      // Replace subtract.
      setSubtractIndex(index)
      return next.map((s, i) => ({ ...s, applyData: i === primaryIndex || i === index }))
    })
  }

  const toggleApplyFilter = (index: number) => {
    if (index < 0 || index >= results.length) return

    if (exclusiveIndex !== null && exclusiveIndex !== index) {
      exitExclusiveMode()
    }

    if (primaryIndex === null) {
      toast.error('请先选择一个“应用数据”的矩阵作为主图')
      return
    }

    const primary = results[primaryIndex]
    const candidate = results[index]
    if (!sameShape(primary, candidate)) {
      toast.warning('矩阵大小不一致，无法合并筛选器')
      return
    }

    setMatrixButtons((prev) => {
      const next = [...prev]
      const cur = next[index]
      if (!cur) return prev
      next[index] = { ...cur, applyFilter: !cur.applyFilter }
      return next
    })

    setActiveFilterIndices((prev) => {
      return prev.includes(index) ? prev.filter((i) => i !== index) : [...prev, index]
    })
  }

  // Persist UI layout.
  useEffect(() => {
    try {
      const payload = { leftWidth, rightWidth, leftTopHeight, rightTopHeight }
      localStorage.setItem('ragviz_similarity_layout_v1', JSON.stringify(payload))
    } catch {
      // ignore
    }
  }, [leftWidth, rightWidth, leftTopHeight, rightTopHeight])

  useEffect(() => {
    try {
      const raw = localStorage.getItem('ragviz_similarity_layout_v1')
      if (!raw) return
      const parsed = JSON.parse(raw)
      if (typeof parsed.leftWidth === 'number') setLeftWidth(parsed.leftWidth)
      if (typeof parsed.rightWidth === 'number') setRightWidth(parsed.rightWidth)
      if (typeof parsed.leftTopHeight === 'number') setLeftTopHeight(parsed.leftTopHeight)
      if (typeof parsed.rightTopHeight === 'number') setRightTopHeight(parsed.rightTopHeight)
    } catch {
      // ignore
    }
  }, [])

  const leftTopStyle = useMemo(() => {
    if (!leftTopHeight) return undefined
    return { height: leftTopHeight }
  }, [leftTopHeight])

  const rightTopStyle = useMemo(() => {
    if (!rightTopHeight) return undefined
    return { height: rightTopHeight }
  }, [rightTopHeight])

  const startResizeSidebar = (side: 'left' | 'right', event: ReactMouseEvent) => {
    event.preventDefault()
    const startX = event.clientX
    const startWidth = side === 'left' ? leftWidth : rightWidth

    const onMove = (e: MouseEvent) => {
      const delta = e.clientX - startX
      const next = side === 'left' ? startWidth + delta : startWidth - delta
      const clamped = Math.max(240, Math.min(560, next))
      if (side === 'left') setLeftWidth(clamped)
      else setRightWidth(clamped)
    }

    const onUp = () => {
      globalThis.window.removeEventListener('mousemove', onMove)
      globalThis.window.removeEventListener('mouseup', onUp)
    }

    globalThis.window.addEventListener('mousemove', onMove)
    globalThis.window.addEventListener('mouseup', onUp)
  }

  const startResizeSplit = (side: 'left' | 'right', event: ReactMouseEvent) => {
    event.preventDefault()
    const container = side === 'left' ? leftSidebarRef.current : rightSidebarRef.current
    if (!container) return
    const rect = container.getBoundingClientRect()
    const startY = event.clientY
    const initial = side === 'left' ? leftTopHeight ?? rect.height * 0.5 : rightTopHeight ?? rect.height * 0.5

    const onMove = (e: MouseEvent) => {
      const delta = e.clientY - startY
      const next = initial + delta
      const min = 140
      const max = rect.height - 140
      const clamped = Math.max(min, Math.min(max, next))
      if (side === 'left') setLeftTopHeight(clamped)
      else setRightTopHeight(clamped)
    }

    const onUp = () => {
      globalThis.window.removeEventListener('mousemove', onMove)
      globalThis.window.removeEventListener('mouseup', onUp)
    }

    globalThis.window.addEventListener('mousemove', onMove)
    globalThis.window.addEventListener('mouseup', onUp)
  }

  return (
    <div className="h-full w-full flex overflow-hidden">
      {/* Left section */}
      <div className="flex h-full">
        <div className="w-12 border-r border-border bg-background flex flex-col items-center py-2">
          <div className="flex flex-col gap-1">
            <IconBtn
              active={leftTopPanel === 'dataSource'}
              title="数据源配置"
              onClick={() => setLeftTopPanel('dataSource')}
              icon={<Database className="h-4 w-4" />}
            />
            <IconBtn
              active={leftTopPanel === 'operations'}
              title="结果操作"
              onClick={() => setLeftTopPanel('operations')}
              icon={<Download className="h-4 w-4" />}
            />
          </div>
          <div className="mt-auto pt-2">
            <IconBtn active title="图表选择与控制" onClick={() => {}} icon={<Grid3X3 className="h-4 w-4" />} />
          </div>
        </div>

        <div
          ref={leftSidebarRef}
          className="relative h-full border-r border-border bg-card flex flex-col"
          style={{ width: leftWidth }}
        >
          <button
            type="button"
            aria-label="Resize left sidebar"
            className="absolute top-0 right-0 h-full w-1 cursor-col-resize hover:bg-primary/20"
            onMouseDown={(e) => startResizeSidebar('left', e)}
          />

          <div className="flex flex-col overflow-hidden">
            <div className="p-3 border-b border-border" style={leftTopStyle}>
	              {leftTopPanel === 'dataSource' ? (
	                <Panel title="数据源配置" rightSlot={
	                  <Button variant="ghost" size="icon" onClick={loadCollections} disabled={collectionsLoading} title="刷新" aria-label="刷新">
	                    <RefreshCw className={cn('h-4 w-4', collectionsLoading && 'animate-spin motion-reduce:animate-none')} />
	                  </Button>
	                }>
                  <p className="text-xs text-muted-foreground">选择横/纵坐标 collections，计算相似度矩阵（Kumi 风格）。</p>
                  {collectionsError ? (
                    <p className="text-xs text-destructive mt-2">{collectionsError}</p>
                  ) : null}

                  <div className="mt-3 space-y-4">
                    <CollectionSelectorBlock
                      label="横坐标 Collection"
                      selections={xSelections}
                      onChange={setXSelections}
                      options={availableCollectionOptions}
                    />
                    <div className="grid grid-cols-2 gap-3">
                      <NumberField
                        label="横坐标最大项目数"
                        value={xMaxItems}
                        onChange={setXMaxItems}
                        min={10}
                        max={500}
                      />
                      <NumberField
                        label="纵坐标最大项目数"
                        value={yMaxItems}
                        onChange={setYMaxItems}
                        min={10}
                        max={500}
                      />
                    </div>
                    <CollectionSelectorBlock
                      label="纵坐标 Collection"
                      selections={ySelections}
                      onChange={setYSelections}
                      options={availableCollectionOptions}
                    />

                    <Button className="w-full" onClick={calculateSimilarity} disabled={isCalculating}>
                      {isCalculating && calcProgress ? `计算中... (${calcProgress.done}/${calcProgress.total})` : '计算相似度'}
                    </Button>
                  </div>
                </Panel>
              ) : (
                <Panel title="结果操作">
                  <div className="space-y-3">
                    <p className="text-xs text-muted-foreground">
                      支持导入/导出当前矩阵数据（用于复现、分享、离线分析）。
                    </p>

                    <div className="space-y-2">
                      <div className="text-xs font-medium text-foreground/80">选择要导出的图表</div>
                      <select
                        className="w-full h-9 rounded-md border border-border bg-background px-2 text-sm outline-none focus:ring-2 focus:ring-primary/30"
                        value={String(exportIndex)}
                        onChange={(e) => setExportIndex(Number(e.target.value) || 0)}
                        disabled={results.length === 0}
                      >
                        {results.length === 0 ? (
                          <option value="0">请先计算相似度</option>
                        ) : (
                          results.map((r, idx) => (
                            <option key={`${r.xCollectionId}__${r.yCollectionId}`} value={idx}>
                              {idx + 1}. {r.xCollectionLabel} vs {r.yCollectionLabel}
                            </option>
                          ))
                        )}
                      </select>
                    </div>

                    <div className="grid grid-cols-2 gap-2">
                      <Button variant="outline" onClick={exportOne} disabled={results.length === 0}>
                        导出JSON
                      </Button>
                      <Button variant="outline" onClick={exportAll} disabled={results.length === 0}>
                        导出所有JSON
                      </Button>
                    </div>

                    <Button
                      variant="default"
                      onClick={() => importInputRef.current?.click()}
                      className="w-full"
                    >
                      导入JSON
                    </Button>

                    <input
                      ref={importInputRef}
                      type="file"
                      accept=".json"
                      multiple
                      className="hidden"
                      onChange={(e) => {
                        detachPromise(importFiles(e.target.files))
                        // Reset so selecting the same file again still triggers onChange.
                        e.currentTarget.value = ''
                      }}
                    />
                  </div>
                </Panel>
              )}
            </div>

            <button
              type="button"
              aria-label="Resize left split"
              className="h-2 cursor-row-resize bg-border/50 hover:bg-primary/20"
              onMouseDown={(e) => startResizeSplit('left', e)}
            />

            <div className="p-3 overflow-auto overscroll-contain no-scrollbar">
              <Panel title="图表选择与控制">
                {results.length === 0 ? (
                  <p className="text-xs text-muted-foreground">请先在“数据源配置”里计算相似度矩阵。</p>
                ) : (
                  <div className="space-y-2">
                    <p className="text-[11px] text-muted-foreground">
                      提示：应用数据=显示/差值；应用筛选器=合并筛选条件(可多选)；独占模式=锁定编辑该图
                    </p>
                    <div className="space-y-2">
                      {results.map((entry, idx) => {
                        const btn = matrixButtons[idx]
                        const isPrimary = primaryIndex === idx
                        const isSubtract = subtractIndex === idx
                        const isExclusive = exclusiveIndex === idx

                        return (
                          <div
                            key={`${entry.xCollectionId}__${entry.yCollectionId}`}
                            className={cn(
                              'flex items-center gap-2 rounded-lg border p-2',
                              isPrimary ? 'border-primary/50 bg-primary/5' : 'border-border bg-background'
                            )}
                          >
                            <div className="flex-1 min-w-0">
                              <div className="text-xs font-medium truncate">
                                {entry.xCollectionLabel} <span className="text-muted-foreground">vs</span> {entry.yCollectionLabel}
                              </div>
                              <div className="text-[11px] text-muted-foreground flex items-center gap-2">
                                <span>
                                  {matrixShape(entry).rows}×{matrixShape(entry).cols}
                                </span>
                                {isPrimary ? (
                                  <span className="px-1.5 py-0.5 rounded bg-primary/10 text-primary">主</span>
                                ) : null}
                                {isSubtract ? (
                                  <span className="px-1.5 py-0.5 rounded bg-amber-500/10 text-amber-700 dark:text-amber-300">
                                    减
                                  </span>
                                ) : null}
                                {isExclusive ? (
                                  <span className="px-1.5 py-0.5 rounded bg-sky-500/10 text-sky-700 dark:text-sky-300">
                                    独占
                                  </span>
                                ) : null}
                              </div>
                            </div>

                            <div className="flex items-center gap-1">
	                              <Button
	                                variant={btn?.applyData ? 'default' : 'outline'}
	                                size="icon"
	                                title="应用数据"
	                                aria-label="应用数据"
	                                onClick={() => toggleApplyData(idx)}
	                              >
	                                <Eye className="h-4 w-4" />
	                              </Button>
	                              <Button
	                                variant={btn?.applyFilter ? 'default' : 'outline'}
	                                size="icon"
	                                title="应用筛选器"
	                                aria-label="应用筛选器"
	                                onClick={() => toggleApplyFilter(idx)}
	                              >
	                                <Filter className="h-4 w-4" />
	                              </Button>
	                              <Button
	                                variant={btn?.exclusive ? 'default' : 'outline'}
	                                size="icon"
	                                title="独占模式"
	                                aria-label="独占模式"
	                                onClick={() => (btn?.exclusive ? exitExclusiveMode() : enterExclusiveMode(idx))}
	                              >
	                                <Lock className="h-4 w-4" />
	                              </Button>
                            </div>
                          </div>
                        )
                      })}
                    </div>
                  </div>
                )}
              </Panel>
            </div>
          </div>
        </div>
      </div>

      {/* Main content */}
      <div className="flex-1 h-full overflow-hidden bg-background">
        <div className="h-full w-full flex flex-col">
          <div className="h-12 border-b border-border flex items-center justify-between px-4">
            <div className="text-sm font-semibold">Collection × Collection 相似度热力图</div>
            <div className="flex items-center gap-2">
              <span className="text-xs text-muted-foreground">配色方案：</span>
              <div className="flex items-center gap-1">
                {COLOR_SCHEMES.map((scheme) => (
                  <button
                    key={scheme.key}
                    type="button"
                    className={cn(
                      'h-3 w-7 rounded border transition',
                      scheme.key === colorScheme ? 'border-primary' : 'border-border hover:border-primary/50'
                    )}
                    title={scheme.label}
                    onClick={() => setColorScheme(scheme.key)}
                    style={{ backgroundImage: scheme.preview }}
                  />
                ))}
              </div>
            </div>
          </div>
          <div className="flex-1 overflow-hidden flex items-center justify-center">
            {primaryEntry && displayMatrix && displayLabels ? (
              <div className="h-full w-full">
                <PlotlyHeatmap
                  matrix={maskedMatrix || displayMatrix}
                  xLabels={displayLabels.xLabels}
                  yLabels={displayLabels.yLabels}
                  colorScheme={colorScheme}
                  isDifference={isDifferenceMode}
                />
              </div>
            ) : (
              <div className="text-sm text-muted-foreground">请先计算相似度矩阵并选择“应用数据”。</div>
            )}
          </div>
        </div>
      </div>

      {/* Right section */}
      <div className="flex h-full">
        <div className="w-12 border-l border-border bg-background flex flex-col items-center py-2">
          <div className="flex flex-col gap-1">
            <IconBtn
              active={rightTopPanel === 'statistics'}
              title="统计信息"
              onClick={() => setRightTopPanel((prev) => (prev === 'statistics' ? null : 'statistics'))}
              icon={<BarChart3 className="h-4 w-4" />}
            />
          </div>
          <div className="mt-auto pt-2">
            <IconBtn
              active={rightBottomPanel === 'filters'}
              title="筛选器控制"
              onClick={() => setRightBottomPanel((prev) => (prev === 'filters' ? null : 'filters'))}
              icon={<Filter className="h-4 w-4" />}
            />
          </div>
        </div>

        <div
          ref={rightSidebarRef}
          className="relative h-full border-l border-border bg-card flex flex-col"
          style={{ width: rightWidth }}
        >
          <button
            type="button"
            aria-label="Resize right sidebar"
            className="absolute top-0 left-0 h-full w-1 cursor-col-resize hover:bg-primary/20"
            onMouseDown={(e) => startResizeSidebar('right', e)}
          />

          <div className="flex flex-col overflow-hidden">
            <div className="p-3 border-b border-border" style={rightTopStyle}>
              {rightTopPanel === 'statistics' ? (
                <Panel title="统计信息">
                  {(() => {
    if (!primaryEntry || !effectiveMask) {
        return (<p className="text-xs text-muted-foreground">请先选择一个主图矩阵。</p>);
    }
    else if (isDifferenceMode && differenceStats) {
            return (<StatsGrid>
                      <StatsItem label="True Positive" value={differenceStats.truePositive} tone="success"/>
                      <StatsItem label="True Negative" value={differenceStats.trueNegative} tone="muted"/>
                      <StatsItem label="False Positive" value={differenceStats.falsePositive} tone="warning"/>
                      <StatsItem label="False Negative" value={differenceStats.falseNegative} tone="danger"/>
                      <StatsItem label="上下文召回率" value={`${(differenceStats.contextRecall * 100).toFixed(2)}%`} tone="info"/>
                      <StatsItem label="上下文精度" value={`${(differenceStats.contextPrecision * 100).toFixed(2)}%`} tone="info"/>
                    </StatsGrid>);
        }
        else if (normalStats) {
                return (<StatsGrid>
                      <StatsItem label="当前显示对比数" value={`${normalStats.currentDisplayCount} / ${normalStats.totalCount}`}/>
                      <StatsItem label="斜对角线对比数" value={`${normalStats.diagonalTrueCount} / ${normalStats.diagonalTotalCount}`}/>
                      {normalStats.topKAxis === 'none' ? null : (<StatsItem label={`缺失匹配(${normalStats.topKAxis === 'x' ? '横轴' : '纵轴'})`} value={normalStats.missingMatchCount} tone={normalStats.missingMatchCount > 0 ? 'warning' : 'muted'}/>)}
                    </StatsGrid>);
            }
            else {
                return (<p className="text-xs text-muted-foreground">暂无统计数据</p>);
            }
})()}
                </Panel>
              ) : (
                <div className="h-full" />
              )}
            </div>

            <button
              type="button"
              aria-label="Resize right split"
              className="h-2 cursor-row-resize bg-border/50 hover:bg-primary/20"
              onMouseDown={(e) => startResizeSplit('right', e)}
            />

            <div className="p-3 overflow-auto overscroll-contain no-scrollbar">
              {rightBottomPanel === 'filters' ? (
                <Panel title="筛选器控制">
                  {primaryEntry ? (
                    <div className="space-y-5">
                      <div className="space-y-2">
                        <div className="text-xs font-medium text-foreground/80">横坐标显示字段</div>
                        <select
                          className="w-full h-9 rounded-md border border-border bg-background px-2 text-sm outline-none focus:ring-2 focus:ring-primary/30"
                          value={primaryEntry.visualConfig.displayFields.xField}
                          onChange={(e) =>
                            updateDisplayFields(e.target.value, primaryEntry.visualConfig.displayFields.yField)
                          }
                        >
                          {primaryEntry.result.x_available_fields.map((f) => (
                            <option key={f} value={f}>
                              {f}
                            </option>
                          ))}
                        </select>
                      </div>

                      <div className="space-y-2">
                        <div className="text-xs font-medium text-foreground/80">纵坐标显示字段</div>
                        <select
                          className="w-full h-9 rounded-md border border-border bg-background px-2 text-sm outline-none focus:ring-2 focus:ring-primary/30"
                          value={primaryEntry.visualConfig.displayFields.yField}
                          onChange={(e) =>
                            updateDisplayFields(primaryEntry.visualConfig.displayFields.xField, e.target.value)
                          }
                        >
                          {primaryEntry.result.y_available_fields.map((f) => (
                            <option key={f} value={f}>
                              {f}
                            </option>
                          ))}
                        </select>
                      </div>

                      <div className="space-y-2">
                        <div className="text-xs font-medium text-foreground/80">相似度阈值范围</div>
                        <div className="space-y-2">
                          <div className="flex items-center gap-2">
                            <input
                              type="range"
                              min={rangeBounds.min}
                              max={rangeBounds.max}
                              step={0.01}
                              value={uiSimilarityRange.min}
                              onChange={(e) =>
                                updateSimilarityRange({ min: Number(e.target.value), max: uiSimilarityRange.max })
                              }
                              className="flex-1"
                            />
                            <input
                              type="number"
                              min={rangeBounds.min}
                              max={rangeBounds.max}
                              step={0.01}
                              value={uiSimilarityRange.min}
                              onChange={(e) =>
                                updateSimilarityRange({ min: Number(e.target.value), max: uiSimilarityRange.max })
                              }
                              className="w-20 h-9 rounded-md border border-border bg-background px-2 text-sm"
                            />
                          </div>
                          <div className="flex items-center gap-2">
                            <input
                              type="range"
                              min={rangeBounds.min}
                              max={rangeBounds.max}
                              step={0.01}
                              value={uiSimilarityRange.max}
                              onChange={(e) =>
                                updateSimilarityRange({ min: uiSimilarityRange.min, max: Number(e.target.value) })
                              }
                              className="flex-1"
                            />
                            <input
                              type="number"
                              min={rangeBounds.min}
                              max={rangeBounds.max}
                              step={0.01}
                              value={uiSimilarityRange.max}
                              onChange={(e) =>
                                updateSimilarityRange({ min: uiSimilarityRange.min, max: Number(e.target.value) })
                              }
                              className="w-20 h-9 rounded-md border border-border bg-background px-2 text-sm"
                            />
                          </div>
                        </div>
                      </div>

                      <div className="space-y-2">
                        <div className="text-xs font-medium text-foreground/80">Top-K 筛选</div>
                        <div className="flex items-center gap-2">
                          <input
                            type="range"
                            min={0}
                            max={Math.max(0, uiTopK.axis === 'x' ? matrixShape(primaryEntry).cols : matrixShape(primaryEntry).rows)}
                            step={1}
                            value={uiTopK.value}
                            onChange={(e) => updateTopK({ ...uiTopK, value: Number(e.target.value) })}
                            className="flex-1"
                          />
                          <input
                            type="number"
                            min={0}
                            max={Math.max(0, uiTopK.axis === 'x' ? matrixShape(primaryEntry).cols : matrixShape(primaryEntry).rows)}
                            step={1}
                            value={uiTopK.value}
                            onChange={(e) => updateTopK({ ...uiTopK, value: Number(e.target.value) })}
                            className="w-20 h-9 rounded-md border border-border bg-background px-2 text-sm"
                          />
                        </div>
                        <div className="flex items-center gap-2">
                          <Button
                            variant={uiTopK.axis === 'x' ? 'default' : 'outline'}
                            size="sm"
                            onClick={() => updateTopK({ ...uiTopK, axis: 'x' })}
                            className="flex-1"
                          >
                            横轴Top-K
                          </Button>
                          <Button
                            variant={uiTopK.axis === 'y' ? 'default' : 'outline'}
                            size="sm"
                            onClick={() => updateTopK({ ...uiTopK, axis: 'y' })}
                            className="flex-1"
                          >
                            纵轴Top-K
                          </Button>
                        </div>
                        <p className="text-[11px] text-muted-foreground">
                          当前：Top-{uiTopK.value}（{(() => {
    if (uiTopK.value === 0) {
        return '显示全部';
    }
    else if (uiTopK.axis === 'x') {
            return '按行取 Top-K';
        }
        else {
            return '按列取 Top-K';
        }
})()}）
                        </p>
                      </div>
                    </div>
                  ) : (
                    <p className="text-xs text-muted-foreground">请先选择一个主图矩阵。</p>
                  )}
                </Panel>
              ) : (
                <div />
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

function IconBtn({
  active,
  icon,
  title,
  onClick,
}: Readonly<{
  active?: boolean
  icon: ReactNode
  title: string
  onClick?: () => void
}>) {
  return (
    <button
      type="button"
      title={title}
      onClick={onClick}
      className={cn(
        'h-9 w-9 rounded-lg flex items-center justify-center border transition-colors',
        active ? 'bg-primary text-primary-foreground border-primary/40' : 'bg-background hover:bg-muted border-border'
      )}
    >
      {icon}
    </button>
  )
}

function Panel({
  title,
  children,
  rightSlot,
}: Readonly<{
  title: string
  children: ReactNode
  rightSlot?: ReactNode
}>) {
  return (
    <div className="h-full flex flex-col">
      <div className="flex items-center justify-between gap-2 mb-2">
        <div className="text-sm font-semibold">{title}</div>
        {rightSlot}
      </div>
      <div className="flex-1">{children}</div>
    </div>
  )
}

type SelectOption = { value: string; label: string; kind?: string; count?: number }

function CollectionSelectorBlock({
  label,
  selections,
  onChange,
  options,
}: Readonly<{
  label: string
  selections: string[]
  onChange: (next: string[]) => void
  options: SelectOption[]
}>) {
  const keyedSelections = useMemo(() => {
    const seen = new Map<string, number>()
    return selections.map((value) => {
      const base = value || '__empty__'
      const count = (seen.get(base) ?? 0) + 1
      seen.set(base, count)
      return { value, key: `${base}:${count}` }
    })
  }, [selections])

  return (
    <div className="space-y-2">
      <div className="text-xs font-medium text-foreground/80">{label}</div>
      <div className="space-y-2">
        {keyedSelections.map(({ value, key }, idx) => (
          <div key={key} className="flex items-center gap-2">
            <select
              className="flex-1 h-9 rounded-md border border-border bg-background px-2 text-sm outline-none focus:ring-2 focus:ring-primary/30"
              value={value}
              onChange={(e) => {
                const next = [...selections]
                next[idx] = e.target.value
                onChange(next)
              }}
            >
              <option value="">请选择...</option>
              {options.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>

	            {idx === 0 ? (
	              <Button
	                type="button"
	                variant="outline"
	                size="icon"
	                title="添加"
	                aria-label="添加"
	                onClick={() => onChange([...selections, ''])}
	              >
	                +
	              </Button>
	            ) : (
	              <Button
	                type="button"
	                variant="outline"
	                size="icon"
	                title="删除"
	                aria-label="删除"
	                onClick={() => onChange(selections.filter((_, i) => i !== idx))}
	              >
	                -
	              </Button>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

function NumberField({
  label,
  value,
  onChange,
  min,
  max,
}: Readonly<{
  label: string
  value: number
  onChange: (next: number) => void
  min: number
  max: number
}>) {
  return (
    <label className="space-y-2 block">
      <div className="text-xs font-medium text-foreground/80">{label}</div>
      <input
        className="w-full h-9 rounded-md border border-border bg-background px-2 text-sm outline-none focus:ring-2 focus:ring-primary/30"
        type="number"
        min={min}
        max={max}
        value={value}
        onChange={(e) => {
          const parsed = Number(e.target.value)
          if (!Number.isFinite(parsed)) return
          onChange(parsed)
        }}
      />
    </label>
  )
}

const DEFAULT_FIELD_NAMES = ['document', 'text', 'name']

function getDefaultDisplayField(fields: string[]) {
  for (const name of DEFAULT_FIELD_NAMES) {
    if (fields.includes(name)) return name
  }
  return fields[0] || ''
}

type VisualConfig = {
  displayFields: { xField: string; yField: string }
  similarityRange: { min: number; max: number }
  filters: { topK: { value: number; axis: 'x' | 'y' } }
  sorting: { order: string }
}

function createDefaultVisualConfig(xFields: string[], yFields: string[]): VisualConfig {
  const defaultXField = getDefaultDisplayField(xFields)
  const defaultYField = getDefaultDisplayField(yFields)

  return {
    displayFields: {
      xField: defaultXField,
      yField: defaultYField,
    },
    similarityRange: { min: 0, max: 1 },
    filters: { topK: { value: 0, axis: 'x' } },
    sorting: { order: 'none' },
  }
}

type SimilarityMatrixEntry = {
  xCollectionId: string
  yCollectionId: string
  xCollectionLabel: string
  yCollectionLabel: string
  result: RagvizSimilarityMatrixResult
  visualConfig: VisualConfig
}

type MatrixButtonState = {
  applyData: boolean
  applyFilter: boolean
  exclusive: boolean
}

type ColorSchemeKey = 'viridis' | 'plasma' | 'cividis' | 'YlGnBu' | 'hot'

const COLOR_SCHEMES: Array<{ key: ColorSchemeKey; label: string; preview: string }> = [
  { key: 'viridis', label: 'Viridis', preview: 'linear-gradient(90deg,#440154,#21908d,#fde725)' },
  { key: 'plasma', label: 'Plasma', preview: 'linear-gradient(90deg,#0d0887,#cc4678,#f0f921)' },
  { key: 'cividis', label: 'Cividis', preview: 'linear-gradient(90deg,#00204c,#5f7d7f,#fee838)' },
  { key: 'YlGnBu', label: 'YlGnBu', preview: 'linear-gradient(90deg,#ffffcc,#1d91c0,#081d58)' },
  { key: 'hot', label: 'Hot', preview: 'linear-gradient(90deg,#000000,#ff0000,#ffff00)' },
]

function toPlotlyColorScale(key: ColorSchemeKey) {
  const mapping: Record<ColorSchemeKey, string> = {
    viridis: 'Viridis',
    plasma: 'Plasma',
    cividis: 'Cividis',
    YlGnBu: 'YlGnBu',
    hot: 'Hot',
  }
  return mapping[key]
}

function generateUniqueLabels(items: Array<Record<string, unknown>>, field: string) {
  const counts = new Map<string, number>()
  return items.map((item) => {
    const raw = String((item && field ? item[field] : '') ?? '').trim()
    const key = raw || '(empty)'
    const next = (counts.get(key) || 0) + 1
    counts.set(key, next)
    return next === 1 ? key : `${key} (${next})`
  })
}

function PlotlyHeatmap({
  matrix,
  xLabels,
  yLabels,
  colorScheme,
  isDifference,
}: Readonly<{
  matrix: Array<Array<number | null>>
  xLabels: string[]
  yLabels: string[]
  colorScheme: ColorSchemeKey
  isDifference: boolean
}>) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [plotly, setPlotly] = useState<PlotlyLike | null>(null)
  const [plotlyLoadState, setPlotlyLoadState] = useState<'loading' | 'ready' | 'error'>('loading')

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const modUnknown: unknown = await import('plotly.js-dist-min')
        const mod = isRecord(modUnknown) ? modUnknown : null
        const plotlyModule = isPlotlyLike(mod?.default) ? mod.default : isPlotlyLike(modUnknown) ? modUnknown : null
        if (!cancelled) {
          setPlotly(plotlyModule)
          setPlotlyLoadState(plotlyModule ? 'ready' : 'error')
        }
      } catch {
        if (!cancelled) {
          setPlotly(null)
          setPlotlyLoadState('error')
        }
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    if (!plotly || !containerRef.current) return

    const zmin = isDifference ? -1 : 0
    const zmax = 1
    const colorscale = isDifference ? 'RdBu' : toPlotlyColorScale(colorScheme)

    const trace: PlotlyTrace = {
      type: 'heatmap',
      z: matrix,
      x: xLabels,
      y: yLabels,
      colorscale,
      zmin,
      zmax,
      hovertemplate: 'x=%{x}<br>y=%{y}<br>value=%{z:.4f}<extra></extra>',
    }

    const layout: PlotlyLayout = {
      margin: { l: 120, r: 30, t: 30, b: 120 },
      xaxis: { automargin: true, tickangle: 45 },
      yaxis: { automargin: true, autorange: 'reversed' },
      paper_bgcolor: 'transparent',
      plot_bgcolor: 'transparent',
    }

    const config: PlotlyConfig = {
      responsive: true,
      displaylogo: false,
    }

    plotly.react(containerRef.current, [trace], layout, config)
  }, [plotly, matrix, xLabels, yLabels, colorScheme, isDifference])

  useEffect(() => {
    if (!plotly || !containerRef.current) return
    const el = containerRef.current
    return () => {
      try {
        plotly.purge(el)
      } catch {
        // ignore
      }
    }
  }, [plotly])

  if (plotlyLoadState === 'loading') {
    return (
      <div className="flex h-full min-h-[320px] flex-col items-center justify-center rounded-xl border border-border/60 bg-background/70 px-6">
        <PageLoading
          message="正在加载相似度热力图..."
          srMessage="Loading similarity heatmap"
          className="min-h-0 flex-none"
        />
        <p className="mt-2 text-xs text-muted-foreground">正在初始化图表引擎...</p>
      </div>
    )
  }

  if (!plotly) {
    return (
      <div className="flex h-full min-h-[320px] items-center justify-center rounded-xl border border-dashed border-border/60 bg-background/70 px-6 text-center text-sm text-muted-foreground">
        图表引擎加载失败，请稍后重试
      </div>
    )
  }

  return <div ref={containerRef} className="h-full w-full" />
}

function computeThresholdMask(matrix: number[][], minSim: number, maxSim: number) {
  const min = Math.min(minSim, maxSim)
  const max = Math.max(minSim, maxSim)
  return matrix.map((row) => row.map((val) => Number.isFinite(val) && val >= min && val <= max))
}

function computeTopKMask(matrix: number[][], topK: number, axis: 'x' | 'y') {
  const rows = matrix.length
  const cols = rows > 0 ? (matrix[0]?.length || 0) : 0
  if (rows === 0 || cols === 0) return []
  if (!topK || topK <= 0) return matrix.map((row) => row.map(() => true))

  const k = axis === 'x' ? Math.min(topK, cols) : Math.min(topK, rows)
  const mask: boolean[][] = Array.from({ length: rows }, () => Array.from({ length: cols }, () => false))

  if (axis === 'x') {
    for (let i = 0; i < rows; i++) {
      const scored = matrix[i]
        .map((v, j) => ({ j, v }))
        .filter((x) => Number.isFinite(x.v))
        .sort((a, b) => b.v - a.v)
        .slice(0, k)
      for (const { j } of scored) mask[i][j] = true
    }
    return mask
  }

  for (let j = 0; j < cols; j++) {
    const scored = []
    for (let i = 0; i < rows; i++) {
      const v = matrix[i][j]
      if (!Number.isFinite(v)) continue
      scored.push({ i, v })
    }
    scored.sort((a, b) => b.v - a.v)
    for (const { i } of scored.slice(0, k)) mask[i][j] = true
  }
  return mask
}

function combineWithAND(a: boolean[][], b: boolean[][]) {
  const rows = Math.min(a.length, b.length)
  const cols = rows > 0 ? Math.min(a[0]?.length || 0, b[0]?.length || 0) : 0
  const out: boolean[][] = Array.from({ length: rows }, () => Array.from({ length: cols }, () => false))
  for (let i = 0; i < rows; i++) {
    for (let j = 0; j < cols; j++) out[i][j] = Boolean(a[i][j] && b[i][j])
  }
  return out
}

function combineWithOR(masks: boolean[][][]) {
  if (masks.length === 0) return []
  const rows = masks[0].length
  const cols = rows > 0 ? masks[0][0].length : 0
  const out: boolean[][] = Array.from({ length: rows }, () => Array.from({ length: cols }, () => false))
  for (const mask of masks) {
    for (let i = 0; i < rows; i++) {
      for (let j = 0; j < cols; j++) out[i][j] = out[i][j] || Boolean(mask[i][j])
    }
  }
  return out
}

function computeFinalMask(
  matrix: number[][],
  range: { min: number; max: number },
  topK: { value: number; axis: 'x' | 'y' }
) {
  const thresholdMask = computeThresholdMask(matrix, range.min, range.max)
  const topKMask = computeTopKMask(matrix, topK.value, topK.axis)
  return combineWithAND(thresholdMask, topKMask)
}

function applyMask(matrix: number[][], mask: boolean[][]): Array<Array<number | null>> {
  const rows = Math.min(matrix.length, mask.length)
  const cols = rows > 0 ? Math.min(matrix[0]?.length || 0, mask[0]?.length || 0) : 0
  const out: Array<Array<number | null>> = Array.from({ length: rows }, () => Array.from({ length: cols }, () => null))
  for (let i = 0; i < rows; i++) {
    for (let j = 0; j < cols; j++) {
      out[i][j] = mask[i][j] ? matrix[i][j] : null
    }
  }
  return out
}

type NormalModeStats = {
  totalCount: number
  currentDisplayCount: number
  diagonalTrueCount: number
  diagonalTotalCount: number
  missingMatchCount: number
  topKAxis: 'x' | 'y' | 'none'
}

function calculateNormalModeStatistics(finalMask: boolean[][], topKAxis: 'x' | 'y' | 'none'): NormalModeStats {
  const rows = finalMask.length
  const cols = rows > 0 ? (finalMask[0]?.length || 0) : 0
  const totalCount = rows * cols

  let currentDisplayCount = 0
  for (let i = 0; i < rows; i++) {
    for (let j = 0; j < cols; j++) if (finalMask[i][j]) currentDisplayCount++
  }

  const diagonalTotalCount = Math.min(rows, cols)
  let diagonalTrueCount = 0
  for (let i = 0; i < diagonalTotalCount; i++) if (finalMask[i][i]) diagonalTrueCount++

  let missingMatchCount = 0
  if (topKAxis === 'x') {
    for (let i = 0; i < rows; i++) {
      let hasTrue = false
      for (let j = 0; j < cols; j++) {
        if (finalMask[i][j]) {
          hasTrue = true
          break
        }
      }
      if (!hasTrue) missingMatchCount++
    }
  } else if (topKAxis === 'y') {
    for (let j = 0; j < cols; j++) {
      let hasTrue = false
      for (let i = 0; i < rows; i++) {
        if (finalMask[i][j]) {
          hasTrue = true
          break
        }
      }
      if (!hasTrue) missingMatchCount++
    }
  }

  return {
    totalCount,
    currentDisplayCount,
    diagonalTrueCount,
    diagonalTotalCount,
    missingMatchCount,
    topKAxis,
  }
}

type DifferenceModeStats = {
  truePositive: number
  trueNegative: number
  falsePositive: number
  falseNegative: number
  contextRecall: number
  contextPrecision: number
}

function calculateDifferenceModeStatistics(groundTruthMask: boolean[][], currentMask: boolean[][]): DifferenceModeStats {
  const rows = Math.min(groundTruthMask.length, currentMask.length)
  const cols =
    rows > 0 ? Math.min(groundTruthMask[0]?.length || 0, currentMask[0]?.length || 0) : 0

  let truePositive = 0
  let trueNegative = 0
  let falsePositive = 0
  let falseNegative = 0

  for (let i = 0; i < rows; i++) {
    for (let j = 0; j < cols; j++) {
      const gt = Boolean(groundTruthMask[i][j])
      const cur = Boolean(currentMask[i][j])
      if (gt && cur) truePositive++
      else if (!gt && !cur) trueNegative++
      else if (!gt && cur) falsePositive++
      else falseNegative++
    }
  }

  const contextRecall = truePositive + falseNegative > 0 ? truePositive / (truePositive + falseNegative) : 0
  const contextPrecision = truePositive + falsePositive > 0 ? truePositive / (truePositive + falsePositive) : 0

  return { truePositive, trueNegative, falsePositive, falseNegative, contextRecall, contextPrecision }
}

function StatsGrid({ children }: Readonly<{ children: ReactNode }>) {
  return <div className="grid grid-cols-2 gap-2">{children}</div>
}

function StatsItem({
  label,
  value,
  tone = 'default',
}: Readonly<{
  label: string
  value: ReactNode
  tone?: 'default' | 'muted' | 'info' | 'success' | 'warning' | 'danger'
}>) {
  const toneClass =
    (() => {
    if (tone === 'success') {
        return 'bg-emerald-50 text-emerald-700 border-emerald-100 dark:bg-emerald-900/15 dark:text-emerald-200 dark:border-emerald-900/30';
    }
    else if (tone === 'warning') {
            return 'bg-amber-50 text-amber-800 border-amber-100 dark:bg-amber-900/15 dark:text-amber-200 dark:border-amber-900/30';
        }
        else if (tone === 'danger') {
                return 'bg-rose-50 text-rose-700 border-rose-100 dark:bg-rose-900/15 dark:text-rose-200 dark:border-rose-900/30';
            }
            else if (tone === 'info') {
                    return 'bg-sky-50 text-sky-700 border-sky-100 dark:bg-sky-900/15 dark:text-sky-200 dark:border-sky-900/30';
                }
                else if (tone === 'muted') {
                        return 'bg-muted text-muted-foreground border-border';
                    }
                    else {
                        return 'bg-card text-foreground border-border';
                    }
})()

  return (
    <div className={cn('rounded-lg border p-2', toneClass)}>
      <div className="text-[11px] font-medium opacity-90">{label}</div>
      <div className="text-sm font-semibold mt-1">{value}</div>
    </div>
  )
}
