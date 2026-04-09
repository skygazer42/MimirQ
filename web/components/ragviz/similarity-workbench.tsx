'use client'

import type { MouseEvent as ReactMouseEvent, ReactNode } from 'react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ragvizApi } from '@/lib/api'
import { SimilarityDiagnosticsGraph } from '@/components/ragviz/similarity-diagnostics-graph'
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
import { buildSimilarityDiagnostics } from '@/components/ragviz/similarity-diagnostics'
import type {
  DiagnosticDecision,
  SimilarityDiagnosticsResult,
} from '@/components/ragviz/similarity-diagnostics'
import {
  BarChart3,
  ChevronLeft,
  ChevronRight,
  ChevronDown,
  Database,
  Download,
  Eye,
  Filter,
  Grid3X3,
  Lock,
  Minus,
  Plus,
  RefreshCw,
} from 'lucide-react'
import { toast } from 'sonner'

type LeftTopPanel = 'dataSource' | 'operations'
type MainViewMode = 'heatmap' | 'diagnostics'
type RightTopPanel = 'statistics' | null
type RightBottomPanel = 'filters' | null
type JsonRecord = Record<string, unknown>
type SelectedHeatmapCell = { rowIndex: number; colIndex: number }

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

type PlotlyClickPoint = {
  pointNumber?: number | number[]
  pointIndex?: number | number[]
  i?: number
  j?: number
}

type PlotlyClickEvent = {
  points?: PlotlyClickPoint[]
}

