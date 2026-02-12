import type { Citation } from '@/types'

export interface RankedEvidenceCitation {
  citation: Citation
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
  const s = String(needle || '').trim()
  if (!s) return 0
  if (/^\d/.test(s)) return 3
  if (/[\\/.:]/.test(s)) return 2
  return 1
}

function citationNumericScore(c: Citation): number {
  const raw = (c.retrieval_score ?? c.rerank_score ?? c.relevance_score ?? c.vector_score ?? c.bm25_score ?? 0) as any
  const n = Number(raw)
  return Number.isFinite(n) ? n : 0
}

export function extractEvidenceNeedles(expectedAnswer: string, opts?: { max_needles?: number }): string[] {
  const maxNeedles = Math.max(1, Math.min(50, Number(opts?.max_needles ?? 12) || 12))
  const text = String(expectedAnswer || '').trim()
  if (!text) return []

  const lower = text.toLowerCase()
  const numbers = lower.match(/\b\d+(?:\.\d+)?\b/g) || []
  const words = lower.match(/[a-z0-9_./\\-]{4,}/g) || []

  const out: string[] = []
  const seen = new Set<string>()

  const push = (raw: string) => {
    const s = String(raw || '').trim().toLowerCase()
    if (!s) return
    if (seen.has(s)) return
    seen.add(s)
    out.push(s)
  }

  for (const n of numbers) push(n)
  for (const w of words) {
    if (STOPWORDS.has(w)) continue
    push(w)
  }

  return out.slice(0, maxNeedles)
}

export function rankEvidenceCitations(citations: Citation[], needles: string[]): RankedEvidenceCitation[] {
  const ns = (needles || []).map((n) => String(n || '').trim().toLowerCase()).filter(Boolean)
  const base = citations || []
  if (!ns.length) {
    return base.map((c) => ({ citation: c, score: 0, hits: [] }))
  }

  const ranked: RankedEvidenceCitation[] = base.map((c) => {
    const hay = `${c.chunk_content || ''}\n${c.header_path || ''}\n${c.document_name || ''}`.toLowerCase()
    const hits: string[] = []
    let score = 0
    for (const n of ns) {
      if (!n) continue
      if (!hay.includes(n)) continue
      hits.push(n)
      score += needleWeight(n)
    }
    return { citation: c, score, hits: hits.slice(0, 8) }
  })

  ranked.sort((a, b) => {
    if (b.score !== a.score) return b.score - a.score
    return citationNumericScore(b.citation) - citationNumericScore(a.citation)
  })

  return ranked
}

