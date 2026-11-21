import { z } from 'zod'
import type { EvidenceItemCreate } from '@/types/backend'
import { getEvidenceScore, type EvidenceCitation } from '@/lib/evidence-citations'

type EvidenceReferenceSource = EvidenceItemCreate['reference_sources'][number]
type EvidenceReferenceIdentity = Pick<
  EvidenceReferenceSource,
  'document_id' | 'chunk_id' | 'chunk_index' | 'pipeline_hash' | 'doc_pipeline_key'
>

const referenceDriftDetailSchema = z.looseObject({
  item_id: z.string().min(1),
  document_id: z.string().min(1),
  chunk_id: z.string().min(1),
  reason: z.string(),
  expected: z.looseObject({
    document_id: z.string().min(1),
    chunk_id: z.string().min(1),
    chunk_index: z.number().nullish(),
    pipeline_hash: z.string().nullish(),
    doc_pipeline_key: z.string().nullish(),
  }),
  observed: z.record(z.string(), z.unknown()).optional(),
})

export type ReferenceDriftDetail = z.infer<typeof referenceDriftDetailSchema>

export function parseReferenceDriftDetails(value: unknown): ReferenceDriftDetail[] {
  return z.array(referenceDriftDetailSchema).parse(value)
}

function getReferenceKey(reference: EvidenceReferenceIdentity): string {
  return JSON.stringify([
    reference.document_id,
    reference.chunk_id,
    reference.chunk_index,
    reference.pipeline_hash,
    reference.doc_pipeline_key,
  ])
}
type WhyMissedReferenceStatus = 'retrieved' | 'missing' | 'drifted' | 'unknown'

type WhyMissedReferenceHints = {
  document_hit_rank?: number
  chunk_index_hit_rank?: number
  family_hit_rank?: number
}

type WhyMissedRetrievalInfo = {
  rank: number
  hit_type?: string | null
  score?: number | null
}

type WhyMissedReferenceReportRow = Pick<
  EvidenceReferenceSource,
  'document_id' | 'chunk_id' | 'chunk_index' | 'label'
> & {
  sourceIndex: number
  status: WhyMissedReferenceStatus
  retrieval?: WhyMissedRetrievalInfo
  drift?: Pick<ReferenceDriftDetail, 'reason' | 'expected' | 'observed'>
  hints?: WhyMissedReferenceHints
}

export type WhyMissedReport = {
  summary: {
    total_references: number
    retrieved_references: number
    missing_references: number
    drifted_references: number
    unknown_references: number
  }
  references: WhyMissedReferenceReportRow[]
}

function getFamilyKey(value: {
  family_collapse_key?: string | null
  hierarchy_family_key?: string | null
  parent_id?: unknown
}): string | undefined {
  for (const key of [value.family_collapse_key, value.hierarchy_family_key, value.parent_id]) {
    if (typeof key === 'string' && key.length > 0) return key
  }
  return undefined
}

function statusWeight(status: WhyMissedReferenceStatus): number {
  switch (status) {
    case 'drifted':
      return 0
    case 'missing':
      return 1
    case 'retrieved':
      return 2
    case 'unknown':
      return 3
  }
}

function compareReferences(left: WhyMissedReferenceReportRow, right: WhyMissedReferenceReportRow): number {
  const statusOrder = statusWeight(left.status) - statusWeight(right.status)
  if (statusOrder !== 0) return statusOrder
  const leftRank = left.retrieval?.rank
  const rightRank = right.retrieval?.rank
  if (leftRank !== undefined && rightRank !== undefined && leftRank !== rightRank) return leftRank - rightRank
  if (leftRank === undefined && rightRank !== undefined) return 1
  if (leftRank !== undefined && rightRank === undefined) return -1
  const chunkOrder = left.chunk_id.localeCompare(right.chunk_id)
  return chunkOrder === 0 ? left.sourceIndex - right.sourceIndex : chunkOrder
}

export function buildWhyMissedReport(args: {
  reference_sources: readonly EvidenceReferenceSource[]
  citations: readonly EvidenceCitation[]
  drifted_references: readonly ReferenceDriftDetail[]
  drift_complete: boolean
}): WhyMissedReport {
  const driftByReference = new Map(args.drifted_references.map((detail) => [getReferenceKey(detail.expected), detail]))
  const citationByChunkId = new Map<string, { citation: EvidenceCitation; rank: number }>()
  const documentHitRank = new Map<string, number>()
  const indexHitRank = new Map<string, number>()
  const familyHitRank = new Map<string, number>()

  for (const [index, citation] of args.citations.entries()) {
    const rank = index + 1
    const chunkId = citation.chunk_id
    if (chunkId && !citationByChunkId.has(chunkId)) citationByChunkId.set(chunkId, { citation, rank })
    const documentId = citation.document_id
    if (documentId && !documentHitRank.has(documentId)) documentHitRank.set(documentId, rank)
    if (documentId && citation.chunk_index !== undefined && citation.chunk_index !== null) {
      const key = `${documentId}:${citation.chunk_index}`
      if (!indexHitRank.has(key)) indexHitRank.set(key, rank)
    }
    const familyKey = getFamilyKey(citation)
    if (familyKey !== undefined && !familyHitRank.has(familyKey)) familyHitRank.set(familyKey, rank)
  }

  const rows: WhyMissedReferenceReportRow[] = []
  const summary = {
    total_references: args.reference_sources.length,
    retrieved_references: 0,
    missing_references: 0,
    drifted_references: 0,
    unknown_references: 0,
  }

  for (const [sourceIndex, reference] of args.reference_sources.entries()) {
    const drift = driftByReference.get(getReferenceKey(reference))
    const retrieved = citationByChunkId.get(reference.chunk_id)
    let status: WhyMissedReferenceStatus
    if (drift !== undefined) {
      status = 'drifted'
      summary.drifted_references += 1
    } else if (!args.drift_complete) {
      status = 'unknown'
      summary.unknown_references += 1
    } else if (retrieved !== undefined) {
      status = 'retrieved'
      summary.retrieved_references += 1
    } else {
      status = 'missing'
      summary.missing_references += 1
    }

    const hints: WhyMissedReferenceHints = {}
    const documentRank = documentHitRank.get(reference.document_id)
    if (documentRank !== undefined) hints.document_hit_rank = documentRank
    if (reference.chunk_index !== undefined && reference.chunk_index !== null) {
      const indexRank = indexHitRank.get(`${reference.document_id}:${reference.chunk_index}`)
      if (indexRank !== undefined) hints.chunk_index_hit_rank = indexRank
    }
    const familyKey = getFamilyKey(reference)
    if (familyKey !== undefined) {
      const familyRank = familyHitRank.get(familyKey)
      if (familyRank !== undefined) hints.family_hit_rank = familyRank
    }

    rows.push({
      sourceIndex,
      document_id: reference.document_id,
      chunk_id: reference.chunk_id,
      chunk_index: reference.chunk_index,
      label: reference.label,
      status,
      retrieval:
        retrieved === undefined
          ? undefined
          : {
              rank: retrieved.rank,
              hit_type: retrieved.citation.hit_type,
              score: getEvidenceScore(retrieved.citation),
            },
      drift:
        drift === undefined
          ? undefined
          : {
              reason: drift.reason,
              expected: drift.expected,
              observed: drift.observed,
            },
      hints: Object.keys(hints).length === 0 ? undefined : hints,
    })
  }
  rows.sort(compareReferences)
  return { summary, references: rows }
}
