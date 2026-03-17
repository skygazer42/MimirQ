import type { Citation } from '@/types'

export type WhyMissedReferenceStatus = 'retrieved' | 'missing' | 'drifted' | 'unknown'

export interface WhyMissedReferenceHints {
  /** Rank (1-based) of the first citation that matches the reference's document_id. */
  document_hit_rank?: number
  /** Rank (1-based) of the first citation that matches (document_id, chunk_index). */
  chunk_index_hit_rank?: number
  /** Rank (1-based) of the first citation that matches the reference's hierarchy family key. */
  family_hit_rank?: number
}

export interface WhyMissedRetrievalInfo {
  rank: number
  hit_type?: string
  score?: number
}

export interface WhyMissedDriftInfo {
  reason: string
  expected?: any
  observed?: any
}

export interface WhyMissedReferenceReportRow {
  document_id: string | null
  chunk_id: string
  chunk_index?: number
  label?: string | null
  status: WhyMissedReferenceStatus
  retrieval?: WhyMissedRetrievalInfo
  drift?: WhyMissedDriftInfo
  hints?: WhyMissedReferenceHints
}

export interface WhyMissedSummary {
  total_references: number
  retrieved_references: number
  missing_references: number
  drifted_references: number
  unknown_references: number
}

export interface WhyMissedReport {
  summary: WhyMissedSummary
  references: WhyMissedReferenceReportRow[]
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

function citationNumericScore(c: Citation): number | undefined {
  const raw = (c.retrieval_score ?? c.rerank_score ?? c.relevance_score ?? c.vector_score ?? c.bm25_score) as any
  const n = Number(raw)
  return Number.isFinite(n) ? n : undefined
}

export function buildWhyMissedReport(args: {
  reference_sources: Array<any>
  citations: Citation[]
  drifted_references?: Array<any>
}): WhyMissedReport {
  const referenceSources = Array.isArray(args.reference_sources) ? args.reference_sources : []
  const citations = Array.isArray(args.citations) ? args.citations : []
  const drifted = Array.isArray(args.drifted_references) ? args.drifted_references : []

  const driftByChunkId = new Map<string, any>()
  for (const d of drifted) {
    const chunkId = asNonEmptyString((d)?.chunk_id)
    if (!chunkId) continue
    driftByChunkId.set(chunkId, d)
  }

  const citationByChunkId = new Map<string, { citation: Citation; rank: number }>()
  const docHitRank = new Map<string, number>()
  const indexHitRank = new Map<string, number>()
  const familyHitRank = new Map<string, number>()
  for (let i = 0; i < citations.length; i++) {
    const c = citations[i] as any
    const rank = i + 1

    const chunkId = asNonEmptyString(c?.chunk_id)
    if (chunkId && !citationByChunkId.has(chunkId)) {
      citationByChunkId.set(chunkId, { citation: c, rank })
    }

    const docId = asNonEmptyString(c?.document_id)
    if (docId && !docHitRank.has(docId)) {
      docHitRank.set(docId, rank)
    }

    const chunkIndex = asOptionalInt(c?.chunk_index)
    if (docId && chunkIndex !== undefined) {
      const key = `${docId}:${chunkIndex}`
      if (!indexHitRank.has(key)) indexHitRank.set(key, rank)
    }

    const fam =
      asNonEmptyString(c?.family_collapse_key) ??
      asNonEmptyString(c?.hierarchy_family_key) ??
      asNonEmptyString(c?.parent_id) ??
      null
    if (fam && !familyHitRank.has(fam)) familyHitRank.set(fam, rank)
  }

  const rows: WhyMissedReferenceReportRow[] = []
  let retrieved = 0
  let missing = 0
  let driftedCnt = 0
  let unknown = 0

  for (const ref of referenceSources) {
    const chunkId = asNonEmptyString((ref)?.chunk_id) || ''
    const docId = asNonEmptyString((ref)?.document_id)
    const chunkIndex = asOptionalInt((ref)?.chunk_index)
    const label = (ref)?.label ?? null

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
    const refFam =
      asNonEmptyString((ref as any)?.family_collapse_key) ??
      asNonEmptyString((ref as any)?.hierarchy_family_key) ??
      asNonEmptyString((ref as any)?.parent_id) ??
      null
    if (refFam) {
      const fRank = familyHitRank.get(refFam)
      if (fRank) hints.family_hit_rank = fRank
    }

    let status: WhyMissedReferenceStatus = 'unknown'
    if (!chunkId) {
      status = 'unknown'
      unknown += 1
    } else if (driftDetail) {
      status = 'drifted'
      driftedCnt += 1
    } else if (cite) {
      status = 'retrieved'
      retrieved += 1
    } else {
      status = 'missing'
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
            hit_type: asNonEmptyString((cite.citation as any)?.hit_type) ?? undefined,
            score: citationNumericScore(cite.citation),
          }
        : undefined,
      drift: driftDetail
        ? {
            reason: String((driftDetail)?.reason || 'drift'),
            expected: (driftDetail)?.expected,
            observed: (driftDetail)?.observed,
          }
        : undefined,
      hints: Object.keys(hints).length ? hints : undefined,
    })
  }

  // Stable ordering for UI.
  rows.sort((a, b) => {
    const aw = (() => {
    if (a.status === 'drifted') {
        return 0;
    }
    else if (a.status === 'missing') {
            return 1;
        }
        else if (a.status === 'retrieved') {
                return 2;
            }
            else {
                return 3;
            }
})()
    const bw = (() => {
    if (b.status === 'drifted') {
        return 0;
    }
    else if (b.status === 'missing') {
            return 1;
        }
        else if (b.status === 'retrieved') {
                return 2;
            }
            else {
                return 3;
            }
})()
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
