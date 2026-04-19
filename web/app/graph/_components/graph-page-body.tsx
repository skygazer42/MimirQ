'use client'

import type { ComponentProps } from 'react'

import { GraphLegend } from '@/components/graph/graph-legend'
import { GraphStatsBar } from '@/components/graph/graph-stats-bar'
import type { GraphData } from '@/lib/graph-parser'

import { GraphCanvas } from './graph-canvas'
import { GraphContextMenu } from './graph-context-menu'
import { GraphExplainabilityPanel } from './graph-explainability-panel'
import { GraphFloatingControls } from './graph-floating-controls'
import { GraphLinkDetailPanel } from './graph-link-detail-panel'
import { GraphNodeDetailPanel } from './graph-node-detail-panel'

type GraphExplainabilityStep = {
  node: string
  reason: string
}

type GraphPageBodyProps = Readonly<{
  canvasProps: ComponentProps<typeof GraphCanvas>
  contextMenuProps: ComponentProps<typeof GraphContextMenu>
  legendVisible: boolean
  legendNodes: GraphData['nodes']
  legendLinks: GraphData['links']
  activeTypeFilters: string[]
  onToggleTypeFilter: (type: string) => void
  explainabilityOpen: boolean
  explainSteps: GraphExplainabilityStep[]
  currentStepIndex: number
  displayNodes: GraphData['nodes']
  showPendingDocs: boolean
  pendingDocCount: number | null
  showStatsBar: boolean
  statsNodeCount: number
  statsLinkCount: number
  statsEntityTypeCount: number
  floatingControlsProps: ComponentProps<typeof GraphFloatingControls>
  nodeDetailPanelProps: ComponentProps<typeof GraphNodeDetailPanel>
  linkDetailPanelProps: ComponentProps<typeof GraphLinkDetailPanel>
}>

export function GraphPageBody({
  canvasProps,
  contextMenuProps,
  legendVisible,
  legendNodes,
  legendLinks,
  activeTypeFilters,
  onToggleTypeFilter,
  explainabilityOpen,
  explainSteps,
  currentStepIndex,
  displayNodes,
  showPendingDocs,
  pendingDocCount,
  showStatsBar,
  statsNodeCount,
  statsLinkCount,
  statsEntityTypeCount,
  floatingControlsProps,
  nodeDetailPanelProps,
  linkDetailPanelProps,
}: GraphPageBodyProps) {
  return (
    <div className="relative flex h-full min-h-0 w-full flex-1">
      <GraphCanvas {...canvasProps} />

      <GraphContextMenu {...contextMenuProps} />

      {legendVisible ? (
        <GraphLegend
          nodes={legendNodes}
          links={legendLinks}
          activeTypeFilters={activeTypeFilters}
          onToggleTypeFilter={onToggleTypeFilter}
        />
      ) : null}

      <GraphExplainabilityPanel
        open={explainabilityOpen}
        explainSteps={explainSteps}
        currentStepIndex={currentStepIndex}
        nodes={displayNodes}
      />

      {showPendingDocs ? (
        <div className="absolute bottom-20 left-1/2 -translate-x-1/2 z-20">
          <div className="flex items-center gap-2 rounded-full border border-primary/20 bg-primary/10 px-3 py-1.5 shadow-sm animate-pulse motion-reduce:animate-none">
            <span className="text-[11px] font-medium text-primary">KG 构建中</span>
            <span className="text-[11px] text-muted-foreground">待处理文档</span>
            <span className="text-[11px] font-mono text-foreground">{pendingDocCount}</span>
          </div>
        </div>
      ) : null}

      {showStatsBar ? (
        <div className="absolute bottom-8 left-1/2 -translate-x-1/2 z-10">
          <GraphStatsBar
            nodeCount={statsNodeCount}
            linkCount={statsLinkCount}
            entityTypeCount={statsEntityTypeCount}
          />
        </div>
      ) : null}

      <GraphFloatingControls {...floatingControlsProps} />

      <GraphNodeDetailPanel {...nodeDetailPanelProps} />

      <GraphLinkDetailPanel {...linkDetailPanelProps} />
    </div>
  )
}
