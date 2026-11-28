'use client'

import type { RefObject } from 'react'

import dynamic from 'next/dynamic'

import { GraphLoadingIndicator } from '@/components/graph/graph-loading-indicator'
import { GraphViewer, type GraphViewerRef, type LayoutMode } from '@/components/graph/graph-viewer'
import type { KnowledgeGraph3DRef } from '@/components/graph/force-graph-3d'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import type { GraphData } from '@/lib/graph-types'

import type { GraphLinkLike, GraphNodeLike } from '../graph-page-utils'
import styles from './graph-workspace.module.css'
const KnowledgeGraph3D = dynamic(
  () => import('@/components/graph/force-graph-3d').then((mod) => mod.KnowledgeGraph3D),
  {
    ssr: false,
    loading: () => (
      <div className="absolute inset-0 z-10 flex items-center justify-center">
        <div className="flex w-full max-w-lg flex-col items-center gap-3 rounded-2xl border border-border/60 bg-card p-6 shadow-none">
          <GraphLoadingIndicator className="min-h-0" message="正在构建 3D 图谱…" hint="正在同步节点布局与交互层" />
          <div className="grid w-full gap-2">
            <Skeleton className="h-3 w-full" />
            <Skeleton className="h-3 w-3/4" />
            <Skeleton className="h-3 w-[60%]" />
          </div>
        </div>
      </div>
    ),
  },
)

type GraphCanvasProps = Readonly<{
  viewportRef: RefObject<HTMLDivElement | null>
  graph2dRef: RefObject<GraphViewerRef | null>
  graph3dRef: RefObject<KnowledgeGraph3DRef | null>
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
  hasLoadError: boolean
  onNodeClick: (node: GraphNodeLike) => void
  onNodeRightClick: (node: GraphNodeLike, event: MouseEvent) => void
  onLinkClick: (link: GraphLinkLike) => void
  onLinkRightClick: (link: GraphLinkLike, event: MouseEvent) => void
  onBackgroundClick: () => void
  onBackgroundRightClick: (event: MouseEvent) => void
  onOpenGraphPicker: () => void
  onTriggerManualKgUpload: () => void
}>

export function GraphCanvas({
  viewportRef,
  graph2dRef,
  graph3dRef,
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
  hasLoadError,
  onNodeClick,
  onNodeRightClick,
  onLinkClick,
  onLinkRightClick,
  onBackgroundClick,
  onBackgroundRightClick,
  onOpenGraphPicker,
  onTriggerManualKgUpload,
}: GraphCanvasProps) {
  return (
    <div
      ref={viewportRef}
      className="relative h-full min-h-0 w-full flex-1 overflow-hidden bg-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-info/40"
      tabIndex={0}
      role="region"
      aria-label="知识图谱画布"
    >
      <div className="absolute inset-0 z-0" style={{ backgroundColor: 'hsl(var(--muted) / 0.25)' }} />
      {graphRenderData.nodes.length > 0 ? (
        <>
          {viewMode === '3d' ? (
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
                showEdgeLabels={showEdgeLabels}
                layoutMode={layoutMode}
              />
            ) : (
              <div className="absolute inset-0 z-10 flex items-center justify-center">
                <GraphLoadingIndicator
                  className="rounded-2xl border border-border/60 bg-card px-6 py-5 shadow-none"
                  message="正在准备图谱画布…"
                />
              </div>
            )
          ) : (
            <GraphViewer
              appearance="diagram"
              showMinimap={!selectedNodeId}
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
          )}
        </>
      ) : (
        <div className={styles.emptyStage}>
          {isLoading ? (
            <GraphLoadingIndicator message="正在读取图谱…" />
          ) : hasLoadError ? null : (
            <div className={styles.filteredEmpty}>
              <h2>当前筛选条件下暂无匹配实体</h2>
              <p>调整实体类型或关系筛选条件，或重新选择图谱范围。</p>
              <div className={styles.filteredEmptyActions}>
                <Button variant="outline" onClick={onOpenGraphPicker}>
                  选择图谱
                </Button>
                <Button variant="outline" onClick={onTriggerManualKgUpload}>
                  导入 KG JSON / JSONL
                </Button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
