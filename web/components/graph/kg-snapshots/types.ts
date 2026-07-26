import type { ReactNode } from 'react'

export type SnapshotPayload = Record<string, unknown>

export type SnapshotDiffEntityRow = {
  type?: string
  delta?: number | null
  [key: string]: unknown
}

export type SnapshotDiffPayload = {
  delta?: SnapshotPayload | null
  entity_types_delta?: SnapshotDiffEntityRow[] | null
  node_diff?: SnapshotExactDiffSummary | null
  edge_diff?: SnapshotExactDiffSummary | null
  [key: string]: unknown
}

export type SnapshotExactDiffSummary = {
  added_count?: number | null
  removed_count?: number | null
  changed_count?: number | null
  sample_limit?: number | null
}

export type SnapshotView = 'diff' | 'a' | 'b'
export type WorkspaceTab = 'studio' | 'audit'
export type StudioCanvasView = 'graph' | 'table' | 'stats'
export type DiffCellStatus = 'same' | 'added' | 'removed' | 'empty'
export type JsonTokenKind =
  | 'plain'
  | 'key'
  | 'string'
  | 'number'
  | 'boolean'
  | 'null'
  | 'punctuation'
export type AuditSeverity = 'healthy' | 'notice' | 'warning'
export type SnapshotInlineStatTone = 'muted' | 'neutral' | 'positive' | 'negative' | 'warning'
export type DeltaDirection = 'positive' | 'negative' | 'flat'

export type PipelineCandidate = {
  hash: string
  documents: number
  source: 'report' | 'documents'
  active: boolean
}

export type DiffCell = {
  lineNumber: number | null
  text: string
  status: DiffCellStatus
}

export type SideBySideDiffRow = {
  left: DiffCell
  right: DiffCell
}

export type SnapshotDeltaRow = {
  key: string
  a: number
  b: number
  delta: number
}

export type SnapshotChartTooltipProps = {
  active?: boolean
  payload?: Array<{ payload?: SnapshotDeltaRow }>
}

export type SnapshotStudioNode = {
  id: string
  label: string
  type: string
  kind: string
  description: string
  x: number
  y: number
  tone: 'blue' | 'green' | 'orange' | 'purple' | 'rose' | 'amber' | 'teal'
  icon: ReactNode
  occurrences: number
  status: '一致' | '新增' | '移除' | '变化'
  relations: Array<{ label: string; target: string }>
}

export type SnapshotStudioLink = {
  source: string
  target: string
  label: string
  strength: 'weak' | 'medium' | 'strong'
}
