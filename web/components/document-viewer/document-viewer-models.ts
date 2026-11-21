import type { DocumentChunk } from '@/types/backend'
import type { DocumentViewSourceContext, HighlightRange } from '@/store/document-view'

export type DocumentChunkLocation = Pick<DocumentChunk, 'id' | 'start_char' | 'end_char'>

export type CitationSnapshot = Readonly<
  Pick<DocumentViewSourceContext, 'chunkIndex' | 'pageNumber'> & {
    chunkId: string
    content: string
    range: HighlightRange | null
  }
>

export type DocumentViewerHighlight =
  { kind: 'chunk'; chunk: DocumentChunk } | { kind: 'citation'; snapshot: CitationSnapshot }
