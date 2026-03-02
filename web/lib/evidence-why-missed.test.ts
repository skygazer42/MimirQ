import { describe, expect, it } from 'vitest'

import { buildWhyMissedReport } from './evidence-why-missed'

describe('buildWhyMissedReport', () => {
  it('classifies retrieved vs missing vs drifted references with ranks and hints', () => {
    const reference_sources = [
      {
        document_id: 'd1',
        chunk_id: 'c1',
        chunk_index: 5,
        label: 'Doc1 chunk5',
      },
      {
        document_id: 'd2',
        chunk_id: 'c2',
        chunk_index: 1,
        label: 'Doc2 chunk1',
      },
    ] as any

    const citations = [
      {
        document_id: 'd1',
        chunk_id: 'c1',
        chunk_index: 5,
        hit_type: 'vector',
        retrieval_score: 0.2,
      },
      {
        document_id: 'd2',
        chunk_id: 'cX',
        chunk_index: 1,
        hit_type: 'keyword',
        retrieval_score: 0.9,
      },
    ] as any

    const drifted_references = [
      {
        document_id: 'd2',
        chunk_id: 'c2',
        reason: 'chunk_missing',
        expected: { chunk_id: 'c2' },
        observed: {},
      },
    ] as any

    const report = buildWhyMissedReport({ reference_sources, citations, drifted_references })

    expect(report.summary.total_references).toBe(2)
    expect(report.summary.retrieved_references).toBe(1)
    expect(report.summary.drifted_references).toBe(1)
    expect(report.summary.missing_references).toBe(0)

    const r1 = report.references.find((r) => r.chunk_id === 'c1')
    expect(r1?.status).toBe('retrieved')
    expect(r1?.retrieval?.rank).toBe(1)

    const r2 = report.references.find((r) => r.chunk_id === 'c2')
    expect(r2?.status).toBe('drifted')
    expect(r2?.drift?.reason).toBe('chunk_missing')
    // Even if the original chunk_id is missing, the same document+index might still show up.
    expect(r2?.hints?.document_hit_rank).toBe(2)
    expect(r2?.hints?.chunk_index_hit_rank).toBe(2)
  })
})

