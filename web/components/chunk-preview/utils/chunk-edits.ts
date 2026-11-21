import type { ChunkPreviewItem } from '@/types'
import type { ChunkOverride } from '../types'

/** Project content/metadata edits. Selection and skip markers belong to the caller. */
export function applyChunkEdits(chunk: ChunkPreviewItem, override: ChunkOverride | undefined): ChunkPreviewItem {
  if (override === undefined) return chunk
  const content = override.content ?? chunk.content
  const metadata = override.metadata ?? chunk.metadata
  const contentChanged = content !== chunk.content
  if (!contentChanged && metadata === chunk.metadata) return chunk
  return {
    ...chunk,
    content,
    metadata,
    length: contentChanged ? Array.from(content).length : chunk.length,
    tokens_est: contentChanged ? undefined : chunk.tokens_est,
  }
}
