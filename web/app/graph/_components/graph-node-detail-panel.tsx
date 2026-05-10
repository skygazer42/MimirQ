'use client'

import { useEffect, useRef, useState, type CSSProperties, type PointerEvent as ReactPointerEvent, type RefObject } from 'react'

import { Box, BoxSelect, ChevronDown, Database, FileText, Info, Layers, Link as LinkIcon, MessageSquare, Network, RefreshCw, Trash2, X } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { coerceTrimmedString, getGraphNodeKind, getGraphNodeType } from '@/app/graph/graph-page-utils'
import type {
  KGEntityAliasItem,
  KGEntityAliasSuggestionItem,
  KGEntityDetailResponse,
  KGEventDetailResponse,
} from '@/types'
import { cn } from '@/lib/utils'

import type { GraphNodeLike } from '../graph-page-utils'

const OMITTED_NODE_KEYS = new Set([
  'id',
  'label',
  'kind',
  'type',
  'x',
  'y',
  'z',
  'vx',
  'vy',
  'vz',
  'fx',
  'fy',
  'fz',
  'index',
  'color',
  '__bckgDimensions',
  'source',
  'meta',
  'group',
  'val',
])

const DETAIL_TONE_CLASSES = [
  'border-[#c8edf1]/70 bg-[rgba(204,254,255,0.48)]',
  'border-[#d3efdf]/70 bg-[rgba(223,255,236,0.56)]',
  'border-[#efe5c9]/75 bg-[rgba(255,244,214,0.62)]',
  'border-[#d9defd]/78 bg-[rgba(238,240,255,0.74)]',
]

const PANEL_MIN_TOP = 16
const PANEL_SIDE_MARGIN = 16
const PANEL_TOP_OFFSET = 104

function clampPanelPosition(args: {
  x: number
  y: number
  containerWidth: number
  containerHeight: number
  panelWidth: number
  panelHeight: number
}) {
  const {
    x,
    y,
    containerWidth,
    containerHeight,
    panelWidth,
    panelHeight,
  } = args

  return {
    x: Math.min(
      Math.max(PANEL_SIDE_MARGIN, x),
      Math.max(PANEL_SIDE_MARGIN, containerWidth - panelWidth - PANEL_SIDE_MARGIN)
    ),
    y: Math.min(
      Math.max(PANEL_MIN_TOP, y),
      Math.max(PANEL_MIN_TOP, containerHeight - panelHeight - PANEL_SIDE_MARGIN)
    ),
  }
}

function getKindBadgeClasses(kind: string): string {
  switch (kind) {
    case 'event':
      return 'border-[#efe0b8]/80 bg-[rgba(255,242,205,0.76)] text-amber-700'
    case 'entity':
      return 'border-[#c8edf1]/80 bg-[rgba(204,254,255,0.74)] text-info'
    case 'trace':
    case 'step':
      return 'border-[#d9defd]/80 bg-[rgba(238,240,255,0.78)] text-indigo-700'
    default:
      return 'border-border/70 bg-muted/60 text-muted-foreground'
  }
}

function getKindLabel(kind: string): string {
  switch (kind) {
    case 'entity':
      return '实体'
    case 'event':
      return '事件'
    case 'trace':
      return '追踪'
    case 'step':
      return '步骤'
    default:
      return kind || '节点'
  }
}

type GraphNodeDetailPanelProps = Readonly<{
  open: boolean
  selectedNode: GraphNodeLike | null
  detailScrollRef: RefObject<HTMLDivElement | null>
  dataSource: 'live' | 'file'
  kgNodeDetailLoading: boolean
  kgNodeDetail: KGEntityDetailResponse | KGEventDetailResponse | null
  entityAliasesLoading: boolean
  entityAliases: KGEntityAliasItem[]
  aliasDraft: string
  aliasSaving: boolean
  aliasSuggestionsLoading: boolean
  aliasSuggestions: KGEntityAliasSuggestionItem[]
  lastResolutionActionId: string | null
  undoSubmitting: boolean
  isLoading: boolean
  onClose: () => void
  onChat: () => void
  onViewSource: () => void
  onExpandNode: () => void
  onStartConnectMode: () => void
  onDeleteNode: () => void
  onOpenMerge: () => void
  onOpenSplit: () => void
  onUndoLastResolution: () => void
  onAliasDraftChange: (value: string) => void
  onSaveAlias: () => void
  onRequestDeleteAlias: (row: KGEntityAliasItem) => void
  onMergeAliasSuggestion: (row: KGEntityAliasSuggestionItem) => void
}>

