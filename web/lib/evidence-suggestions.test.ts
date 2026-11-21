import { describe, expect, it } from 'vitest'
import { formatEvidenceScore, getEvidenceScore, parseEvidenceCitations } from './evidence-citations'
import { extractEvidenceNeedles, rankEvidenceCitations } from './evidence-suggestions'

describe('evidence suggestion projections', () => {
  it('keeps zero and negative scores distinct from missing scores', () => {
    const citations = parseEvidenceCitations([{ relevance_score: -1 }, {}, { retrieval_score: 0, relevance_score: 1 }])
    const ranked = rankEvidenceCitations(citations, ['same'])
    expect(ranked.map((entry) => entry.sourceIndex)).toEqual([2, 0, 1])
    expect(getEvidenceScore(citations[2])).toBe(0)
    expect(formatEvidenceScore(citations[2])).toBe('0.0000')
    expect(formatEvidenceScore(citations[1])).toBe('未提供')
    expect(citations.map((citation) => citation.relevance_score)).toEqual([-1, undefined, 1])
  })

  it('preserves source row identity when matching terms reorder citations', () => {
    const citations = parseEvidenceCitations([
      { chunk_content: '' },
      { chunk_content: '  Policy 12\n', header_path: null },
    ])
    const ranked = rankEvidenceCitations(citations, extractEvidenceNeedles('Policy 12'))
    expect(ranked.map((entry) => entry.sourceIndex)).toEqual([1, 0])
    expect(ranked[0].citation).toBe(citations[1])
    expect(ranked[0].score).toBe(4)
    expect(ranked[0].hits).toEqual(['12', 'policy'])
    expect(citations[1].chunk_content).toBe('  Policy 12\n')
  })

  it('keeps server order when there are no matching terms to rank by', () => {
    const citations = parseEvidenceCitations([{ relevance_score: 0 }, { relevance_score: 1 }])
    expect(rankEvidenceCitations(citations, []).map((entry) => entry.sourceIndex)).toEqual([0, 1])
  })
})
