'use client'

import type {
  DiagnosticDecision,
  SimilarityDiagnosticsResult,
} from '@/components/ragviz/similarity-diagnostics'
import type { ColorSchemeKey, SimilarityMatrixEntry } from './color-schemes'
import {
  HeatmapScaleLegend,
  SimilarityDiagnosticsView,
  SimilarityEmptyState,
} from './display-components'
import { PlotlyHeatmap } from './plotly-heatmap'
import type { SelectedHeatmapCell } from './plotly-types'

export type MainViewMode = 'heatmap' | 'diagnostics'
export type DisplayLabels = { xLabels: string[]; yLabels: string[] }
export type SimilarityDisplayMatrix = Array<Array<number | null>>

type SimilarityMainPanelProps = Readonly<{
  primaryEntry: SimilarityMatrixEntry | null
  displayMatrix: number[][] | null
  displayLabels: DisplayLabels | null
  mainView: MainViewMode
  diagnostics: SimilarityDiagnosticsResult | null
  maskedMatrix: SimilarityDisplayMatrix | null
  colorScheme: ColorSchemeKey
  isDifferenceMode: boolean
  onDecisionChange: (candidateId: string, decision: DiagnosticDecision | null) => void
  onCellSelect: (cell: SelectedHeatmapCell) => void
}>

export function SimilarityMainPanel({
  primaryEntry,
  displayMatrix,
  displayLabels,
  mainView,
  diagnostics,
  maskedMatrix,
  colorScheme,
  isDifferenceMode,
  onDecisionChange,
  onCellSelect,
}: SimilarityMainPanelProps) {
  if (!primaryEntry || !displayMatrix || !displayLabels) {
    return (
      <div className="flex h-full items-start justify-center px-8 pb-14 pt-0">
        <SimilarityEmptyState />
      </div>
    )
  }

  if (mainView === 'diagnostics') {
    return (
      <SimilarityDiagnosticsPanel
        diagnostics={diagnostics}
        onDecisionChange={onDecisionChange}
      />
    )
  }

  return (
    <SimilarityHeatmapPanel
      primaryEntry={primaryEntry}
      displayMatrix={displayMatrix}
      displayLabels={displayLabels}
      maskedMatrix={maskedMatrix}
      colorScheme={colorScheme}
      isDifferenceMode={isDifferenceMode}
      onCellSelect={onCellSelect}
    />
  )
}

function SimilarityDiagnosticsPanel({
  diagnostics,
  onDecisionChange,
}: Readonly<{
  diagnostics: SimilarityDiagnosticsResult | null
  onDecisionChange: (
    candidateId: string,
    decision: DiagnosticDecision | null
  ) => void
}>) {
  if (diagnostics) {
    return (
      <SimilarityDiagnosticsView
        diagnostics={diagnostics}
        onDecisionChange={onDecisionChange}
      />
    )
  }

  return (
    <div className="flex h-full items-center justify-center px-6">
      <div className="rounded-2xl border border-dashed border-sidebar-border/60 bg-muted/30 px-6 py-8 text-center">
        <div className="text-sm font-semibold text-foreground">
          向量诊断暂不可用
        </div>
        <p className="mt-2 text-sm text-muted-foreground">
          当前处于差值模式，3D 投影预览和异常点标注只在单个主图矩阵上启用。
        </p>
      </div>
    </div>
  )
}

function SimilarityHeatmapPanel({
  primaryEntry,
  displayMatrix,
  displayLabels,
  maskedMatrix,
  colorScheme,
  isDifferenceMode,
  onCellSelect,
}: Readonly<{
  primaryEntry: SimilarityMatrixEntry
  displayMatrix: number[][]
  displayLabels: DisplayLabels
  maskedMatrix: SimilarityDisplayMatrix | null
  colorScheme: ColorSchemeKey
  isDifferenceMode: boolean
  onCellSelect: (cell: SelectedHeatmapCell) => void
}>) {
  return (
    <div className="h-full overflow-auto p-4">
      <section className="flex min-h-[560px] flex-col overflow-hidden rounded-[1.75rem] border border-border/38 bg-card/76 shadow-[0_24px_70px_-58px_hsl(var(--foreground)/0.42),inset_0_1px_0_hsl(var(--card)/0.7)]">
        <div className="flex items-center justify-between gap-3 border-b border-border/34 bg-muted/[0.10] px-4 py-3">
          <div className="min-w-0">
            <div className="truncate text-sm font-semibold text-foreground">
              {primaryEntry.xCollectionLabel}（X 轴）
            </div>
            <div className="mt-0.5 text-[11px] text-muted-foreground">
              {displayLabels.xLabels.length} 项 × {displayLabels.yLabels.length} 项
            </div>
          </div>
          <div className="rounded-full border border-border/34 bg-background/44 px-2.5 py-1 text-[11px] font-medium text-muted-foreground/70">
            点击单元格查看右侧统计
          </div>
        </div>

        <div className="min-h-0 flex-1 p-3">
          <PlotlyHeatmap
            matrix={maskedMatrix ?? displayMatrix}
            xLabels={displayLabels.xLabels}
            yLabels={displayLabels.yLabels}
            colorScheme={colorScheme}
            isDifference={isDifferenceMode}
            onCellSelect={onCellSelect}
          />
        </div>

        <HeatmapScaleLegend
          colorScheme={colorScheme}
          isDifference={isDifferenceMode}
        />
      </section>
    </div>
  )
}