function GraphNodeKgDetail({
  selectedNode,
  kgNodeDetailLoading,
  kgNodeDetail,
  entityAliasesLoading,
  entityAliases,
  aliasDraft,
  aliasSaving,
  aliasSuggestionsLoading,
  aliasSuggestions,
  onAliasDraftChange,
  onSaveAlias,
  onRequestDeleteAlias,
  onMergeAliasSuggestion,
}: Omit<
  GraphNodeDetailPanelProps,
  | 'open'
  | 'detailScrollRef'
  | 'dataSource'
  | 'lastResolutionActionId'
  | 'undoSubmitting'
  | 'isLoading'
  | 'onClose'
  | 'onChat'
  | 'onViewSource'
  | 'onExpandNode'
  | 'onStartConnectMode'
  | 'onDeleteNode'
  | 'onOpenMerge'
  | 'onOpenSplit'
  | 'onUndoLastResolution'
>) {
  if (kgNodeDetailLoading) {
    return (
      <div className="rounded-lg border border-[#c8edf1]/70 bg-[rgba(204,254,255,0.36)] p-2.5 text-[11px] text-muted-foreground">
        Loading...
      </div>
    )
  }

  if (!kgNodeDetail) {
    return (
      <div className="rounded-lg border border-[#d9defd]/70 bg-[rgba(238,240,255,0.44)] p-2.5 text-[11px] text-muted-foreground">
        No KG detail available
      </div>
    )
  }

  if (selectedNode?.meta?.kind !== 'entity') {
    const eventDetail = kgNodeDetail as KGEventDetailResponse
    return (
      <div className="rounded-lg border border-[#d3efdf]/75 bg-[rgba(223,255,236,0.52)] p-2.5">
        <div className="mb-1.5 text-[11px] font-medium uppercase tracking-[0.08em] text-emerald-800/70">Entities</div>
        <div className="space-y-1.5">
          {eventDetail.entities?.slice(0, 12)?.map((row) => (
            <div key={row.entity.id} className="flex items-center justify-between gap-2 text-[11px]">
              <span className="truncate text-foreground" title={row.entity.name}>
                {row.entity.name || row.entity.id}
              </span>
              <span className="rounded-md bg-background/70 px-1.5 py-0.5 text-[11px] text-muted-foreground">
                {row.role || row.entity.type}
              </span>
            </div>
          ))}
        </div>
      </div>
    )
  }

  const entityDetail = kgNodeDetail as KGEntityDetailResponse

  return (
    <div className="space-y-2.5">
      <div className="rounded-lg border border-[#c8edf1]/75 bg-[rgba(204,254,255,0.46)] p-2.5">
        <div className="mb-1.5 text-[11px] font-medium uppercase tracking-[0.08em] text-info/70">Recent Events</div>
        <div className="space-y-1.5">
          {entityDetail.events?.slice(0, 6)?.map((ev) => (
            <div key={ev.id} className="truncate text-[11px] text-foreground" title={ev.title}>
              {ev.title}
            </div>
          ))}
        </div>
      </div>

      <div className="rounded-lg border border-[#d3efdf]/75 bg-[rgba(223,255,236,0.52)] p-2.5">
        <div className="mb-1.5 text-[11px] font-medium uppercase tracking-[0.08em] text-emerald-800/70">Top Neighbors</div>
        <div className="space-y-1.5">
          {entityDetail.neighbors?.slice(0, 8)?.map((neighbor) => (
            <div key={neighbor.entity_id} className="flex items-center justify-between gap-2 text-[11px]">
              <span className="truncate text-foreground" title={neighbor.name}>
                {neighbor.name || neighbor.entity_id}
              </span>
              <span className="rounded-md bg-background/70 px-1.5 py-0.5 font-mono text-[11px] text-muted-foreground">
                {neighbor.count}
              </span>
            </div>
          ))}
        </div>
      </div>

      <div className="rounded-lg border border-[#efe5c9]/80 bg-[rgba(255,244,214,0.56)] p-2.5">
        <div className="mb-1.5 text-[11px] font-medium uppercase tracking-[0.08em] text-amber-800/75">Aliases</div>
        {entityAliasesLoading ? (
          <div className="text-[11px] text-muted-foreground">Loading...</div>
        ) : entityAliases.length === 0 ? (
          <div className="text-[11px] text-muted-foreground">No aliases</div>
        ) : (
          <div className="flex flex-wrap gap-1.5">
            {entityAliases.slice(0, 12).map((alias) => (
              <div key={alias.id} className="inline-flex items-center gap-1 rounded-full border border-border/65 bg-background/72 px-2 py-0.5 text-[11px]">
                <span className="max-w-[150px] truncate" title={alias.alias}>
                  {alias.alias}
                </span>
                <button
                  type="button"
                  onClick={() => onRequestDeleteAlias(alias)}
                  aria-label={`删除 alias ${alias.alias}`}
                  className="text-muted-foreground hover:text-foreground hover:bg-muted rounded-md p-0.5 transition-colors"
                >
                  <X className="size-3" />
                </button>
              </div>
            ))}
          </div>
        )}

        <div className="mt-2.5 flex items-center gap-2">
          <Input
            value={aliasDraft}
            onChange={(event) => onAliasDraftChange(event.target.value)}
            placeholder="Add alias…"
            className="h-7.5 text-[11px]"
          />
          <Button
            type="button"
            variant="outline"
            className="h-7.5 border-[#efe5c9]/80 bg-background/72 px-2.5 text-[11px] shadow-none hover:bg-background"
            onClick={onSaveAlias}
            disabled={aliasSaving || !aliasDraft.trim()}
          >
            添加
          </Button>
        </div>
      </div>

      <div className="rounded-lg border border-[#d9defd]/78 bg-[rgba(238,240,255,0.6)] p-2.5">
        <div className="mb-1.5 text-[11px] font-medium uppercase tracking-[0.08em] text-indigo-800/70">Suggestions</div>
        {aliasSuggestionsLoading ? (
          <div className="text-[11px] text-muted-foreground">Loading...</div>
        ) : aliasSuggestions.length === 0 ? (
          <div className="text-[11px] text-muted-foreground">No suggestions</div>
        ) : (
          <div className="space-y-1.5">
            {aliasSuggestions.slice(0, 6).map((suggestion) => (
              <div key={suggestion.entity_id} className="flex items-center justify-between gap-2 text-[11px]">
                <span className="truncate text-foreground" title={suggestion.name}>
                  {suggestion.name || suggestion.entity_id}
                </span>
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  className="h-6.5 border-[#d9defd]/80 bg-background/72 px-2 text-[11px] shadow-none hover:bg-background"
                  onClick={() => onMergeAliasSuggestion(suggestion)}
                >
                  合并
                </Button>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

export function GraphNodeDetailPanel({
  open,
  selectedNode,
  detailScrollRef,
  dataSource,
  kgNodeDetailLoading,
  kgNodeDetail,
  entityAliasesLoading,
  entityAliases,
  aliasDraft,
  aliasSaving,
  aliasSuggestionsLoading,
  aliasSuggestions,
  lastResolutionActionId,
  undoSubmitting,
  isLoading,
  onClose,
  onChat,
  onViewSource,
  onExpandNode,
  onStartConnectMode,
  onDeleteNode,
  onOpenMerge,
  onOpenSplit,
  onUndoLastResolution,
  onAliasDraftChange,
  onSaveAlias,
  onRequestDeleteAlias,
  onMergeAliasSuggestion,
}: GraphNodeDetailPanelProps) {
  const nodeKind = getGraphNodeKind(selectedNode)
  const nodeType = getGraphNodeType(selectedNode)
  const summaryBadges = [
    { label: 'ID', value: selectedNode?.id == null ? '' : String(selectedNode.id), className: 'border-[#c8edf1]/80 bg-[rgba(204,254,255,0.74)] text-info' },
    nodeKind ? { label: '类别', value: getKindLabel(nodeKind), className: getKindBadgeClasses(nodeKind) } : null,
    nodeType ? { label: '类型', value: nodeType, className: 'border-[#d9defd]/80 bg-[rgba(238,240,255,0.76)] text-indigo-700' } : null,
    selectedNode?.group != null ? { label: '组', value: String(selectedNode.group), className: 'border-[#d3efdf]/80 bg-[rgba(223,255,236,0.74)] text-emerald-700' } : null,
    selectedNode?.val != null ? { label: '权重', value: String(selectedNode.val), className: 'border-[#efe5c9]/80 bg-[rgba(255,244,214,0.76)] text-amber-700' } : null,
  ].filter(Boolean) as Array<{ label: string; value: string; className: string }>

  const detailEntries = selectedNode
    ? Object.entries(selectedNode).filter(([key, value]) => {
        if (OMITTED_NODE_KEYS.has(key) || key.startsWith('__')) return false
        if (value == null) return false
        if (typeof value === 'string' && !value.trim()) return false
        return true
      })
    : []

  const quickActionBaseClass =
    'h-8 w-full rounded-lg px-2 text-[11px] text-slate-700 shadow-none hover:text-slate-900'
  const panelRef = useRef<HTMLDivElement>(null)
  const dragStateRef = useRef<{
    pointerId: number
    originX: number
    originY: number
    startX: number
    startY: number
  } | null>(null)
  const [panelPosition, setPanelPosition] = useState<{ x: number; y: number } | null>(null)
  const [isDragging, setIsDragging] = useState(false)
  const [isKgDetailExpanded, setIsKgDetailExpanded] = useState(false)
  const [isHovered, setIsHovered] = useState(false)

  useEffect(() => {
    setIsKgDetailExpanded(false)
  }, [selectedNode?.id])

  useEffect(() => {
    if (!open || !selectedNode) return
    const panel = panelRef.current
    const container = panel?.offsetParent
    if (!(panel instanceof HTMLElement) || !(container instanceof HTMLElement)) return

    const nextPosition = panelPosition
      ? clampPanelPosition({
          ...panelPosition,
          containerWidth: container.clientWidth,
          containerHeight: container.clientHeight,
          panelWidth: panel.offsetWidth,
          panelHeight: panel.offsetHeight,
        })
      : clampPanelPosition({
          x: container.clientWidth - panel.offsetWidth - PANEL_SIDE_MARGIN,
          y: PANEL_TOP_OFFSET,
          containerWidth: container.clientWidth,
          containerHeight: container.clientHeight,
          panelWidth: panel.offsetWidth,
          panelHeight: panel.offsetHeight,
        })

    if (!panelPosition || nextPosition.x !== panelPosition.x || nextPosition.y !== panelPosition.y) {
      setPanelPosition(nextPosition)
    }
  }, [open, panelPosition, selectedNode])

  useEffect(() => {
    if (!open || !selectedNode) return

    const handleResize = () => {
      const panel = panelRef.current
      const container = panel?.offsetParent
      if (!(panel instanceof HTMLElement) || !(container instanceof HTMLElement)) return

      setPanelPosition((current) => {
        const base = current ?? {
          x: container.clientWidth - panel.offsetWidth - PANEL_SIDE_MARGIN,
          y: PANEL_TOP_OFFSET,
        }
        return clampPanelPosition({
          ...base,
          containerWidth: container.clientWidth,
          containerHeight: container.clientHeight,
          panelWidth: panel.offsetWidth,
          panelHeight: panel.offsetHeight,
        })
      })
    }

    globalThis.window.addEventListener('resize', handleResize)
    return () => {
      globalThis.window.removeEventListener('resize', handleResize)
    }
  }, [open, selectedNode])

  const handleDragStart = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (event.button !== 0) return

    const panel = panelRef.current
    const container = panel?.offsetParent
    if (!(panel instanceof HTMLElement) || !(container instanceof HTMLElement)) return

    const basePosition = panelPosition ?? {
      x: panel.offsetLeft,
      y: panel.offsetTop,
    }

    dragStateRef.current = {
      pointerId: event.pointerId,
      originX: basePosition.x,
      originY: basePosition.y,
      startX: event.clientX,
      startY: event.clientY,
    }
    event.currentTarget.setPointerCapture(event.pointerId)
    setIsDragging(true)
  }

  const handleDragMove = (event: ReactPointerEvent<HTMLDivElement>) => {
    const dragState = dragStateRef.current
    const panel = panelRef.current
    const container = panel?.offsetParent
    if (!dragState || dragState.pointerId !== event.pointerId) return
    if (!(panel instanceof HTMLElement) || !(container instanceof HTMLElement)) return

    const nextX = dragState.originX + event.clientX - dragState.startX
    const nextY = dragState.originY + event.clientY - dragState.startY

    setPanelPosition(
      clampPanelPosition({
        x: nextX,
        y: nextY,
        containerWidth: container.clientWidth,
        containerHeight: container.clientHeight,
        panelWidth: panel.offsetWidth,
        panelHeight: panel.offsetHeight,
      })
    )
  }

  const handleDragEnd = (event: ReactPointerEvent<HTMLDivElement>) => {
    const dragState = dragStateRef.current
    if (!dragState || dragState.pointerId !== event.pointerId) return

    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId)
    }

    dragStateRef.current = null
    setIsDragging(false)
  }

  const shouldLiftCard = isDragging || isHovered
  const innerCardStyle: CSSProperties = {
    transformStyle: 'preserve-3d',
    transform: shouldLiftCard ? 'rotateY(-5deg) rotateX(1.2deg) scale(1.018)' : 'rotateY(0deg) rotateX(0deg) scale(1)',
  }
  const backCardStyle: CSSProperties = {
    backfaceVisibility: 'hidden',
    transform: shouldLiftCard
      ? 'translateZ(-16px) translateX(6px) translateY(5px) rotateY(8deg)'
      : 'translateZ(-12px) translateX(4px) translateY(4px) rotateY(6deg)',
  }
  const frontCardStyle: CSSProperties = {
    backfaceVisibility: 'hidden',
    transform: shouldLiftCard ? 'translateZ(10px)' : 'translateZ(7px)',
  }

  return (
    <div
      ref={panelRef}
      className={cn(
        'group absolute z-20 flex w-[18.25rem] max-h-[min(31rem,calc(100vh-5.5rem))] transform flex-col overflow-visible rounded-2xl transition-transform duration-200 ease-out',
        open && selectedNode ? 'translate-x-0' : 'translate-x-[120%]'
      )}
      style={{
        left: panelPosition?.x ?? undefined,
        top: panelPosition?.y ?? PANEL_TOP_OFFSET,
        perspective: '1400px',
      }}
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
    >
      {selectedNode ? (
        <div className="relative transition-transform duration-500 ease-[cubic-bezier(0.22,1,0.36,1)]" style={innerCardStyle}>
          <div
            aria-hidden="true"
            className={cn(
              'pointer-events-none absolute inset-0 -z-20 rounded-[1.45rem] bg-[radial-gradient(circle_at_top_left,rgba(255,255,255,0.74),rgba(204,254,255,0.34)_34%,transparent_66%),radial-gradient(circle_at_bottom_right,rgba(170,217,242,0.18),transparent_48%)] blur-xl transition-all duration-300',
              isDragging ? 'scale-[1.02] opacity-95' : 'opacity-70 group-hover:opacity-90'
            )}
          />
          <div
            aria-hidden="true"
            className={cn(
              'pointer-events-none absolute inset-0 -z-10 rounded-[1.35rem] border border-border/55 bg-[linear-gradient(145deg,rgba(255,255,255,0.48),rgba(244,248,252,0.28)_55%,rgba(204,254,255,0.18))] shadow-[12px_17px_51px_rgba(15,23,42,0.16)] backdrop-blur-[10px] transition-transform duration-500 ease-[cubic-bezier(0.22,1,0.36,1)]'
            )}
            style={backCardStyle}
          />
          <div
            className="overflow-hidden rounded-2xl border border-border/70 bg-[linear-gradient(180deg,rgba(252,253,255,0.78)_0%,rgba(245,248,250,0.58)_100%)] shadow-[12px_17px_51px_rgba(15,23,42,0.18)] backdrop-blur-[16px] transition-transform duration-500 ease-[cubic-bezier(0.22,1,0.36,1)]"
            style={frontCardStyle}
          >
          <div
            className={cn(
              'border-b border-border/55 bg-[linear-gradient(180deg,rgba(255,255,255,0.52)_0%,rgba(255,255,255,0.26)_100%)] px-3.5 py-3 select-none',
              isDragging ? 'cursor-grabbing' : 'cursor-grab'
            )}
            onPointerDown={handleDragStart}
            onPointerMove={handleDragMove}
            onPointerUp={handleDragEnd}
            onPointerCancel={handleDragEnd}
          >
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="mb-1.5 flex flex-wrap gap-1.5">
                  {summaryBadges.map((badge) => (
                    <span
                      key={`${badge.label}:${badge.value}`}
                      className={cn(
                        'inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium tracking-[0.02em]',
                        badge.className
                      )}
                    >
                      {badge.label === 'ID' ? <Database className="size-3" /> : null}
                      <span className="opacity-70">{badge.label}</span>
                      <span className="max-w-[7rem] truncate" title={badge.value}>
                        {badge.value}
                      </span>
                    </span>
                  ))}
                </div>
                <h2 className="line-clamp-2 text-[14px] font-semibold leading-5 text-foreground">
                  {selectedNode.label}
                </h2>
              </div>
              <button
                type="button"
                onClick={onClose}
                aria-label="关闭详情面板"
                className="rounded-xl border border-transparent bg-card/30 p-1 text-muted-foreground transition-all hover:border-black/5 hover:bg-card/55 hover:text-foreground"
                onPointerDown={(event) => event.stopPropagation()}
              >
                <X className="w-4 h-4" />
              </button>
            </div>
          </div>

          <div ref={detailScrollRef} className="flex-1 space-y-3 overflow-y-auto overscroll-contain p-3.5 no-scrollbar">
            <div className="grid grid-cols-4 gap-1.5">
              <Button
                variant="outline"
                onClick={onChat}
                className={cn(
                  quickActionBaseClass,
                  'border-[#c8edf1]/75 bg-[rgba(204,254,255,0.56)] hover:bg-[rgba(204,254,255,0.84)]'
                )}
              >
                <MessageSquare className="w-3.5 h-3.5 mr-1" />
                对话
              </Button>
              <Button
                variant="outline"
                onClick={onViewSource}
                className={cn(
                  quickActionBaseClass,
                  'border-[#d9defd]/75 bg-[rgba(238,240,255,0.68)] hover:bg-[rgba(238,240,255,0.9)]'
                )}
              >
                <FileText className="w-3.5 h-3.5 mr-1" />
                来源
              </Button>
              <Button
                variant="outline"
                onClick={onStartConnectMode}
                className={cn(
                  quickActionBaseClass,
                  'border-[#d3efdf]/75 bg-[rgba(223,255,236,0.58)] hover:bg-[rgba(223,255,236,0.88)]'
                )}
              >
                <LinkIcon className="w-3.5 h-3.5 mr-1" />
                连接
              </Button>
              <Button
                variant="outline"
                onClick={onDeleteNode}
                className="h-8 w-full rounded-lg border-destructive/20 bg-destructive/5 px-2 text-[11px] text-destructive shadow-none hover:border-destructive/35 hover:bg-destructive/10 hover:text-destructive"
              >
                <Trash2 className="w-3.5 h-3.5 mr-1" />
                删除
              </Button>
            </div>

            <Button
              variant="outline"
              onClick={onExpandNode}
              disabled={isLoading}
              className="h-8 w-full justify-start rounded-lg border-[#c8edf1]/75 bg-[rgba(204,254,255,0.42)] px-3 text-[11px] text-slate-700 shadow-none hover:bg-[rgba(204,254,255,0.76)] hover:text-slate-900"
            >
              <Network className="w-3 h-3 mr-1.5" />
              {isLoading ? '展开中...' : '展开邻居节点'}
            </Button>

            {dataSource === 'live' && selectedNode?.meta?.kind === 'entity' ? (
              <div className="grid grid-cols-2 gap-1.5">
                <Button
                  variant="outline"
                  onClick={onOpenMerge}
                  className="h-7.5 w-full justify-start rounded-lg border-[#efe5c9]/75 bg-[rgba(255,244,214,0.64)] px-2.5 text-[11px] text-slate-700 shadow-none hover:bg-[rgba(255,244,214,0.9)] hover:text-slate-900"
                >
                  <BoxSelect className="w-3 h-3 mr-1.5" />
                  合并
                </Button>
                <Button
                  variant="outline"
                  onClick={onOpenSplit}
                  className="h-7.5 w-full justify-start rounded-lg border-[#d9defd]/75 bg-[rgba(238,240,255,0.7)] px-2.5 text-[11px] text-slate-700 shadow-none hover:bg-[rgba(238,240,255,0.94)] hover:text-slate-900"
                >
                  <Box className="w-3 h-3 mr-1.5" />
                  拆分
                </Button>
              </div>
            ) : null}

            {lastResolutionActionId ? (
              <Button
                variant="outline"
                onClick={onUndoLastResolution}
                disabled={undoSubmitting}
                className="h-7.5 w-full justify-start rounded-lg border-primary/20 bg-primary/5 px-2.5 text-[11px] text-primary shadow-none hover:bg-primary/10 hover:text-primary"
              >
                <RefreshCw className="w-3 h-3 mr-1.5" />
                {undoSubmitting ? '撤销中…' : '撤销上次变更'}
              </Button>
            ) : null}

            <div className="space-y-2">
              <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
                <Info className="w-3 h-3 text-indigo-700/75" />
                属性详情
              </div>
              <div className="grid grid-cols-2 gap-1.5">
                {detailEntries.map(([key, value], index) => (
                  <div
                    key={key}
                    className={cn(
                      'rounded-lg border px-2.5 py-2',
                      DETAIL_TONE_CLASSES[index % DETAIL_TONE_CLASSES.length]
                    )}
                  >
                    <div className="mb-1 text-[11px] font-medium uppercase tracking-[0.06em] text-slate-700/78 capitalize">
                      {key}
                    </div>
                    <div className="min-w-0 break-words text-[11px] leading-4.5 text-foreground/88">
                      {typeof value === 'object' ? coerceTrimmedString(JSON.stringify(value)) || String(value) : String(value)}
                    </div>
                  </div>
                ))}
                {selectedNode.source ? (
                  <button
                    type="button"
                    onClick={onViewSource}
                    className={cn(
                      'col-span-2 rounded-lg border px-2.5 py-2 text-left transition-colors hover:brightness-[0.98] focus-ring',
                      DETAIL_TONE_CLASSES[0]
                    )}
                  >
                    <div className="mb-1 text-[11px] font-medium uppercase tracking-[0.08em] text-info/70">
                      文档来源
                    </div>
                    <div className="text-[11px] leading-4.5 text-info underline underline-offset-4">
                      {String(selectedNode.source)}
                    </div>
                  </button>
                ) : null}
              </div>
            </div>

            {dataSource === 'live' &&
            (selectedNode?.meta?.kind === 'entity' || selectedNode?.meta?.kind === 'event') ? (
              <div className="space-y-2">
                <button
                  type="button"
                  onClick={() => setIsKgDetailExpanded((value) => !value)}
                  className="flex w-full items-center justify-between rounded-xl border border-[#d9defd]/70 bg-[linear-gradient(180deg,rgba(255,255,255,0.82),rgba(241,245,255,0.82))] px-3 py-2 text-left transition-colors hover:bg-[linear-gradient(180deg,rgba(255,255,255,0.9),rgba(236,242,255,0.92))] focus-ring"
                >
                  <span className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
                    <Layers className="w-3 h-3 text-amber-700/80" />
                    KG Detail
                  </span>
                  <span className="inline-flex items-center gap-1 text-[11px] font-medium text-slate-600">
                    {isKgDetailExpanded ? '收起' : '展开'}
                    <ChevronDown className={cn('h-3.5 w-3.5 transition-transform duration-200', isKgDetailExpanded ? 'rotate-180' : null)} />
                  </span>
                </button>

                {isKgDetailExpanded ? (
                  <GraphNodeKgDetail
                    selectedNode={selectedNode}
                    kgNodeDetailLoading={kgNodeDetailLoading}
                    kgNodeDetail={kgNodeDetail}
                    entityAliasesLoading={entityAliasesLoading}
                    entityAliases={entityAliases}
                    aliasDraft={aliasDraft}
                    aliasSaving={aliasSaving}
                    aliasSuggestionsLoading={aliasSuggestionsLoading}
                    aliasSuggestions={aliasSuggestions}
                    onAliasDraftChange={onAliasDraftChange}
                    onSaveAlias={onSaveAlias}
                    onRequestDeleteAlias={onRequestDeleteAlias}
                    onMergeAliasSuggestion={onMergeAliasSuggestion}
                  />
                ) : (
                  <div className="rounded-lg border border-[#d9defd]/65 bg-[rgba(238,240,255,0.4)] px-3 py-2 text-[11px] text-muted-foreground">
                    展开查看最近事件、邻居、别名和合并建议。
                  </div>
                )}
              </div>
            ) : null}
          </div>
          </div>
        </div>
      ) : null}
    </div>
  )
}
