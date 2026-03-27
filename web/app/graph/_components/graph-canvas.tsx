'use client'

import { useCallback, useEffect, useId, useMemo, useState, type RefObject } from 'react'

import { Share2, Upload } from 'lucide-react'

import { GraphViewer, type GraphViewerRef, type LayoutMode } from '@/components/graph/graph-viewer'
import { KnowledgeGraph3D, type KnowledgeGraph3DRef } from '@/components/graph/force-graph-3d'
import { Button } from '@/components/ui/button'
import { EmptyState } from '@/components/ui/empty-state'
import type { GraphData } from '@/lib/graph-parser'

import type { GraphLinkLike, GraphNodeLike } from '../graph-page-utils'

const SEMANTIC_LIST_ITEM_LIMIT = 200

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

function normalizeNodeLabel(node: Record<string, unknown>, fallback: string) {
  const candidate = [node.label, node.name, node.title, node.id].find(
    (value) => typeof value === 'string' && value.trim().length > 0
  )
  return typeof candidate === 'string' ? candidate : fallback
}

function normalizeLinkEndpoint(endpoint: unknown) {
  if (typeof endpoint === 'string' && endpoint.trim()) return endpoint
  if (typeof endpoint === 'number') return String(endpoint)
  if (endpoint && typeof endpoint === 'object' && 'id' in endpoint) {
    const value = (endpoint as { id?: unknown }).id
    if (typeof value === 'string' && value.trim()) return value
    if (typeof value === 'number') return String(value)
  }
  return 'unknown'
}

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
  const [isSemanticListVisible, setIsSemanticListVisible] = useState(viewMode === '3d')
  const semanticPanelId = useId()
  const semanticNodeCount = graphRenderData.nodes.length
  const semanticLinkCount = graphRenderData.links.length
  const isSemanticListTruncated =
    semanticNodeCount > SEMANTIC_LIST_ITEM_LIMIT || semanticLinkCount > SEMANTIC_LIST_ITEM_LIMIT

  useEffect(() => {
    if (viewMode === '3d') {
      setIsSemanticListVisible(true)
    }
  }, [viewMode])

  const semanticNodes = useMemo(
    () =>
      isSemanticListVisible
        ? graphRenderData.nodes.slice(0, SEMANTIC_LIST_ITEM_LIMIT).map((node, index) => {
        const nodeRecord = node as Record<string, unknown>
        const meta = (nodeRecord.meta ?? {}) as Record<string, unknown>
        const nodeId =
          typeof nodeRecord.id === 'string' && nodeRecord.id.trim().length > 0 ? nodeRecord.id : `node-${index + 1}`
        const type = String(meta.type ?? nodeRecord.type ?? 'unknown').trim() || 'unknown'
        const kind = String(meta.kind ?? 'entity').trim() || 'entity'
        return {
          id: nodeId,
          label: normalizeNodeLabel(nodeRecord, nodeId),
          type,
          kind,
          raw: node as GraphNodeLike,
        }
      })
        : [],
    [graphRenderData.nodes, isSemanticListVisible]
  )
  const semanticLinks = useMemo(
    () =>
      isSemanticListVisible
        ? graphRenderData.links.slice(0, SEMANTIC_LIST_ITEM_LIMIT).map((link, index) => {
        const linkRecord = link as Record<string, unknown>
        const meta = (linkRecord.meta ?? {}) as Record<string, unknown>
        const source = normalizeLinkEndpoint(linkRecord.source)
        const target = normalizeLinkEndpoint(linkRecord.target)
        const relation = String(linkRecord.label ?? linkRecord.relation ?? meta.kind ?? '关联').trim() || '关联'
        return {
          id: `${source}-${target}-${index}`,
          source,
          target,
          relation,
        }
      })
        : [],
    [graphRenderData.links, isSemanticListVisible]
  )
  const focusSemanticNode = useCallback(
    (nodeId: string) => {
      graph3dRef.current?.focusNode(nodeId)
      graph2dRef.current?.focusNode(nodeId)
    },
    [graph2dRef, graph3dRef]
  )

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
          )}
          <aside className="absolute top-4 left-4 z-20 w-[min(28rem,calc(100%-2rem))] pointer-events-none">
            <div className="pointer-events-auto rounded-xl border border-border/80 bg-card/90 shadow-soft backdrop-blur-sm supports-[backdrop-filter]:bg-card/75">
              <div className="flex items-center justify-between gap-3 px-3 py-2 border-b border-border/60">
                <div className="min-w-0">
                  <h2 className="text-sm font-medium text-foreground">语义图谱列表</h2>
                  <p className="text-xs text-muted-foreground">
                    当前数据：{semanticNodeCount} 个节点，{semanticLinkCount} 条连线
                  </p>
                </div>
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  className="h-8 shrink-0"
                  aria-expanded={isSemanticListVisible}
                  aria-controls={semanticPanelId}
                  onClick={() => setIsSemanticListVisible((visible) => !visible)}
                >
                  {isSemanticListVisible ? '隐藏语义列表' : '显示语义列表'}
                </Button>
              </div>
              {viewMode === '3d' ? (
                <p className="px-3 pt-2 text-xs text-muted-foreground">
                  3D 视图为视觉展示，语义列表提供可读结构，便于键盘与屏幕阅读器访问；按 Tab 键可逐个聚焦节点。
                </p>
              ) : null}
              <div
                id={semanticPanelId}
                hidden={!isSemanticListVisible}
                role="region"
                aria-label="知识图谱语义化结构列表"
                className="space-y-3 px-3 py-3 max-h-72 overflow-auto"
              >
                {isSemanticListVisible ? (
                  <>
                    {isSemanticListTruncated ? (
                      <p className="text-xs text-muted-foreground">
                        为避免大图谱阻塞页面，语义列表仅展示前 {SEMANTIC_LIST_ITEM_LIMIT} 个节点和前{' '}
                        {SEMANTIC_LIST_ITEM_LIMIT} 条连线。
                      </p>
                    ) : null}
                    <section aria-labelledby={`${semanticPanelId}-nodes`}>
                      <h3 id={`${semanticPanelId}-nodes`} className="text-xs font-semibold uppercase text-muted-foreground">
                        节点
                      </h3>
                      <ul className="mt-2 space-y-1.5 text-sm text-foreground">
                        {semanticNodes.map((node) => (
                          <li key={node.id}>
                            <button
                              type="button"
                              className="w-full rounded-lg border border-transparent px-2 py-1.5 text-left transition-colors hover:border-border/70 hover:bg-muted/50 focus-visible:border-primary/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/20"
                              aria-label={`聚焦节点：${node.label}`}
                              aria-pressed={selectedNodeId === node.id}
                              onFocus={() => focusSemanticNode(node.id)}
                              onClick={() => {
                                focusSemanticNode(node.id)
                                onNodeClick(node.raw)
                              }}
                            >
                              <span className="font-medium">{node.label}</span>
                              <span className="text-muted-foreground">（ID: {node.id}，类型: {node.type}，类别: {node.kind}）</span>
                            </button>
                          </li>
                        ))}
                      </ul>
                    </section>
                    <section aria-labelledby={`${semanticPanelId}-links`}>
                      <h3 id={`${semanticPanelId}-links`} className="text-xs font-semibold uppercase text-muted-foreground">
                        连线
                      </h3>
                      <ol className="mt-2 space-y-1.5 text-sm text-foreground">
                        {semanticLinks.map((link) => (
                          <li key={link.id}>
                            <span className="font-medium">{link.source}</span>
                            <span className="text-muted-foreground"> → {link.target}（关系: {link.relation}）</span>
                          </li>
                        ))}
                      </ol>
                    </section>
                  </>
                ) : null}
              </div>
            </div>
          </aside>
        </>
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
