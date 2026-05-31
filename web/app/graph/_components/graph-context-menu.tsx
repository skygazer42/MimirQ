'use client'

import { Copy, FileText, Info, Layers, Maximize, MessageSquare, Route, Trash2, Type, X, Link as LinkIcon } from 'lucide-react'

import { Button } from '@/components/ui/button'

import {
  type GraphContextMenuState,
  type GraphLinkLike,
  type GraphNodeLike,
  getGraphLinkPredicate,
} from '../graph-page-utils'

type GraphContextMenuProps = Readonly<{
  contextMenu: GraphContextMenuState | null
  viewMode: '2d' | '3d'
  showEdgeLabels: boolean
  onClose: () => void
  onExpandNode: (nodeId: string) => void
  onStartPathFromNode: (node: GraphNodeLike) => void
  onStartConnectFromNode: (node: GraphNodeLike) => void
  onChatWithNode: (node: GraphNodeLike) => void
  onViewSourceForNode: (node: GraphNodeLike) => void
  onCopyNodeId: (nodeId: string) => void
  onDeleteNode: (node: GraphNodeLike) => void
  onOpenLinkDetail: (link: GraphLinkLike) => void
  onCopyLinkPredicate: (predicate: string) => void
  onZoomToFit: () => void
  onClearHighlights: () => void
  onToggleShowEdgeLabels: () => void
}>

export function GraphContextMenu({
  contextMenu,
  viewMode,
  showEdgeLabels,
  onClose,
  onExpandNode,
  onStartPathFromNode,
  onStartConnectFromNode,
  onChatWithNode,
  onViewSourceForNode,
  onCopyNodeId,
  onDeleteNode,
  onOpenLinkDetail,
  onCopyLinkPredicate,
  onZoomToFit,
  onClearHighlights,
  onToggleShowEdgeLabels,
}: GraphContextMenuProps) {
  if (!contextMenu) return null

  return (
    <div
      role="menu"
      aria-label="图谱上下文菜单"
      tabIndex={-1}
      className="absolute z-30"
      style={{ left: contextMenu.x, top: contextMenu.y }}
      onMouseDown={(e) => e.stopPropagation()}
      onContextMenu={(e) => e.preventDefault()}
    >
      <div className="w-64 overflow-hidden rounded-xl border border-border/60 bg-card/95 shadow-strong backdrop-blur-sm">
        {contextMenu.target.type === 'node' ? (
          (() => {
            const node = contextMenu.target.node
            return (
              <div>
                <div className="border-b border-border/60 bg-muted/30 px-3 py-2">
                  <div className="text-[11px] font-medium uppercase text-muted-foreground">Node</div>
                  <div className="truncate text-sm font-semibold text-foreground">
                    {String(node?.label || node?.id || 'Node')}
                  </div>
                  <div className="truncate font-mono text-[11px] text-muted-foreground">
                    {String(node?.id || '')}
                  </div>
                </div>
                <div className="p-1">
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    className="h-8 w-full justify-start"
                    onClick={() => {
                      onClose()
                      onExpandNode(String(node?.id || ''))
                    }}
                  >
                    <Layers className="w-4 h-4 mr-2" />
                    展开邻居
                  </Button>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    className="h-8 w-full justify-start"
                    onClick={() => {
                      onClose()
                      onStartPathFromNode(node)
                    }}
                  >
                    <Route className="w-4 h-4 mr-2" />
                    查找路径
                  </Button>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    className="h-8 w-full justify-start"
                    onClick={() => {
                      onClose()
                      onStartConnectFromNode(node)
                    }}
                  >
                    <LinkIcon className="w-4 h-4 mr-2" />
                    连线
                  </Button>
                  <div className="my-1 h-px bg-border/60" />
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    className="h-8 w-full justify-start"
                    onClick={() => {
                      onClose()
                      onChatWithNode(node)
                    }}
                  >
                    <MessageSquare className="w-4 h-4 mr-2" />
                    对话
                  </Button>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    className="h-8 w-full justify-start"
                    onClick={() => {
                      onClose()
                      onViewSourceForNode(node)
                    }}
                  >
                    <FileText className="w-4 h-4 mr-2" />
                    来源
                  </Button>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    className="h-8 w-full justify-start"
                    onClick={() => {
                      onClose()
                      onCopyNodeId(String(node?.id || ''))
                    }}
                  >
                    <Copy className="w-4 h-4 mr-2" />
                    复制 ID
                  </Button>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    className="h-8 w-full justify-start text-destructive hover:text-destructive"
                    onClick={() => {
                      onClose()
                      onDeleteNode(node)
                    }}
                  >
                    <Trash2 className="w-4 h-4 mr-2" />
                    删除
                  </Button>
                </div>
              </div>
            )
          })()
        ) : contextMenu.target.type === 'link' ? (
          (() => {
            const link = contextMenu.target.link
            const predicate = getGraphLinkPredicate(link)
            return (
              <div>
                <div className="border-b border-border/60 bg-muted/30 px-3 py-2">
                  <div className="text-[11px] font-medium uppercase text-muted-foreground">Link</div>
                  <div className="truncate text-sm font-semibold text-foreground">
                    {predicate || 'Relationship'}
                  </div>
                  <div className="truncate font-mono text-[11px] text-muted-foreground">
                    {typeof link?.id === 'string' || typeof link?.id === 'number'
                      ? String(link.id)
                      : typeof link?.meta?.id === 'string' || typeof link?.meta?.id === 'number'
                        ? String(link.meta.id)
                        : ''}
                  </div>
                </div>
                <div className="p-1">
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    className="h-8 w-full justify-start"
                    onClick={() => {
                      onClose()
                      onOpenLinkDetail(link)
                    }}
                  >
                    <Info className="w-4 h-4 mr-2" />
                    查看详情
                  </Button>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    className="h-8 w-full justify-start"
                    onClick={() => {
                      onClose()
                      onCopyLinkPredicate(predicate)
                    }}
                  >
                    <Copy className="w-4 h-4 mr-2" />
                    复制 Predicate
                  </Button>
                </div>
              </div>
            )
          })()
        ) : (
          <div>
            <div className="border-b border-border/60 bg-muted/30 px-3 py-2">
              <div className="text-[11px] font-medium uppercase text-muted-foreground">Graph</div>
              <div className="truncate text-sm font-semibold text-foreground">
                {viewMode === '3d' ? '3D View' : '2D View'}
              </div>
            </div>
            <div className="p-1">
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="h-8 w-full justify-start"
                onClick={() => {
                  onClose()
                  onZoomToFit()
                }}
              >
                <Maximize className="w-4 h-4 mr-2" />
                适应屏幕
              </Button>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="h-8 w-full justify-start"
                onClick={() => {
                  onClose()
                  onClearHighlights()
                }}
              >
                <X className="w-4 h-4 mr-2" />
                清除高亮
              </Button>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="h-8 w-full justify-start"
                onClick={() => {
                  onClose()
                  onToggleShowEdgeLabels()
                }}
              >
                <Type className="w-4 h-4 mr-2" />
                {showEdgeLabels ? '隐藏连线标签' : '显示连线标签'}
              </Button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
