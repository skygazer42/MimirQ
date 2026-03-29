export type DocumentPreviewAnchor = {
  pageNumber?: number
  searchText?: string
}

type CitationLikePreviewAnchor = {
  page_number?: number | null
  matched_terms?: unknown
  chunk_content?: unknown
}

function sanitizePageNumber(value: unknown): number | undefined {
  if (typeof value !== 'number' || !Number.isFinite(value)) return undefined
  const normalized = Math.trunc(value)
  return normalized > 0 ? normalized : undefined
}

function sanitizeSearchText(value: unknown): string | undefined {
  if (typeof value !== 'string') return undefined
  const normalized = value.replace(/\s+/g, ' ').trim()
  if (!normalized) return undefined
  return normalized.slice(0, 120)
}

export function sanitizeDocumentPreviewAnchor(
  anchor: Partial<DocumentPreviewAnchor> | null | undefined
): DocumentPreviewAnchor | null {
  if (!anchor) return null

  const pageNumber = sanitizePageNumber(anchor.pageNumber)
  const searchText = sanitizeSearchText(anchor.searchText)
  if (!pageNumber && !searchText) return null

  return {
    ...(pageNumber ? { pageNumber } : {}),
    ...(searchText ? { searchText } : {}),
  }
}

export function getDocumentPreviewAnchorFromCitation<T extends CitationLikePreviewAnchor>(
  citation: T | null | undefined
): DocumentPreviewAnchor | null {
  if (!citation) return null

  const matchedTerms = Array.isArray(citation.matched_terms) ? citation.matched_terms : []
  const searchText =
    matchedTerms.map((term) => sanitizeSearchText(term)).find(Boolean) || sanitizeSearchText(citation.chunk_content)

  return sanitizeDocumentPreviewAnchor({
    pageNumber: citation.page_number ?? undefined,
    searchText,
  })
}

export function buildPdfPreviewSrc(fileUrl: string, anchor?: Partial<DocumentPreviewAnchor> | null): string {
  const normalizedUrl = String(fileUrl || '').trim()
  if (!normalizedUrl) return ''

  const sanitizedAnchor = sanitizeDocumentPreviewAnchor(anchor)
  const hash = new URLSearchParams()
  hash.set('toolbar', '0')

  if (sanitizedAnchor?.pageNumber) {
    hash.set('page', String(sanitizedAnchor.pageNumber))
  }
  if (sanitizedAnchor?.searchText) {
    hash.set('search', sanitizedAnchor.searchText)
  }

  const [baseUrl] = normalizedUrl.split('#', 1)
  return `${baseUrl}#${hash.toString()}`
}
