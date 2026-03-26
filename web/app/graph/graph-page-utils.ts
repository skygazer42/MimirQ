import type { GraphData, GraphLink, GraphNode } from '@/lib/graph-parser'
import { toTrimmedPrimitiveString } from '@/lib/primitive-text'

export type GraphConfBucket = 'high' | 'medium' | 'low'
export type GraphRecord = Record<string, unknown>
export type GraphEndpointRef =
  | string
  | number
  | {
      id?: string | number | null
      label?: string | number | null
    }
  | null
  | undefined

export type GraphNodeLike = GraphNode & {
  meta?: GraphRecord
  kind?: unknown
  type?: unknown
  source?: unknown
}

export type GraphLinkLike = Omit<GraphLink, 'source' | 'target'> & {
  source: GraphEndpointRef
  target: GraphEndpointRef
  meta?: GraphRecord
  id?: string | number | null
  index?: number
  kind?: unknown
  predicate?: unknown
  label?: unknown
  confidence?: unknown
  weight?: unknown
}

export type GraphDatasetDocumentSummary = {
  id?: unknown
  status?: unknown
}

export type GraphContextMenuTarget =
  | { type: 'node'; node: GraphNodeLike }
  | { type: 'link'; link: GraphLinkLike }
  | { type: 'background' }

export type GraphContextMenuState = {
  x: number
  y: number
  target: GraphContextMenuTarget
}

export function coerceTrimmedString(value: unknown): string {
  return toTrimmedPrimitiveString(value)
}

export function stripFilenameExtension(name: string): string {
  const value = String(name || '').trim()
  if (!value) return ''
  const idx = value.lastIndexOf('.')
  if (idx <= 0) return value
  return value.slice(0, idx)
}

export function asGraphRecord(value: unknown): GraphRecord | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null
  return value as GraphRecord
}

export function getGraphNodeKind(node: GraphNodeLike | null | undefined): string {
  return coerceTrimmedString(node?.meta?.kind ?? node?.kind)
}

export function getGraphNodeType(node: GraphNodeLike | null | undefined): string {
  return coerceTrimmedString(node?.meta?.type ?? node?.type)
}

export function getGraphLinkKind(link: GraphLinkLike | null | undefined): string {
  return coerceTrimmedString(link?.meta?.kind ?? link?.kind)
}

export function getGraphLinkPredicate(link: GraphLinkLike | null | undefined): string {
  return coerceTrimmedString(link?.meta?.predicate ?? link?.predicate ?? link?.label)
}

export function getGraphLinkConfidence(link: GraphLinkLike | null | undefined): number | null {
  const raw = link?.meta?.confidence ?? link?.confidence ?? link?.weight
  const num = Number(raw)
  if (!Number.isFinite(num)) return null
  return num
}

export function getGraphLinkEndpointId(raw: GraphEndpointRef): string {
  if (raw == null) return ''
  if (typeof raw === 'string' || typeof raw === 'number') return String(raw)
  if (typeof raw === 'object' && 'id' in raw) {
    return String(raw.id || '')
  }
  return ''
}

export function bucketConfidence(conf: number | null): GraphConfBucket | null {
  if (conf == null) return null
  if (conf >= 0.8) return 'high'
  if (conf >= 0.5) return 'medium'
  return 'low'
}

export function parseCsvList(value: string | null): string[] {
  if (!value) return []
  return value
    .split(',')
    .map((segment) => segment.trim())
    .filter(Boolean)
}

export function coerceBoundedInt(
  value: string | null,
  fallback: number,
  min: number,
  max: number
): number {
  const num = Math.floor(Number(value))
  if (!Number.isFinite(num)) return fallback
  return Math.min(max, Math.max(min, num))
}

export function getScopedDocumentId(item: GraphDatasetDocumentSummary): string {
  return String(item.id || '').trim()
}

export function isPendingScopedDocument(item: GraphDatasetDocumentSummary): boolean {
  const status = String(item.status || '').trim().toLowerCase()
  return status === 'pending' || status === 'processing'
}

export function isGraphData(value: unknown): value is GraphData {
  return Boolean(
    value &&
      typeof value === 'object' &&
      'nodes' in value &&
      'links' in value &&
      Array.isArray((value as GraphData).nodes) &&
      Array.isArray((value as GraphData).links)
  )
}
