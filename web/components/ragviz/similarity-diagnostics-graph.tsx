'use client'

import { useMemo, useRef, useState } from 'react'
import dynamic from 'next/dynamic'
import { useTranslations } from 'next-intl'
import { useTheme } from 'next-themes'
import type { ForceGraphProps } from 'react-force-graph-3d'

import { PageLoading } from '@/components/ui/page-loading'
import { useResizeObserver } from '@/hooks/use-resize-observer'
import { getCssHslColor } from '@/lib/css-vars'
import { cn } from '@/lib/utils'

import type { SimilarityDiagnosticLink, SimilarityDiagnosticNode } from './similarity-diagnostics'

const MAX_DIAGNOSTICS_GRAPH_NODES = 180
const MAX_DIAGNOSTICS_GRAPH_LINKS = 900

function formatDiagnosticPercent(value: number | null): string {
  return value === null ? '—' : `${(value * 100).toFixed(0)}%`
}

type SimilarityDiagnosticsGraphProps = Readonly<{
  nodes: SimilarityDiagnosticNode[]
  links: SimilarityDiagnosticLink[]
}>

type GraphNode = SimilarityDiagnosticNode & {
  val: number
}

const ForceGraph3D = dynamic<ForceGraphProps<GraphNode, SimilarityDiagnosticLink>>(
  () => import('react-force-graph-3d').then(({ default: Graph }) => Graph<GraphNode, SimilarityDiagnosticLink>),
  { ssr: false, loading: () => <GraphLoadingShell /> },
)

export function SimilarityDiagnosticsGraph({ nodes, links }: SimilarityDiagnosticsGraphProps) {
  const { resolvedTheme } = useTheme()
  const t = useTranslations('SimilarityDiagnosticsGraph')
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
      links: links.map((link) => ({ ...link })),
    }),
    [links, nodes],
  )

  const selectedNode = nodes.find((node) => node.id === selectedNodeId)
  const selectedLink = links.find((link) => link.id === selectedLinkId)
  const exceedsGraphComplexityBudget =
    nodes.length > MAX_DIAGNOSTICS_GRAPH_NODES || links.length > MAX_DIAGNOSTICS_GRAPH_LINKS
  const selectedNodeDescription = selectedNode
    ? t('nodeCardSelectedDescription', {
        axis: selectedNode.axis.toUpperCase(),
        mean: formatDiagnosticPercent(selectedNode.averageSimilarity),
        peak: formatDiagnosticPercent(selectedNode.peakSimilarity),
      })
    : t('nodeCardEmptyDescription')
  const selectedLinkTitle = selectedLink
    ? t('linkCardSelectedTitle', {
        score: (selectedLink.similarity * 100).toFixed(0),
        overlap: (selectedLink.lexicalOverlap * 100).toFixed(0),
      })
    : t('linkCardEmptyTitle')
  const selectedLinkDescription = selectedLink
    ? t('linkCardSelectedDescription', {
        source: selectedLink.sourceLabel,
        target: selectedLink.targetLabel,
      })
    : t('linkCardEmptyDescription')

  if (nodes.length === 0 || links.length === 0) {
    return (
      <div className="flex min-h-[360px] items-center justify-center rounded-2xl border border-dashed border-border/60 bg-background/70 px-6 text-center text-sm text-muted-foreground">
        {t('noGraphData')}
      </div>
    )
  }

  return (
    <div className="space-y-3">
      <div
        ref={containerRef}
        className="relative h-[420px] overflow-hidden rounded-2xl border border-border/60 bg-card"
      >
        {exceedsGraphComplexityBudget ? (
          <div className="flex h-full items-center justify-center px-6 text-center">
            <div className="max-w-lg">
              <div className="text-sm font-semibold text-foreground">{t('graphTooLargeTitle')}</div>
              <p className="mt-2 text-sm text-muted-foreground">{t('graphTooLargeHint')}</p>
              <p className="mt-2 text-xs text-muted-foreground">
                {t('graphTooLargeMetrics', {
                  nodeCount: nodes.length,
                  linkCount: links.length,
                  nodeLimit: MAX_DIAGNOSTICS_GRAPH_NODES,
                  linkLimit: MAX_DIAGNOSTICS_GRAPH_LINKS,
                })}
              </p>
            </div>
          </div>
        ) : width > 0 && height > 0 ? (
          <ForceGraph3D
            graphData={graphData}
            width={width}
            height={height}
            backgroundColor={backgroundColor}
            showNavInfo={false}
            enableNodeDrag={false}
            cooldownTicks={0}
            nodeLabel={(node) => {
              const tooltip = document.createElement('span')
              tooltip.textContent = t('nodeTooltip', {
                axis: node.axis.toUpperCase(),
                label: node.label,
                outlierSuffix: node.isOutlier ? t('nodeTooltipOutlierSuffix') : '',
                mean: formatDiagnosticPercent(node.averageSimilarity),
                peak: formatDiagnosticPercent(node.peakSimilarity),
              })
              return tooltip.outerHTML
            }}
            nodeColor={(node) => node.color}
            nodeRelSize={5}
            linkOpacity={0.35}
            linkDirectionalParticles={(link) => (link.isOutlier ? 2 : 0)}
            linkDirectionalParticleWidth={(link) => (link.isMarked ? 4 : 2)}
            linkColor={(link) => {
              if (link.isMarked) return '#f59e0b'
              if (link.isOutlier) return '#ef4444'
              return '#64748b'
            }}
            linkWidth={(link) => {
              if (link.isMarked) return 4
              if (link.isOutlier) return 3
              return Math.max(1.1, link.similarity * 3.2)
            }}
            onNodeClick={(node) => setSelectedNodeId(node.id)}
            onLinkClick={(link) => {
              if (link.isOutlier) setSelectedLinkId(link.id)
            }}
          />
        ) : null}

        <div className="pointer-events-none absolute left-3 top-3 rounded-xl border border-border/70 bg-background/85 px-3 py-2 shadow-sm backdrop-blur">
          <div className="text-xs font-medium text-foreground">{t('previewLabel')}</div>
          <div className="mt-1 text-[11px] text-muted-foreground">{t('previewHint')}</div>
        </div>
      </div>

      <div className="grid gap-3 md:grid-cols-2">
        <DiagnosticsDetailCard
          label={t('nodeCardLabel')}
          title={selectedNode?.label ?? t('nodeCardEmptyTitle')}
          description={selectedNodeDescription}
        />
        <DiagnosticsDetailCard
          label={t('linkCardLabel')}
          title={selectedLinkTitle}
          description={selectedLinkDescription}
          tone={selectedLink?.isOutlier ? 'warning' : 'default'}
        />
      </div>
    </div>
  )
}

function GraphLoadingShell() {
  const t = useTranslations('SimilarityDiagnosticsGraph')

  return (
    <div className="flex h-full min-h-[360px] flex-col items-center justify-center rounded-2xl border border-border/60 bg-background/70 px-6">
      <PageLoading message={t('loadingMessage')} srMessage={t('loadingSrMessage')} className="min-h-0 flex-none" />
      <p className="mt-2 text-xs text-muted-foreground">{t('loadingHint')}</p>
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
        tone === 'warning' ? 'border-warning/30 bg-warning/5' : 'border-border/60 bg-background/70',
      )}
    >
      <div className="text-[11px] font-medium uppercase tracking-[0.08em] text-muted-foreground">{label}</div>
      <div className="mt-1 text-sm font-semibold text-foreground">{title}</div>
      <p className="mt-2 text-xs text-muted-foreground">{description}</p>
    </div>
  )
}
