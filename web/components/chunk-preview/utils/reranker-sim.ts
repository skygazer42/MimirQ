import type { ChunkPreviewItem } from '@/types'
import type { ChunkSearchResult } from './retrieval-search'

export type RerankedChunkSearchResult = ChunkSearchResult & {
  retrieval_score: number
  retrieval_norm: number
  rerank_score: number
  combined_score: number
}

function clamp01(value: number) {
  if (!Number.isFinite(value)) return 0
  return Math.max(0, Math.min(1, value))
}

function tokenizeLoose(text: string): string[] {
  const s = String(text || '').toLowerCase()
  // Tokenize alnum words and contiguous CJK blocks (best-effort, fast).
  return s.match(/[a-z0-9]+|[\u4e00-\u9fff]+/g) ?? []
}

export function computeRerankSimScore(query: string, content: string): number {
  const q = String(query || '').trim()
  if (!q) return 0

  const qTokens = tokenizeLoose(q).filter((t) => t.length >= 1).slice(0, 16)
  if (!qTokens.length) return 0

  const c = String(content || '')
  const cLower = c.toLowerCase()
  const qLower = q.toLowerCase()

  const phraseHit = cLower.includes(qLower) ? 1 : 0

  // Keep this cheap: cap content scanned to reduce worst-case UI cost.
  const cTokens = new Set(tokenizeLoose(c.slice(0, 4000)))
  let overlap = 0
  for (const t of qTokens) {
    if (cTokens.has(t)) overlap += 1
  }
  const coverage = overlap / qTokens.length

  // Combine: token coverage dominates, phrase hit gives a small bonus.
  return clamp01(0.8 * coverage + 0.2 * phraseHit)
}

export function rerankChunkSearchResults(
  results: ChunkSearchResult[],
  query: string,
  chunks: ChunkPreviewItem[],
  options?: { alpha?: number }
): RerankedChunkSearchResult[] {
  const q = String(query || '').trim()
  const alpha = clamp01(Number(options?.alpha ?? 0.65))
  const maxRetrieval = Math.max(0, ...(results || []).map((r) => Number(r.score || 0)))

  const byIndex = new Map<number, ChunkPreviewItem>()
  for (const c of chunks || []) byIndex.set(Number((c as any)?.index), c)

  const enriched: RerankedChunkSearchResult[] = (results || []).map((r) => {
    const retrievalScore = Number(r.score || 0)
    const retrievalNorm = maxRetrieval > 0 ? retrievalScore / maxRetrieval : 0
    const chunk = byIndex.get(Number(r.index))
    const rerankScore = computeRerankSimScore(q, String(chunk?.content ?? ''))
    const combined = alpha * retrievalNorm + (1 - alpha) * rerankScore

    return {
      ...r,
      retrieval_score: retrievalScore,
      retrieval_norm: clamp01(retrievalNorm),
      rerank_score: clamp01(rerankScore),
      combined_score: clamp01(combined),
    }
  })

  enriched.sort((a, b) => {
    const dc = b.combined_score - a.combined_score
    if (dc) return dc
    const dr = b.retrieval_score - a.retrieval_score
    if (dr) return dr
    return a.index - b.index
  })

  return q ? enriched : []
}

