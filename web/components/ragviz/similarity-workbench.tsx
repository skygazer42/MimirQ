'use client'

import type { MouseEvent as ReactMouseEvent, ReactNode } from 'react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { ragvizApi } from '@/lib/api-client'
import type {
  RagvizSimilarityCollection,
  RagvizSimilarityCalculateResponse,
  RagvizSimilarityCollectionsResponse,
  RagvizSimilarityMatrixResult,
  RagvizSimilarityRequest,
} from '@/types'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import {
  BarChart3,
  Database,
  Download,
  Funnel,
  Grid3X3,
  RefreshCw,
} from 'lucide-react'
import { toast } from 'sonner'

type LeftTopPanel = 'dataSource' | 'operations'
type LeftBottomPanel = 'chartControl'
type RightTopPanel = 'statistics' | null
type RightBottomPanel = 'filters' | null

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

  const [leftTopPanel, setLeftTopPanel] = useState<LeftTopPanel>('dataSource')
  const [leftBottomPanel] = useState<LeftBottomPanel>('chartControl')
  const [rightTopPanel, setRightTopPanel] = useState<RightTopPanel>('statistics')
  const [rightBottomPanel, setRightBottomPanel] = useState<RightBottomPanel>('filters')

  const [leftWidth, setLeftWidth] = useState<number>(320)
  const [rightWidth, setRightWidth] = useState<number>(320)
  const [leftTopHeight, setLeftTopHeight] = useState<number | null>(null)
  const [rightTopHeight, setRightTopHeight] = useState<number | null>(null)

  const leftSidebarRef = useRef<HTMLDivElement>(null)
  const rightSidebarRef = useRef<HTMLDivElement>(null)

  const [results, setResults] = useState<SimilarityMatrixEntry[]>([])

  const loadCollections = async () => {
    setCollectionsError('')
    setCollectionsLoading(true)
    try {
      const res: RagvizSimilarityCollectionsResponse = await ragvizApi.listSimilarityCollections()
      setCollections(res.collections || [])
    } catch (e: any) {
      setCollectionsError(e?.message || '加载 collections 失败')
    } finally {
      setCollectionsLoading(false)
    }
  }

  useEffect(() => {
    loadCollections()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

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
        } catch (e: any) {
          const msg = e?.message || '计算失败'
          toast.error(`${resolveCollectionLabel(x)} vs ${resolveCollectionLabel(y)}：${msg}`)
        } finally {
          done += 1
          setCalcProgress({ done, total })
        }
      }
    }

    setResults(nextResults)
    setIsCalculating(false)
    setCalcProgress(null)
    if (nextResults.length > 0) {
      toast.success(`成功计算 ${nextResults.length} 个相似度矩阵`)
    }
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
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
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
    }

    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
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
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
    }

    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
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
          <div
            className="absolute top-0 right-0 h-full w-1 cursor-col-resize hover:bg-primary/20"
            onMouseDown={(e) => startResizeSidebar('left', e)}
          />

          <div className="flex flex-col overflow-hidden">
            <div className="p-3 border-b border-border" style={leftTopStyle}>
              {leftTopPanel === 'dataSource' ? (
                <Panel title="数据源配置" rightSlot={
                  <Button variant="ghost" size="icon" onClick={loadCollections} disabled={collectionsLoading} title="刷新">
                    <RefreshCw className={cn('h-4 w-4', collectionsLoading && 'animate-spin')} />
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
                  <p className="text-xs text-muted-foreground">导入/导出 JSON（后续实现）。</p>
                </Panel>
              )}
            </div>

            <div
              className="h-2 cursor-row-resize bg-border/50 hover:bg-primary/20"
              onMouseDown={(e) => startResizeSplit('left', e)}
            />

            <div className="p-3 overflow-auto">
              <Panel title="图表选择与控制">
                <p className="text-xs text-muted-foreground">矩阵列表与按钮状态（后续实现）。</p>
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
              <div className="flex items-center gap-2">
                <div className="h-3 w-6 rounded bg-gradient-to-r from-indigo-600 via-emerald-500 to-yellow-400" />
                <div className="h-3 w-6 rounded bg-gradient-to-r from-fuchsia-500 via-orange-500 to-yellow-300" />
                <div className="h-3 w-6 rounded bg-gradient-to-r from-slate-800 via-sky-500 to-emerald-300" />
              </div>
            </div>
          </div>
          <div className="flex-1 overflow-hidden flex items-center justify-center">
            <div className="text-sm text-muted-foreground">热力图渲染（Plotly）将在下一步接入。</div>
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
              icon={<Funnel className="h-4 w-4" />}
            />
          </div>
        </div>

        <div
          ref={rightSidebarRef}
          className="relative h-full border-l border-border bg-card flex flex-col"
          style={{ width: rightWidth }}
        >
          <div
            className="absolute top-0 left-0 h-full w-1 cursor-col-resize hover:bg-primary/20"
            onMouseDown={(e) => startResizeSidebar('right', e)}
          />

          <div className="flex flex-col overflow-hidden">
            <div className="p-3 border-b border-border" style={rightTopStyle}>
              {rightTopPanel === 'statistics' ? (
                <Panel title="统计信息">
                  <p className="text-xs text-muted-foreground">TP/TN/FP/FN 与对角线统计将在后续实现。</p>
                </Panel>
              ) : (
                <div className="h-full" />
              )}
            </div>

            <div
              className="h-2 cursor-row-resize bg-border/50 hover:bg-primary/20"
              onMouseDown={(e) => startResizeSplit('right', e)}
            />

            <div className="p-3 overflow-auto">
              {rightBottomPanel === 'filters' ? (
                <Panel title="筛选器控制">
                  <p className="text-xs text-muted-foreground">阈值与 Top-K 控件将在后续实现。</p>
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
}: {
  active?: boolean
  icon: ReactNode
  title: string
  onClick?: () => void
}) {
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
}: {
  title: string
  children: ReactNode
  rightSlot?: ReactNode
}) {
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
}: {
  label: string
  selections: string[]
  onChange: (next: string[]) => void
  options: SelectOption[]
}) {
  return (
    <div className="space-y-2">
      <div className="text-xs font-medium text-foreground/80">{label}</div>
      <div className="space-y-2">
        {selections.map((value, idx) => (
          <div key={idx} className="flex items-center gap-2">
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
}: {
  label: string
  value: number
  onChange: (next: number) => void
  min: number
  max: number
}) {
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

const DEFAULT_FIELD_NAMES = ['document', 'text', 'name'] as const

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
