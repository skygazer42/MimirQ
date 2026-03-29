'use client'

import { useMemo, useRef, useState } from 'react'
import dynamic from 'next/dynamic'
import { useTheme } from 'next-themes'

import { PageLoading } from '@/components/ui/page-loading'
import { useResizeObserver } from '@/hooks/use-resize-observer'
import { getCssHslColor } from '@/lib/css-vars'
import { cn } from '@/lib/utils'

import type { SimilarityDiagnosticLink, SimilarityDiagnosticNode } from './similarity-diagnostics'

const ForceGraph3D = dynamic(() => import('react-force-graph-3d'), {
  ssr: false,
  loading: () => (
    <div className="flex h-full min-h-[360px] flex-col items-center justify-center rounded-2xl border border-border/60 bg-background/70 px-6">
      <PageLoading
        message="正在重建向量邻域..."
        srMessage="Loading embedding diagnostics graph"
        className="min-h-0 flex-none"
      />
      <p className="mt-2 text-xs text-muted-foreground">基于当前相似度矩阵派生诊断，不额外请求后端坐标。</p>
    </div>
  ),
})

type SimilarityDiagnosticsGraphProps = Readonly<{
  nodes: SimilarityDiagnosticNode[]
  links: SimilarityDiagnosticLink[]
}>

type GraphNode = SimilarityDiagnosticNode & {
  val?: number
}

export function SimilarityDiagnosticsGraph({ nodes, links }: SimilarityDiagnosticsGraphProps) {
  const { resolvedTheme } = useTheme()
  const containerRef = useRef<HTMLDivElement>(null)
  const { width, height } = useResizeObserver(containerRef)
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null)
  const [selectedLinkId, setSelectedLinkId] = useState<string | null>(null)

  const isDark = resolvedTheme === 'dark'
  const backgroundColor = getCssHslColor('--background', isDark ? '#020617' : '#ffffff')

  const graphData = useMemo(
    () => ({
      nodes: nodes.map((node) => ({
        ...node,
        val: Math.max(4, node.supportCount * 2 + (node.isOutlier ? 2 : 1)),
      })),
      links,
    }),
    [links, nodes]
  )

  const selectedNode = nodes.find((node) => node.id === selectedNodeId) ?? null
  const selectedLink = links.find((link) => link.id === selectedLinkId) ?? null

  if (nodes.length === 0 || links.length === 0) {
    return (
      <div className="flex min-h-[360px] items-center justify-center rounded-2xl border border-dashed border-border/60 bg-background/70 px-6 text-center text-sm text-muted-foreground">
        当前筛选结果没有足够的高相似连线，暂时无法生成 3D 投影预览。
      </div>
    )
  }

  return (
    <div className="space-y-3">
      <div ref={containerRef} className="relative h-[420px] overflow-hidden rounded-2xl border border-border/60 bg-card">
        {width > 0 && height > 0 ? (
          <ForceGraph3D
            graphData={graphData}
            width={width}
            height={height}
            backgroundColor={backgroundColor}
            showNavInfo={false}
            enableNodeDrag={false}
            cooldownTicks={0}
            nodeLabel={(node) => {
              const current = node as SimilarityDiagnosticNode
              return `[${current.axis.toUpperCase()}] ${current.label}${current.isOutlier ? ' · outlier' : ''}\nmean ${(current.averageSimilarity * 100).toFixed(0)}% / peak ${(current.peakSimilarity * 100).toFixed(0)}%`
            }}
            nodeColor={(node) => (node as SimilarityDiagnosticNode).color}
            nodeRelSize={5}
            linkOpacity={0.35}
            linkDirectionalParticles={(link) => ((link as SimilarityDiagnosticLink).isOutlier ? 2 : 0)}
            linkDirectionalParticleWidth={(link) => ((link as SimilarityDiagnosticLink).isMarked ? 4 : 2)}
            linkColor={(link) => {
              const current = link as SimilarityDiagnosticLink
              if (current.isMarked) return '#f59e0b'
              if (current.isOutlier) return '#ef4444'
              return '#64748b'
            }}
            linkWidth={(link) => {
              const current = link as SimilarityDiagnosticLink
              if (current.isMarked) return 4
              if (current.isOutlier) return 3
              return Math.max(1.1, current.similarity * 3.2)
            }}
            onNodeClick={(node) => {
              const current = node as GraphNode
              setSelectedNodeId(current.id)
            }}
            onLinkClick={(link) => {
              const current = link as SimilarityDiagnosticLink
              if (current.isOutlier) setSelectedLinkId(current.id)
            }}
          />
        ) : null}

        <div className="pointer-events-none absolute left-3 top-3 rounded-xl border border-border/70 bg-background/85 px-3 py-2 shadow-sm backdrop-blur">
          <div className="text-xs font-medium text-foreground">3D 投影预览</div>
          <div className="mt-1 text-[11px] text-muted-foreground">颜色越亮代表越值得关注，橙色表示已标记待审的候选。</div>
        </div>
      </div>

      <div className="grid gap-3 md:grid-cols-2">
        <DiagnosticsDetailCard
          label="当前节点"
          title={selectedNode?.label ?? '点击节点查看摘要'}
          description={
            selectedNode
              ? `${selectedNode.axis.toUpperCase()} 轴 · mean ${(selectedNode.averageSimilarity * 100).toFixed(0)}% · peak ${(selectedNode.peakSimilarity * 100).toFixed(0)}%`
              : '选中节点后会显示它在当前局部邻域中的位置和强度。'
          }
        />
        <DiagnosticsDetailCard
          label="当前连线"
          title={
            selectedLink
              ? `score ${(selectedLink.similarity * 100).toFixed(0)}% · overlap ${(selectedLink.lexicalOverlap * 100).toFixed(0)}%`
              : '点击连线查看匹配强度'
          }
          description={
            selectedLink
              ? `${selectedLink.sourceLabel} → ${selectedLink.targetLabel}`
              : '优先检查红色或橙色连线，它们通常代表高分但支撑不足的候选。'
          }
          tone={selectedLink?.isOutlier ? 'warning' : 'default'}
        />
      </div>
    </div>
  )
}

function DiagnosticsDetailCard({
  label,
  title,
  description,
  tone = 'default',
}: Readonly<{
  label: string
  title: string
  description: string
  tone?: 'default' | 'warning'
}>) {
  return (
    <div
      className={cn(
        'rounded-2xl border px-4 py-3',
        tone === 'warning'
          ? 'border-orange-200/70 bg-orange-50/70 dark:border-orange-900/40 dark:bg-orange-950/10'
          : 'border-border/60 bg-background/70'
      )}
    >
      <div className="text-[11px] font-medium uppercase tracking-[0.08em] text-muted-foreground">{label}</div>
      <div className="mt-1 text-sm font-semibold text-foreground">{title}</div>
      <p className="mt-2 text-xs text-muted-foreground">{description}</p>
    </div>
  )
}
