import type { Citation } from '@/types'
import type {
  WhyMissedDriftInfo,
  WhyMissedReferenceHints,
  WhyMissedReferenceReportRow,
  WhyMissedReferenceStatus,
  WhyMissedReport,
  WhyMissedRetrievalInfo,
  WhyMissedSummary,
} from '@/types/evaluation'

export type {
  WhyMissedDriftInfo,
  WhyMissedReferenceHints,
  WhyMissedReferenceReportRow,
  WhyMissedReferenceStatus,
  WhyMissedReport,
  WhyMissedRetrievalInfo,
  WhyMissedSummary,
} from '@/types/evaluation'

type WhyMissedUnknownRecord = Record<string, unknown>
type WhyMissedReferenceSource = WhyMissedUnknownRecord & {
  document_id?: unknown
  chunk_id?: unknown
  chunk_index?: unknown
  label?: unknown
  family_collapse_key?: unknown
  hierarchy_family_key?: unknown
  parent_id?: unknown
}
type WhyMissedDriftReference = WhyMissedUnknownRecord & {
  chunk_id?: unknown
  reason?: unknown
  expected?: unknown
  observed?: unknown
}

function asNonEmptyString(value: unknown): string | null {
  if (typeof value !== 'string') return null
  const s = value.trim()
  return s || null
}

function asOptionalInt(value: unknown): number | undefined {
  if (value === null || value === undefined) return undefined
  const n = Number(value)
  if (!Number.isFinite(n)) return undefined
  return Math.trunc(n)
}

function asRecord(value: unknown): WhyMissedUnknownRecord | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null
  return value as WhyMissedUnknownRecord
}

function getRecordString(record: WhyMissedUnknownRecord | null, key: string): string | null {
  return asNonEmptyString(record?.[key])
}

function getRecordInt(record: WhyMissedUnknownRecord | null, key: string): number | undefined {
  return asOptionalInt(record?.[key])
}

function getFamilyKey(record: WhyMissedUnknownRecord | null): string | null {
  return (
    getRecordString(record, 'family_collapse_key') ??
    getRecordString(record, 'hierarchy_family_key') ??
    getRecordString(record, 'parent_id')
  )
}

function statusWeight(status: WhyMissedReferenceStatus): number {
  switch (status) {
    case 'drifted':
      return 0
    case 'missing':
      return 1
    case 'retrieved':
      return 2
    default:
      return 3
  }
}

function citationNumericScore(c: Citation): number | undefined {
  const raw: unknown = c.retrieval_score ?? c.rerank_score ?? c.relevance_score ?? c.vector_score ?? c.bm25_score
  const n = Number(raw)
  return Number.isFinite(n) ? n : undefined
}

export function buildWhyMissedReport(args: {
  reference_sources: WhyMissedReferenceSource[]
  citations: Citation[]
  drifted_references: WhyMissedDriftReference[]
}): WhyMissedReport {
  const referenceSources = args.reference_sources
  const citations = args.citations
  const drifted = args.drifted_references

  const driftByChunkId = new Map<string, WhyMissedDriftReference>()
  for (const d of drifted) {
    const chunkId = getRecordString(d, 'chunk_id')
    if (!chunkId) continue
    driftByChunkId.set(chunkId, d)
  }

  const citationByChunkId = new Map<string, { citation: Citation; rank: number }>()
  const docHitRank = new Map<string, number>()
  const indexHitRank = new Map<string, number>()
  const familyHitRank = new Map<string, number>()
  for (let i = 0; i < citations.length; i++) {
    const c = citations[i]
    const citationRecord = asRecord(c)
    const rank = i + 1

    const chunkId = getRecordString(citationRecord, 'chunk_id')
    if (chunkId && !citationByChunkId.has(chunkId)) {
      citationByChunkId.set(chunkId, { citation: c, rank })
    }

    const docId = getRecordString(citationRecord, 'document_id')
    if (docId && !docHitRank.has(docId)) {
      docHitRank.set(docId, rank)
    }

    const chunkIndex = getRecordInt(citationRecord, 'chunk_index')
    if (docId && chunkIndex !== undefined) {
      const key = `${docId}:${chunkIndex}`
      if (!indexHitRank.has(key)) indexHitRank.set(key, rank)
    }

    const fam = getFamilyKey(citationRecord)
    if (fam && !familyHitRank.has(fam)) familyHitRank.set(fam, rank)
  }

  const rows: WhyMissedReferenceReportRow[] = []
  let retrieved = 0
  let missing = 0
  let driftedCnt = 0
  let unknown = 0

  for (const ref of referenceSources) {
    const chunkId = getRecordString(ref, 'chunk_id') || ''
    const docId = getRecordString(ref, 'document_id')
    const chunkIndex = getRecordInt(ref, 'chunk_index')
    const rawLabel = ref.label
    const label =
      typeof rawLabel === 'string' || typeof rawLabel === 'number' || typeof rawLabel === 'boolean'
        ? String(rawLabel)
        : null

    const driftDetail = chunkId ? driftByChunkId.get(chunkId) : undefined
    const cite = chunkId ? citationByChunkId.get(chunkId) : undefined

    const hints: WhyMissedReferenceHints = {}
    if (docId) {
      const dRank = docHitRank.get(docId)
      if (dRank) hints.document_hit_rank = dRank
      if (chunkIndex !== undefined) {
        const iRank = indexHitRank.get(`${docId}:${chunkIndex}`)
        if (iRank) hints.chunk_index_hit_rank = iRank
      }
    }
    const refFam = getFamilyKey(ref)
    if (refFam) {
      const fRank = familyHitRank.get(refFam)
      if (fRank) hints.family_hit_rank = fRank
    }

    const status: WhyMissedReferenceStatus = chunkId
      ? driftDetail
        ? 'drifted'
        : cite
          ? 'retrieved'
          : 'missing'
      : 'unknown'
    if (!chunkId) {
      unknown += 1
    } else if (driftDetail) {
      driftedCnt += 1
    } else if (cite) {
      retrieved += 1
    } else {
      missing += 1
    }

    rows.push({
      document_id: docId,
      chunk_id: chunkId,
      chunk_index: chunkIndex,
      label,
      status,
      retrieval: cite
        ? {
            rank: cite.rank,
            hit_type: getRecordString(asRecord(cite.citation), 'hit_type') ?? undefined,
            score: citationNumericScore(cite.citation),
          }
        : undefined,
      drift: driftDetail
        ? {
            reason: typeof driftDetail.reason === 'string' ? driftDetail.reason : 'drift',
            expected: driftDetail.expected,
            observed: driftDetail.observed,
          }
        : undefined,
      hints: Object.keys(hints).length ? hints : undefined,
    })
  }

  // Stable ordering for UI.
  rows.sort((a, b) => {
    const aw = statusWeight(a.status)
    const bw = statusWeight(b.status)
    if (aw !== bw) return aw - bw
    const ar = a.retrieval?.rank ?? 1_000_000
    const br = b.retrieval?.rank ?? 1_000_000
    if (ar !== br) return ar - br
    return String(a.chunk_id || '').localeCompare(String(b.chunk_id || ''))
  })

  return {
    summary: {
      total_references: rows.length,
      retrieved_references: retrieved,
      missing_references: missing,
      drifted_references: driftedCnt,
      unknown_references: unknown,
    },
    references: rows,
  }
}
