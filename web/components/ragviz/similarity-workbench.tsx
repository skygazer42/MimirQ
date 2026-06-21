'use client'

import type { MouseEvent as ReactMouseEvent, ReactNode } from 'react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ragvizApi } from '@/lib/api'
import { SimilarityDiagnosticsGraph } from '@/components/ragviz/similarity-diagnostics-graph'
import type {
  RagvizSimilarityCollection,
  RagvizSimilarityCalculateResponse,
  RagvizSimilarityMatrixResult,
  RagvizSimilarityRequest,
} from '@/types'
import { Button } from '@/components/ui/button'
import { PageHeader } from '@/components/ui/page-header'
import { PageLoading } from '@/components/ui/page-loading'
import { readClientStorage, writeClientStorage } from '@/lib/client-storage'
import { cn, detachPromise } from '@/lib/utils'
import { queryKeys } from '@/lib/query-keys'
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
  Play,
  RefreshCw,
  Target,
} from 'lucide-react'
import { toast } from 'sonner'

type LeftTopPanel = 'dataSource' | 'operations'
type MainViewMode = 'heatmap' | 'diagnostics'
type RightTopPanel = 'statistics' | null
type RightBottomPanel = 'filters' | null
type JsonRecord = Record<string, unknown>
type SelectedHeatmapCell = { rowIndex: number; colIndex: number }
type SimilarityTopKAxis = 'x' | 'y' | 'none'
type DisplayLabels = { xLabels: string[]; yLabels: string[] }
type SimilarityDisplayMatrix = Array<Array<number | null>>
type PlotlyColorScale = string | Array<[number, string]>

type PlotlyTrace = {
  type: 'heatmap'
  z: Array<Array<number | null>>
  x: string[]
  y: string[]
  colorscale: PlotlyColorScale
  zmin: number
  zmax: number
  text?: string[][]
  texttemplate?: string
  textfont?: { color: string; size: number }
  showscale?: boolean
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
  displayModeBar?: boolean
}

type PlotlyLike = {
  react: (
    element: HTMLDivElement,
    data: PlotlyTrace[],
    layout: PlotlyLayout,
    config: PlotlyConfig
  ) => void
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
  on?: (
    eventName: 'plotly_click',
    handler: (event: PlotlyClickEvent) => void
  ) => void
  removeAllListeners?: (eventName?: string) => void
}

