'use client'

import type { RefObject } from 'react'

import { Box, BoxSelect, Database, FileText, Info, Layers, Link as LinkIcon, MessageSquare, Network, RefreshCw, Trash2, X } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
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
])

type GraphNodeDetailPanelProps = Readonly<{
  open: boolean
  selectedNode: GraphNodeLike | null
  detailScrollRef: RefObject<HTMLDivElement | null>
  dataSource: 'live' | 'mock' | 'file'
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
      <div className="text-xs text-muted-foreground bg-muted rounded-xl p-3 border border-border">
        Loading...
      </div>
    )
  }

  if (!kgNodeDetail) {
    return (
      <div className="text-xs text-muted-foreground bg-muted rounded-xl p-3 border border-border">
        No KG detail available
      </div>
    )
  }

  if (selectedNode?.meta?.kind !== 'entity') {
    const eventDetail = kgNodeDetail as KGEventDetailResponse
    return (
      <div className="bg-muted rounded-xl p-3 border border-border">
        <div className="text-[10px] font-medium text-muted-foreground mb-2">Entities</div>
        <div className="space-y-1">
          {eventDetail.entities?.slice(0, 12)?.map((row) => (
            <div key={row.entity.id} className="flex items-center justify-between gap-2 text-xs">
              <span className="text-foreground truncate" title={row.entity.name}>
                {row.entity.name || row.entity.id}
              </span>
              <span className="text-muted-foreground">{row.role || row.entity.type}</span>
            </div>
          ))}
        </div>
      </div>
    )
  }

  const entityDetail = kgNodeDetail as KGEntityDetailResponse

  return (
    <div className="space-y-3">
      <div className="bg-muted rounded-xl p-3 border border-border">
        <div className="text-[10px] font-medium text-muted-foreground mb-1">Recent Events</div>
        <div className="space-y-1">
          {entityDetail.events?.slice(0, 6)?.map((ev) => (
            <div key={ev.id} className="text-xs text-foreground truncate" title={ev.title}>
              {ev.title}
            </div>
          ))}
        </div>
      </div>

      <div className="bg-muted rounded-xl p-3 border border-border">
        <div className="text-[10px] font-medium text-muted-foreground mb-1">Top Neighbors</div>
        <div className="space-y-1">
          {entityDetail.neighbors?.slice(0, 8)?.map((neighbor) => (
            <div key={neighbor.entity_id} className="flex items-center justify-between gap-2 text-xs">
              <span className="text-foreground truncate" title={neighbor.name}>
                {neighbor.name || neighbor.entity_id}
              </span>
              <span className="text-muted-foreground font-mono">{neighbor.count}</span>
            </div>
          ))}
        </div>
      </div>

      <div className="bg-muted rounded-xl p-3 border border-border">
        <div className="text-[10px] font-medium text-muted-foreground mb-2">Aliases</div>
        {entityAliasesLoading ? (
          <div className="text-xs text-muted-foreground">Loading...</div>
        ) : entityAliases.length === 0 ? (
          <div className="text-xs text-muted-foreground">No aliases</div>
        ) : (
          <div className="flex flex-wrap gap-2">
            {entityAliases.slice(0, 12).map((alias) => (
              <div key={alias.id} className="inline-flex items-center gap-1 rounded-full bg-background/60 px-2 py-1 text-[11px] border border-border">
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

        <div className="mt-3 flex items-center gap-2">
          <Input
            value={aliasDraft}
            onChange={(event) => onAliasDraftChange(event.target.value)}
            placeholder="Add alias…"
            className="h-8 text-xs"
          />
          <Button
            type="button"
            variant="outline"
            className="h-8 text-xs"
            onClick={onSaveAlias}
            disabled={aliasSaving || !aliasDraft.trim()}
          >
            添加
          </Button>
        </div>
      </div>

      <div className="bg-muted rounded-xl p-3 border border-border">
        <div className="text-[10px] font-medium text-muted-foreground mb-2">Suggestions</div>
        {aliasSuggestionsLoading ? (
          <div className="text-xs text-muted-foreground">Loading...</div>
        ) : aliasSuggestions.length === 0 ? (
          <div className="text-xs text-muted-foreground">No suggestions</div>
        ) : (
          <div className="space-y-1">
            {aliasSuggestions.slice(0, 6).map((suggestion) => (
              <div key={suggestion.entity_id} className="flex items-center justify-between gap-2 text-xs">
                <span className="text-foreground truncate" title={suggestion.name}>
                  {suggestion.name || suggestion.entity_id}
                </span>
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  className="h-7 px-2 text-[11px]"
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
  return (
    <div
      className={cn(
        'absolute top-4 right-4 bottom-24 w-80 bg-card rounded-2xl shadow-strong border border-border transform transition-transform duration-200 ease-out z-20 flex flex-col overflow-hidden',
        open && selectedNode ? 'translate-x-0' : 'translate-x-[120%]'
      )}
    >
      {selectedNode ? (
        <>
          <div className="p-5 border-b border-border flex items-start justify-between bg-card">
            <div>
              <h2 className="font-bold text-lg text-foreground line-clamp-2">{selectedNode.label}</h2>
              <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[10px] font-medium bg-info/10 text-info mt-2 border border-info/20">
                <Database className="w-3 h-3" />
                ID: {selectedNode.id}
              </span>
            </div>
            <button
              type="button"
              onClick={onClose}
              aria-label="关闭详情面板"
              className="text-muted-foreground hover:text-muted-foreground hover:bg-muted rounded-lg p-1 transition-colors"
            >
              <X className="w-5 h-5" />
            </button>
          </div>

          <div ref={detailScrollRef} className="flex-1 overflow-y-auto overscroll-contain no-scrollbar p-5 space-y-6">
            <div className="grid grid-cols-2 gap-3">
              <Button variant="info" onClick={onChat} className="w-full">
                <MessageSquare className="w-4 h-4 mr-2" />
                对话
              </Button>
              <Button variant="outline" onClick={onViewSource} className="w-full">
                <FileText className="w-4 h-4 mr-2" />
                来源
              </Button>
            </div>

            {dataSource === 'live' &&
            (selectedNode?.meta?.kind === 'entity' || selectedNode?.meta?.kind === 'event') ? (
              <div>
                <h3 className="text-xs font-semibold text-muted-foreground uppercase mb-3 flex items-center gap-2">
                  <Network className="w-3 h-3" />
                  KG Detail
                </h3>
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
              </div>
            ) : null}

            <div>
              <h3 className="text-xs font-semibold text-muted-foreground uppercase mb-3 flex items-center gap-2">
                <Info className="w-3 h-3" />
                属性详情
              </h3>
              <div className="space-y-3">
                {Object.entries(selectedNode)
                  .filter(([key]) => !OMITTED_NODE_KEYS.has(key))
                  .map(([key, value]) => (
                    <div key={key} className="bg-muted rounded-xl p-3 border border-border">
                      <span className="block text-xs font-medium text-muted-foreground mb-1 capitalize">{key}</span>
                      <span className="block text-sm text-foreground break-words">{String(value)}</span>
                    </div>
                  ))}

                {selectedNode.source ? (
                  <div className="rounded-xl border border-info/25 bg-info/10 p-3">
                    <span className="block text-xs font-medium text-info mb-1 capitalize">Source Document</span>
                    <button
                      type="button"
                      onClick={onViewSource}
                      className="block w-full text-left text-sm text-info break-words underline underline-offset-4 hover:text-info/80 rounded-md focus-ring"
                    >
                      {String(selectedNode.source)}
                    </button>
                  </div>
                ) : null}
              </div>
            </div>

            <div>
              <h3 className="text-xs font-semibold text-muted-foreground uppercase mb-3 flex items-center gap-2">
                <Layers className="w-3 h-3" />
                操作
              </h3>
              <div className="space-y-2">
                <Button
                  variant="outline"
                  onClick={onExpandNode}
                  disabled={isLoading}
                  className="w-full justify-start text-xs h-9 hover:bg-info/10 hover:text-info text-muted-foreground"
                >
                  <Network className="w-3 h-3 mr-2" />
                  {isLoading ? '展开中...' : '展开邻居节点'}
                </Button>

                <div className="grid grid-cols-2 gap-2">
                  <Button
                    variant="outline"
                    onClick={onStartConnectMode}
                    className="w-full justify-start text-xs h-9 hover:bg-success/10 hover:text-success hover:border-success/20 text-muted-foreground"
                  >
                    <LinkIcon className="w-3 h-3 mr-2" />
                    连接
                  </Button>
                  <Button
                    variant="outline"
                    onClick={onDeleteNode}
                    className="w-full justify-start text-xs h-9 hover:bg-destructive/10 hover:text-destructive hover:border-destructive/20 text-muted-foreground"
                  >
                    <Trash2 className="w-3 h-3 mr-2" />
                    删除
                  </Button>
                </div>

                {dataSource === 'live' && selectedNode?.meta?.kind === 'entity' ? (
                  <div className="grid grid-cols-2 gap-2">
                    <Button
                      variant="outline"
                      onClick={onOpenMerge}
                      className="w-full justify-start text-xs h-9 hover:bg-warning/10 hover:text-warning hover:border-warning/20 text-muted-foreground"
                    >
                      <BoxSelect className="w-3 h-3 mr-2" />
                      合并
                    </Button>
                    <Button
                      variant="outline"
                      onClick={onOpenSplit}
                      className="w-full justify-start text-xs h-9 hover:bg-accent hover:text-accent-foreground hover:border-accent text-muted-foreground"
                    >
                      <Box className="w-3 h-3 mr-2" />
                      拆分
                    </Button>
                  </div>
                ) : null}

                {lastResolutionActionId ? (
                  <Button
                    variant="outline"
                    onClick={onUndoLastResolution}
                    disabled={undoSubmitting}
                    className="w-full justify-start text-xs h-9 hover:bg-primary/10 hover:text-primary text-muted-foreground"
                  >
                    <RefreshCw className="w-3 h-3 mr-2" />
                    {undoSubmitting ? '撤销中…' : '撤销上次变更'}
                  </Button>
                ) : null}
              </div>
            </div>
          </div>
        </>
      ) : null}
    </div>
  )
}
