'use client'

import type { RefObject } from 'react'

import { Share2, Upload } from 'lucide-react'

import { GraphViewer, type GraphViewerRef, type LayoutMode } from '@/components/graph/graph-viewer'
import { KnowledgeGraph3D, type KnowledgeGraph3DRef } from '@/components/graph/force-graph-3d'
import { Button } from '@/components/ui/button'
import { EmptyState } from '@/components/ui/empty-state'
import type { GraphData } from '@/lib/graph-parser'

import type { GraphLinkLike, GraphNodeLike } from '../graph-page-utils'

type GraphCanvasProps = Readonly<{
  viewportRef: RefObject<HTMLDivElement | null>
  graph2dRef: RefObject<GraphViewerRef | null>
  graph3dRef: RefObject<KnowledgeGraph3DRef | null>
  isDark: boolean
  graphRenderData: GraphData
  viewMode: '2d' | '3d'
  graphViewportWidth: number
  graphViewportHeight: number
  selectedNodeId: string | null
  highlightedNodeIds: Set<string>
  highlightedLinkIds: Set<string>
  showEdgeLabels: boolean
  layoutMode: LayoutMode
  isLoading: boolean
  onNodeClick: (node: GraphNodeLike) => void
  onNodeRightClick: (node: GraphNodeLike, event: MouseEvent) => void
  onLinkClick: (link: GraphLinkLike) => void
  onLinkRightClick: (link: GraphLinkLike, event: MouseEvent) => void
  onBackgroundClick: () => void
  onBackgroundRightClick: (event: MouseEvent) => void
  onLoadMock: () => void
  onTriggerFileUpload: () => void
}>

export function GraphCanvas({
  viewportRef,
  graph2dRef,
  graph3dRef,
  isDark,
  graphRenderData,
  viewMode,
  graphViewportWidth,
  graphViewportHeight,
  selectedNodeId,
  highlightedNodeIds,
  highlightedLinkIds,
  showEdgeLabels,
  layoutMode,
  isLoading,
  onNodeClick,
  onNodeRightClick,
  onLinkClick,
  onLinkRightClick,
  onBackgroundClick,
  onBackgroundRightClick,
  onLoadMock,
  onTriggerFileUpload,
}: GraphCanvasProps) {
  return (
    <div ref={viewportRef} className="flex-1 w-full relative bg-background overflow-hidden min-h-[500px]">
      <div
        className="absolute inset-0 z-0 opacity-[0.4]"
        style={{
          backgroundImage: isDark
            ? 'radial-gradient(rgba(148, 163, 184, 0.16) 1px, transparent 1px)'
            : 'radial-gradient(rgba(203, 213, 225, 0.9) 1px, transparent 1px)',
          backgroundSize: '24px 24px',
        }}
      />

      {graphRenderData.nodes.length > 0 ? (
        viewMode === '3d' ? (
          graphViewportWidth > 0 && graphViewportHeight > 0 ? (
            <KnowledgeGraph3D
              ref={graph3dRef}
              data={graphRenderData}
              width={graphViewportWidth}
              height={graphViewportHeight}
              onNodeClick={onNodeClick}
              onNodeRightClick={onNodeRightClick}
              onLinkClick={onLinkClick}
              onLinkRightClick={onLinkRightClick}
              onBackgroundClick={onBackgroundClick}
              onBackgroundRightClick={onBackgroundRightClick}
              highlightedNodeIds={highlightedNodeIds}
              highlightedLinkIds={highlightedLinkIds}
              selectedNodeId={selectedNodeId}
              layoutMode={layoutMode}
            />
          ) : (
            <div className="absolute inset-0 z-10 flex items-center justify-center text-muted-foreground">
              Loading graph...
            </div>
          )
        ) : (
          <GraphViewer
            ref={graph2dRef}
            data={graphRenderData}
            onNodeClick={onNodeClick}
            onNodeRightClick={onNodeRightClick}
            onLinkClick={onLinkClick}
            onLinkRightClick={onLinkRightClick}
            onBackgroundClick={onBackgroundClick}
            onBackgroundRightClick={onBackgroundRightClick}
            highlightedNodeIds={highlightedNodeIds}
            highlightedLinkIds={highlightedLinkIds}
            selectedNodeId={selectedNodeId}
            showEdgeLabels={showEdgeLabels}
            layoutMode={layoutMode}
          />
        )
      ) : (
        <div className="absolute inset-0 z-10 flex items-center justify-center p-6">
          <EmptyState
            icon={Share2}
            iconClassName="text-sky-500 dark:text-sky-300"
            title="探索知识网络"
            description={
              <>
                连接知识孤岛，发现潜在关联。<br />
                支持实时数据加载、搜索与深度分析。
              </>
            }
            className="w-full max-w-2xl bg-card/80 border-border"
          >
            <Button
              size="lg"
              variant="outline"
              onClick={onLoadMock}
              disabled={isLoading}
              className="border-border hover:bg-muted hover:text-foreground"
            >
              {isLoading ? '加载中...' : '加载示例数据'}
            </Button>
            <Button
              size="lg"
              className="bg-primary text-primary-foreground hover:bg-primary/90 shadow-soft"
              onClick={onTriggerFileUpload}
            >
              <Upload className="w-5 h-5" />
              开始上传
            </Button>
          </EmptyState>
        </div>
      )}
    </div>
  )
}
