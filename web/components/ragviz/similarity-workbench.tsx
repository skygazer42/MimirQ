'use client'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { ragvizApi } from '@/lib/api';
import { formatApiError } from '@/lib/api-errors';
import type { RagvizSimilarityCollection, RagvizSimilarityCalculateResponse, RagvizSimilarityRequest } from '@/types';
import { Button } from '@/components/ui/button';
import { OperationalWorkspace, WorkspaceMetrics, WorkspaceNotice, workspaceStyles as ws } from '@/components/ui/operational-workspace';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog';
import { cn as joinClasses } from '@/lib/utils';
import { cn, detachPromise } from '@/lib/utils';
import { queryKeys } from '@/lib/query-keys';
import { buildSimilarityDiagnostics } from '@/components/ragviz/similarity-diagnostics';
import type { DiagnosticDecision, SimilarityDiagnosticsResult } from '@/components/ragviz/similarity-diagnostics';
import { COLOR_SCHEMES, createDefaultVisualConfig, generateUniqueLabels, isVisualConfig, type ColorSchemeKey, type MatrixButtonState, type SimilarityMatrixEntry, type VisualConfig } from '@/components/ragviz/similarity/color-schemes';
import { EmptyControlTile, Panel, RelatedListCard, RightEmptyInfoCard, StatsGrid, StatsItem } from '@/components/ragviz/similarity/display-components';
import { CollectionSelectorBlock, NumberField, isEmptyCollectionOption, similarityInputClass, similarityNativeSelectClass, type SelectOption } from '@/components/ragviz/similarity/form-controls';
import { SimilarityMainPanel, type MainViewMode } from '@/components/ragviz/similarity/panels';
import type { SelectedHeatmapCell } from '@/components/ragviz/similarity/heatmap-types';
import { applyMask, calculateDifferenceModeStatistics, calculateNormalModeStatistics, combineWithAND, combineWithOR, computeFinalMask, formatHeatmapValue, type SimilarityTopKAxis } from '@/components/ragviz/similarity/similarity-matrix-math';
import { collectionLabel, firstSimilarityDisplayString, formatPercent, getErrorMessage, importedPayloadEntries, isRecord, isSimilarityMatrixResult } from '@/components/ragviz/similarity/utils';
import { Eye, Filter, Grid3X3, Lock, Target } from '@/components/icons';
import { toast } from 'sonner';

