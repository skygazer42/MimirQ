import type { JsonObject } from '@/types/common'
import type { ChunkPreviewItem } from '@/types/processing'

const PARENT_START_KEYS = ['parent_start_char', 'parent_start_index', 'parent_start'] as const
const PARENT_END_KEYS = ['parent_end_char', 'parent_end_index', 'parent_end'] as const

export function readChunkMetadataOffset(metadata: JsonObject | undefined, keys: readonly string[]): number | undefined {
  if (metadata === undefined) return undefined
  for (const key of keys) {
    const value = metadata[key]
    if (typeof value !== 'number' && typeof value !== 'string') continue
    if (typeof value === 'string' && value.trim().length === 0) continue
    const offset = Number(value)
    if (Number.isInteger(offset) && offset >= 0) return offset
  }
  return undefined
}

function projectParentOffsets(
  metadata: JsonObject | undefined,
  toDisplayOffset: (offset: number) => number | undefined,
): JsonObject | undefined {
  if (metadata === undefined) return undefined
  const keys = [...PARENT_START_KEYS, ...PARENT_END_KEYS]
  if (!keys.some((key) => key in metadata)) return metadata
  const result = { ...metadata }
  for (const key of keys) delete result[key]
  const start = readChunkMetadataOffset(metadata, PARENT_START_KEYS)
  const end = readChunkMetadataOffset(metadata, PARENT_END_KEYS)
  if (start === undefined || end === undefined || end < start) return result
  const displayStart = toDisplayOffset(start)
  const displayEnd = toDisplayOffset(end)
  if (displayStart === undefined || displayEnd === undefined) return result
  return { ...result, parent_start_char: displayStart, parent_end_char: displayEnd }
}

export function projectChunkTextPositions(
  chunks: readonly ChunkPreviewItem[],
  toDisplayOffset: (offset: number) => number | undefined,
): ChunkPreviewItem[] {
  const items: ChunkPreviewItem[] = []
  for (const chunk of chunks) {
    if (chunk.end_index < chunk.start_index) continue
    const start = toDisplayOffset(chunk.start_index)
    const end = toDisplayOffset(chunk.end_index)
    if (start === undefined || end === undefined) continue
    items.push({
      ...chunk,
      start_index: start,
      end_index: end,
      metadata: projectParentOffsets(chunk.metadata, toDisplayOffset),
    })
  }
  return items
}