type PlotlyEventTarget = HTMLDivElement & {
  on?: (eventName: 'plotly_click', handler: (event: PlotlyClickEvent) => void) => void
  removeAllListeners?: (eventName?: string) => void
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
  const [mainView, setMainView] = useState<MainViewMode>('heatmap')
  const [diagnosticDecisions, setDiagnosticDecisions] = useState<Record<string, DiagnosticDecision>>({})
  const [selectedCell, setSelectedCell] = useState<SelectedHeatmapCell | null>(null)

  const [leftTopPanel, setLeftTopPanel] = useState<LeftTopPanel>('dataSource')
  const [rightTopPanel, setRightTopPanel] = useState<RightTopPanel>('statistics')
  const [rightBottomPanel, setRightBottomPanel] = useState<RightBottomPanel>('filters')
  const [isLeftSidebarCollapsed, setIsLeftSidebarCollapsed] = useState(false)
  const [isRightSidebarCollapsed, setIsRightSidebarCollapsed] = useState(false)

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
    setMainView('heatmap')
    setDiagnosticDecisions({})
    setSelectedCell(null)

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

    setMainView('heatmap')
    setDiagnosticDecisions({})
    setSelectedCell(null)
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

  useEffect(() => {
    if (isDifferenceMode && mainView === 'diagnostics') {
      setMainView('heatmap')
    }
  }, [isDifferenceMode, mainView])

  useEffect(() => {
    if (mainView !== 'heatmap') {
      setSelectedCell(null)
    }
  }, [mainView])

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

  const selectedCellDetails = useMemo(() => {
    if (!selectedCell || !displayLabels || !displayMatrix) return null

    const rawValue = displayMatrix[selectedCell.rowIndex]?.[selectedCell.colIndex]
    if (typeof rawValue !== 'number' || !Number.isFinite(rawValue)) return null

    const maskedValue = maskedMatrix?.[selectedCell.rowIndex]?.[selectedCell.colIndex]
    const isVisible = effectiveMask
      ? Boolean(effectiveMask[selectedCell.rowIndex]?.[selectedCell.colIndex])
      : true

    return {
      ...selectedCell,
      xLabel: displayLabels.xLabels[selectedCell.colIndex] || `X${selectedCell.colIndex + 1}`,
      yLabel: displayLabels.yLabels[selectedCell.rowIndex] || `Y${selectedCell.rowIndex + 1}`,
      rawValue,
      maskedValue: typeof maskedValue === 'number' && Number.isFinite(maskedValue) ? maskedValue : null,
      isVisible,
    }
  }, [displayLabels, displayMatrix, effectiveMask, maskedMatrix, selectedCell])

  useEffect(() => {
    if (!selectedCell || !displayMatrix || !displayLabels) return

    const rowCount = displayMatrix.length
    const colCount = rowCount > 0 ? (displayMatrix[0]?.length || 0) : 0
    const outOfBounds = selectedCell.rowIndex >= rowCount || selectedCell.colIndex >= colCount
    const labelsMissing =
      selectedCell.rowIndex >= displayLabels.yLabels.length || selectedCell.colIndex >= displayLabels.xLabels.length

    if (outOfBounds || labelsMissing) {
      setSelectedCell(null)
    }
  }, [displayLabels, displayMatrix, selectedCell])

  const diagnostics = useMemo<SimilarityDiagnosticsResult | null>(() => {
    if (!primaryEntry || !displayLabels || isDifferenceMode) return null
    const matrixForDiagnostics = maskedMatrix ?? displayMatrix
    if (!matrixForDiagnostics) return null

    return buildSimilarityDiagnostics({
      matrix: matrixForDiagnostics.map((row) => row.map((value) => (typeof value === 'number' ? value : 0))),
      xItems: primaryEntry.result.x_data,
      yItems: primaryEntry.result.y_data,
      xLabels: displayLabels.xLabels,
      yLabels: displayLabels.yLabels,
      decisions: diagnosticDecisions,
    })
  }, [diagnosticDecisions, displayLabels, displayMatrix, isDifferenceMode, maskedMatrix, primaryEntry])

  const setDiagnosticDecision = (candidateId: string, decision: DiagnosticDecision | null) => {
    setDiagnosticDecisions((prev) => {
      if (decision === null || prev[candidateId] === decision) {
        const next = { ...prev }
        delete next[candidateId]
        return next
      }
      return { ...prev, [candidateId]: decision }
    })
  }

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

  const handleHeatmapCellSelect = useCallback((cell: SelectedHeatmapCell) => {
    setSelectedCell((prev) =>
      prev && prev.rowIndex === cell.rowIndex && prev.colIndex === cell.colIndex ? null : cell
    )
  }, [])

  const handleStatisticsPanelToggle = useCallback(() => {
    if (isRightSidebarCollapsed) {
      setIsRightSidebarCollapsed(false)
      setRightTopPanel('statistics')
      return
    }
    setRightTopPanel((prev) => (prev === 'statistics' ? null : 'statistics'))
  }, [isRightSidebarCollapsed])

  const handleFilterPanelToggle = useCallback(() => {
    if (isRightSidebarCollapsed) {
      setIsRightSidebarCollapsed(false)
      setRightBottomPanel('filters')
      return
    }
    setRightBottomPanel((prev) => (prev === 'filters' ? null : 'filters'))
  }, [isRightSidebarCollapsed])

  const handleLeftTopPanelSelect = useCallback(
    (panel: LeftTopPanel) => {
      if (isLeftSidebarCollapsed) {
        setIsLeftSidebarCollapsed(false)
      }
      setLeftTopPanel(panel)
    },
    [isLeftSidebarCollapsed]
  )

  const handleLeftChartControlsOpen = useCallback(() => {
    if (isLeftSidebarCollapsed) {
      setIsLeftSidebarCollapsed(false)
    }
  }, [isLeftSidebarCollapsed])

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
      const payload = {
        leftWidth,
        rightWidth,
        leftTopHeight,
        rightTopHeight,
        isLeftSidebarCollapsed,
        isRightSidebarCollapsed,
      }
      localStorage.setItem('ragviz_similarity_layout_v1', JSON.stringify(payload))
    } catch {
      // ignore
    }
  }, [isLeftSidebarCollapsed, isRightSidebarCollapsed, leftWidth, rightWidth, leftTopHeight, rightTopHeight])

  useEffect(() => {
    try {
      const raw = localStorage.getItem('ragviz_similarity_layout_v1')
      if (!raw) return
      const parsed = JSON.parse(raw)
      if (typeof parsed.leftWidth === 'number') setLeftWidth(parsed.leftWidth)
      if (typeof parsed.rightWidth === 'number') setRightWidth(parsed.rightWidth)
      if (typeof parsed.leftTopHeight === 'number') setLeftTopHeight(parsed.leftTopHeight)
      if (typeof parsed.rightTopHeight === 'number') setRightTopHeight(parsed.rightTopHeight)
      if (typeof parsed.isLeftSidebarCollapsed === 'boolean') setIsLeftSidebarCollapsed(parsed.isLeftSidebarCollapsed)
      if (typeof parsed.isRightSidebarCollapsed === 'boolean') setIsRightSidebarCollapsed(parsed.isRightSidebarCollapsed)
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
        <div className="w-12 border-r border-sidebar-border/70 bg-muted flex flex-col items-center py-2">
          <div className="flex flex-col gap-1">
            <IconBtn
              active={!isLeftSidebarCollapsed && leftTopPanel === 'dataSource'}
              title="数据源配置"
              onClick={() => handleLeftTopPanelSelect('dataSource')}
              icon={<Database className="size-4" />}
            />
            <IconBtn
              active={!isLeftSidebarCollapsed && leftTopPanel === 'operations'}
              title="结果操作"
              onClick={() => handleLeftTopPanelSelect('operations')}
              icon={<Download className="size-4" />}
            />
            <IconBtn
              active={false}
              title={isLeftSidebarCollapsed ? '展开左侧栏' : '收起左侧栏'}
              onClick={() => setIsLeftSidebarCollapsed((prev) => !prev)}
              icon={isLeftSidebarCollapsed ? <ChevronRight className="size-4" /> : <ChevronLeft className="size-4" />}
            />
          </div>
          <div className="mt-auto pt-2">
            <IconBtn
              active={!isLeftSidebarCollapsed}
              title="图表选择与控制"
              onClick={handleLeftChartControlsOpen}
              icon={<Grid3X3 className="size-4" />}
            />
          </div>
        </div>

        <div
          ref={leftSidebarRef}
          className={cn(
            'relative h-full border-r border-sidebar-border/70 bg-muted flex flex-col overflow-hidden transition-[width,opacity] duration-200 ease-out',
            isLeftSidebarCollapsed ? 'opacity-0' : 'opacity-100'
          )}
          style={{ width: isLeftSidebarCollapsed ? 0 : leftWidth }}
          aria-hidden={isLeftSidebarCollapsed}
        >
          {isLeftSidebarCollapsed ? null : (
            <button
              type="button"
              aria-label="Resize left sidebar"
              className="absolute top-0 right-0 h-full w-1 cursor-col-resize hover:bg-primary/20"
              onMouseDown={(e) => startResizeSidebar('left', e)}
            />
          )}

          <div className="flex flex-col overflow-hidden">
            <div className="p-3 border-b border-sidebar-border/70" style={leftTopStyle}>
	              {leftTopPanel === 'dataSource' ? (
	                <Panel title="数据源配置" rightSlot={
	                  <Button variant="ghost" size="icon" onClick={loadCollections} disabled={collectionsLoading} title="刷新" aria-label="刷新">
	                    <RefreshCw className={cn('size-4', collectionsLoading && 'animate-spin motion-reduce:animate-none')} />
	                  </Button>
	                }>
                  <div className="space-y-2.5">
                    <div className="rounded-2xl border border-sidebar-border/70 bg-card p-2.5 shadow-soft">
                      <div className="flex items-start gap-2.5">
                        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-xl border border-primary/10 bg-primary/10 text-primary">
                          <Grid3X3 className="size-4" />
                        </div>
                        <div className="min-w-0">
                          <div className="text-[11px] font-medium uppercase tracking-[0.14em] text-muted-foreground">
                            Matrix Setup
                          </div>
                          <p className="mt-0.5 text-[11px] leading-5 text-muted-foreground">
                            选择横/纵坐标 collections，计算相似度矩阵。
                          </p>
                        </div>
                      </div>
                    </div>

                    {collectionsError ? (
                      <div className="rounded-2xl border border-destructive/20 bg-destructive/5 px-3 py-2 text-xs text-destructive">
                        {collectionsError}
                      </div>
                    ) : null}

                    <div className="space-y-2.5">
                      <AxisConfigCard
                        eyebrow="X Axis"
                        title="横坐标 Collection"
                        badge="横向对比"
                        badgeClassName="border-primary/20 bg-primary/10 text-primary"
                      >
                        <CollectionSelectorBlock
                          label="横坐标 Collection"
                          showLabel={false}
                          selections={xSelections}
                          onChange={setXSelections}
                          options={availableCollectionOptions}
                        />
                        <NumberField label="最大项目数" value={xMaxItems} onChange={setXMaxItems} min={10} max={500} />
                      </AxisConfigCard>

                      <AxisConfigCard
                        eyebrow="Y Axis"
                        title="纵坐标 Collection"
                        badge="纵向对比"
                        badgeClassName="border-success/20 bg-success/10 text-success"
                      >
                        <CollectionSelectorBlock
                          label="纵坐标 Collection"
                          showLabel={false}
                          selections={ySelections}
                          onChange={setYSelections}
                          options={availableCollectionOptions}
                        />
                        <NumberField label="最大项目数" value={yMaxItems} onChange={setYMaxItems} min={10} max={500} />
                      </AxisConfigCard>
                    </div>

                    <Button
                      className="h-10 w-full rounded-2xl shadow-soft"
                      onClick={calculateSimilarity}
                      disabled={isCalculating}
                    >
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
                  <div className="rounded-2xl border border-dashed border-sidebar-border/60 bg-muted/30 px-4 py-5 text-center">
                    <div className="text-sm font-medium text-foreground">等待矩阵结果</div>
                    <p className="mt-1 text-xs leading-5 text-muted-foreground">
                      先在上方选择两个 collections，再生成热力图并在这里切换主图、筛选器和独占模式。
                    </p>
                  </div>
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
	                                aria-label={`将 ${entry.xCollectionLabel} vs ${entry.yCollectionLabel} 设为显示数据矩阵`}
	                                onClick={() => toggleApplyData(idx)}
	                              >
	                                <Eye className="size-4" />
	                              </Button>
	                              <Button
	                                variant={btn?.applyFilter ? 'default' : 'outline'}
	                                size="icon"
	                                title="应用筛选器"
	                                aria-label={`将 ${entry.xCollectionLabel} vs ${entry.yCollectionLabel} 的筛选条件加入当前视图`}
	                                onClick={() => toggleApplyFilter(idx)}
	                              >
	                                <Filter className="size-4" />
	                              </Button>
	                              <Button
	                                variant={btn?.exclusive ? 'default' : 'outline'}
	                                size="icon"
	                                title="独占模式"
	                                aria-label={
                                    btn?.exclusive
                                      ? `退出 ${entry.xCollectionLabel} vs ${entry.yCollectionLabel} 的独占编辑模式`
                                      : `将 ${entry.xCollectionLabel} vs ${entry.yCollectionLabel} 设为独占编辑矩阵`
                                  }
	                                onClick={() => (btn?.exclusive ? exitExclusiveMode() : enterExclusiveMode(idx))}
	                              >
	                                <Lock className="size-4" />
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
          <div className="border-b border-sidebar-border/70 bg-muted/20 px-4 py-3">
            <div className="flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
              <div>
                <div className="text-sm font-semibold">
                  {mainView === 'diagnostics' ? '向量诊断' : '跨集合相似度热力图'}
                </div>
                <p className="mt-1 text-[11px] text-muted-foreground">
                  {mainView === 'diagnostics'
                    ? '基于当前相似度矩阵重建局部向量邻域，帮助识别高分但支撑不足的干扰项。'
                    : '使用当前主图矩阵和筛选器观察不同集合之间的相似度分布。'}
                </p>
              </div>

              <div className="flex flex-wrap items-center gap-3">
                <div className="inline-flex items-center rounded-lg border border-border bg-card p-1">
                  <Button
                    variant={mainView === 'heatmap' ? 'default' : 'outline'}
                    size="sm"
                    onClick={() => setMainView('heatmap')}
                  >
                    热力图
                  </Button>
                  <Button
                    variant={mainView === 'diagnostics' ? 'default' : 'outline'}
                    size="sm"
                    onClick={() => setMainView('diagnostics')}
                    disabled={!primaryEntry || !displayLabels || isDifferenceMode}
                    title={isDifferenceMode ? '差值模式暂不支持向量诊断' : '查看向量诊断'}
                  >
                    向量诊断
                  </Button>
                </div>

                {mainView === 'heatmap' ? (
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
                ) : (
                  <div className="flex items-center gap-2 text-xs text-muted-foreground">
                    <span>3D 投影预览</span>
                    <span className="rounded-full border border-border px-2 py-0.5">
                      {diagnostics?.summary.activeOutlierCount ?? 0} 个活跃异常点
                    </span>
                  </div>
                )}
              </div>
            </div>
          </div>
          <div className="flex-1 overflow-hidden">
            {primaryEntry && displayMatrix && displayLabels ? (
              mainView === 'diagnostics' ? (
                diagnostics ? (
                  <SimilarityDiagnosticsView diagnostics={diagnostics} onDecisionChange={setDiagnosticDecision} />
                ) : (
                  <div className="flex h-full items-center justify-center px-6">
                    <div className="rounded-2xl border border-dashed border-sidebar-border/60 bg-muted/30 px-6 py-8 text-center">
                      <div className="text-sm font-semibold text-foreground">向量诊断暂不可用</div>
                      <p className="mt-2 text-sm text-muted-foreground">
                        当前处于差值模式，3D 投影预览和异常点标注只在单个主图矩阵上启用。
                      </p>
                    </div>
                  </div>
                )
              ) : (
                <div className="h-full w-full">
                  <PlotlyHeatmap
                    matrix={maskedMatrix || displayMatrix}
                    xLabels={displayLabels.xLabels}
                    yLabels={displayLabels.yLabels}
                    colorScheme={colorScheme}
                    isDifference={isDifferenceMode}
                    onCellSelect={handleHeatmapCellSelect}
                  />
                </div>
              )
            ) : (
              <div className="flex h-full items-center justify-center px-6">
                <div className="rounded-2xl border border-dashed border-sidebar-border/60 bg-muted/30 px-6 py-8 text-center text-sm text-muted-foreground">
                  请先计算相似度矩阵并选择“应用数据”。
                </div>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Right section */}
      <div className="flex h-full">
        <div className="w-12 border-l border-sidebar-border/70 bg-muted flex flex-col items-center py-2">
          <div className="flex flex-col gap-1">
            <IconBtn
              active={!isRightSidebarCollapsed && rightTopPanel === 'statistics'}
              title="统计信息"
              onClick={handleStatisticsPanelToggle}
              icon={<BarChart3 className="size-4" />}
            />
            <IconBtn
              active={false}
              title={isRightSidebarCollapsed ? '展开右侧栏' : '收起右侧栏'}
              onClick={() => setIsRightSidebarCollapsed((prev) => !prev)}
              icon={isRightSidebarCollapsed ? <ChevronLeft className="size-4" /> : <ChevronRight className="size-4" />}
            />
          </div>
          <div className="mt-auto pt-2">
            <IconBtn
              active={!isRightSidebarCollapsed && rightBottomPanel === 'filters'}
              title="筛选器控制"
              onClick={handleFilterPanelToggle}
              icon={<Filter className="size-4" />}
            />
          </div>
        </div>

        <div
          ref={rightSidebarRef}
          className={cn(
            'relative h-full border-l border-sidebar-border/70 bg-muted flex flex-col overflow-hidden transition-[width,opacity] duration-200 ease-out',
            isRightSidebarCollapsed ? 'opacity-0' : 'opacity-100'
          )}
          style={{ width: isRightSidebarCollapsed ? 0 : rightWidth }}
          aria-hidden={isRightSidebarCollapsed}
        >
          {isRightSidebarCollapsed ? null : (
            <button
              type="button"
              aria-label="Resize right sidebar"
              className="absolute top-0 left-0 h-full w-1 cursor-col-resize hover:bg-primary/20"
              onMouseDown={(e) => startResizeSidebar('right', e)}
            />
          )}

          <div className="flex flex-col overflow-hidden">
            <div className="p-3 border-b border-sidebar-border/70" style={rightTopStyle}>
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

                  {mainView === 'heatmap' ? (
                    <div className="mt-4 border-t border-sidebar-border/60 pt-4">
                      <div className="mb-2 flex items-center justify-between gap-2">
                        <div className="text-[11px] font-medium uppercase tracking-[0.12em] text-muted-foreground">
                          选中单元
                        </div>
                        {selectedCellDetails ? (
                          <Button variant="ghost" size="sm" className="h-7 px-2 text-[11px]" onClick={() => setSelectedCell(null)}>
                            清除
                          </Button>
                        ) : null}
                      </div>

                      {selectedCellDetails ? (
                        <div className="space-y-2">
                          <div className="rounded-xl border border-sidebar-border/70 bg-muted/40 p-3 shadow-soft">
                            <div className="flex items-start justify-between gap-3">
                              <div className="min-w-0 space-y-1">
                                <div className="text-[11px] text-muted-foreground">横轴</div>
                                <div className="truncate text-sm font-medium text-foreground">
                                  {selectedCellDetails.xLabel}
                                </div>
                              </div>
                              <div
                                className={cn(
                                  'inline-flex items-center rounded-full border px-2 py-0.5 text-[11px]',
                                  selectedCellDetails.isVisible
                                    ? 'border-emerald-500/25 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300'
                                    : 'border-amber-500/25 bg-amber-500/10 text-amber-700 dark:text-amber-300'
                                )}
                              >
                                {selectedCellDetails.isVisible ? '显示中' : '已过滤'}
                              </div>
                            </div>

                            <div className="mt-3 min-w-0">
                              <div className="text-[11px] text-muted-foreground">纵轴</div>
                              <div className="truncate text-sm font-medium text-foreground">
                                {selectedCellDetails.yLabel}
                              </div>
                            </div>
                          </div>

                          <div className="grid grid-cols-2 gap-2">
                            <StatsItem
                              label={isDifferenceMode ? '差值' : '相似度'}
                              value={formatHeatmapValue(selectedCellDetails.rawValue)}
                              tone={selectedCellDetails.isVisible ? 'info' : 'muted'}
                            />
                            <StatsItem
                              label="当前显示"
                              value={
                                selectedCellDetails.maskedValue === null
                                  ? '隐藏'
                                  : formatHeatmapValue(selectedCellDetails.maskedValue)
                              }
                              tone={selectedCellDetails.maskedValue === null ? 'warning' : 'success'}
                            />
                            <StatsItem label="行索引" value={selectedCellDetails.rowIndex + 1} tone="muted" />
                            <StatsItem label="列索引" value={selectedCellDetails.colIndex + 1} tone="muted" />
                          </div>
                        </div>
                      ) : (
                        <p className="text-xs text-muted-foreground">
                          点击热力图任意单元后，在这里查看坐标和值。
                        </p>
                      )}
                    </div>
                  ) : null}
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

function SimilarityDiagnosticsView({
  diagnostics,
  onDecisionChange,
}: Readonly<{
  diagnostics: SimilarityDiagnosticsResult
  onDecisionChange: (candidateId: string, decision: DiagnosticDecision | null) => void
}>) {
  return (
    <div className="h-full overflow-auto p-4">
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.6fr)_minmax(320px,380px)]">
        <div className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-3">
            <DiagnosticMetricCard
              label="诊断节点"
              value={String(diagnostics.summary.totalNodes)}
              hint="当前 X/Y 两侧共同参与投影的节点数"
            />
            <DiagnosticMetricCard
              label="邻域连线"
              value={String(diagnostics.summary.totalLinks)}
              hint="按当前筛选保留下来的高相似度近邻边"
            />
            <DiagnosticMetricCard
              label="活跃异常点"
              value={String(diagnostics.summary.activeOutlierCount)}
              hint="仍然需要人工处理的高分异常候选"
            />
          </div>

          <section className="rounded-2xl border border-sidebar-border/70 bg-muted/50 p-3 shadow-soft">
            <div className="flex flex-col gap-3 border-b border-sidebar-border/70 pb-3 md:flex-row md:items-start md:justify-between">
              <div>
                <div className="text-sm font-semibold">3D 投影预览</div>
                <p className="mt-1 text-xs text-muted-foreground">
                  基于当前相似度矩阵重建局部向量邻域，帮助观察高分簇、孤立点和异常连线。
                </p>
              </div>
              <div className="flex flex-wrap items-center gap-2 text-[11px]">
                <LegendPill className="border-sky-200 bg-sky-50 text-sky-700 dark:border-sky-900/40 dark:bg-sky-900/20 dark:text-sky-200">
                  X 侧项目
                </LegendPill>
                <LegendPill className="border-success/20 bg-success/10 text-success">
                  Y 侧项目
                </LegendPill>
                <LegendPill className="border-orange-200 bg-orange-50 text-orange-700 dark:border-orange-900/40 dark:bg-orange-900/20 dark:text-orange-200">
                  异常点候选
                </LegendPill>
                <LegendPill className="border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-900/40 dark:bg-amber-900/20 dark:text-amber-200">
                  标记待审
                </LegendPill>
              </div>
            </div>

            <div className="mt-3">
              <SimilarityDiagnosticsGraph nodes={diagnostics.nodes} links={diagnostics.links} />
            </div>
          </section>
        </div>

        <section className="overflow-hidden rounded-2xl border border-sidebar-border/70 bg-muted/50 shadow-soft">
          <div className="border-b border-sidebar-border/70 p-4">
            <div className="text-sm font-semibold">异常点标注</div>
            <p className="mt-1 text-xs text-muted-foreground">
              高分但词面支撑偏弱的候选会列在这里，可直接禁用候选或标记待审。
            </p>
          </div>

          <div className="space-y-3 overflow-auto p-4">
            {diagnostics.outliers.length === 0 ? (
              <div className="rounded-xl border border-dashed border-sidebar-border/60 bg-muted/30 px-4 py-6 text-sm text-muted-foreground">
                当前筛选结果里没有需要人工干预的高分异常候选。
              </div>
            ) : (
              diagnostics.outliers.map((candidate) => {
                const isDisabled = candidate.decision === 'disabled'
                const isMarked = candidate.decision === 'marked'

                return (
                  <article key={candidate.id} className="rounded-xl border border-sidebar-border/70 bg-muted/40 p-4 shadow-soft">
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <div className="text-sm font-medium text-foreground">
                          {candidate.xLabel} <span className="text-muted-foreground">→</span> {candidate.yLabel}
                        </div>
                        <p className="mt-1 text-xs text-muted-foreground">{candidate.reason}</p>
                      </div>
                      <span
                        className={cn(
                          'rounded-full border px-2 py-0.5 text-[11px]',
                          isDisabled
                            ? 'border-border bg-muted text-muted-foreground'
                            : isMarked
                              ? 'border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-900/40 dark:bg-amber-900/20 dark:text-amber-200'
                              : 'border-orange-200 bg-orange-50 text-orange-700 dark:border-orange-900/40 dark:bg-orange-900/20 dark:text-orange-200'
                        )}
                      >
                        {isDisabled ? '已禁用' : isMarked ? '待审' : '待处理'}
                      </span>
                    </div>

                    <div className="mt-3 grid grid-cols-2 gap-2">
                      <DiagnosticMetricCard label="相似度" value={formatPercent(candidate.similarity)} compact />
                      <DiagnosticMetricCard label="词面重叠" value={formatPercent(candidate.lexicalOverlap)} compact />
                    </div>

                    <div className="mt-3 flex gap-2">
                      <Button
                        variant={isDisabled ? 'default' : 'outline'}
                        size="sm"
                        className="flex-1"
                        onClick={() => onDecisionChange(candidate.id, isDisabled ? null : 'disabled')}
                      >
                        {isDisabled ? '恢复候选' : '禁用候选'}
                      </Button>
                      <Button
                        variant={isMarked ? 'default' : 'outline'}
                        size="sm"
                        className="flex-1"
                        onClick={() => onDecisionChange(candidate.id, isMarked ? null : 'marked')}
                      >
                        {isMarked ? '取消标记' : '标记待审'}
                      </Button>
                    </div>
                  </article>
                )
              })
            )}
          </div>
        </section>
      </div>
    </div>
  )
}

function LegendPill({ className, children }: Readonly<{ className?: string; children: ReactNode }>) {
  return <span className={cn('rounded-full border px-2 py-0.5', className)}>{children}</span>
}

function DiagnosticMetricCard({
  label,
  value,
  hint,
  compact = false,
}: Readonly<{
  label: string
  value: string
  hint?: string
  compact?: boolean
}>) {
  return (
    <div className={cn('rounded-xl border border-sidebar-border/70 bg-muted/40', compact ? 'p-3' : 'p-4')}>
      <div className="text-[11px] font-medium uppercase tracking-[0.08em] text-muted-foreground">{label}</div>
      <div className={cn('mt-1 font-semibold text-foreground', compact ? 'text-base' : 'text-2xl')}>{value}</div>
      {hint ? <p className="mt-1 text-[11px] text-muted-foreground">{hint}</p> : null}
    </div>
  )
}

function formatPercent(value: number) {
  return `${(value * 100).toFixed(1)}%`
}

type SelectOption = { value: string; label: string; kind?: string; count?: number }

function AxisConfigCard({
  eyebrow,
  title,
  badge,
  badgeClassName,
  children,
}: Readonly<{
  eyebrow: string
  title: string
  badge: string
  badgeClassName?: string
  children: ReactNode
}>) {
  return (
    <section className="rounded-2xl border border-sidebar-border/70 bg-muted/40 p-2.5 shadow-soft">
      <div className="mb-2.5 flex items-start justify-between gap-2.5">
        <div className="min-w-0">
          <div className="text-[11px] font-medium uppercase tracking-[0.14em] text-muted-foreground">{eyebrow}</div>
          <div className="mt-0.5 text-sm font-semibold text-foreground">{title}</div>
        </div>
        <span
          className={cn(
            'inline-flex shrink-0 items-center rounded-full border px-2 py-0.5 text-[11px] font-medium',
            badgeClassName
          )}
        >
          {badge}
        </span>
      </div>
      <div className="space-y-2.5">{children}</div>
    </section>
  )
}

function CollectionSelectorBlock({
  label,
  showLabel = true,
  selections,
  onChange,
  options,
}: Readonly<{
  label: string
  showLabel?: boolean
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
    <div className="space-y-1.5">
      {showLabel ? <div className="text-[11px] font-medium uppercase tracking-[0.08em] text-foreground/72">{label}</div> : null}
      <div className="space-y-1.5">
        {keyedSelections.map(({ value, key }, idx) => (
          <div key={key} className="flex items-center gap-1.5">
            <div className="relative flex-1">
              <select
                className="h-9 w-full appearance-none rounded-[16px] border border-slate-200/80 bg-[linear-gradient(180deg,rgba(255,255,255,0.98),rgba(244,247,250,0.96))] px-3 pr-9 text-sm text-foreground shadow-[0_1px_0_rgba(255,255,255,0.85),0_6px_16px_rgba(15,23,42,0.06)] outline-none transition-[border-color,box-shadow,transform] hover:border-primary/25 focus:border-primary/35 focus:shadow-[0_1px_0_rgba(255,255,255,0.9),0_0_0_4px_rgba(59,130,246,0.10),0_10px_24px_rgba(15,23,42,0.08)]"
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
              <span className="pointer-events-none absolute inset-y-0 right-3 flex items-center text-muted-foreground/70">
                <ChevronDown className="size-4" />
              </span>
            </div>

	            {idx === 0 ? (
	              <Button
	                type="button"
	                variant="outline"
	                size="icon"
	                title="添加"
	                aria-label={`为${label}添加一个 Collection 选择器`}
	                className="h-9 w-9 rounded-[14px] border-slate-200/80 bg-[linear-gradient(180deg,rgba(255,255,255,0.98),rgba(244,247,250,0.94))] text-muted-foreground shadow-[0_1px_0_rgba(255,255,255,0.85),0_6px_16px_rgba(15,23,42,0.06)] hover:border-primary/25 hover:bg-background hover:text-primary"
	                onClick={() => onChange([...selections, ''])}
	              >
	                <Plus className="size-4" />
	              </Button>
	            ) : (
	              <Button
	                type="button"
	                variant="outline"
	                size="icon"
	                title="删除"
	                aria-label={`删除第 ${idx + 1} 个${label}选择器`}
	                className="h-9 w-9 rounded-[14px] border-slate-200/80 bg-[linear-gradient(180deg,rgba(255,255,255,0.98),rgba(244,247,250,0.94))] text-muted-foreground shadow-[0_1px_0_rgba(255,255,255,0.85),0_6px_16px_rgba(15,23,42,0.06)] hover:border-primary/25 hover:bg-background hover:text-primary"
	                onClick={() => onChange(selections.filter((_, i) => i !== idx))}
	              >
	                <Minus className="size-4" />
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
    <label className="space-y-1.5 block">
      <div className="flex items-center justify-between gap-2">
        <div className="text-[11px] font-medium uppercase tracking-[0.08em] text-foreground/72">{label}</div>
        <div className="text-[10px] text-muted-foreground">
          {min}-{max}
        </div>
      </div>
      <input
        className="h-9 w-full rounded-[16px] border border-slate-200/80 bg-[linear-gradient(180deg,rgba(255,255,255,0.98),rgba(244,247,250,0.96))] px-3 text-sm text-foreground shadow-[0_1px_0_rgba(255,255,255,0.85),0_6px_16px_rgba(15,23,42,0.06)] outline-none transition-[border-color,box-shadow] hover:border-primary/25 focus:border-primary/35 focus:shadow-[0_1px_0_rgba(255,255,255,0.9),0_0_0_4px_rgba(59,130,246,0.10),0_10px_24px_rgba(15,23,42,0.08)]"
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
  onCellSelect,
}: Readonly<{
  matrix: Array<Array<number | null>>
  xLabels: string[]
  yLabels: string[]
  colorScheme: ColorSchemeKey
  isDifference: boolean
  onCellSelect?: (cell: SelectedHeatmapCell) => void
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

    const plotTarget = containerRef.current as PlotlyEventTarget
    plotTarget.removeAllListeners?.('plotly_click')
    plotTarget.on?.('plotly_click', (event) => {
      const cell = resolveHeatmapPoint(event)
      if (cell) onCellSelect?.(cell)
    })
  }, [colorScheme, isDifference, matrix, onCellSelect, plotly, xLabels, yLabels])

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

function resolveHeatmapPoint(event: PlotlyClickEvent): SelectedHeatmapCell | null {
  const point = event.points?.[0]
  if (!point) return null

  const pair = Array.isArray(point.pointNumber)
    ? point.pointNumber
    : Array.isArray(point.pointIndex)
      ? point.pointIndex
      : null

  const rowIndex =
    typeof point.i === 'number'
      ? point.i
      : Array.isArray(pair) && typeof pair[0] === 'number'
        ? pair[0]
        : null
  const colIndex =
    typeof point.j === 'number'
      ? point.j
      : Array.isArray(pair) && typeof pair[1] === 'number'
        ? pair[1]
        : null

  if (rowIndex === null || colIndex === null) return null
  return { rowIndex, colIndex }
}

function formatHeatmapValue(value: number | null) {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '—'
  return value.toFixed(4).replace(/\.?0+$/, '')
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
        return 'bg-success/10 text-success border-success/20';
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