export function RagvizSimilarityWorkbench() {
  const [panel, setPanel] = useState<'source' | 'operations' | 'controls' | 'statistics' | 'filters' | null>(null)
  const [calculationErrors, setCalculationErrors] = useState<string[]>([])
  const [xSelections, setXSelections] = useState<string[]>([''])
  const [ySelections, setYSelections] = useState<string[]>([''])
  const [xMaxItems, setXMaxItems] = useState<number>(30)
  const [yMaxItems, setYMaxItems] = useState<number>(30)
  const [isCalculating, setIsCalculating] = useState(false)
  const [calcProgress, setCalcProgress] = useState<{
    done: number
    total: number
  } | null>(null)
  const [colorScheme, setColorScheme] = useState<ColorSchemeKey>('viridis')
  const [tempSimilarityRange, setTempSimilarityRange] = useState<{
    min: number
    max: number
  }>({ min: 0, max: 1 })
  const [tempTopK, setTempTopK] = useState<{ value: number; axis: 'x' | 'y' }>({
    value: 0,
    axis: 'x',
  })
  const [mainView, setMainView] = useState<MainViewMode>('heatmap')
  const [diagnosticDecisions, setDiagnosticDecisions] = useState<
    Record<string, DiagnosticDecision>
  >({})
  const [selectedCell, setSelectedCell] = useState<SelectedHeatmapCell | null>(
    null
  )

  const importInputRef = useRef<HTMLInputElement>(null)

  const [results, setResults] = useState<SimilarityMatrixEntry[]>([])
  const [matrixButtons, setMatrixButtons] = useState<MatrixButtonState[]>([])
  const [primaryIndex, setPrimaryIndex] = useState<number | null>(null)
  const [subtractIndex, setSubtractIndex] = useState<number | null>(null)
  const [activeFilterIndices, setActiveFilterIndices] = useState<number[]>([])
  const [exclusiveIndex, setExclusiveIndex] = useState<number | null>(null)
  const [exportIndex, setExportIndex] = useState<number>(0)

  const collectionsQuery = useQuery({
    queryKey: queryKeys.ragviz.similarityCollections,
    queryFn: ragvizApi.listSimilarityCollections,
  })
  const collections: RagvizSimilarityCollection[] = useMemo(
    () => collectionsQuery.data?.collections || [],
    [collectionsQuery.data?.collections]
  )
  const collectionsLoading = collectionsQuery.isFetching
  const collectionsError = collectionsQuery.error
    ? getErrorMessage(collectionsQuery.error, '加载 collections 失败')
    : ''
  const refreshCollections = () => {
    collectionsQuery.refetch()
  }

  const availableCollectionOptions = useMemo(() => {
    return collections.map((c) => ({
      value: c.id,
      label: c.label,
      kind: c.kind,
      count: c.count,
    }))
  }, [collections])
  const collectionOptionById = useMemo(() => {
    return new Map(availableCollectionOptions.map((option) => [option.value, option]))
  }, [availableCollectionOptions])

  const resolveCollectionLabel = (id: string) => {
    const found = collections.find((c) => c.id === id)
    return found?.label || id
  }

  const calculateSimilarity = async () => {
    setCalculationErrors([])
    const xs = xSelections.map((x) => x.trim()).filter(Boolean)
    const ys = ySelections.map((y) => y.trim()).filter(Boolean)

    if (xs.length === 0) {
      setCalculationErrors(['请至少选择一个横坐标 Collection'])
      return
    }
    if (ys.length === 0) {
      setCalculationErrors(['请至少选择一个纵坐标 Collection'])
      return
    }
    const emptySelections: SelectOption[] = []
    for (const id of [...xs, ...ys]) {
      const option = collectionOptionById.get(id)
      if (option && isEmptyCollectionOption(option)) {
        emptySelections.push(option)
      }
    }

    if (emptySelections.length > 0) {
      toast.error(
        `所选 Collection 没有数据：${emptySelections
          .map((option) => option.label)
          .join('、')}`
      )
      return
    }

    const total = xs.length * ys.length
    setPanel(null)
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
          const res: RagvizSimilarityCalculateResponse =
            await ragvizApi.calculateSimilarityMatrix(payload)
          if (!res.success || !res.result) {
            throw new Error(res.error || '计算失败')
          }

          const visualConfig = createDefaultVisualConfig(
            res.result.x_available_fields,
            res.result.y_available_fields
          )
          nextResults.push({
            xCollectionId: x,
            yCollectionId: y,
            xCollectionLabel: resolveCollectionLabel(x),
            yCollectionLabel: resolveCollectionLabel(y),
            result: res.result,
            visualConfig,
          })
        } catch (error: unknown) {
          const msg = formatApiError(error, '计算失败')
          setCalculationErrors(current => [...current, `${resolveCollectionLabel(x)} / ${resolveCollectionLabel(y)}：${msg}`])
          toast.error(
            `${resolveCollectionLabel(x)} vs ${resolveCollectionLabel(y)}：${msg}`
          )
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

    const init: MatrixButtonState[] = entries.map(() => ({
      applyData: false,
      applyFilter: false,
      exclusive: false,
    }))
    init[0] = { applyData: true, applyFilter: true, exclusive: true }
    setMatrixButtons(init)
    setPrimaryIndex(0)
    setSubtractIndex(null)
    setActiveFilterIndices([0])
    setExclusiveIndex(0)
    setExportIndex(0)
  }

  const downloadJson = (filename: string, data: unknown) => {
    const blob = new Blob([JSON.stringify(data, null, 2)], {
      type: 'application/json;charset=utf-8',
    })
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
    const entries = importedPayloadEntries(raw)
    const out: SimilarityMatrixEntry[] = []
    for (const entry of entries) {
      if (!isRecord(entry)) continue
      const result = entry.result
      if (!isSimilarityMatrixResult(result)) continue
      const metadata = isRecord(result.metadata) ? result.metadata : null
      const xCollectionId = firstSimilarityDisplayString(
        entry.xCollectionId,
        entry.xCollection,
        metadata?.x_collection
      )
      const yCollectionId = firstSimilarityDisplayString(
        entry.yCollectionId,
        entry.yCollection,
        metadata?.y_collection
      )
      const xCollectionLabel = collectionLabel(entry.xCollectionLabel, xCollectionId, 'X')
      const yCollectionLabel = collectionLabel(entry.yCollectionLabel, yCollectionId, 'Y')
      const visualConfig: VisualConfig = isVisualConfig(entry.visualConfig)
        ? entry.visualConfig
        : createDefaultVisualConfig(
            result.x_available_fields || [],
            result.y_available_fields || []
          )

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
        toast.error(
          `导入失败：${file.name}（${getErrorMessage(error, 'JSON 解析错误')}）`
        )
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
      const appended = imported.map(() => ({
        applyData: false,
        applyFilter: false,
        exclusive: false,
      }))
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
  const rangeBounds = useMemo(
    () => (isDifferenceMode ? { min: -1, max: 1 } : { min: 0, max: 1 }),
    [isDifferenceMode]
  )

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
    if (a.length !== b.length || (a[0]?.length || 0) !== (b[0]?.length || 0))
      return a
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

  const uiSimilarityRange =
    exclusiveIndex !== null && activeVisualConfig
      ? activeVisualConfig.similarityRange
      : tempSimilarityRange
  const uiTopK =
    exclusiveIndex !== null && activeVisualConfig
      ? activeVisualConfig.filters.topK
      : tempTopK

  const effectiveMask = useMemo(() => {
    if (!displayMatrix || !primaryEntry) return null

    // Exclusive mode: only use the editing matrix config.
    if (exclusiveIndex !== null && activeVisualConfig) {
      return computeFinalMask(
        displayMatrix,
        activeVisualConfig.similarityRange,
        activeVisualConfig.filters.topK
      )
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
        if (
          shape.rows !== primaryShape.rows ||
          shape.cols !== primaryShape.cols
        )
          return null
        return computeFinalMask(
          entry.result.matrix,
          entry.visualConfig.similarityRange,
          entry.visualConfig.filters.topK
        )
      })
      .filter(Boolean) as boolean[][][]

    if (filterMasks.length > 0) {
      mask = combineWithOR(filterMasks)
    }

    const tempMask = computeFinalMask(
      displayMatrix,
      tempSimilarityRange,
      tempTopK
    )
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
    if (!effectiveMask) return displayMatrix
    return applyMask(displayMatrix, effectiveMask)
  }, [displayMatrix, effectiveMask])

  const selectedCellDetails = useMemo(() => {
    if (!selectedCell || !displayLabels || !displayMatrix) return null

    const rawValue =
      displayMatrix[selectedCell.rowIndex]?.[selectedCell.colIndex]
    if (typeof rawValue !== 'number' || !Number.isFinite(rawValue)) return null

    const maskedValue =
      maskedMatrix?.[selectedCell.rowIndex]?.[selectedCell.colIndex]
    const isVisible = effectiveMask
      ? Boolean(effectiveMask[selectedCell.rowIndex]?.[selectedCell.colIndex])
      : true

    return {
      ...selectedCell,
      xLabel:
        displayLabels.xLabels[selectedCell.colIndex] ||
        `X${selectedCell.colIndex + 1}`,
      yLabel:
        displayLabels.yLabels[selectedCell.rowIndex] ||
        `Y${selectedCell.rowIndex + 1}`,
      rawValue,
      maskedValue:
        typeof maskedValue === 'number' && Number.isFinite(maskedValue)
          ? maskedValue
          : null,
      isVisible,
    }
  }, [displayLabels, displayMatrix, effectiveMask, maskedMatrix, selectedCell])

  useEffect(() => {
    if (!selectedCell || !displayMatrix || !displayLabels) return

    const rowCount = displayMatrix.length
    const colCount = rowCount > 0 ? displayMatrix[0]?.length || 0 : 0
    const outOfBounds =
      selectedCell.rowIndex >= rowCount || selectedCell.colIndex >= colCount
    const labelsMissing =
      selectedCell.rowIndex >= displayLabels.yLabels.length ||
      selectedCell.colIndex >= displayLabels.xLabels.length

    if (outOfBounds || labelsMissing) {
      setSelectedCell(null)
    }
  }, [displayLabels, displayMatrix, selectedCell])

  const diagnostics = useMemo<SimilarityDiagnosticsResult | null>(() => {
    if (!primaryEntry || !displayLabels || isDifferenceMode) return null
    const matrixForDiagnostics = maskedMatrix ?? displayMatrix
    if (!matrixForDiagnostics) return null

    return buildSimilarityDiagnostics({
      matrix: matrixForDiagnostics.map((row) =>
        row.map((value) => (typeof value === 'number' ? value : 0))
      ),
      xItems: primaryEntry.result.x_data,
      yItems: primaryEntry.result.y_data,
      xLabels: displayLabels.xLabels,
      yLabels: displayLabels.yLabels,
      decisions: diagnosticDecisions,
    })
  }, [
    diagnosticDecisions,
    displayLabels,
    displayMatrix,
    isDifferenceMode,
    maskedMatrix,
    primaryEntry,
  ])

  const setDiagnosticDecision = (
    candidateId: string,
    decision: DiagnosticDecision | null
  ) => {
    setDiagnosticDecisions((prev) => {
      if (decision === null || prev[candidateId] === decision) {
        const next = { ...prev }
        delete next[candidateId]
        return next
      }
      return { ...prev, [candidateId]: decision }
    })
  }

  const topKAxisForStats: SimilarityTopKAxis = useMemo(() => {
    const topK = uiTopK
    if (!topK?.value) return 'none'
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
    const tempMask = computeFinalMask(
      displayMatrix,
      tempSimilarityRange,
      tempTopK
    )
    const isTempDefault =
      tempSimilarityRange.min === -1 &&
      tempSimilarityRange.max === 1 &&
      tempTopK.value === 0
    const currentMask = isTempDefault ? subtractMask : tempMask

    return calculateDifferenceModeStatistics(groundTruthMask, currentMask)
  }, [
    displayMatrix,
    primaryEntry,
    subtractEntry,
    tempSimilarityRange,
    tempTopK,
  ])

  const handleHeatmapCellSelect = useCallback((cell: SelectedHeatmapCell) => {
    setSelectedCell((prev) =>
      prev?.rowIndex === cell.rowIndex && prev.colIndex === cell.colIndex
        ? null
        : cell
    )
  }, [])

  const updateDisplayFields = (xField: string, yField: string) => {
    if (primaryIndex === null) return
    const target = exclusiveIndex ?? primaryIndex
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
    const clamp = (v: number) =>
      Math.max(rangeBounds.min, Math.min(rangeBounds.max, v))
    const min = clamp(range.min)
    const max = clamp(range.max)
    const next = { min: Math.min(min, max), max: Math.max(min, max) }

    if (exclusiveIndex !== null) {
      setResults((prev) =>
        prev.map((entry, idx) => {
          if (idx !== exclusiveIndex) return entry
          return {
            ...entry,
            visualConfig: { ...entry.visualConfig, similarityRange: next },
          }
        })
      )
      return
    }
    setTempSimilarityRange(next)
  }

  const updateTopK = (nextTopK: { value: number; axis: 'x' | 'y' }) => {
    const shape = primaryEntry
      ? matrixShape(primaryEntry)
      : { rows: 0, cols: 0 }
    const max = nextTopK.axis === 'x' ? shape.cols : shape.rows
    const clamped = {
      ...nextTopK,
      value: Math.max(0, Math.min(Number(nextTopK.value) || 0, max)),
    }
    if (exclusiveIndex !== null) {
      setResults((prev) =>
        prev.map((entry, idx) => {
          if (idx !== exclusiveIndex) return entry
          return {
            ...entry,
            visualConfig: { ...entry.visualConfig, filters: { topK: clamped } },
          }
        })
      )
      return
    }
    setTempTopK(clamped)
  }

  const matrixShape = (entry: SimilarityMatrixEntry | null) => {
    const m = entry?.result?.matrix || []
    const rows = m.length
    const cols = rows > 0 ? m[0]?.length || 0 : 0
    return { rows, cols }
  }

  const sameShape = (
    a: SimilarityMatrixEntry | null,
    b: SimilarityMatrixEntry | null
  ) => {
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
      prev.map((_, i) => ({
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
        return next.map((s, i) => ({
          ...s,
          applyData: i === primaryIndex || i === index,
        }))
      }

      // Replace subtract.
      setSubtractIndex(index)
      return next.map((s, i) => ({
        ...s,
        applyData: i === primaryIndex || i === index,
      }))
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
      return prev.includes(index)
        ? prev.filter((i) => i !== index)
        : [...prev, index]
    })
  }

  const heatmapSummaryMetrics = useMemo(() => {
    if (!primaryEntry) return []

    const rowCount = primaryEntry.result.y_data.length
    const colCount = primaryEntry.result.x_data.length
    const stats = primaryEntry.result.stats
    const totalPairs = Math.max(
      0,
      Number(stats?.total_pairs || rowCount * colCount || 0)
    )
    const highCount = typeof stats?.high_similarity_count === 'number' ? Math.max(0, stats.high_similarity_count) : null
    const highRatio = highCount !== null && totalPairs > 0 ? highCount / totalPairs : null

    return [
      { label: '矩阵规模', value: `${rowCount} × ${colCount}` },
      {
        label: '平均相似度',
        value: formatHeatmapValue(stats?.avg_similarity ?? null),
      },
      {
        label: '最高相似度',
        value: formatHeatmapValue(stats?.max_similarity ?? null),

      },
      { label: '高相似占比', value: highRatio === null ? '—' : formatPercent(highRatio) },
    ]
  }, [primaryEntry])

  const selectedCellNeighbors = useMemo(() => {
    if (!selectedCellDetails || !displayMatrix || !displayLabels) return null

    const selectedRow = displayMatrix[selectedCellDetails.rowIndex] || []
    const topX = selectedRow
      .map((value, index) => ({
        label: displayLabels.xLabels[index] || `X${index + 1}`,
        value,
        index,
      }))
      .filter(
        (item) =>
          item.index !== selectedCellDetails.colIndex &&
          Number.isFinite(item.value)
      )
      .sort((left, right) => right.value - left.value)
      .slice(0, 5)

    const topY = displayMatrix
      .map((row, index) => ({
        label: displayLabels.yLabels[index] || `Y${index + 1}`,
        value: row[selectedCellDetails.colIndex],
        index,
      }))
      .filter(
        (item) =>
          item.index !== selectedCellDetails.rowIndex &&
          Number.isFinite(item.value)
      )
      .sort((left, right) => right.value - left.value)
      .slice(0, 5)

    return { topX, topY }
  }, [displayLabels, displayMatrix, selectedCellDetails])


  const titles = { source: '数据源与计算', operations: '导入与导出', controls: '矩阵管理', statistics: selectedCellDetails ? '单元详情与统计' : '矩阵统计', filters: '显示与筛选' }
  return <OperationalWorkspace title="向量相似度诊断" icon="rag-visualization" mode="canvas" context={primaryEntry ? `${primaryEntry.xCollectionLabel} / ${primaryEntry.yCollectionLabel}` : '选择横轴与纵轴数据源'} actions={<><Button variant="outline" disabled={isCalculating} onClick={() => setPanel('operations')}>导入与导出</Button><Button disabled={isCalculating} onClick={() => setPanel('source')}>{isCalculating ? `正在计算 ${calcProgress?.done ?? 0}/${calcProgress?.total ?? 0}` : '数据源与计算'}</Button></>} toolbar={<>
    <div role="group" aria-label="相似度视图" className="flex gap-2"><Button variant={mainView === 'heatmap' ? 'secondary' : 'ghost'} onClick={() => setMainView('heatmap')}>相似度矩阵</Button><Button variant={mainView === 'diagnostics' ? 'secondary' : 'ghost'} disabled={!primaryEntry || !displayLabels || isDifferenceMode} onClick={() => setMainView('diagnostics')}>向量诊断</Button></div>
    <Button variant="ghost" disabled={!results.length} onClick={() => setPanel('controls')}>矩阵管理 {results.length || ''}</Button><Button variant="ghost" disabled={!primaryEntry} onClick={() => setPanel('filters')}>显示与筛选</Button><Button variant="ghost" disabled={!primaryEntry} onClick={() => setPanel('statistics')}>统计与详情</Button>
    <label className="ml-auto flex items-center gap-2 text-[13px]">色阶<select aria-label="矩阵色阶" value={colorScheme} onChange={event => setColorScheme(event.target.value as ColorSchemeKey)} className="h-9 rounded-md border border-input bg-background px-3">{COLOR_SCHEMES.map(scheme => <option key={scheme.key} value={scheme.key}>{scheme.label}</option>)}</select></label>
  </>}>
    {calculationErrors.length ? <div className="px-4">{calculationErrors.map((message, index) => <WorkspaceNotice key={`${index}:${message}`} retry={() => setPanel('source')} retryLabel="检查数据源">{message}</WorkspaceNotice>)}</div> : null}
    {heatmapSummaryMetrics.length ? <div className="px-4 md:px-6"><WorkspaceMetrics items={heatmapSummaryMetrics.map(metric => ({ label: metric.label, value: metric.value }))} /></div> : null}
    <div className="min-h-0 min-w-0 flex-1 overflow-auto" aria-label="相似度工作区">
      {primaryEntry ? <div className="h-full min-h-[560px] min-w-[640px]"><SimilarityMainPanel
              primaryEntry={primaryEntry}
              displayMatrix={displayMatrix}
              displayLabels={displayLabels}
              mainView={mainView}
              diagnostics={diagnostics}
              maskedMatrix={maskedMatrix}
              colorScheme={colorScheme}
              isDifferenceMode={isDifferenceMode}
              onDecisionChange={setDiagnosticDecision}
              onCellSelect={cell => { handleHeatmapCellSelect(cell); setPanel('statistics') }}
            /></div> : <div className="px-6 py-8"><div className={ws.empty}><h2>{isCalculating ? '正在计算相似度矩阵' : '尚未生成相似度矩阵'}</h2><p>{isCalculating ? '计算完成后可查看单元值、筛选结果和导出数据。' : '选择横轴、纵轴数据源后计算，也可导入已有矩阵。'}</p>{!isCalculating ? <div className="flex flex-wrap gap-3"><Button onClick={() => setPanel('source')}>选择数据源</Button><Button variant="outline" onClick={() => setPanel('operations')}>导入矩阵</Button></div> : null}</div></div>}
    </div>
    <Dialog open={panel !== null} onOpenChange={open => { if (!open) setPanel(null) }}><DialogContent aria-describedby={undefined} className={joinClasses(ws.dialog, panel === 'statistics' || panel === 'controls' ? ws.wideDialog : '')}><DialogHeader className={ws.dialogHeader}><DialogTitle>{panel ? titles[panel] : ''}</DialogTitle></DialogHeader><div className={ws.dialogBody}>
      {panel === 'source' ? <fieldset disabled={isCalculating} className="space-y-5">
        {collectionsError ? <WorkspaceNotice retry={refreshCollections}>{collectionsError}</WorkspaceNotice> : null}
        <div className="flex items-center justify-between gap-3"><p className="text-[13px] text-muted-foreground">{collectionsLoading ? '正在读取可用数据源…' : `可用数据源 ${collections.length}`}</p><Button variant="ghost" disabled={collectionsLoading} onClick={refreshCollections}>重新读取数据源</Button></div>
        <div className="grid gap-8 sm:grid-cols-2"><section className="space-y-4"><h2 className={ws.sectionTitle}>横轴</h2><CollectionSelectorBlock label="横轴数据源" selections={xSelections} onChange={setXSelections} options={availableCollectionOptions} /><NumberField label="横轴最大项目数" value={xMaxItems} onChange={setXMaxItems} min={10} max={500} /></section><section className="space-y-4"><h2 className={ws.sectionTitle}>纵轴</h2><CollectionSelectorBlock label="纵轴数据源" selections={ySelections} onChange={setYSelections} options={availableCollectionOptions} /><NumberField label="纵轴最大项目数" value={yMaxItems} onChange={setYMaxItems} min={10} max={500} /></section></div>
        {calculationErrors.length ? <p className="text-[13px] text-destructive">{calculationErrors.join('；')}</p> : null}
      </fieldset> : null}
      {panel === 'operations' ? <Panel title="">
                  <div className="space-y-3">
                    <p className="text-xs text-muted-foreground">
                      支持导入/导出当前矩阵数据（用于复现、分享、离线分析）。
                    </p>

                    <div className="space-y-2">
                      <div className="text-xs font-medium text-foreground/80">
                        选择要导出的图表
                      </div>
                      <select
                        className={similarityNativeSelectClass}
                        value={String(exportIndex)}
                        onChange={(e) =>
                          setExportIndex(Number(e.target.value) || 0)
                        }
                        disabled={results.length === 0}
                      >
                        {results.length === 0 ? (
                          <option value="0">请先计算相似度</option>
                        ) : (
                          results.map((r, idx) => (
                            <option
                              key={`${r.xCollectionId}__${r.yCollectionId}`}
                              value={idx}
                            >
                              {idx + 1}. {r.xCollectionLabel} vs{' '}
                              {r.yCollectionLabel}
                            </option>
                          ))
                        )}
                      </select>
                    </div>

                    <div className="grid grid-cols-2 gap-2">
                      <Button
                        variant="outline"
                        onClick={exportOne}
                        disabled={results.length === 0}
                      >
                        导出JSON
                      </Button>
                      <Button
                        variant="outline"
                        onClick={exportAll}
                        disabled={results.length === 0}
                      >
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
                </Panel> : null}
      {panel === 'controls' ? <Panel title="">
                {results.length === 0 ? (
                  <div className="rounded-[1.25rem] border border-border/34 bg-card/58 p-3.5 text-center shadow-[inset_0_1px_0_hsl(var(--card)/0.55)]">
                    <div className="text-[13px] font-semibold text-foreground/84">
                      等待矩阵结果
                    </div>
                    <p className="mt-1 text-[11px] leading-4 text-muted-foreground/64">
                      先在上方选择两个
                      collections，再生成热力图并在这里切换主图、筛选器和独占模式。
                    </p>
                    <div className="mt-4 grid grid-cols-3 gap-2">
                      <EmptyControlTile
                        icon={<Grid3X3 className="size-5" />}
                        label="主图"
                      />
                      <EmptyControlTile
                        icon={<Filter className="size-5" />}
                        label="筛选器"
                      />
                      <EmptyControlTile
                        icon={<Target className="size-5" />}
                        label="独占模式"
                      />
                    </div>
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
                              isPrimary
                                ? 'border-primary/50 bg-primary/5'
                                : 'border-border bg-background'
                            )}
                          >
                            <div className="flex-1 min-w-0">
                              <div className="text-xs font-medium truncate">
                                {entry.xCollectionLabel}{' '}
                                <span className="text-muted-foreground">
                                  vs
                                </span>{' '}
                                {entry.yCollectionLabel}
                              </div>
                              <div className="text-[11px] text-muted-foreground flex items-center gap-2">
                                <span>
                                  {matrixShape(entry).rows}×
                                  {matrixShape(entry).cols}
                                </span>
                                {isPrimary ? (
                                  <span className="px-1.5 py-0.5 rounded bg-primary/10 text-primary">
                                    主
                                  </span>
                                ) : null}
                                {isSubtract ? (
                                  <span className="px-1.5 py-0.5 rounded bg-warning/10 text-warning">
                                    减
                                  </span>
                                ) : null}
                                {isExclusive ? (
                                  <span className="px-1.5 py-0.5 rounded bg-info/10 text-info">
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
                                variant={
                                  btn?.applyFilter ? 'default' : 'outline'
                                }
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
                                onClick={() =>
                                  btn?.exclusive
                                    ? exitExclusiveMode()
                                    : enterExclusiveMode(idx)
                                }
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
              </Panel> : null}
      {panel === 'statistics' ? <Panel title="" subtitle="数据概览与交互信息">
                  {(() => {
                    if (!primaryEntry || !effectiveMask) {
                      return (
                        <RightEmptyInfoCard
                          title="选中单元"
                          icon={<Grid3X3 className="size-5" />}
                          description="点击热力图任意单元后，在这里查看坐标、相似度和 Top 相关项。"
                        />
                      )
                    } else if (isDifferenceMode && differenceStats) {
                      return (
                        <StatsGrid>
                          <StatsItem
                            label="True Positive"
                            value={differenceStats.truePositive}
                            tone="success"
                          />
                          <StatsItem
                            label="True Negative"
                            value={differenceStats.trueNegative}
                            tone="muted"
                          />
                          <StatsItem
                            label="False Positive"
                            value={differenceStats.falsePositive}
                            tone="warning"
                          />
                          <StatsItem
                            label="False Negative"
                            value={differenceStats.falseNegative}
                            tone="danger"
                          />
                          <StatsItem
                            label="上下文召回率"
                            value={`${(differenceStats.contextRecall * 100).toFixed(2)}%`}
                            tone="info"
                          />
                          <StatsItem
                            label="上下文精度"
                            value={`${(differenceStats.contextPrecision * 100).toFixed(2)}%`}
                            tone="info"
                          />
                        </StatsGrid>
                      )
                    } else if (normalStats) {
                      return (
                        <StatsGrid>
                          <StatsItem
                            label="当前显示对比数"
                            value={`${normalStats.currentDisplayCount} / ${normalStats.totalCount}`}
                          />
                          <StatsItem
                            label="斜对角线对比数"
                            value={`${normalStats.diagonalTrueCount} / ${normalStats.diagonalTotalCount}`}
                          />
                          {normalStats.topKAxis === 'none' ? null : (
                            <StatsItem
                              label={`缺失匹配(${normalStats.topKAxis === 'x' ? '横轴' : '纵轴'})`}
                              value={normalStats.missingMatchCount}
                              tone={
                                normalStats.missingMatchCount > 0
                                  ? 'warning'
                                  : 'muted'
                              }
                            />
                          )}
                        </StatsGrid>
                      )
                    } else {
                      return (
                        <p className="text-xs text-muted-foreground">
                          暂无统计数据
                        </p>
                      )
                    }
                  })()}

                  {mainView === 'heatmap' && primaryEntry ? (
                    <div className="mt-4 border-t border-sidebar-border/60 pt-4">
                      <div className="mb-2 flex items-center justify-between gap-2">
                        <div className="text-[11px] font-medium uppercase tracking-[0.12em] text-muted-foreground">
                          选中单元
                        </div>
                        {selectedCellDetails ? (
                          <Button
                            variant="ghost"
                            size="sm"
                            className="h-7 px-2 text-[11px]"
                            onClick={() => setSelectedCell(null)}
                          >
                            清除
                          </Button>
                        ) : null}
                      </div>

                      {selectedCellDetails ? (
                        <div className="space-y-2">
                          <div className="border-b border-border py-4">
                            <div className="grid grid-cols-2 gap-3">
                              <div className="min-w-0">
                                <div className="text-[11px] font-medium text-muted-foreground">
                                  X（列）
                                </div>
                                <div className="mt-1 truncate text-sm font-semibold text-foreground">
                                  {selectedCellDetails.xLabel}
                                </div>
                              </div>
                              <div className="min-w-0">
                                <div className="text-[11px] font-medium text-muted-foreground">
                                  Y（行）
                                </div>
                                <div className="mt-1 truncate text-sm font-semibold text-foreground">
                                  {selectedCellDetails.yLabel}
                                </div>
                              </div>
                            </div>

                            <div className="mt-4 grid grid-cols-[1fr_auto] items-end gap-3">
                              <div>
                                <div className="text-[11px] font-medium text-muted-foreground">
                                  {isDifferenceMode ? '差值' : '相似度'}
                                </div>
                                <div
                                  className={cn(
                                    'mt-1 text-3xl font-semibold tabular-nums',
                                    selectedCellDetails.rawValue >= 0.8
                                      ? 'text-destructive'
                                      : 'text-foreground'
                                  )}
                                >
                                  {formatHeatmapValue(
                                    selectedCellDetails.rawValue
                                  )}
                                </div>
                              </div>
                              <div
                                className={cn(
                                  'inline-flex items-center rounded-full border px-2 py-0.5 text-[11px]',
                                  selectedCellDetails.isVisible
                                    ? 'border-success/25 bg-success/10 text-success'
                                    : 'border-warning/25 bg-warning/10 text-warning'
                                )}
                              >
                                {selectedCellDetails.isVisible
                                  ? '显示中'
                                  : '已过滤'}
                              </div>
                            </div>
                          </div>

                          <div className="grid grid-cols-2 gap-2">
                            <StatsItem
                              label="当前显示"
                              value={
                                selectedCellDetails.maskedValue === null
                                  ? '隐藏'
                                  : formatHeatmapValue(
                                      selectedCellDetails.maskedValue
                                    )
                              }
                              tone={
                                selectedCellDetails.maskedValue === null
                                  ? 'warning'
                                  : 'success'
                              }
                            />
                            <StatsItem
                              label="行索引"
                              value={selectedCellDetails.rowIndex + 1}
                              tone="muted"
                            />
                            <StatsItem
                              label="列索引"
                              value={selectedCellDetails.colIndex + 1}
                              tone="muted"
                            />
                          </div>

                          {selectedCellNeighbors ? (
                            <div className="space-y-2 pt-1">
                              <RelatedListCard
                                title={`Top 相关（Y 轴 · ${selectedCellDetails.yLabel}）`}
                                items={selectedCellNeighbors.topX}
                              />
                              <RelatedListCard
                                title={`Top 相关（X 轴 · ${selectedCellDetails.xLabel}）`}
                                items={selectedCellNeighbors.topY}
                              />
                            </div>
                          ) : null}
                        </div>
                      ) : (
                        <div className="rounded-[1.1rem] border border-dashed border-border/36 bg-card/54 p-4 text-xs leading-5 text-muted-foreground/70">
                          点击热力图任意单元后，在这里查看坐标、相似度和 Top
                          相关项。
                        </div>
                      )}
                    </div>
                  ) : null}
                </Panel> : null}
      {panel === 'filters' ? <Panel title="">
                  {primaryEntry ? (
                    <div className="space-y-5">
                      <div className="space-y-2">
                        <div className="text-xs font-medium text-foreground/80">
                          横坐标显示字段
                        </div>
                        <select
                          className={similarityNativeSelectClass}
                          value={primaryEntry.visualConfig.displayFields.xField}
                          onChange={(e) =>
                            updateDisplayFields(
                              e.target.value,
                              primaryEntry.visualConfig.displayFields.yField
                            )
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
                        <div className="text-xs font-medium text-foreground/80">
                          纵坐标显示字段
                        </div>
                        <select
                          className={similarityNativeSelectClass}
                          value={primaryEntry.visualConfig.displayFields.yField}
                          onChange={(e) =>
                            updateDisplayFields(
                              primaryEntry.visualConfig.displayFields.xField,
                              e.target.value
                            )
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
                        <div className="text-xs font-medium text-foreground/80">
                          相似度阈值范围
                        </div>
                        <div className="space-y-2">
                          <div className="flex items-center gap-2">
                            <input
                              type="range" style={{ accentColor: 'hsl(var(--primary))' }}
                              min={rangeBounds.min}
                              max={rangeBounds.max}
                              step={0.01}
                              value={uiSimilarityRange.min}
                              onChange={(e) =>
                                updateSimilarityRange({
                                  min: Number(e.target.value),
                                  max: uiSimilarityRange.max,
                                })
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
                                updateSimilarityRange({
                                  min: Number(e.target.value),
                                  max: uiSimilarityRange.max,
                                })
                              }
                              className={cn(similarityInputClass, 'w-20')}
                            />
                          </div>
                          <div className="flex items-center gap-2">
                            <input
                              type="range" style={{ accentColor: 'hsl(var(--primary))' }}
                              min={rangeBounds.min}
                              max={rangeBounds.max}
                              step={0.01}
                              value={uiSimilarityRange.max}
                              onChange={(e) =>
                                updateSimilarityRange({
                                  min: uiSimilarityRange.min,
                                  max: Number(e.target.value),
                                })
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
                                updateSimilarityRange({
                                  min: uiSimilarityRange.min,
                                  max: Number(e.target.value),
                                })
                              }
                              className={cn(similarityInputClass, 'w-20')}
                            />
                          </div>
                        </div>
                      </div>

                      <div className="space-y-2">
                        <div className="text-xs font-medium text-foreground/80">
                          Top-K 筛选
                        </div>
                        <div className="flex items-center gap-2">
                          <input
                            type="range" style={{ accentColor: 'hsl(var(--primary))' }}
                            min={0}
                            max={Math.max(
                              0,
                              uiTopK.axis === 'x'
                                ? matrixShape(primaryEntry).cols
                                : matrixShape(primaryEntry).rows
                            )}
                            step={1}
                            value={uiTopK.value}
                            onChange={(e) =>
                              updateTopK({
                                ...uiTopK,
                                value: Number(e.target.value),
                              })
                            }
                            className="flex-1"
                          />
                          <input
                            type="number"
                            min={0}
                            max={Math.max(
                              0,
                              uiTopK.axis === 'x'
                                ? matrixShape(primaryEntry).cols
                                : matrixShape(primaryEntry).rows
                            )}
                            step={1}
                            value={uiTopK.value}
                            onChange={(e) =>
                              updateTopK({
                                ...uiTopK,
                                value: Number(e.target.value),
                              })
                            }
                            className={cn(similarityInputClass, 'w-20')}
                          />
                        </div>
                        <div className="flex items-center gap-2">
                          <Button
                            variant={
                              uiTopK.axis === 'x' ? 'default' : 'outline'
                            }
                            size="sm"
                            onClick={() => updateTopK({ ...uiTopK, axis: 'x' })}
                            className="flex-1"
                          >
                            横轴Top-K
                          </Button>
                          <Button
                            variant={
                              uiTopK.axis === 'y' ? 'default' : 'outline'
                            }
                            size="sm"
                            onClick={() => updateTopK({ ...uiTopK, axis: 'y' })}
                            className="flex-1"
                          >
                            纵轴Top-K
                          </Button>
                        </div>
                        <p className="text-[11px] text-muted-foreground">
                          当前：Top-{uiTopK.value}（
                          {(() => {
                            if (uiTopK.value === 0) {
                              return '显示全部'
                            } else if (uiTopK.axis === 'x') {
                              return '按行取 Top-K'
                            } else {
                              return '按列取 Top-K'
                            }
                          })()}
                          ）
                        </p>
                      </div>
                    </div>
                  ) : (
                    <RightEmptyInfoCard
                      title=""
                      icon={<Filter className="size-5" />}
                      description="请先生成相似度矩阵后，在这里选择一个主图矩阵。"
                    />
                  )}
                </Panel> : null}
    </div><DialogFooter className={ws.dialogFooter}><Button variant="outline" onClick={() => setPanel(null)}>完成</Button>{panel === 'source' ? <Button disabled={isCalculating || collectionsLoading || !xSelections.some(Boolean) || !ySelections.some(Boolean)} onClick={() => { void calculateSimilarity() }}>计算相似度</Button> : null}</DialogFooter></DialogContent></Dialog>
  </OperationalWorkspace>
}