function isRecord(value: unknown): value is JsonRecord {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

function isPlotlyLike(value: unknown): value is PlotlyLike {
  if (!value || (typeof value !== 'object' && typeof value !== 'function'))
    return false
  const maybe = value as { react?: unknown; purge?: unknown }
  return typeof maybe.react === 'function' && typeof maybe.purge === 'function'
}

function similarityDisplayString(value: unknown): string {
  if (typeof value === 'string') return value.trim()
  if (
    typeof value === 'number' ||
    typeof value === 'boolean' ||
    typeof value === 'bigint'
  ) {
    return String(value)
  }
  return ''
}

function firstSimilarityDisplayString(...values: unknown[]): string {
  for (const value of values) {
    const text = similarityDisplayString(value)
    if (text) return text
  }
  return ''
}

function isSimilarityMatrixResult(
  value: unknown
): value is RagvizSimilarityMatrixResult {
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
  if (error instanceof Error && error.message.trim())
    return error.message.trim()
  const text = similarityDisplayString(error)
  return text || fallback
}

function importedPayloadEntries(raw: unknown): unknown[] {
  if (!raw) return []
  if (Array.isArray(raw)) return raw
  if (isRecord(raw) && Array.isArray(raw.entries)) return raw.entries
  return [raw]
}

function collectionLabel(
  explicitLabel: unknown,
  collectionId: string,
  fallback: string
) {
  return firstSimilarityDisplayString(explicitLabel, collectionId, fallback)
}

function metricToneClass(tone?: string) {
  return tone === 'danger' ? 'text-destructive' : 'text-foreground'
}

function emptyMatrixSwatchClass(index: number) {
  if (index % 4 === 0) return 'bg-blue-500/80'
  if (index % 3 === 0) return 'bg-blue-400/55'
  return 'bg-blue-200/80'
}

function emptyMatrixCellClass(index: number) {
  if (index % 9 === 0) return 'bg-blue-500/70'
  if (index % 5 === 0) return 'bg-blue-300/75'
  return 'bg-blue-100'
}

function diagnosticCandidateStatusClass(isDisabled: boolean, isMarked: boolean) {
  if (isDisabled) return 'border-border bg-muted text-muted-foreground'
  if (isMarked) {
    return 'border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-900/40 dark:bg-amber-900/20 dark:text-amber-200'
  }
  return 'border-orange-200 bg-orange-50 text-orange-700 dark:border-orange-900/40 dark:bg-orange-900/20 dark:text-orange-200'
}

function diagnosticCandidateStatusLabel(isDisabled: boolean, isMarked: boolean) {
  if (isDisabled) return '已禁用'
  if (isMarked) return '待审'
  return '待处理'
}

function pickPlotlyModule(modUnknown: unknown): PlotlyLike | null {
  const mod = isRecord(modUnknown) ? modUnknown : null
  if (isPlotlyLike(mod?.default)) return mod.default
  if (isPlotlyLike(modUnknown)) return modUnknown
  return null
}

function uniqueLabelRaw(item: Record<string, unknown>, field: string) {
  if (!field) return ''
  return similarityDisplayString(item[field])
}

function compactAxisLabel(value: string, maxLength = 42) {
  const text = value.trim()
  if (text.length <= maxLength) return text
  return `${text.slice(0, Math.max(1, maxLength - 3))}...`
}

function oneBasedItemNumber(value: unknown) {
  return typeof value === 'number' && Number.isFinite(value)
    ? Math.max(1, Math.trunc(value) + 1)
    : null
}

function axisLabelForItem(item: Record<string, unknown>, field: string) {
  const fieldText = uniqueLabelRaw(item, field)
  const documentText = firstSimilarityDisplayString(item.document, item.name)
  const chunkNumber = oneBasedItemNumber(item.chunk_index)
  if (chunkNumber !== null) {
    const base = documentText || fieldText || `chunk ${chunkNumber}`
    return `${compactAxisLabel(base, 34)} · chunk ${chunkNumber}`
  }

  const questionNumber = oneBasedItemNumber(item.order_id)
  if (questionNumber !== null && fieldText) {
    return `Q${questionNumber} · ${compactAxisLabel(fieldText, 44)}`
  }

  return compactAxisLabel(fieldText)
}

function heatmapPointPair(point: PlotlyClickPoint): number[] | null {
  if (Array.isArray(point.pointNumber)) return point.pointNumber
  if (Array.isArray(point.pointIndex)) return point.pointIndex
  return null
}

function heatmapPointCoordinate(
  directValue: unknown,
  pair: number[] | null,
  pairIndex: number
) {
  if (typeof directValue === 'number') return directValue
  if (Array.isArray(pair) && typeof pair[pairIndex] === 'number') {
    return pair[pairIndex]
  }
  return null
}

type SimilarityMainPanelProps = Readonly<{
  primaryEntry: SimilarityMatrixEntry | null
  displayMatrix: number[][] | null
  displayLabels: DisplayLabels | null
  mainView: MainViewMode
  diagnostics: SimilarityDiagnosticsResult | null
  maskedMatrix: SimilarityDisplayMatrix | null
  colorScheme: ColorSchemeKey
  isDifferenceMode: boolean
  onDecisionChange: (candidateId: string, decision: DiagnosticDecision | null) => void
  onCellSelect: (cell: SelectedHeatmapCell) => void
}>

function SimilarityMainPanel({
  primaryEntry,
  displayMatrix,
  displayLabels,
  mainView,
  diagnostics,
  maskedMatrix,
  colorScheme,
  isDifferenceMode,
  onDecisionChange,
  onCellSelect,
}: SimilarityMainPanelProps) {
  if (!primaryEntry || !displayMatrix || !displayLabels) {
    return (
      <div className="flex h-full items-start justify-center px-8 pb-14 pt-0">
        <SimilarityEmptyState />
      </div>
    )
  }

  if (mainView === 'diagnostics') {
    return (
      <SimilarityDiagnosticsPanel
        diagnostics={diagnostics}
        onDecisionChange={onDecisionChange}
      />
    )
  }

  return (
    <SimilarityHeatmapPanel
      primaryEntry={primaryEntry}
      displayMatrix={displayMatrix}
      displayLabels={displayLabels}
      maskedMatrix={maskedMatrix}
      colorScheme={colorScheme}
      isDifferenceMode={isDifferenceMode}
      onCellSelect={onCellSelect}
    />
  )
}

function SimilarityDiagnosticsPanel({
  diagnostics,
  onDecisionChange,
}: Readonly<{
  diagnostics: SimilarityDiagnosticsResult | null
  onDecisionChange: (
    candidateId: string,
    decision: DiagnosticDecision | null
  ) => void
}>) {
  if (diagnostics) {
    return (
      <SimilarityDiagnosticsView
        diagnostics={diagnostics}
        onDecisionChange={onDecisionChange}
      />
    )
  }

  return (
    <div className="flex h-full items-center justify-center px-6">
      <div className="rounded-2xl border border-dashed border-sidebar-border/60 bg-muted/30 px-6 py-8 text-center">
        <div className="text-sm font-semibold text-foreground">
          向量诊断暂不可用
        </div>
        <p className="mt-2 text-sm text-muted-foreground">
          当前处于差值模式，3D 投影预览和异常点标注只在单个主图矩阵上启用。
        </p>
      </div>
    </div>
  )
}

function SimilarityHeatmapPanel({
  primaryEntry,
  displayMatrix,
  displayLabels,
  maskedMatrix,
  colorScheme,
  isDifferenceMode,
  onCellSelect,
}: Readonly<{
  primaryEntry: SimilarityMatrixEntry
  displayMatrix: number[][]
  displayLabels: DisplayLabels
  maskedMatrix: SimilarityDisplayMatrix | null
  colorScheme: ColorSchemeKey
  isDifferenceMode: boolean
  onCellSelect: (cell: SelectedHeatmapCell) => void
}>) {
  return (
    <div className="h-full overflow-auto p-4">
      <section className="flex min-h-[560px] flex-col overflow-hidden rounded-[1.75rem] border border-border/38 bg-card/76 shadow-[0_24px_70px_-58px_hsl(var(--foreground)/0.42),inset_0_1px_0_hsl(var(--card)/0.7)]">
        <div className="flex items-center justify-between gap-3 border-b border-border/34 bg-muted/[0.10] px-4 py-3">
          <div className="min-w-0">
            <div className="truncate text-sm font-semibold text-foreground">
              {primaryEntry.xCollectionLabel}（X 轴）
            </div>
            <div className="mt-0.5 text-[11px] text-muted-foreground">
              {displayLabels.xLabels.length} 项 × {displayLabels.yLabels.length} 项
            </div>
          </div>
          <div className="rounded-full border border-border/34 bg-background/44 px-2.5 py-1 text-[11px] font-medium text-muted-foreground/70">
            点击单元格查看右侧统计
          </div>
        </div>

        <div className="min-h-0 flex-1 p-3">
          <PlotlyHeatmap
            matrix={maskedMatrix ?? displayMatrix}
            xLabels={displayLabels.xLabels}
            yLabels={displayLabels.yLabels}
            colorScheme={colorScheme}
            isDifference={isDifferenceMode}
            onCellSelect={onCellSelect}
          />
        </div>

        <HeatmapScaleLegend
          colorScheme={colorScheme}
          isDifference={isDifferenceMode}
        />
      </section>
    </div>
  )
}

export function RagvizSimilarityWorkbench() {
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

  const [leftTopPanel, setLeftTopPanel] = useState<LeftTopPanel>('dataSource')
  const [rightTopPanel, setRightTopPanel] =
    useState<RightTopPanel>('statistics')
  const [rightBottomPanel, setRightBottomPanel] =
    useState<RightBottomPanel>('filters')
  const [isLeftSidebarCollapsed, setIsLeftSidebarCollapsed] = useState(false)
  const [isRightSidebarCollapsed, setIsRightSidebarCollapsed] = useState(false)

  const [leftWidth, setLeftWidth] = useState<number>(312)
  const [rightWidth, setRightWidth] = useState<number>(248)
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
          const msg = getErrorMessage(error, '计算失败')
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
      writeClientStorage(
        'ragviz_similarity_layout_v2',
        JSON.stringify(payload)
      )
    } catch {
      // ignore
    }
  }, [
    isLeftSidebarCollapsed,
    isRightSidebarCollapsed,
    leftWidth,
    rightWidth,
    leftTopHeight,
    rightTopHeight,
  ])

  useEffect(() => {
    try {
      const raw = readClientStorage('ragviz_similarity_layout_v2')
      if (!raw) return
      const parsed = JSON.parse(raw)
      if (typeof parsed.leftWidth === 'number') setLeftWidth(parsed.leftWidth)
      if (typeof parsed.rightWidth === 'number')
        setRightWidth(parsed.rightWidth)
      if (typeof parsed.leftTopHeight === 'number')
        setLeftTopHeight(parsed.leftTopHeight)
      if (typeof parsed.rightTopHeight === 'number')
        setRightTopHeight(parsed.rightTopHeight)
      if (typeof parsed.isLeftSidebarCollapsed === 'boolean')
        setIsLeftSidebarCollapsed(parsed.isLeftSidebarCollapsed)
      if (typeof parsed.isRightSidebarCollapsed === 'boolean')
        setIsRightSidebarCollapsed(parsed.isRightSidebarCollapsed)
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

  const startResizeSidebar = (
    side: 'left' | 'right',
    event: ReactMouseEvent
  ) => {
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
    const container =
      side === 'left' ? leftSidebarRef.current : rightSidebarRef.current
    if (!container) return
    const rect = container.getBoundingClientRect()
    const startY = event.clientY
    const initial =
      side === 'left'
        ? (leftTopHeight ?? rect.height * 0.5)
        : (rightTopHeight ?? rect.height * 0.5)

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

  const heatmapSummaryMetrics = useMemo(() => {
    if (!primaryEntry) return []

    const rowCount = primaryEntry.result.y_data.length
    const colCount = primaryEntry.result.x_data.length
    const stats = primaryEntry.result.stats
    const totalPairs = Math.max(
      0,
      Number(stats?.total_pairs || rowCount * colCount || 0)
    )
    const highCount = Math.max(0, Number(stats?.high_similarity_count || 0))
    const highRatio = totalPairs > 0 ? highCount / totalPairs : 0

    return [
      { label: '矩阵规模', value: `${rowCount} × ${colCount}` },
      {
        label: '平均相似度',
        value: formatHeatmapValue(stats?.avg_similarity ?? null),
      },
      {
        label: '最高相似度',
        value: formatHeatmapValue(stats?.max_similarity ?? null),
        tone: 'danger' as const,
      },
      { label: '高相似占比', value: formatPercent(highRatio) },
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

  return (
    <div className="flex h-full w-full overflow-hidden bg-[radial-gradient(circle_at_50%_-12%,hsl(var(--primary)/0.10),transparent_34%),linear-gradient(180deg,hsl(var(--background)),hsl(var(--surface-2)/0.34))]">
      {/* Left section */}
      <div className="flex h-full">
        <div className="flex w-12 flex-col items-center border-r border-border/34 bg-card/46 py-2 shadow-[8px_0_24px_-28px_hsl(var(--foreground)/0.22)] backdrop-blur-xl">
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
              icon={
                isLeftSidebarCollapsed ? (
                  <ChevronRight className="size-4" />
                ) : (
                  <ChevronLeft className="size-4" />
                )
              }
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
            'relative flex h-full flex-col overflow-hidden border-r border-border/34 bg-card/42 backdrop-blur-xl transition-[width,opacity] duration-200 ease-out',
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
            <div
              className="border-b border-border/34 bg-card/40 p-3.5"
              style={leftTopStyle}
            >
              {leftTopPanel === 'dataSource' ? (
                <Panel
                  title="数据源配置"
                  subtitle="选择横/纵坐标 collections，计算两侧相似度。"
                  rightSlot={
                    <Button
                      variant="ghost"
                      size="icon"
                      onClick={refreshCollections}
                      disabled={collectionsLoading}
                      title="刷新"
                      aria-label="刷新"
                    >
                      <RefreshCw
                        className={cn(
                          'size-4',
                          collectionsLoading &&
                            'animate-spin motion-reduce:animate-none'
                        )}
                      />
                    </Button>
                  }
                >
                  <div className="overflow-hidden rounded-[1.35rem] border border-border/38 bg-card/68 shadow-[0_18px_42px_-36px_hsl(var(--foreground)/0.28),inset_0_1px_0_hsl(var(--card)/0.68)]">
                    <div className="border-b border-border/32 bg-muted/[0.12] px-3.5 py-3">
                      <div className="flex items-start gap-3">
                        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-[0.9rem] border border-primary/14 bg-primary/[0.07] text-primary">
                          <Grid3X3 className="size-4" />
                        </div>
                        <div className="min-w-0">
                          <div className="text-[10px] font-semibold uppercase tracking-[0.16em] text-muted-foreground/58">
                            Matrix Setup
                          </div>
                          <div className="mt-0.5 text-[14px] font-semibold leading-4 text-foreground/88">
                            矩阵设置
                          </div>
                        </div>
                      </div>
                    </div>

                    {collectionsError ? (
                      <div className="m-4 rounded-2xl border border-destructive/20 bg-destructive/5 px-3 py-2 text-xs text-destructive">
                        {collectionsError}
                      </div>
                    ) : null}

                    <div>
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
                        <NumberField
                          label="最大项目数"
                          value={xMaxItems}
                          onChange={setXMaxItems}
                          min={10}
                          max={500}
                        />
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
                        <NumberField
                          label="最大项目数"
                          value={yMaxItems}
                          onChange={setYMaxItems}
                          min={10}
                          max={500}
                        />
                      </AxisConfigCard>
                    </div>

                    <div className="px-3.5 pb-3.5 pt-2">
                      <Button
                        className="h-9 w-full rounded-full bg-primary text-primary-foreground shadow-[0_14px_28px_-20px_hsl(var(--primary)/0.62)] hover:bg-primary/92"
                        onClick={calculateSimilarity}
                        disabled={isCalculating}
                      >
                        {isCalculating ? null : (
                          <Play className="mr-2 size-3.5 fill-current" />
                        )}
                        {isCalculating && calcProgress
                          ? `计算中... (${calcProgress.done}/${calcProgress.total})`
                          : '计算相似度'}
                      </Button>
                    </div>
                  </div>
                </Panel>
              ) : (
                <Panel title="结果操作">
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
                </Panel>
              )}
            </div>

            <button
              type="button"
              aria-label="Resize left split"
              className="h-2 cursor-row-resize bg-border/28 hover:bg-primary/14"
              onMouseDown={(e) => startResizeSplit('left', e)}
            />

            <div className="overflow-auto overscroll-contain bg-card/30 p-3.5 no-scrollbar">
              <Panel title="图表选择与控制">
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
              </Panel>
            </div>
          </div>
        </div>
      </div>

      {/* Main content */}
      <div className="h-full flex-1 overflow-hidden bg-transparent">
        <div className="h-full w-full flex flex-col">
          <div className="px-8 pb-3 pt-6">
            <PageHeader
              title={
                mainView === 'diagnostics'
                  ? '向量诊断'
                  : '跨集合相似度热力图'
              }
              description={
                mainView === 'diagnostics'
                  ? '基于当前相似度矩阵重建局部向量邻域，帮助识别高分但支撑不足的干扰项。'
                  : '使用当前主图矩阵和筛选器观察不同集合之间的相似度分布。'
              }
              iconImage="rag-visualization"
              icon={Grid3X3}
              iconColor="text-info"
              badge="RAG"
              compact
              className="p-0"
            >
              <div className="flex flex-wrap items-center gap-3">
                <div className="inline-flex items-center rounded-2xl border border-border/70 bg-card p-1 shadow-subtle">
                  <Button
                    variant={mainView === 'heatmap' ? 'default' : 'outline'}
                    size="sm"
                    className={cn(
                      'rounded-xl',
                      mainView === 'heatmap' &&
                        'bg-info text-primary-foreground hover:bg-info/90'
                    )}
                    onClick={() => setMainView('heatmap')}
                  >
                    热力图
                  </Button>
                  <Button
                    variant={mainView === 'diagnostics' ? 'default' : 'outline'}
                    size="sm"
                    className="rounded-xl"
                    onClick={() => setMainView('diagnostics')}
                    disabled={
                      !primaryEntry || !displayLabels || isDifferenceMode
                    }
                    title={
                      isDifferenceMode
                        ? '差值模式暂不支持向量诊断'
                        : '查看向量诊断'
                    }
                  >
                    向量诊断
                  </Button>
                </div>

                {mainView === 'heatmap' ? (
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-medium text-muted-foreground">
                      配色方案：
                    </span>
                    <div className="flex items-center gap-1">
                      {COLOR_SCHEMES.map((scheme) => (
                        <button
                          key={scheme.key}
                          type="button"
                          className={cn(
                            'h-3 w-7 rounded-full border transition',
                            scheme.key === colorScheme
                              ? 'border-primary'
                              : 'border-border hover:border-primary/50'
                          )}
                          title={scheme.label}
                          onClick={() => setColorScheme(scheme.key)}
                          style={{ backgroundImage: scheme.preview }}
                        />
                      ))}
                    </div>
                    <ChevronDown className="size-3.5 text-muted-foreground" />
                  </div>
                ) : (
                  <div className="flex items-center gap-2 text-xs text-muted-foreground">
                    <span>3D 投影预览</span>
                    <span className="rounded-full border border-border px-2 py-0.5">
                      {diagnostics?.summary.activeOutlierCount ?? 0}{' '}
                      个活跃异常点
                    </span>
                  </div>
                )}
              </div>
            </PageHeader>

            {heatmapSummaryMetrics.length > 0 ? (
              <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                {heatmapSummaryMetrics.map((metric) => (
                  <div
                    key={metric.label}
                    className="rounded-[1.1rem] border border-border/34 bg-card/58 px-4 py-3 text-center shadow-[inset_0_1px_0_hsl(var(--card)/0.55)]"
                  >
                    <div className="text-[11px] font-medium text-muted-foreground">
                      {metric.label}
                    </div>
                    <div
                      className={cn(
                        'mt-1 text-2xl font-semibold tabular-nums',
                        metricToneClass(metric.tone)
                      )}
                    >
                      {metric.value}
                    </div>
                  </div>
                ))}
              </div>
            ) : null}
          </div>
          <div className="flex-1 overflow-hidden">
            <SimilarityMainPanel
              primaryEntry={primaryEntry}
              displayMatrix={displayMatrix}
              displayLabels={displayLabels}
              mainView={mainView}
              diagnostics={diagnostics}
              maskedMatrix={maskedMatrix}
              colorScheme={colorScheme}
              isDifferenceMode={isDifferenceMode}
              onDecisionChange={setDiagnosticDecision}
              onCellSelect={handleHeatmapCellSelect}
            />
          </div>
        </div>
      </div>

      {/* Right section */}
      <div className="flex h-full">
        <div className="flex w-12 flex-col items-center border-l border-border/34 bg-card/46 py-2 shadow-[-8px_0_24px_-28px_hsl(var(--foreground)/0.22)] backdrop-blur-xl">
          <div className="flex flex-col gap-1">
            <IconBtn
              active={
                !isRightSidebarCollapsed && rightTopPanel === 'statistics'
              }
              title="统计信息"
              onClick={handleStatisticsPanelToggle}
              icon={<BarChart3 className="size-4" />}
            />
            <IconBtn
              active={false}
              title={isRightSidebarCollapsed ? '展开右侧栏' : '收起右侧栏'}
              onClick={() => setIsRightSidebarCollapsed((prev) => !prev)}
              icon={
                isRightSidebarCollapsed ? (
                  <ChevronLeft className="size-4" />
                ) : (
                  <ChevronRight className="size-4" />
                )
              }
            />
          </div>
          <div className="mt-auto pt-2">
            <IconBtn
              active={
                !isRightSidebarCollapsed && rightBottomPanel === 'filters'
              }
              title="筛选器控制"
              onClick={handleFilterPanelToggle}
              icon={<Filter className="size-4" />}
            />
          </div>
        </div>

        <div
          ref={rightSidebarRef}
          className={cn(
            'relative flex h-full flex-col overflow-hidden border-l border-border/34 bg-card/42 backdrop-blur-xl transition-[width,opacity] duration-200 ease-out',
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
            <div
              className="border-b border-border/34 bg-card/40 p-3.5"
              style={rightTopStyle}
            >
              {rightTopPanel === 'statistics' ? (
                <Panel title="统计信息" subtitle="数据概览与交互信息">
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
                          <div className="rounded-[1.2rem] border border-border/34 bg-card/62 p-3 shadow-[inset_0_1px_0_hsl(var(--card)/0.55)]">
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
                                    ? 'border-emerald-500/25 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300'
                                    : 'border-amber-500/25 bg-amber-500/10 text-amber-700 dark:text-amber-300'
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
                </Panel>
              ) : (
                <div className="h-full" />
              )}
            </div>

            <button
              type="button"
              aria-label="Resize right split"
              className="h-2 cursor-row-resize bg-border/28 hover:bg-primary/14"
              onMouseDown={(e) => startResizeSplit('right', e)}
            />

            <div className="overflow-auto overscroll-contain bg-card/30 p-3.5 no-scrollbar">
              {rightBottomPanel === 'filters' ? (
                <Panel title="筛选器控制">
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
                              type="range"
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
                              type="range"
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
                            type="range"
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
        'flex h-9 w-9 items-center justify-center rounded-[0.95rem] border shadow-[inset_0_1px_0_hsl(var(--card)/0.52)] transition-colors',
        active
          ? 'border-info bg-info text-primary-foreground'
          : 'border-border/36 bg-background/50 text-muted-foreground hover:border-primary/26 hover:bg-background/70 hover:text-primary'
      )}
    >
      {icon}
    </button>
  )
}

function EmptyControlTile({
  icon,
  label,
}: Readonly<{ icon: ReactNode; label: string }>) {
  return (
    <div className="flex min-h-[74px] flex-col items-center justify-center rounded-[1rem] border border-border/32 bg-background/42 text-muted-foreground">
      <div className="text-primary/58">{icon}</div>
      <div className="mt-2 text-[11px] font-medium text-foreground/76">
        {label}
      </div>
    </div>
  )
}

function RightEmptyInfoCard({
  title,
  icon,
  description,
}: Readonly<{
  title: string
  icon: ReactNode
  description: string
}>) {
  return (
    <section className="rounded-[1.25rem] border border-border/34 bg-card/58 p-3.5 shadow-[inset_0_1px_0_hsl(var(--card)/0.55)]">
      {title ? (
        <div className="mb-3 text-[14px] font-semibold text-foreground/86">
          {title}
        </div>
      ) : null}
      <div
        className={cn(
          'flex flex-col items-center justify-center rounded-[1.15rem] border border-dashed border-border/34 bg-background/42 px-5 text-center',
          title ? 'min-h-[188px]' : 'min-h-[160px]'
        )}
      >
        <div className="flex size-11 items-center justify-center rounded-full border border-primary/14 bg-primary/[0.055] text-primary/58">
          {icon}
        </div>
        <p className="mt-4 text-[12px] leading-5 text-muted-foreground/68">
          {description}
        </p>
      </div>
    </section>
  )
}

function SimilarityEmptyState() {
  return (
    <section
      aria-label="相似度矩阵空状态"
      className="flex h-full w-full max-w-[920px] flex-col items-center justify-center overflow-hidden rounded-[2rem] border border-border/40 bg-[linear-gradient(180deg,hsl(var(--card)/0.86),hsl(var(--background)/0.74))] px-10 py-8 text-center shadow-[0_24px_70px_-58px_hsl(var(--foreground)/0.42),inset_0_1px_0_hsl(var(--card)/0.72)]"
    >
      <div className="relative h-48 w-72">
        <div className="absolute left-1/2 top-4 h-36 w-36 -translate-x-1/2 rounded-full border border-primary/16" />
        <div className="absolute left-1/2 top-0 h-48 w-48 -translate-x-1/2 rounded-full border border-primary/10" />
        <div className="absolute left-[88px] top-[48px] h-24 w-32 rotate-[-9deg] rounded-[1.35rem] border border-primary/18 bg-[linear-gradient(145deg,hsl(var(--card)),hsl(var(--primary)/0.06))] shadow-[0_24px_60px_-42px_hsl(var(--primary)/0.55)]">
          <div className="grid grid-cols-5 gap-1 p-5">
            {Array.from({ length: 20 }, (_, barIndex) => barIndex).map((barIndex) => (
              <span
                key={`empty-matrix-swatch-${barIndex}`}
                className={cn(
                  'h-4 rounded-[4px]',
                  emptyMatrixSwatchClass(barIndex)
                )}
              />
            ))}
          </div>
        </div>
        <div className="absolute right-12 top-7 flex size-14 rotate-[12deg] items-center justify-center rounded-2xl border border-primary/12 bg-primary/[0.045] text-primary/42 shadow-subtle">
          <BarChart3 className="size-7" />
        </div>
        <span className="absolute left-12 top-12 size-2 rounded-full border border-primary/24" />
        <span className="absolute left-7 top-28 size-3 rounded-full bg-primary/14" />
        <span className="absolute right-16 top-28 size-2 rounded-full bg-primary/20" />
      </div>

      <div className="mt-5 flex w-full max-w-[560px] items-start justify-between rounded-full border border-border/32 bg-background/42 px-3 py-2">
        <EmptyStep
          index={1}
          title="选择 X Collection"
          description="从下拉框选择横坐标 Collection"
        />
        <EmptyStepConnector />
        <EmptyStep
          index={2}
          title="选择 Y Collection"
          description="从下拉框选择纵坐标 Collection"
        />
        <EmptyStepConnector />
        <EmptyStep
          index={3}
          title="计算相似度"
          description="点击“计算相似度”生成矩阵"
        />
      </div>

      <div className="mt-6 w-full max-w-[520px] rounded-[1.35rem] border border-border/34 bg-background/54 px-8 py-5 shadow-[inset_0_1px_0_hsl(var(--card)/0.62)]">
        <div className="grid grid-cols-[56px_1fr] gap-3">
          <div className="space-y-2 pt-5">
            {Array.from({ length: 5 }, (_, rowIndex) => rowIndex).map((rowIndex) => (
              <div key={`empty-matrix-row-${rowIndex}`} className="h-2 rounded-full bg-muted" />
            ))}
          </div>
          <div className="space-y-1.5">
            <div className="grid grid-cols-8 gap-1.5">
              {Array.from({ length: 8 }, (_, colIndex) => colIndex).map((colIndex) => (
                <div key={`empty-matrix-column-${colIndex}`} className="h-2 rounded-full bg-muted" />
              ))}
            </div>
            <div className="grid grid-cols-8 gap-1.5">
              {Array.from({ length: 56 }, (_, cellIndex) => cellIndex).map((cellIndex) => (
                <span
                  key={`empty-matrix-cell-${cellIndex}`}
                  className={cn(
                    'h-4 rounded-[3px]',
                    emptyMatrixCellClass(cellIndex)
                  )}
                />
              ))}
            </div>
          </div>
        </div>
      </div>

      <div className="mt-5 flex w-full max-w-[780px] items-center justify-between rounded-full border border-border/34 bg-background/52 px-5 py-3 text-[12px] text-muted-foreground/74 shadow-subtle">
        <div className="flex items-center gap-2">
          <span className="flex size-5 items-center justify-center rounded-full border border-primary/20 text-primary">
            i
          </span>
          <span>支持切换主图、筛选器和独占模式，进一步探索和聚焦数据</span>
        </div>
        <div className="flex items-center gap-4 text-primary/70">
          <Grid3X3 className="size-5" />
          <Filter className="size-5" />
          <Target className="size-5" />
        </div>
      </div>
    </section>
  )
}

function EmptyStep({
  index,
  title,
  description,
}: Readonly<{
  index: number
  title: string
  description: string
}>) {
  return (
    <div className="flex w-36 flex-col items-center">
      <div className="flex size-7 items-center justify-center rounded-full bg-primary/[0.11] text-[12px] font-semibold text-primary ring-1 ring-primary/14">
        {index}
      </div>
      <div className="mt-2 text-[12px] font-semibold text-foreground/84">
        {title}
      </div>
      <div className="mt-0.5 text-[11px] leading-4 text-muted-foreground/64">
        {description}
      </div>
    </div>
  )
}

function EmptyStepConnector() {
  return (
    <div className="mt-3.5 h-px flex-1 border-t border-dashed border-primary/18" />
  )
}

function Panel({
  title,
  children,
  rightSlot,
  subtitle,
}: Readonly<{
  title: string
  children: ReactNode
  rightSlot?: ReactNode
  subtitle?: string
}>) {
  return (
    <div className="h-full flex flex-col">
      <div className="relative mb-2.5 min-h-8 pr-9">
        <div>
          <div className="text-[14px] font-semibold leading-5 tracking-[-0.012em] text-foreground/88">
            {title}
          </div>
          {subtitle ? (
            <div className="mt-0.5 text-[11px] leading-4 text-muted-foreground/64">
              {subtitle}
            </div>
          ) : null}
        </div>
        {rightSlot ? (
          <div className="absolute right-0 top-0">{rightSlot}</div>
        ) : null}
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
  onDecisionChange: (
    candidateId: string,
    decision: DiagnosticDecision | null
  ) => void
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

          <section className="rounded-[1.35rem] border border-border/36 bg-card/62 p-3 shadow-[inset_0_1px_0_hsl(var(--card)/0.55)]">
            <div className="flex flex-col gap-3 border-b border-border/32 pb-3 md:flex-row md:items-start md:justify-between">
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
              <SimilarityDiagnosticsGraph
                nodes={diagnostics.nodes}
                links={diagnostics.links}
              />
            </div>
          </section>
        </div>

        <section className="overflow-hidden rounded-[1.35rem] border border-border/36 bg-card/62 shadow-[inset_0_1px_0_hsl(var(--card)/0.55)]">
          <div className="border-b border-border/32 p-4">
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
                  <article
                    key={candidate.id}
                    className="rounded-[1.1rem] border border-border/34 bg-background/42 p-4 shadow-[inset_0_1px_0_hsl(var(--card)/0.45)]"
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <div className="text-sm font-medium text-foreground">
                          {candidate.xLabel}{' '}
                          <span className="text-muted-foreground">→</span>{' '}
                          {candidate.yLabel}
                        </div>
                        <p className="mt-1 text-xs text-muted-foreground">
                          {candidate.reason}
                        </p>
                      </div>
                      <span
                        className={cn(
                          'rounded-full border px-2 py-0.5 text-[11px]',
                          diagnosticCandidateStatusClass(isDisabled, isMarked)
                        )}
                      >
                        {diagnosticCandidateStatusLabel(isDisabled, isMarked)}
                      </span>
                    </div>

                    <div className="mt-3 grid grid-cols-2 gap-2">
                      <DiagnosticMetricCard
                        label="相似度"
                        value={formatPercent(candidate.similarity)}
                        compact
                      />
                      <DiagnosticMetricCard
                        label="词面重叠"
                        value={formatPercent(candidate.lexicalOverlap)}
                        compact
                      />
                    </div>

                    <div className="mt-3 flex gap-2">
                      <Button
                        variant={isDisabled ? 'default' : 'outline'}
                        size="sm"
                        className="flex-1"
                        onClick={() =>
                          onDecisionChange(
                            candidate.id,
                            isDisabled ? null : 'disabled'
                          )
                        }
                      >
                        {isDisabled ? '恢复候选' : '禁用候选'}
                      </Button>
                      <Button
                        variant={isMarked ? 'default' : 'outline'}
                        size="sm"
                        className="flex-1"
                        onClick={() =>
                          onDecisionChange(
                            candidate.id,
                            isMarked ? null : 'marked'
                          )
                        }
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

function LegendPill({
  className,
  children,
}: Readonly<{ className?: string; children: ReactNode }>) {
  return (
    <span className={cn('rounded-full border px-2 py-0.5', className)}>
      {children}
    </span>
  )
}

function HeatmapScaleLegend({
  colorScheme,
  isDifference,
}: Readonly<{ colorScheme: ColorSchemeKey; isDifference: boolean }>) {
  return (
    <div className="border-t border-sidebar-border/70 px-4 py-3">
      <div className="flex max-w-md items-center gap-3 text-xs font-medium text-foreground">
        <span>{isDifference ? '差值' : '相似度'}</span>
        <span className="font-mono text-[11px] text-muted-foreground tabular-nums">
          {isDifference ? '-1' : '0'}
        </span>
        <div
          className="h-3 flex-1 rounded-full border border-border/50"
          style={{ backgroundImage: heatmapLegendBackground(colorScheme, isDifference) }}
        />
        <span className="font-mono text-[11px] text-muted-foreground tabular-nums">
          1
        </span>
      </div>
    </div>
  )
}

function RelatedListCard({
  title,
  items,
}: Readonly<{
  title: string
  items: Array<{ label: string; value: number; index: number }>
}>) {
  return (
    <section className="rounded-[1.1rem] border border-border/34 bg-card/58 p-3 shadow-[inset_0_1px_0_hsl(var(--card)/0.55)]">
      <div className="mb-2 text-[12px] font-semibold text-foreground">
        {title}
      </div>
      {items.length === 0 ? (
        <div className="text-xs text-muted-foreground">暂无可比较项</div>
      ) : (
        <div className="space-y-2">
          {items.map((item, index) => (
            <div
              key={`${item.label}-${item.index}`}
              className="grid grid-cols-[18px_minmax(0,1fr)_44px] items-center gap-2"
            >
              <span className="text-[11px] font-medium text-muted-foreground">
                {index + 1}
              </span>
              <div className="min-w-0">
                <div className="truncate text-[12px] font-medium text-foreground">
                  {item.label}
                </div>
                <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-muted">
                  <div
                    className="h-full rounded-full bg-[linear-gradient(90deg,#fb923c,#ef4444)]"
                    style={{
                      width: `${Math.max(4, Math.min(100, item.value * 100))}%`,
                    }}
                  />
                </div>
              </div>
              <span className="text-right font-mono text-[11px] font-semibold tabular-nums text-foreground">
                {formatHeatmapValue(item.value)}
              </span>
            </div>
          ))}
        </div>
      )}
    </section>
  )
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
    <div
      className={cn(
        'rounded-[1rem] border border-border/34 bg-card/52',
        compact ? 'p-3' : 'p-4'
      )}
    >
      <div className="text-[11px] font-medium uppercase tracking-[0.08em] text-muted-foreground">
        {label}
      </div>
      <div
        className={cn(
          'mt-1 font-semibold text-foreground',
          compact ? 'text-base' : 'text-2xl'
        )}
      >
        {value}
      </div>
      {hint ? (
        <p className="mt-1 text-[11px] text-muted-foreground">{hint}</p>
      ) : null}
    </div>
  )
}

function formatPercent(value: number) {
  return `${(value * 100).toFixed(1)}%`
}

type SelectOption = {
  value: string
  label: string
  kind?: string
  count?: number
}

const similaritySelectClass =
  'h-9 w-full appearance-none rounded-[0.9rem] border border-border/38 bg-background/58 px-3 pr-9 text-[12px] font-medium text-foreground/84 shadow-[inset_0_1px_0_hsl(var(--card)/0.62),0_10px_24px_-22px_hsl(var(--foreground)/0.28)] outline-none transition-[border-color,box-shadow,background-color] hover:border-primary/26 hover:bg-background/76 focus:border-primary/38 focus:shadow-[inset_0_1px_0_hsl(var(--card)/0.72),0_0_0_4px_hsl(var(--primary)/0.10)]'
const similarityInputClass =
  'h-9 w-full rounded-[0.9rem] border border-border/38 bg-background/58 px-3 text-[12px] font-medium text-foreground/84 shadow-[inset_0_1px_0_hsl(var(--card)/0.62),0_10px_24px_-22px_hsl(var(--foreground)/0.28)] outline-none transition-[border-color,box-shadow,background-color] hover:border-primary/26 hover:bg-background/76 focus:border-primary/38 focus:shadow-[inset_0_1px_0_hsl(var(--card)/0.72),0_0_0_4px_hsl(var(--primary)/0.10)]'
const similarityIconControlClass =
  'h-9 w-9 rounded-[0.9rem] border-border/38 bg-background/58 text-muted-foreground shadow-[inset_0_1px_0_hsl(var(--card)/0.62),0_10px_24px_-22px_hsl(var(--foreground)/0.28)] hover:border-primary/30 hover:bg-background/76 hover:text-primary'
const similarityNativeSelectClass =
  'h-9 w-full rounded-[0.9rem] border border-border/38 bg-background/58 px-3 text-[12px] font-medium text-foreground/84 shadow-[inset_0_1px_0_hsl(var(--card)/0.62)] outline-none focus:border-primary/38 focus:ring-4 focus:ring-primary/10'

function isEmptyCollectionOption(option: SelectOption) {
  return typeof option.count === 'number' && option.count <= 0
}

function collectionOptionLabel(option: SelectOption) {
  if (typeof option.count !== 'number') return option.label
  if (option.count <= 0) return `${option.label}（0 项，暂无数据）`
  return `${option.label}（${option.count} 项）`
}

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
    <section className="border-b border-border/28 px-3.5 py-3.5 last:border-b-0">
      <div className="mb-2.5 flex items-start justify-between gap-2.5">
        <div className="min-w-0">
          <div className="text-[10px] font-semibold uppercase tracking-[0.16em] text-primary/72">
            {eyebrow}
          </div>
          <div className="mt-0.5 text-[13px] font-semibold leading-4 text-foreground/86">
            {title}
          </div>
        </div>
        <span
          className={cn(
            'inline-flex shrink-0 items-center rounded-full border px-2 py-0.5 text-[10px] font-medium',
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
      {showLabel ? (
        <div className="text-[11px] font-medium uppercase tracking-[0.08em] text-foreground/72">
          {label}
        </div>
      ) : null}
      <div className="space-y-1.5">
        {keyedSelections.map(({ value, key }, idx) => (
          <div key={key} className="flex items-center gap-1.5">
            <div className="relative flex-1">
              <select
                className={similaritySelectClass}
                value={value}
                onChange={(e) => {
                  const next = [...selections]
                  next[idx] = e.target.value
                  onChange(next)
                }}
              >
                <option value="">请选择...</option>
                {options.map((opt) => (
                  <option
                    key={opt.value}
                    value={opt.value}
                    disabled={isEmptyCollectionOption(opt)}
                  >
                    {collectionOptionLabel(opt)}
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
                className={similarityIconControlClass}
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
                className={similarityIconControlClass}
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
    <div className="space-y-1.5 block">
      <div className="flex items-center justify-between gap-2">
        <div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-muted-foreground/60">
          {label}
        </div>
        <div className="text-[10.5px] font-medium text-muted-foreground/58">
          {min}-{max}
        </div>
      </div>
      <input
        aria-label={label}
        className={similarityInputClass}
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
    </div>
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

function createDefaultVisualConfig(
  xFields: string[],
  yFields: string[]
): VisualConfig {
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

const DIFFERENCE_COLORSCALE: Array<[number, string]> = [
  [0, '#2563eb'],
  [0.5, '#f8fafc'],
  [1, '#dc2626'],
]

const DIFFERENCE_COLOR_PREVIEW =
  'linear-gradient(90deg,#2563eb,#f8fafc,#dc2626)'

const COLOR_SCHEMES: Array<{
  key: ColorSchemeKey
  label: string
  preview: string
  colorscale: Array<[number, string]>
}> = [
  {
    key: 'viridis',
    label: 'Viridis',
    preview: 'linear-gradient(90deg,#440154,#21908d,#fde725)',
    colorscale: [
      [0, '#440154'],
      [0.5, '#21908d'],
      [1, '#fde725'],
    ],
  },
  {
    key: 'plasma',
    label: 'Plasma',
    preview: 'linear-gradient(90deg,#0d0887,#cc4678,#f0f921)',
    colorscale: [
      [0, '#0d0887'],
      [0.5, '#cc4678'],
      [1, '#f0f921'],
    ],
  },
  {
    key: 'cividis',
    label: 'Cividis',
    preview: 'linear-gradient(90deg,#00204c,#5f7d7f,#fee838)',
    colorscale: [
      [0, '#00204c'],
      [0.5, '#5f7d7f'],
      [1, '#fee838'],
    ],
  },
  {
    key: 'YlGnBu',
    label: 'YlGnBu',
    preview: 'linear-gradient(90deg,#ffffcc,#1d91c0,#081d58)',
    colorscale: [
      [0, '#ffffcc'],
      [0.5, '#1d91c0'],
      [1, '#081d58'],
    ],
  },
  {
    key: 'hot',
    label: 'Hot',
    preview: 'linear-gradient(90deg,#000000,#ff0000,#ffff00)',
    colorscale: [
      [0, '#000000'],
      [0.5, '#ff0000'],
      [1, '#ffff00'],
    ],
  },
]

function toPlotlyColorScale(key: ColorSchemeKey) {
  return COLOR_SCHEMES.find((scheme) => scheme.key === key)?.colorscale ?? COLOR_SCHEMES[0].colorscale
}

function heatmapLegendBackground(
  key: ColorSchemeKey,
  isDifference: boolean
) {
  if (isDifference) return DIFFERENCE_COLOR_PREVIEW
  return COLOR_SCHEMES.find((scheme) => scheme.key === key)?.preview ?? COLOR_SCHEMES[0].preview
}

function generateUniqueLabels(
  items: Array<Record<string, unknown>>,
  field: string
) {
  const counts = new Map<string, number>()
  return items.map((item) => {
    const raw = axisLabelForItem(item, field)
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
  const [plotlyLoadState, setPlotlyLoadState] = useState<
    'loading' | 'ready' | 'error'
  >('loading')

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const modUnknown: unknown = await import('plotly.js-dist-min')
        const plotlyModule = pickPlotlyModule(modUnknown)
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
    const colorscale = isDifference
      ? DIFFERENCE_COLORSCALE
      : toPlotlyColorScale(colorScheme)

    const trace: PlotlyTrace = {
      type: 'heatmap',
      z: matrix,
      x: xLabels,
      y: yLabels,
      colorscale,
      zmin,
      zmax,
      text: matrix.map((row) => row.map((value) => formatHeatmapValue(value))),
      texttemplate: '%{text}',
      textfont: { color: '#0f172a', size: 11 },
      showscale: false,
      hovertemplate: '<b>%{z:.3f}</b><br>X: %{x}<br>Y: %{y}<extra></extra>',
    }

    const layout: PlotlyLayout = {
      margin: { l: 108, r: 20, t: 36, b: 96 },
      xaxis: { automargin: true, tickangle: -28 },
      yaxis: { automargin: true, autorange: 'reversed' },
      paper_bgcolor: 'transparent',
      plot_bgcolor: 'transparent',
    }

    const config: PlotlyConfig = {
      responsive: true,
      displaylogo: false,
      displayModeBar: false,
    }

    plotly.react(containerRef.current, [trace], layout, config)

    const plotTarget = containerRef.current as PlotlyEventTarget
    plotTarget.removeAllListeners?.('plotly_click')
    plotTarget.on?.('plotly_click', (event) => {
      const cell = resolveHeatmapPoint(event)
      if (cell) onCellSelect?.(cell)
    })
  }, [
    colorScheme,
    isDifference,
    matrix,
    onCellSelect,
    plotly,
    xLabels,
    yLabels,
  ])

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
        <p className="mt-2 text-xs text-muted-foreground">
          正在初始化图表引擎...
        </p>
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

function computeThresholdMask(
  matrix: number[][],
  minSim: number,
  maxSim: number
) {
  const min = Math.min(minSim, maxSim)
  const max = Math.max(minSim, maxSim)
  return matrix.map((row) =>
    row.map((val) => Number.isFinite(val) && val >= min && val <= max)
  )
}

function matrixDimensions(matrix: readonly { length: number }[]) {
  const rows = matrix.length
  const cols = rows > 0 ? matrix[0]?.length || 0 : 0
  return { rows, cols }
}

function createBooleanMatrix(rows: number, cols: number, value: boolean) {
  return Array.from({ length: rows }, () =>
    Array.from({ length: cols }, () => value)
  )
}

function finiteRowScores(row: number[]) {
  return row
    .map((v, j) => ({ j, v }))
    .filter((x) => Number.isFinite(x.v))
    .sort((a, b) => b.v - a.v)
}

function applyTopKByRow(matrix: number[][], mask: boolean[][], k: number) {
  for (let i = 0; i < matrix.length; i++) {
    for (const { j } of finiteRowScores(matrix[i]).slice(0, k)) {
      mask[i][j] = true
    }
  }
}

function finiteColumnScores(matrix: number[][], columnIndex: number) {
  const scored = []
  for (let i = 0; i < matrix.length; i++) {
    const v = matrix[i][columnIndex]
    if (Number.isFinite(v)) scored.push({ i, v })
  }
  return scored.sort((a, b) => b.v - a.v)
}

function applyTopKByColumn(
  matrix: number[][],
  mask: boolean[][],
  cols: number,
  k: number
) {
  for (let j = 0; j < cols; j++) {
    for (const { i } of finiteColumnScores(matrix, j).slice(0, k)) {
      mask[i][j] = true
    }
  }
}

function computeTopKMask(matrix: number[][], topK: number, axis: 'x' | 'y') {
  const { rows, cols } = matrixDimensions(matrix)
  if (rows === 0 || cols === 0) return []
  if (!topK || topK <= 0) return createBooleanMatrix(rows, cols, true)

  const k = axis === 'x' ? Math.min(topK, cols) : Math.min(topK, rows)
  const mask = createBooleanMatrix(rows, cols, false)
  if (axis === 'x') applyTopKByRow(matrix, mask, k)
  if (axis === 'y') applyTopKByColumn(matrix, mask, cols, k)
  return mask
}

function combineWithAND(a: boolean[][], b: boolean[][]) {
  const rows = Math.min(a.length, b.length)
  const cols = rows > 0 ? Math.min(a[0]?.length || 0, b[0]?.length || 0) : 0
  const out: boolean[][] = Array.from({ length: rows }, () =>
    Array.from({ length: cols }, () => false)
  )
  for (let i = 0; i < rows; i++) {
    for (let j = 0; j < cols; j++) out[i][j] = Boolean(a[i][j] && b[i][j])
  }
  return out
}

function combineWithOR(masks: boolean[][][]) {
  if (masks.length === 0) return []
  const rows = masks[0].length
  const cols = rows > 0 ? masks[0][0].length : 0
  const out: boolean[][] = Array.from({ length: rows }, () =>
    Array.from({ length: cols }, () => false)
  )
  for (const mask of masks) {
    for (let i = 0; i < rows; i++) {
      for (let j = 0; j < cols; j++)
        out[i][j] = out[i][j] || Boolean(mask[i][j])
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

function applyMask(
  matrix: number[][],
  mask: boolean[][]
): Array<Array<number | null>> {
  const rows = Math.min(matrix.length, mask.length)
  const cols =
    rows > 0 ? Math.min(matrix[0]?.length || 0, mask[0]?.length || 0) : 0
  const out: Array<Array<number | null>> = Array.from({ length: rows }, () =>
    Array.from({ length: cols }, () => null)
  )
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
  topKAxis: SimilarityTopKAxis
}

function countTrueCells(mask: boolean[][], rows: number, cols: number) {
  let count = 0
  for (let i = 0; i < rows; i++) {
    for (let j = 0; j < cols; j++) {
      if (mask[i][j]) count++
    }
  }
  return count
}

function countTrueDiagonal(mask: boolean[][], diagonalTotalCount: number) {
  let count = 0
  for (let i = 0; i < diagonalTotalCount; i++) {
    if (mask[i][i]) count++
  }
  return count
}

function rowHasTrue(mask: boolean[][], rowIndex: number, cols: number) {
  for (let j = 0; j < cols; j++) {
    if (mask[rowIndex][j]) return true
  }
  return false
}

function columnHasTrue(mask: boolean[][], columnIndex: number, rows: number) {
  for (let i = 0; i < rows; i++) {
    if (mask[i][columnIndex]) return true
  }
  return false
}

function countRowsWithoutMatch(mask: boolean[][], rows: number, cols: number) {
  let count = 0
  for (let i = 0; i < rows; i++) {
    if (!rowHasTrue(mask, i, cols)) count++
  }
  return count
}

function countColumnsWithoutMatch(mask: boolean[][], rows: number, cols: number) {
  let count = 0
  for (let j = 0; j < cols; j++) {
    if (!columnHasTrue(mask, j, rows)) count++
  }
  return count
}

function missingMatchCountByAxis(
  mask: boolean[][],
  rows: number,
  cols: number,
  topKAxis: SimilarityTopKAxis
) {
  if (topKAxis === 'x') return countRowsWithoutMatch(mask, rows, cols)
  if (topKAxis === 'y') return countColumnsWithoutMatch(mask, rows, cols)
  return 0
}

function calculateNormalModeStatistics(
  finalMask: boolean[][],
  topKAxis: SimilarityTopKAxis
): NormalModeStats {
  const { rows, cols } = matrixDimensions(finalMask)
  const totalCount = rows * cols

  const diagonalTotalCount = Math.min(rows, cols)

  return {
    totalCount,
    currentDisplayCount: countTrueCells(finalMask, rows, cols),
    diagonalTrueCount: countTrueDiagonal(finalMask, diagonalTotalCount),
    diagonalTotalCount,
    missingMatchCount: missingMatchCountByAxis(finalMask, rows, cols, topKAxis),
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

function calculateDifferenceModeStatistics(
  groundTruthMask: boolean[][],
  currentMask: boolean[][]
): DifferenceModeStats {
  const rows = Math.min(groundTruthMask.length, currentMask.length)
  const cols =
    rows > 0
      ? Math.min(groundTruthMask[0]?.length || 0, currentMask[0]?.length || 0)
      : 0

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

  const contextRecall =
    truePositive + falseNegative > 0
      ? truePositive / (truePositive + falseNegative)
      : 0
  const contextPrecision =
    truePositive + falsePositive > 0
      ? truePositive / (truePositive + falsePositive)
      : 0

  return {
    truePositive,
    trueNegative,
    falsePositive,
    falseNegative,
    contextRecall,
    contextPrecision,
  }
}

function resolveHeatmapPoint(
  event: PlotlyClickEvent
): SelectedHeatmapCell | null {
  const point = event.points?.[0]
  if (!point) return null

  const pair = heatmapPointPair(point)
  const rowIndex = heatmapPointCoordinate(point.i, pair, 0)
  const colIndex = heatmapPointCoordinate(point.j, pair, 1)

  if (rowIndex === null || colIndex === null) return null
  return { rowIndex, colIndex }
}

function formatHeatmapValue(value: number | null) {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '—'
  let formatted = value.toFixed(4)
  while (formatted.includes('.') && formatted.endsWith('0')) {
    formatted = formatted.slice(0, -1)
  }
  return formatted.endsWith('.') ? formatted.slice(0, -1) : formatted
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
  const toneClass = (() => {
    if (tone === 'success') {
      return 'bg-success/10 text-success border-success/20'
    } else if (tone === 'warning') {
      return 'bg-amber-50 text-amber-800 border-amber-100 dark:bg-amber-900/15 dark:text-amber-200 dark:border-amber-900/30'
    } else if (tone === 'danger') {
      return 'bg-rose-50 text-rose-700 border-rose-100 dark:bg-rose-900/15 dark:text-rose-200 dark:border-rose-900/30'
    } else if (tone === 'info') {
      return 'bg-sky-50 text-sky-700 border-sky-100 dark:bg-sky-900/15 dark:text-sky-200 dark:border-sky-900/30'
    } else if (tone === 'muted') {
      return 'bg-muted text-muted-foreground border-border'
    } else {
      return 'bg-card text-foreground border-border'
    }
  })()

  return (
    <div className={cn('rounded-xl border p-2.5 shadow-subtle', toneClass)}>
      <div className="text-[11px] font-medium opacity-90">{label}</div>
      <div className="text-sm font-semibold mt-1">{value}</div>
    </div>
  )
}
