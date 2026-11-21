import type { ChunkPreviewItem } from '@/types'
import type { ChunkSearchResult } from './retrieval-search'

export type RerankedChunkSearchResult = ChunkSearchResult & {
  retrieval_score: number
  retrieval_norm: number
  rerank_score: number
  combined_score: number
}

function clamp01(value: number) {
  return Math.max(0, Math.min(1, value))
}

function tokenizeLoose(text: string): string[] {
  const normalized = text.toLowerCase()
  // Tokenize alnum words and contiguous CJK blocks (best-effort, fast).
  return normalized.match(/[a-z0-9]+|[\u4e00-\u9fff]+/g) ?? []
}

function computeRerankSimScore(query: string, queryTokens: readonly string[], content: string): number {
  if (queryTokens.length === 0) return 0

  const phraseHit = content.toLowerCase().includes(query) ? 1 : 0

  // Keep this cheap: cap content scanned to reduce worst-case UI cost.
  const contentTokens = new Set(tokenizeLoose(content.slice(0, 4000)))
  let overlap = 0
  for (const token of queryTokens) {
    if (contentTokens.has(token)) overlap += 1
  }
  const coverage = overlap / queryTokens.length

  // Combine: token coverage dominates, phrase hit gives a small bonus.
  return clamp01(0.8 * coverage + 0.2 * phraseHit)
}

export function rerankChunkSearchResults(
  results: readonly ChunkSearchResult[],
  query: string,
  chunks: readonly ChunkPreviewItem[],
  options?: { alpha?: number },
): RerankedChunkSearchResult[] {
  const normalizedQuery = query.trim().toLowerCase()
  const requestedAlpha = options?.alpha ?? 0.65
  if (!Number.isFinite(requestedAlpha)) throw new RangeError('Local rerank weight must be finite')
  if (normalizedQuery === '') return []
  const queryTokens = tokenizeLoose(normalizedQuery).slice(0, 16)
  const alpha = clamp01(requestedAlpha)
  const maxRetrieval = results.reduce((maximum, result) => Math.max(maximum, result.score), 0)

  const byIndex = new Map<number, ChunkPreviewItem>()
  for (const chunk of chunks) byIndex.set(chunk.index, chunk)

  const enriched: RerankedChunkSearchResult[] = results.map((r) => {
    const retrievalScore = r.score
    const retrievalNorm = maxRetrieval === 0 ? 0 : retrievalScore / maxRetrieval
    const chunk = byIndex.get(r.index)
    if (chunk === undefined) throw new Error(`Missing chunk ${r.index} for local rerank`)
    const rerankScore = computeRerankSimScore(normalizedQuery, queryTokens, chunk.content)
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

  return enriched
}
