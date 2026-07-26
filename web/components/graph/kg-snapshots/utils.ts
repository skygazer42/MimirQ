import { toast } from 'sonner'

import { reportClientError } from '@/lib/client-logging'
import type { Dataset, Document } from '@/types'

import { DELTA_TEXT_CLASSES } from './constants'
import type {
  AuditSeverity,
  DeltaDirection,
  PipelineCandidate,
  SnapshotDiffPayload,
  SnapshotExactDiffSummary,
  SnapshotInlineStatTone,
  SnapshotView,
} from './types'

export function prettyJson(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

export function primitiveDisplayString(value: unknown): string {
  if (typeof value === 'string') return value.trim()
  if (typeof value === 'number' || typeof value === 'boolean' || typeof value === 'bigint') {
    return String(value).trim()
  }
  return ''
}

export function firstDisplayString(...values: unknown[]): string {
  for (const value of values) {
    const direct = primitiveDisplayString(value)
    if (direct) return direct

    if (value && typeof value === 'object') {
      const record = value as Record<string, unknown>
      const nested = firstDisplayString(record.id, record.name, record.label, record.title)
      if (nested) return nested
    }
  }
  return ''
}

export function deltaDirection(value: number): DeltaDirection {
  if (value > 0) return 'positive'
  if (value < 0) return 'negative'
  return 'flat'
}

export function deltaSign(value: number): string {
  return value > 0 ? '+' : ''
}

export function deltaFill(value: number): string {
  const direction = deltaDirection(value)
  if (direction === 'positive') return '#10b981'
  if (direction === 'negative') return '#f43f5e'
  return '#94a3b8'
}

export function driftScoreToneForSeverity(severity: AuditSeverity): SnapshotInlineStatTone {
  if (severity === 'healthy') return 'positive'
  if (severity === 'notice') return 'warning'
  return 'negative'
}

export function inlineStatToneForDelta(value: number): SnapshotInlineStatTone {
  const direction = deltaDirection(value)
  if (direction === 'positive') return 'positive'
  if (direction === 'negative') return 'negative'
  return 'muted'
}

export function auditSeverityForDriftScore(score: number): AuditSeverity {
  if (score >= 0.35) return 'warning'
  if (score >= 0.12) return 'notice'
  return 'healthy'
}

export function getHashPairStatus(hasA: boolean, hasB: boolean): string {
  if (hasA && hasB) return '已就绪'
  if (hasA || hasB) return '待补全'
  return '未设置'
}

export function getHashPairTone(hasA: boolean, hasB: boolean): SnapshotInlineStatTone {
  if (hasA && hasB) return 'positive'
  if (hasA || hasB) return 'warning'
  return 'muted'
}

export function getSnapshotScopeSubtitle(
  documentCount: number,
  datasetId: string | undefined,
  datasetLabel: string
): string {
  if (documentCount > 0) return `${documentCount} 个文档范围`
  if (datasetId) return `${datasetLabel} · 数据集范围`
  return '后端全局范围'
}

export function getSelectedDatasetLabel(
  selectedDataset: Dataset | null,
  selectedDatasetId: string
): string {
  if (selectedDataset) return getDatasetLabel(selectedDataset)
  if (selectedDatasetId) return selectedDatasetId
  return '全部数据集'
}

export function getScopeDocumentCountLabel(documentCount: number, selectedDatasetId: string): string {
  if (documentCount > 0) return `${documentCount} 个文档`
  if (selectedDatasetId) return '后端解析'
  return '全局范围'
}

export function downloadJson(value: unknown, filename: string): void {
  const content = JSON.stringify(value ?? {}, null, 2)
  const blob = new Blob([content], { type: 'application/json;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  globalThis.window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}

export async function copyToClipboard(text: string, label: string): Promise<void> {
  const v = String(text || '')
  if (!v.trim()) {
    toast.error('无可复制内容')
    return
  }
  try {
    await navigator.clipboard.writeText(v)
    toast.success(`已复制 ${label}`)
  } catch (err) {
    reportClientError('Failed to copy KG snapshot value to clipboard', err)
    toast.error('复制失败（浏览器权限限制）')
  }
}

export function parseDocumentIds(raw: string): string[] {
  const input = String(raw || '').trim()
  if (!input) return []
  return input
    .split(/[,\n]/g)
    .map((s) => s.trim())
    .filter(Boolean)
}

export function getDatasetLabel(dataset: Dataset | null | undefined): string {
  return String(dataset?.name || dataset?.id || '').trim()
}

export function getDocumentMetaValue(document: Document, ...keys: string[]): unknown {
  const meta = document.metadata && typeof document.metadata === 'object' ? document.metadata : {}
  for (const key of keys) {
    const direct = (document as Record<string, unknown>)[key]
    if (direct != null && direct !== '') return direct
    const metaValue = (meta as Record<string, unknown>)[key]
    if (metaValue != null && metaValue !== '') return metaValue
  }
  return undefined
}

export function compactHashLabel(hash: string): string {
  const value = String(hash || '').trim()
  if (value.length <= 18) return value
  return `${value.slice(0, 10)}…${value.slice(-6)}`
}

export function mergePipelineCandidate(
  map: Map<string, PipelineCandidate>,
  candidate: PipelineCandidate
) {
  const hash = candidate.hash.trim()
  if (!hash) return
  const current = map.get(hash)
  if (!current) {
    map.set(hash, { ...candidate, hash })
    return
  }
  map.set(hash, {
    hash,
    source: current.source === 'report' ? current.source : candidate.source,
    documents: Math.max(current.documents, candidate.documents),
    active: current.active || candidate.active,
  })
}

export function sortPipelineCandidates(candidates: PipelineCandidate[]): PipelineCandidate[] {
  return [...candidates].sort((a, b) => {
    if (a.active !== b.active) return a.active ? -1 : 1
    if (a.documents !== b.documents) return b.documents - a.documents
    return a.hash.localeCompare(b.hash)
  })
}

export function toneClassForDelta(value: number) {
  return DELTA_TEXT_CLASSES[deltaDirection(value)]
}

export function tabLabelForView(view: SnapshotView) {
  if (view === 'diff') return 'Diff 对比'
  if (view === 'a') return '视图 A'
  return '视图 B'
}

export function exactDiffCount(
  summary: SnapshotExactDiffSummary | null | undefined,
  key: keyof SnapshotExactDiffSummary
): number {
  const value = Number(summary?.[key] ?? 0)
  return Number.isFinite(value) ? value : 0
}

export function exactDiffSample(
  diff: SnapshotDiffPayload | null,
  key: string
): Array<Record<string, unknown>> {
  const value = diff?.[key]
  return Array.isArray(value)
    ? value.filter((item): item is Record<string, unknown> =>
        Boolean(item && typeof item === 'object')
      )
    : []
}
