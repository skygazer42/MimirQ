'use client'

import type { ComponentProps, ReactNode } from 'react'
import type { GraphData } from '@/lib/graph-parser'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { GraphCanvas } from './graph-canvas'
import { GraphContextMenu } from './graph-context-menu'
import { GraphExplainabilityPanel } from './graph-explainability-panel'
import { GraphFloatingControls } from './graph-floating-controls'
import { GraphLinkDetailPanel } from './graph-link-detail-panel'
import { GraphNodeDetailPanel } from './graph-node-detail-panel'
import { KgNetworkAnalysisPanel } from './kg-network-analysis-panel'
import styles from './graph-workspace.module.css'

type GraphExplainabilityStep = {
  node: string
  reason: string
}

type GraphPageBodyProps = Readonly<{
  summary?: ReactNode
  canvasLabel?: ReactNode
  analysisOpen: boolean
  onAnalysisOpenChange: (open: boolean) => void
  canvasProps: ComponentProps<typeof GraphCanvas>
  contextMenuProps: ComponentProps<typeof GraphContextMenu>
  explainabilityOpen: boolean
  explainSteps: GraphExplainabilityStep[]
  currentStepIndex: number
  displayNodes: GraphData['nodes']
  networkAnalysisNodes: GraphData['nodes']
  networkAnalysisLinks: GraphData['links']
  networkAnalysisSelectedNodeId?: string | null
  floatingControlsProps: ComponentProps<typeof GraphFloatingControls>
  nodeDetailPanelProps: ComponentProps<typeof GraphNodeDetailPanel>
  linkDetailPanelProps: ComponentProps<typeof GraphLinkDetailPanel>
}>

export function GraphPageBody({
  canvasProps, contextMenuProps, explainabilityOpen, explainSteps, currentStepIndex, displayNodes,
  networkAnalysisNodes, networkAnalysisLinks, networkAnalysisSelectedNodeId,
  floatingControlsProps, nodeDetailPanelProps, linkDetailPanelProps,
  summary, canvasLabel, analysisOpen, onAnalysisOpenChange,
}: GraphPageBodyProps) {
  return <div className={styles.canvasRegion} data-graph-canvas-zone>
    {canvasLabel}
    <div className={styles.graphViewport}><GraphCanvas {...canvasProps} showSemanticPanel={false} /></div>
    <GraphContextMenu {...contextMenuProps} />
    <GraphExplainabilityPanel open={explainabilityOpen} explainSteps={explainSteps} currentStepIndex={currentStepIndex} nodes={displayNodes} />
    {summary}
    <GraphFloatingControls {...floatingControlsProps} />
    {nodeDetailPanelProps.open ? <GraphNodeDetailPanel {...nodeDetailPanelProps} /> : null}
    {linkDetailPanelProps.open ? <GraphLinkDetailPanel {...linkDetailPanelProps} /> : null}
    <Dialog open={analysisOpen} onOpenChange={onAnalysisOpenChange}><DialogContent className="max-h-[calc(100dvh-32px)] max-w-2xl overflow-y-auto">
      <DialogHeader><DialogTitle>网络分析</DialogTitle><DialogDescription>分析当前已加载图谱的节点与关系</DialogDescription></DialogHeader>
      <KgNetworkAnalysisPanel nodes={networkAnalysisNodes} links={networkAnalysisLinks} selectedNodeId={networkAnalysisSelectedNodeId} embedded />
    </DialogContent></Dialog>
  </div>
}
