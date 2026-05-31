import type { GraphData, GraphLink, GraphNode } from '@/lib/graph-parser'
import { toTrimmedPrimitiveString } from '@/lib/primitive-text'
import type { RagTrace } from '@/types'

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
  return typeof item.id === 'string' || typeof item.id === 'number' ? String(item.id).trim() : ''
}

export function isPendingScopedDocument(item: GraphDatasetDocumentSummary): boolean {
  const status =
    typeof item.status === 'string' || typeof item.status === 'number' ? String(item.status).trim().toLowerCase() : ''
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

export function isRagTraceValue(value: unknown): value is RagTrace {
  const record = asGraphRecord(value)
  return Boolean(record && typeof record.ts_ms === 'number' && Array.isArray(record.steps))
}

export function extractTraceFromPayload(payload: unknown): RagTrace | null {
  if (!payload) return null

  if (Array.isArray(payload)) {
    const [first] = payload
    return isRagTraceValue(first) ? first : null
  }

  const payloadRecord = asGraphRecord(payload)
  if (!payloadRecord) return null

  const responseItems = payloadRecord.items
  if (Array.isArray(responseItems)) {
    const [first] = responseItems
    return isRagTraceValue(first) ? first : null
  }

  return isRagTraceValue(payloadRecord) ? payloadRecord : null
}

export function buildGraphFromTrace(trace: RagTrace): {
  graph: GraphData
  steps: { node: string; reason: string }[]
} {
  const rootId = `rag-trace:${trace.request_id || trace.ts_ms}`
  const nodes: GraphData['nodes'] = []
  const links: GraphData['links'] = []

  const hasRerank = Boolean(trace?.rerank?.enabled || trace?.rerank?.elapsed_sec != null)
  const idRetrieve = `${rootId}:retrieve`
  const idRerank = `${rootId}:rerank`
  const idCitations = `${rootId}:citations`

  nodes.push(
    { id: rootId, label: 'RAG Trace', kind: 'trace', val: 2.5, color: '#0ea5e9' },
    { id: idRetrieve, label: 'Retrieve', kind: 'step', val: 2, color: '#2563eb' }
  )
  if (hasRerank) {
    nodes.push({ id: idRerank, label: 'Rerank', kind: 'step', val: 2, color: '#14b8a6' })
  }
  nodes.push({ id: idCitations, label: 'Citations', kind: 'step', val: 2, color: '#f97316' })

  links.push({ source: rootId, target: idRetrieve, label: 'start' })
  if (hasRerank) {
    links.push(
      { source: idRetrieve, target: idRerank, label: 'rerank' },
      { source: idRerank, target: idCitations, label: 'cite' }
    )
  } else {
    links.push({ source: idRetrieve, target: idCitations, label: 'cite' })
  }

  const citations = (trace.citations || []).slice(0, 20)
  const citationNodeIds: string[] = []
  citations.forEach((citation, idx) => {
    const doc = String(citation.document_id || '').slice(0, 8) || 'doc'
    const page = citation.page_number == null ? '' : `p${citation.page_number}`
    const score = citation.rerank_score ?? citation.retrieval_score ?? citation.relevance_score
    const scoreText = score == null ? '' : ` score=${Number(score).toFixed(3)}`
    const pageText = page ? ` · ${page}` : ''
    const id = `${rootId}:c${idx}`

    citationNodeIds.push(id)
    nodes.push({
      id,
      label: `#${idx + 1} ${doc}${pageText}${scoreText}`,
      kind: 'citation',
      val: 1.2,
      color: '#64748b',
      meta: citation,
    })
  })

  if (citationNodeIds.length > 0) {
    links.push({ source: idCitations, target: citationNodeIds[0], label: 'topk' })
    for (let idx = 1; idx < citationNodeIds.length; idx += 1) {
      links.push({ source: citationNodeIds[idx - 1], target: citationNodeIds[idx], label: 'next' })
    }
  }

  const steps: { node: string; reason: string }[] = []
  steps.push({
    node: idRetrieve,
    reason: `mode=${trace?.retrieval?.mode || '—'} · elapsed=${trace?.retrieval?.elapsed_sec ?? '—'}s`,
  })
  if (hasRerank) {
    steps.push({
      node: idRerank,
      reason: `provider=${trace?.rerank?.provider || '—'} · elapsed=${trace?.rerank?.elapsed_sec ?? '—'}s`,
    })
  }
  steps.push({ node: idCitations, reason: `count=${trace.citations_count}` })
  citationNodeIds.forEach((id) => {
    steps.push({ node: id, reason: 'retrieved citation' })
  })

  return { graph: { nodes, links }, steps }
}
