import type { ChunkPreviewItem, DocumentChunk, JsonObject } from '@/types'

function toInt(value: unknown): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) return Math.trunc(value)
  if (typeof value === 'string' && value.trim()) {
    const n = Number.parseInt(value, 10)
    return Number.isFinite(n) ? n : null
  }
  return null
}

function toJsonObject(value: unknown): JsonObject {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return {}
  return value as JsonObject
}

/**
 * Adapt persisted DocumentChunk rows to the ChunkPreviewItem shape used by the Monaco highlighter.
 *
 * Notes:
 * - start/end offsets are best-effort. When `end_char` is missing we fall back to `start + content.length`.
 * - If both DB fields and metadata offsets are missing, we fall back to 0 so the UI can still render.
 */
export function mapDocumentChunksToPreviewItems(chunks: DocumentChunk[]): ChunkPreviewItem[] {
  const list = Array.isArray(chunks) ? [...chunks] : []
  list.sort((a, b) => (a.chunk_index || 0) - (b.chunk_index || 0))

  return list.map((chunk) => {
    const meta = toJsonObject(chunk.metadata)

    const start =
      toInt(chunk.start_char) ??
      toInt(meta.start_char) ??
      toInt(meta.start_index) ??
      toInt(meta.start) ??
      0

    const endRaw =
      toInt(chunk.end_char) ??
      toInt(meta.end_char) ??
      toInt(meta.end_index) ??
      toInt(meta.end)

    const content = String(chunk.content || '')
    const end = Math.max(start, endRaw ?? start + content.length)

    return {
      index: Number.isFinite(chunk.chunk_index) ? Number(chunk.chunk_index) : 0,
      content,
      length: content.length,
      tokens_est: Math.max(1, Math.ceil(content.length / 4)),
      start_index: start,
      end_index: end,
      page_number: typeof chunk.page_number === 'number' ? chunk.page_number : undefined,
      metadata: meta,
    }
  })
}
