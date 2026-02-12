import { describe, expect, it } from 'vitest'

import { extractEvidenceNeedles, rankEvidenceCitations } from './evidence-suggestions'

describe('extractEvidenceNeedles', () => {
  it('extracts numbers and path-like tokens', () => {
    const needles = extractEvidenceNeedles('Refund within 30 days. See docs/refund-policy.md for details.')
    expect(needles).toContain('30')
    expect(needles).toContain('docs/refund-policy.md')
  })

  it('respects max_needles', () => {
    const needles = extractEvidenceNeedles('one two three four five six seven eight nine ten eleven twelve', { max_needles: 3 })
    expect(needles.length).toBeLessThanOrEqual(3)
  })
})

describe('rankEvidenceCitations', () => {
  it('ranks citations by expected-answer keyword hits', () => {
    const expected = 'refund within 30 days (docs/refund-policy.md)'
    const needles = extractEvidenceNeedles(expected)

    const citations = [
      {
        chunk_id: 'c1',
        chunk_content: 'You can request a refund within 30 days of purchase.',
        retrieval_score: 0.1,
        document_name: 'Refund Policy',
      },
      {
        chunk_id: 'c2',
        chunk_content: 'Shipping policy and delivery timelines.',
        retrieval_score: 0.9,
        document_name: 'Shipping Policy',
      },
    ] as any

    const ranked = rankEvidenceCitations(citations, needles)
    expect(ranked[0].citation.chunk_id).toBe('c1')
    expect(ranked[0].score).toBeGreaterThan(0)
  })
})

