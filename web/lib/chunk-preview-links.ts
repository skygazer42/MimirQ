export function buildChunkPreviewDocumentHref(documentId: string): string {
  return `/chunk-preview?docId=${encodeURIComponent(documentId)}`
}
