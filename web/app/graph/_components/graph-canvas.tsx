'use client'

import type { RefObject } from 'react'

import { Network } from '@/components/icons'
import dynamic from 'next/dynamic'

import { GraphLoadingIndicator } from '@/components/graph/graph-loading-indicator'
import { GraphViewer, type GraphViewerRef, type LayoutMode } from '@/components/graph/graph-viewer'
import type { KnowledgeGraph3DRef } from '@/components/graph/force-graph-3d'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import type { GraphData } from '@/lib/graph-types'

import type { GraphLinkLike, GraphNodeLike } from '../graph-page-utils'
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
  hasActiveScope: boolean
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
  hasActiveScope,
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
        <div className="absolute inset-0 z-10 flex items-center justify-center px-5 py-6">
          {isLoading ? (
            <GraphLoadingIndicator message="正在读取图谱…" />
          ) : hasLoadError ? null : (
            <section className="mx-auto flex w-full max-w-[36rem] flex-col items-center justify-center px-8 py-14 text-center md:px-10 md:py-16">
              <div className="mb-7 flex items-center justify-center">
                <svg aria-hidden="true" viewBox="0 0 180 72" className="h-14 w-36">
                  <path
                    d="M36 46H90M90 46H144M90 46V22"
                    fill="none"
                    stroke="hsl(var(--info) / 0.24)"
                    strokeWidth="1.6"
                    strokeLinecap="round"
                  />
                  <circle
                    cx="36"
                    cy="46"
                    r="8.7"
                    fill="hsl(var(--background) / 0.92)"
                    stroke="hsl(var(--info) / 0.32)"
                    strokeWidth="1.5"
                  />
                  <circle
                    cx="144"
                    cy="46"
                    r="8.7"
                    fill="hsl(var(--background) / 0.92)"
                    stroke="hsl(var(--info) / 0.32)"
                    strokeWidth="1.5"
                  />
                  <circle
                    cx="90"
                    cy="22"
                    r="10.2"
                    fill="hsl(var(--info) / 0.10)"
                    stroke="hsl(var(--info) / 0.62)"
                    strokeWidth="1.6"
                  />
                  <circle
                    cx="90"
                    cy="46"
                    r="8.7"
                    fill="hsl(var(--background) / 0.92)"
                    stroke="hsl(var(--info) / 0.32)"
                    strokeWidth="1.5"
                  />
                  <circle cx="36" cy="46" r="2" fill="hsl(var(--info) / 0.48)" />
                  <circle cx="90" cy="46" r="2" fill="hsl(var(--info) / 0.48)" />
                  <circle cx="144" cy="46" r="2" fill="hsl(var(--info) / 0.48)" />
                  <circle cx="90" cy="22" r="2.7" fill="hsl(var(--info))" />
                </svg>
              </div>
              <h2 className="mx-auto w-full max-w-[19rem] text-balance text-[1.42rem] font-semibold  text-foreground md:text-[1.56rem]">
                {hasActiveScope ? '当前范围暂无图谱' : '选择图谱'}
              </h2>
              <div className="mx-auto mt-3 w-full max-w-[30rem] text-pretty text-sm leading-7 text-muted-foreground md:text-[15px]">
                {hasActiveScope
                  ? '当前范围还没有实体与关系，可以切换到其他已有图谱。'
                  : '选择数据集或文档，查看已有的实体、关系与来源。'}
              </div>
              <div className="mx-auto mt-7 flex w-full max-w-[30rem] flex-wrap items-center justify-center gap-3">
                <Button
                  variant="outline"
                  className="h-9 gap-2 rounded-md px-3 text-[13px] shadow-none"
                  onClick={onTriggerManualKgUpload}
                >
                  <Network className="h-4 w-4" />
                  导入 KG JSON / JSONL
                </Button>
                <Button className="h-9 gap-2 rounded-md px-3 text-[13px] shadow-none" onClick={onOpenGraphPicker}>
                  选择图谱
                </Button>
              </div>
            </section>
          )}
        </div>
      )}
    </div>
  )
}
