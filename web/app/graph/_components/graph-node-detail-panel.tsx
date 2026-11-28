'use client'

import {
  useEffect,
  useRef,
  useState,
  type CSSProperties,
  type PointerEvent as ReactPointerEvent,
  type RefObject,
} from 'react'

import {
  Box,
  BoxSelect,
  ChevronDown,
  Database,
  FileText,
  Info,
  Layers,
  Link as LinkIcon,
  MessageSquare,
  Network,
  RefreshCw,
  Trash2,
  X,
} from '@/components/icons'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { WorkspaceNotice } from '@/components/ui/operational-workspace'
import { getGraphNodeKind, getGraphNodeType } from '@/app/graph/graph-page-utils'
import type {
  KGEntityAliasItem,
  KGEntityAliasSuggestionItem,
  KGEntityDetailResponse,
  KGEventDetailResponse,
} from '@/types'
import { cn } from '@/lib/utils'

import type { GraphNodeLike } from '../graph-page-utils'
import styles from './graph-workspace.module.css'

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
  const { x, y, containerWidth, containerHeight, panelWidth, panelHeight } = args

  return {
    x: Math.min(
      Math.max(PANEL_SIDE_MARGIN, x),
      Math.max(PANEL_SIDE_MARGIN, containerWidth - panelWidth - PANEL_SIDE_MARGIN),
    ),
    y: Math.min(Math.max(PANEL_MIN_TOP, y), Math.max(PANEL_MIN_TOP, containerHeight - panelHeight - PANEL_SIDE_MARGIN)),
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
  kgNodeDetailError: string | null
  onRetryNodeDetail: () => void
  entityAliasesLoading: boolean
  entityAliasesError: string | null
  entityAliases: KGEntityAliasItem[]
  aliasDraft: string
  aliasSaving: boolean
  aliasSuggestionsLoading: boolean
  aliasSuggestionsError: string | null
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
  onOpenSplit?: () => void
  onUndoLastResolution: () => void
  onAliasDraftChange: (value: string) => void
  onSaveAlias: () => void
  onRequestDeleteAlias: (row: KGEntityAliasItem) => void
  onMergeAliasSuggestion: (row: KGEntityAliasSuggestionItem) => void
}>

type GraphNodeKgDetailProps = Pick<
  GraphNodeDetailPanelProps,
  | 'kgNodeDetailLoading'
  | 'kgNodeDetail'
  | 'entityAliasesLoading'
  | 'entityAliasesError'
  | 'entityAliases'
  | 'aliasDraft'
  | 'aliasSaving'
  | 'aliasSuggestionsLoading'
  | 'aliasSuggestionsError'
  | 'aliasSuggestions'
  | 'onAliasDraftChange'
  | 'onSaveAlias'
  | 'onRequestDeleteAlias'
  | 'onMergeAliasSuggestion'
>

