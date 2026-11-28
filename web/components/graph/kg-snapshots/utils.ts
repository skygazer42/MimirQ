import { toast } from 'sonner'

import { reportClientError } from '@/lib/client-logging'
import { downloadBlob } from '@/lib/download'
import type { Dataset, Document } from '@/types'

import { DELTA_TEXT_CLASSES } from './constants'
import type {
  AuditSeverity,
  DeltaDirection,
  PipelineCandidate,
  SnapshotDiffPayload,
  SnapshotInlineStatTone,
  SnapshotPayload,
} from './types'

export function prettyJson(value: SnapshotPayload | SnapshotDiffPayload): string {
  return JSON.stringify(value, null, 2)
}

function primitiveDisplayString(value: unknown): string {
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
  if (direction === 'positive') return 'hsl(var(--success))'
  if (direction === 'negative') return 'hsl(var(--destructive))'
  return 'hsl(var(--muted-foreground))'
}

export function driftScoreToneForSeverity(severity: AuditSeverity): SnapshotInlineStatTone {
  if (severity === 'healthy') return 'neutral'
  if (severity === 'notice') return 'warning'
  return 'negative'
}

export function auditSeverityForDriftScore(score: number): AuditSeverity {
  if (score >= 0.35) return 'warning'
  if (score >= 0.12) return 'notice'
  return 'healthy'
}

export function getSnapshotScopeSubtitle(
  documentCount: number,
  datasetId: string | undefined,
  datasetLabel: string,
): string {
  if (documentCount > 0) return `${documentCount} 个文档范围`
  if (datasetId) return `${datasetLabel} · 数据集范围`
  return '全部数据集'
}

export function getSelectedDatasetLabel(selectedDataset: Dataset | null, selectedDatasetId: string): string {
  if (selectedDataset !== null) {
    const name = selectedDataset.name.trim()
    return name === '' ? selectedDataset.id : name
  }
  if (selectedDatasetId) return selectedDatasetId
  return '全部数据集'
}

export function downloadJson(value: SnapshotPayload | SnapshotDiffPayload, filename: string): void {
  const content = prettyJson(value)
  const blob = new Blob([content], { type: 'application/json;charset=utf-8' })
  downloadBlob(filename, blob)
}

export async function copyToClipboard(text: string, label: string): Promise<void> {
  if (text.trim() === '') {
    toast.error('无可复制内容')
    return
  }
  try {
    await navigator.clipboard.writeText(text)
    toast.success(`已复制 ${label}`)
  } catch (err) {
    reportClientError('Failed to copy KG snapshot value to clipboard', err)
    toast.error('复制失败（浏览器权限限制）')
  }
}

export function parseDocumentIds(raw: string): string[] {
  return raw
    .split(/[,\n]/)
    .map((id) => id.trim())
    .filter((id) => id !== '')
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
  const value = hash.trim()
  if (value.length <= 18) return value
  return `${value.slice(0, 10)}…${value.slice(-6)}`
}

export function mergePipelineCandidate(map: Map<string, PipelineCandidate>, candidate: PipelineCandidate) {
  const hash = candidate.hash.trim()
  if (hash === '' || hash === 'unknown') return
  const current = map.get(hash)
  if (!current) {
    map.set(hash, { ...candidate, hash })
    return
  }
  const recorded = current.source === 'report' ? current : candidate
  map.set(hash, {
    ...recorded,
    hash,
    documents: recorded.source === 'report' ? recorded.documents : current.documents + candidate.documents,
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

export function exactDiffTotal(diff: SnapshotDiffPayload | null): number | undefined {
  let total = 0
  for (const summary of [diff?.node_diff, diff?.edge_diff]) {
    if (summary == null) return undefined
    for (const count of [summary.added_count, summary.removed_count, summary.changed_count]) {
      if (typeof count !== 'number' || !Number.isSafeInteger(count) || count < 0) return undefined
      total += count
    }
  }
  return total
}

export function exactDiffSample(diff: SnapshotDiffPayload | null, key: string): Array<Record<string, unknown>> {
  const value = diff?.[key]
  return Array.isArray(value)
    ? value.filter(
        (item): item is Record<string, unknown> => typeof item === 'object' && item !== null && !Array.isArray(item),
      )
    : []
}
