/** Text offsets are UTF-16 positions after parser position tags have been removed. */
type ChunkTextRange = {
  index: number
  start_index: number
  end_index: number
}

export type BlockTextRange = {
  id: string
  start: number
  end: number
}

type ChunkMatch = {
  index: number
  overlap: number
  length: number
  start: number
}

function isBetterChunkMatch(candidate: ChunkMatch, current: ChunkMatch | null): boolean {
  if (current === null) return true
  if (candidate.overlap !== current.overlap) return candidate.overlap > current.overlap
  if (candidate.length !== current.length) return candidate.length < current.length
  if (candidate.start !== current.start) return candidate.start < current.start
  return candidate.index < current.index
}

function readValidTextRange(start: number, end: number): { start: number; end: number } | null {
  if (!Number.isFinite(start) || !Number.isFinite(end)) return null
  if (end <= start) return null
  return { start, end }
}

function getRangeOverlapLength(aStart: number, aEnd: number, bStart: number, bEnd: number): number {
  const lo = Math.max(aStart, bStart)
  const hi = Math.min(aEnd, bEnd)
  return Math.max(0, hi - lo)
}

/**
 * Build a best-effort mapping from parsing block id -> chunk index.
 *
 * Heuristic:
 * - pick the chunk with the largest overlap with the block range
 * - tie-breaker: prefer smaller chunk length, then earlier start, then smaller index
 */
export function buildBlockIdToBestChunkIndex(
  blockRanges: readonly BlockTextRange[],
  chunks: readonly ChunkTextRange[],
): Map<string, number> {
  const result = new Map<string, number>()
  const orderedChunks = chunks
    .map((c) => {
      const range = readValidTextRange(c.start_index, c.end_index)
      if (!range) return null
      return { index: c.index, start: range.start, end: range.end, length: range.end - range.start }
    })
    .filter((v): v is { index: number; start: number; end: number; length: number } => v !== null)
    .sort((a, b) => a.start - b.start || a.end - b.end || a.index - b.index)

  if (orderedChunks.length === 0) return result

  const orderedBlocks = blockRanges
    .map((b) => {
      const range = readValidTextRange(b.start, b.end)
      if (!range) return null
      return { id: b.id, start: range.start, end: range.end }
    })
    .filter((v): v is { id: string; start: number; end: number } => v !== null)
    .sort((a, b) => a.start - b.start || a.end - b.end || a.id.localeCompare(b.id))

  let firstCandidateIndex = 0
  for (const block of orderedBlocks) {
    while (firstCandidateIndex < orderedChunks.length && orderedChunks[firstCandidateIndex].end <= block.start) {
      firstCandidateIndex += 1
    }

    let bestChunk: ChunkMatch | null = null
    for (let candidateIndex = firstCandidateIndex; candidateIndex < orderedChunks.length; candidateIndex += 1) {
      const chunk = orderedChunks[candidateIndex]
      if (chunk.start >= block.end) break
      const overlap = getRangeOverlapLength(block.start, block.end, chunk.start, chunk.end)
      if (overlap <= 0) continue

      const candidate = { index: chunk.index, overlap, length: chunk.length, start: chunk.start }
      if (isBetterChunkMatch(candidate, bestChunk)) bestChunk = candidate
    }

    if (bestChunk !== null) result.set(block.id, bestChunk.index)
  }

  return result
}
