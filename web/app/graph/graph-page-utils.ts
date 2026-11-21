import { z } from 'zod'

import type { GraphData, GraphLink, GraphNode } from '@/lib/graph-types'
import { toTrimmedPrimitiveString } from '@/lib/primitive-text'

export type GraphConfBucket = 'high' | 'medium' | 'low'
export const GRAPH_CONFIDENCE_THRESHOLDS = { high: 0.8, medium: 0.5 } as const
type GraphRecord = Record<string, unknown>
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

export type GraphContextMenuTarget =
  { type: 'node'; node: GraphNodeLike } | { type: 'link'; link: GraphLinkLike } | { type: 'background' }

export type GraphContextMenuState = {
  x: number
  y: number
  target: GraphContextMenuTarget
}

export function coerceTrimmedString(value: unknown): string {
  return toTrimmedPrimitiveString(value)
}

export function stripFilenameExtension(name: string): string {
  const value = name.trim()
  const idx = value.lastIndexOf('.')
  if (idx <= 0) return value
  return value.slice(0, idx)
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
  const confidence = link?.meta?.confidence ?? link?.confidence
  const value = typeof confidence === 'string' && confidence.trim() !== '' ? Number(confidence) : confidence
  return typeof value === 'number' && value >= 0 && value <= 1 ? value : null
}

export function getGraphLinkDisplayWeight(link: GraphLinkLike): number | null {
  const weight = link.meta?.confidence ?? link.confidence ?? link.weight
  const value = typeof weight === 'string' && weight.trim() !== '' ? Number(weight) : weight
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

export function getGraphLinkEndpointId(raw: GraphEndpointRef): string {
  if (raw == null) return ''
  if (typeof raw === 'string' || typeof raw === 'number') return String(raw)
  return raw.id == null ? '' : String(raw.id)
}

export function bucketConfidence(conf: number | null): GraphConfBucket | null {
  if (conf == null) return null
  if (conf >= GRAPH_CONFIDENCE_THRESHOLDS.high) return 'high'
  if (conf >= GRAPH_CONFIDENCE_THRESHOLDS.medium) return 'medium'
  return 'low'
}

export function parseCsvList(value: string | null): string[] {
  if (value === null) return []
  return value
    .split(',')
    .map((segment) => segment.trim())
    .filter((segment) => segment !== '')
}

export function coerceBoundedInt(value: string | null, fallback: number, min: number, max: number): number {
  if (value === null || value.trim() === '') return fallback
  const num = Math.floor(Number(value))
  if (!Number.isFinite(num)) return fallback
  return Math.min(max, Math.max(min, num))
}

const graphTraceReplaySchema = z.object({
  ts_ms: z.number(),
  request_id: z.string().nullish(),
  steps: z.array(z.unknown()),
  retrieval: z.object({ mode: z.string().nullish(), elapsed_sec: z.number().nullish() }).nullish(),
  rerank: z
    .object({ enabled: z.boolean().optional(), provider: z.string().nullish(), elapsed_sec: z.number().nullish() })
    .nullish(),
  citations_count: z.number().int().nonnegative().optional(),
  citations: z
    .array(
      z.looseObject({
        document_id: z.string().nullish(),
        page_number: z.number().nullish(),
        relevance_score: z.number().nullish(),
        retrieval_score: z.number().nullish(),
        rerank_score: z.number().nullish(),
      }),
    )
    .nullish(),
})

export type GraphTraceReplay = z.infer<typeof graphTraceReplaySchema>

export function extractTraceFromPayload(payload: unknown): GraphTraceReplay | null {
  let trace = payload
  if (Array.isArray(payload)) {
    trace = payload[0]
  } else if (payload !== null && typeof payload === 'object' && 'items' in payload && Array.isArray(payload.items)) {
    trace = payload.items[0]
  }
  const result = graphTraceReplaySchema.safeParse(trace)
  return result.success ? result.data : null
}

export function buildGraphFromTrace(trace: GraphTraceReplay): {
  rootId: string
  graph: GraphData
  steps: { node: string; reason: string }[]
} {
  const rootId = `rag-trace:${trace.request_id ? trace.request_id : trace.ts_ms}`
  const nodes: GraphData['nodes'] = []
  const links: GraphData['links'] = []

  const hasRerank = trace.rerank?.enabled ?? trace.rerank?.elapsed_sec != null
  const idRetrieve = `${rootId}:retrieve`
  const idRerank = `${rootId}:rerank`
  const idCitations = `${rootId}:citations`

  nodes.push(
    { id: rootId, label: 'RAG Trace', kind: 'trace', val: 2.5, color: '#0ea5e9' },
    { id: idRetrieve, label: 'Retrieve', kind: 'step', val: 2, color: '#2563eb' },
  )
  if (hasRerank) {
    nodes.push({ id: idRerank, label: 'Rerank', kind: 'step', val: 2, color: '#14b8a6' })
  }
  nodes.push({ id: idCitations, label: 'Citations', kind: 'step', val: 2, color: '#f97316' })

  links.push({ source: rootId, target: idRetrieve, label: 'start' })
  if (hasRerank) {
    links.push(
      { source: idRetrieve, target: idRerank, label: 'rerank' },
      { source: idRerank, target: idCitations, label: 'cite' },
    )
  } else {
    links.push({ source: idRetrieve, target: idCitations, label: 'cite' })
  }

  const citations = (trace.citations ?? []).slice(0, 20)
  const citationNodeIds: string[] = []
  citations.forEach((citation, idx) => {
    const documentId = citation.document_id?.slice(0, 8)
    const documentLabel = documentId === undefined || documentId === '' ? 'doc' : documentId
    const score = citation.rerank_score ?? citation.retrieval_score ?? citation.relevance_score
    const scoreText = score == null ? '' : ` score=${score.toFixed(3)}`
    const pageText = citation.page_number == null ? '' : ` · p${citation.page_number}`
    const id = `${rootId}:c${idx}`

    citationNodeIds.push(id)
    nodes.push({
      id,
      label: `#${idx + 1} ${documentLabel}${pageText}${scoreText}`,
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
    reason: `mode=${trace.retrieval?.mode ?? '—'} · elapsed=${trace.retrieval?.elapsed_sec ?? '—'}s`,
  })
  if (hasRerank) {
    steps.push({
      node: idRerank,
      reason: `provider=${trace.rerank?.provider ?? '—'} · elapsed=${trace.rerank?.elapsed_sec ?? '—'}s`,
    })
  }
  steps.push({
    node: idCitations,
    reason: trace.citations_count === undefined ? '查看记录中的引用' : `count=${trace.citations_count}`,
  })
  citationNodeIds.forEach((id) => {
    steps.push({ node: id, reason: 'retrieved citation' })
  })

  return { rootId, graph: { nodes, links }, steps }
}
