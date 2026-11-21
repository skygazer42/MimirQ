import type { DocumentChunk } from '@/types/backend'
import type { ChunkPreviewItem } from '@/types/processing'
import { createCodePointToUtf16Converter } from './text-offsets'
import { projectChunkTextPositions, readChunkMetadataOffset } from './chunk-text-positions'

/** Project known API code point spans into the loaded clean text's UTF-16 coordinates. */
export function mapDocumentChunksToPreviewItems(chunks: DocumentChunk[], text: string): ChunkPreviewItem[] {
  const converter = createCodePointToUtf16Converter(text)
  const items: ChunkPreviewItem[] = []
  const ordered = [...chunks].sort((left, right) => left.chunk_index - right.chunk_index)
  for (const chunk of ordered) {
    const sourceStart =
      chunk.start_char ?? readChunkMetadataOffset(chunk.metadata, ['start_char', 'start_index', 'start'])
    const sourceEnd = chunk.end_char ?? readChunkMetadataOffset(chunk.metadata, ['end_char', 'end_index', 'end'])
    if (sourceStart === undefined || sourceEnd === undefined || sourceEnd < sourceStart) continue
    items.push({
      index: chunk.chunk_index,
      content: chunk.content,
      length: chunk.content.length,
      start_index: sourceStart,
      end_index: sourceEnd,
      page_number: chunk.page_number ?? undefined,
      metadata: chunk.metadata,
    })
  }
  return projectChunkTextPositions(items, converter.toUtf16)
}
