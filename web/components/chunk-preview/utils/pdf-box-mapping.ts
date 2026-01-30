export type ChunkRangeLike = {
  index?: number
  start_index: number
  end_index: number
}

export type BlockRangeLike = {
  id: string
  start: number
  end: number
}

function asFiniteInt(value: unknown): number | null {
  const n = Number(value)
  if (!Number.isFinite(n)) return null
  return Math.trunc(n)
}

function normalizeRange(startRaw: unknown, endRaw: unknown): { start: number; end: number } | null {
  const start = asFiniteInt(startRaw)
  const end = asFiniteInt(endRaw)
  if (start == null || end == null) return null
  if (end <= start) return null
  return { start, end }
}

function overlapLen(aStart: number, aEnd: number, bStart: number, bEnd: number): number {
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
  blockRanges: BlockRangeLike[],
  chunks: ChunkRangeLike[]
): Map<string, number> {
  const result = new Map<string, number>()
  if (!Array.isArray(blockRanges) || blockRanges.length === 0) return result
  if (!Array.isArray(chunks) || chunks.length === 0) return result

  const normalizedChunks = chunks
    .map((c, arrayIndex) => {
      const range = normalizeRange(c.start_index, c.end_index)
      if (!range) return null
      const idxRaw = c.index
      const idx = typeof idxRaw === 'number' && Number.isFinite(idxRaw) ? Math.trunc(idxRaw) : arrayIndex
      return { idx, start: range.start, end: range.end, len: range.end - range.start }
    })
    .filter((v): v is { idx: number; start: number; end: number; len: number } => Boolean(v))
    .sort((a, b) => a.start - b.start || a.end - b.end || a.idx - b.idx)

  if (normalizedChunks.length === 0) return result

  const normalizedBlocks = blockRanges
    .map((b) => {
      const range = normalizeRange(b.start, b.end)
      if (!range) return null
      return { id: String(b.id), start: range.start, end: range.end }
    })
    .filter((v): v is { id: string; start: number; end: number } => Boolean(v))
    .sort((a, b) => a.start - b.start || a.end - b.end || a.id.localeCompare(b.id))

  let chunkStartPtr = 0
  for (const block of normalizedBlocks) {
    const { start: bStart, end: bEnd } = block

    while (chunkStartPtr < normalizedChunks.length && normalizedChunks[chunkStartPtr].end <= bStart) {
      chunkStartPtr += 1
    }

    let best: { idx: number; overlap: number; len: number; start: number } | null = null
    for (let i = chunkStartPtr; i < normalizedChunks.length; i += 1) {
      const chunk = normalizedChunks[i]
      if (chunk.start >= bEnd) break
      const ov = overlapLen(bStart, bEnd, chunk.start, chunk.end)
      if (ov <= 0) continue

      if (!best) {
        best = { idx: chunk.idx, overlap: ov, len: chunk.len, start: chunk.start }
        continue
      }

      if (ov > best.overlap) {
        best = { idx: chunk.idx, overlap: ov, len: chunk.len, start: chunk.start }
        continue
      }
      if (ov === best.overlap) {
        if (chunk.len < best.len) {
          best = { idx: chunk.idx, overlap: ov, len: chunk.len, start: chunk.start }
          continue
        }
        if (chunk.len === best.len) {
          if (chunk.start < best.start) {
            best = { idx: chunk.idx, overlap: ov, len: chunk.len, start: chunk.start }
            continue
          }
          if (chunk.start === best.start && chunk.idx < best.idx) {
            best = { idx: chunk.idx, overlap: ov, len: chunk.len, start: chunk.start }
          }
        }
      }
    }

    if (best) result.set(block.id, best.idx)
  }

  return result
}
