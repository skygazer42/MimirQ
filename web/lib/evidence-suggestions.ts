import { getEvidenceScore, type EvidenceCitation } from '@/lib/evidence-citations'

export type RankedEvidenceCitation = {
  citation: EvidenceCitation
  sourceIndex: number
  score: number
  hits: string[]
}

const STOPWORDS = new Set([
  'a',
  'an',
  'and',
  'are',
  'as',
  'at',
  'be',
  'by',
  'can',
  'could',
  'for',
  'from',
  'has',
  'have',
  'in',
  'is',
  'it',
  'its',
  'of',
  'on',
  'or',
  'should',
  'that',
  'the',
  'this',
  'to',
  'was',
  'were',
  'will',
  'with',
])

function needleWeight(needle: string): number {
  if (/^\d/.test(needle)) return 3
  if (/[\\/.:]/.test(needle)) return 2
  return 1
}

export function extractEvidenceNeedles(expectedAnswer: string): string[] {
  const text = expectedAnswer.trim().toLowerCase()
  const numbers = text.match(/\b\d+(?:\.\d+)?\b/g) ?? []
  const words = text.match(/[a-z0-9_./\\-]{4,}/g) ?? []
  const needles = new Set<string>(numbers)
  for (const word of words) {
    if (!STOPWORDS.has(word)) needles.add(word)
  }
  return Array.from(needles).slice(0, 12)
}

export function rankEvidenceCitations(
  citations: readonly EvidenceCitation[],
  needles: readonly string[],
): RankedEvidenceCitation[] {
  const normalizedNeedles = needles.map((needle) => needle.trim().toLowerCase()).filter((needle) => needle.length > 0)
  const ranked = citations.map((citation, sourceIndex): RankedEvidenceCitation => {
    const text = [citation.chunk_content, citation.header_path, citation.document_name]
      .filter((value) => typeof value === 'string')
      .join('\n')
      .toLowerCase()
    const hits = normalizedNeedles.filter((needle) => text.includes(needle))
    const score = hits.reduce((total, needle) => total + needleWeight(needle), 0)
    return { citation, sourceIndex, score, hits: hits.slice(0, 8) }
  })
  if (normalizedNeedles.length === 0) return ranked
  return ranked.sort((a, b) => {
    if (a.score !== b.score) return b.score - a.score
    const aScore = getEvidenceScore(a.citation)
    const bScore = getEvidenceScore(b.citation)
    if (aScore === undefined || aScore === null) return bScore === undefined || bScore === null ? 0 : 1
    if (bScore === undefined || bScore === null) return -1
    return bScore - aScore
  })
}