function GraphNodeKgDetail({
  kgNodeDetailLoading,
  kgNodeDetail,
  entityAliasesLoading,
  entityAliasesError,
  entityAliases,
  aliasDraft,
  aliasSaving,
  aliasSuggestionsLoading,
  aliasSuggestionsError,
  aliasSuggestions,
  onAliasDraftChange,
  onSaveAlias,
  onRequestDeleteAlias,
  onMergeAliasSuggestion,
}: GraphNodeKgDetailProps) {
  if (kgNodeDetailLoading && kgNodeDetail === null) {
    return (
      <div className="rounded-lg border border-info/30 bg-info/10 p-2.5 text-[11px] text-muted-foreground">
        Loading...
      </div>
    )
  }

  if (kgNodeDetail === null) return null

  if ('event' in kgNodeDetail) {
    const eventDetail = kgNodeDetail
    return (
      <div className={styles.evidenceCard}>
        {eventDetail.event.content ? (
          <blockquote className={styles.evidenceQuote}>{eventDetail.event.content}</blockquote>
        ) : null}
        <div className={styles.inspectorSectionLabel}>Entities</div>
        <div className="space-y-1.5">
          {eventDetail.entities.slice(0, 12).map((row) => (
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

  const entityDetail = kgNodeDetail
  let aliasContent: React.ReactNode
  if (entityAliasesLoading) {
    aliasContent = <div className="text-[11px] text-muted-foreground">Loading...</div>
  } else if (entityAliasesError !== null) {
    aliasContent = (
      <div role="alert" className="text-[11px] text-destructive">
        {entityAliasesError}
      </div>
    )
  } else if (entityAliases.length === 0) {
    aliasContent = <div className="text-[11px] text-muted-foreground">No aliases</div>
  } else {
    aliasContent = (
      <div className="flex flex-wrap gap-1.5">
        {entityAliases.slice(0, 12).map((alias) => (
          <div
            key={alias.id}
            className="inline-flex items-center gap-1 rounded-full border border-border/65 bg-background/72 px-2 py-0.5 text-[11px]"
          >
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
    )
  }

  let aliasSuggestionsContent: React.ReactNode
  if (aliasSuggestionsLoading) {
    aliasSuggestionsContent = <div className="text-[11px] text-muted-foreground">Loading...</div>
  } else if (aliasSuggestionsError !== null) {
    aliasSuggestionsContent = (
      <div role="alert" className="text-[11px] text-destructive">
        {aliasSuggestionsError}
      </div>
    )
  } else if (aliasSuggestions.length === 0) {
    aliasSuggestionsContent = <div className="text-[11px] text-muted-foreground">No suggestions</div>
  } else {
    aliasSuggestionsContent = (
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
              className="h-6.5 border-primary/30 bg-background/72 px-2 text-[11px] shadow-none hover:bg-background"
              onClick={() => onMergeAliasSuggestion(suggestion)}
            >
              合并
            </Button>
          </div>
        ))}
      </div>
    )
  }

  return (
    <div className="space-y-2.5">
      <div className={styles.evidenceCard}>
        <div className={styles.inspectorSectionLabel}>Recent Events</div>
        <div className="space-y-1.5">
          {entityDetail.events.slice(0, 6).map((ev) => (
            <div key={ev.id}>
              <div className="truncate text-[11px] text-foreground" title={ev.title}>
                {ev.title}
              </div>
              {ev.content ? <blockquote className={styles.evidenceQuote}>{ev.content}</blockquote> : null}
            </div>
          ))}
        </div>
      </div>

      <div className={styles.propertyCard}>
        <div className={styles.inspectorSectionLabel}>Top Neighbors</div>
        <div className="space-y-1.5">
          {entityDetail.neighbors.slice(0, 8).map((neighbor) => (
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

      <div className={styles.propertyCard}>
        <div className={styles.inspectorSectionLabel}>Aliases</div>
        {aliasContent}

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
            className="h-7.5 border-warning/30 bg-background/72 px-2.5 text-[11px] shadow-none hover:bg-background"
            onClick={onSaveAlias}
            disabled={aliasSaving || !aliasDraft.trim()}
          >
            添加
          </Button>
        </div>
      </div>

      <div className={styles.propertyCard}>
        <div className={styles.inspectorSectionLabel}>Suggestions</div>
        {aliasSuggestionsContent}
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
  kgNodeDetailError,
  onRetryNodeDetail,
  entityAliasesLoading,
  entityAliasesError,
  entityAliases,
  aliasDraft,
  aliasSaving,
  aliasSuggestionsLoading,
  aliasSuggestionsError,
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
    selectedNode === null ? null : { label: 'ID', value: selectedNode.id, className: styles.neutralBadge },
    nodeKind ? { label: '类别', value: getKindLabel(nodeKind), className: styles.typeBadge } : null,
    nodeType ? { label: '类型', value: nodeType, className: styles.typeBadge } : null,
    selectedNode?.group == null
      ? null
      : { label: '组', value: String(selectedNode.group), className: styles.neutralBadge },
    selectedNode?.val == null
      ? null
      : { label: '权重', value: String(selectedNode.val), className: styles.neutralBadge },
  ].filter((badge) => badge !== null)

  const detailEntries = selectedNode
    ? Object.entries(selectedNode).filter(([key, value]) => {
        if (OMITTED_NODE_KEYS.has(key) || key.startsWith('__')) return false
        if (value == null) return false
        if (typeof value === 'string' && !value.trim()) return false
        return true
      })
    : []

  const quickActionBaseClass = cn(styles.inspectorAction, 'h-8 w-full rounded-lg px-2 text-[11px] shadow-none')
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
  const [isHovered, setIsHovered] = useState(false)

  useEffect(() => {
    if (open && selectedNode?.id) panelRef.current?.focus()
  }, [open, selectedNode?.id])

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

    if (panelPosition?.x !== nextPosition.x || panelPosition.y !== nextPosition.y) {
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
    if (dragState?.pointerId !== event.pointerId) return
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
      }),
    )
  }

  const handleDragEnd = (event: ReactPointerEvent<HTMLDivElement>) => {
    const dragState = dragStateRef.current
    if (dragState?.pointerId !== event.pointerId) return

    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId)
    }

    dragStateRef.current = null
    setIsDragging(false)
  }

  const shouldLiftCard = isDragging || isHovered
  const innerCardStyle: CSSProperties = {
    transform: shouldLiftCard ? 'translateY(-1px)' : 'none',
  }
  const undoActionLabel = undoSubmitting ? '撤销中…' : '撤销上次变更'
  const selectedNodeSourceLabel =
    typeof selectedNode?.source === 'string' || typeof selectedNode?.source === 'number'
      ? String(selectedNode.source)
      : ''
  let detailContent: React.ReactNode = null

  if (selectedNode) {
    let kgDetailSection: React.ReactNode = null
    if (dataSource === 'live' && (nodeKind === 'entity' || nodeKind === 'event')) {
      kgDetailSection = (
        <details key={selectedNode.id} className="group/kg-detail space-y-2">
          <summary className="focus-ring flex w-full cursor-pointer list-none items-center justify-between rounded-xl border border-border/60 bg-card px-3 py-2 text-left transition-colors hover:bg-muted/30 [&::-webkit-details-marker]:hidden">
            <span className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
              <Layers className="w-3 h-3 text-warning/80" />
              节点详情
            </span>
            <ChevronDown className="h-3.5 w-3.5 text-muted-foreground transition-transform group-open/kg-detail:rotate-180 motion-reduce:transition-none" />
          </summary>
          {kgNodeDetailError !== null ? (
            <WorkspaceNotice retry={onRetryNodeDetail} pending={kgNodeDetailLoading}>
              {kgNodeDetailError}
            </WorkspaceNotice>
          ) : null}
          <GraphNodeKgDetail
            kgNodeDetailLoading={kgNodeDetailLoading}
            kgNodeDetail={kgNodeDetail}
            entityAliasesLoading={entityAliasesLoading}
            entityAliasesError={entityAliasesError}
            entityAliases={entityAliases}
            aliasDraft={aliasDraft}
            aliasSaving={aliasSaving}
            aliasSuggestionsLoading={aliasSuggestionsLoading}
            aliasSuggestionsError={aliasSuggestionsError}
            aliasSuggestions={aliasSuggestions}
            onAliasDraftChange={onAliasDraftChange}
            onSaveAlias={onSaveAlias}
            onRequestDeleteAlias={onRequestDeleteAlias}
            onMergeAliasSuggestion={onMergeAliasSuggestion}
          />
        </details>
      )
    }

    detailContent = (
      <div className="relative transition-transform duration-300 ease-out" style={innerCardStyle}>
        <div className={cn(styles.inspectorCard, 'transition-transform duration-300 ease-out')}>
          <div
            className={cn(
              styles.inspectorHeader,
              'px-3.5 py-3 select-none',
              isDragging ? 'cursor-grabbing' : 'cursor-grab',
            )}
            onPointerDown={handleDragStart}
            onPointerMove={handleDragMove}
            onPointerUp={handleDragEnd}
            onPointerCancel={handleDragEnd}
          >
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <i className={styles.iconTray} aria-hidden="true">
                  <Network />
                </i>
                <div className="mb-1.5 flex flex-wrap gap-1.5">
                  {summaryBadges.map((badge) => (
                    <span
                      key={`${badge.label}:${badge.value}`}
                      className={cn('inline-flex items-center gap-1 text-[11px] font-medium', badge.className)}
                    >
                      {badge.label === 'ID' ? <Database className="size-3" /> : null}
                      <span>{badge.label}</span>
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
                className="rounded-xl border border-border/60 bg-card p-1 text-muted-foreground transition-all hover:bg-muted/40 hover:text-foreground"
                onPointerDown={(event) => event.stopPropagation()}
              >
                <X className="w-4 h-4" />
              </button>
            </div>
          </div>

          <div ref={detailScrollRef} className="flex-1 space-y-3 overflow-y-auto overscroll-contain p-3.5 no-scrollbar">
            <div className="grid grid-cols-4 gap-1.5">
              <Button variant="outline" onClick={onChat} className={quickActionBaseClass}>
                <MessageSquare className="w-3.5 h-3.5 mr-1" />
                对话
              </Button>
              <Button variant="outline" onClick={onViewSource} className={quickActionBaseClass}>
                <FileText className="w-3.5 h-3.5 mr-1" />
                来源
              </Button>
              <Button variant="outline" onClick={onStartConnectMode} className={quickActionBaseClass}>
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
              className={cn(quickActionBaseClass, 'justify-start px-3')}
            >
              <Network className="w-3 h-3 mr-1.5" />
              {isLoading ? '展开中...' : '展开邻居节点'}
            </Button>

            {dataSource === 'live' && nodeKind === 'entity' ? (
              <div className="grid grid-cols-2 gap-1.5">
                <Button
                  variant="outline"
                  onClick={onOpenMerge}
                  className={cn(quickActionBaseClass, 'justify-start px-2.5')}
                >
                  <BoxSelect className="w-3 h-3 mr-1.5" />
                  合并
                </Button>
                <Button
                  variant="outline"
                  onClick={onOpenSplit}
                  disabled={onOpenSplit === undefined}
                  className={cn(quickActionBaseClass, 'justify-start px-2.5')}
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
                {undoActionLabel}
              </Button>
            ) : null}

            <div className="space-y-2">
              <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
                <Info className="w-3 h-3 text-primary/75" />
                属性详情
              </div>
              <div className="grid grid-cols-2 gap-1.5">
                {detailEntries.map(([key, value]) => (
                  <div key={key} className={styles.propertyCard}>
                    <div className="mb-1 text-[11px] font-medium uppercase tracking-[0.06em] text-foreground/85 capitalize">
                      {key}
                    </div>
                    <div className="min-w-0 break-words text-[11px] leading-4.5 text-foreground/88">
                      {typeof value === 'object' ? JSON.stringify(value) : String(value)}
                    </div>
                  </div>
                ))}
                {selectedNodeSourceLabel !== '' ? (
                  <button
                    type="button"
                    onClick={onViewSource}
                    className={cn(styles.evidenceCard, 'col-span-2 text-left focus-ring')}
                  >
                    <div className={styles.inspectorSectionLabel}>文档来源</div>
                    <div className="text-[11px] leading-4.5 underline underline-offset-4">
                      {selectedNodeSourceLabel}
                    </div>
                  </button>
                ) : null}
              </div>
            </div>

            {kgDetailSection}
          </div>
        </div>
      </div>
    )
  }

  return (
    <section
      ref={panelRef}
      aria-label="图谱节点详情"
      tabIndex={-1}
      data-kind={nodeKind}
      data-entity-type={nodeType}
      className={cn(
        styles.nodeInspector,
        'group absolute z-20 flex w-[18.25rem] max-h-[min(31rem,calc(100vh-5.5rem))] transform flex-col overflow-visible rounded-2xl transition-transform duration-200 ease-out',
        open && selectedNode ? 'translate-x-0' : 'translate-x-[120%]',
      )}
      style={{
        left: panelPosition?.x ?? undefined,
        top: panelPosition?.y ?? PANEL_TOP_OFFSET,
      }}
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
    >
      {detailContent}
    </section>
  )
}
