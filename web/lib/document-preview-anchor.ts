import type { ParsingPosition } from '@/lib/parsing-positions'

export const DOCUMENT_PREVIEW_BBOX_ID = 'citation-bbox'

export type DocumentPreviewBbox = {
  x0: number
  y0: number
  x1: number
  y1: number
}

export type DocumentPreviewAnchor = {
  pageNumber?: number
  searchText?: string
  bbox?: DocumentPreviewBbox
  bboxPageNumber?: number
}

type CitationLikePreviewAnchor = {
  bbox?: unknown
  bbox_page_number?: number | null
  page_number?: number | null
  matched_terms?: unknown
  chunk_content?: unknown
}

export type DocumentPreviewBboxOverlayItem = {
  id: typeof DOCUMENT_PREVIEW_BBOX_ID
  position: ParsingPosition
}

export type DocumentPreviewBboxOverlay = {
  activeBlockIds: string[]
  blockIdToPageIndex: Map<string, number>
  boxesByPage: Map<number, DocumentPreviewBboxOverlayItem[]>
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

function sanitizeBbox(value: unknown): DocumentPreviewBbox | undefined {
  if (!value || typeof value !== 'object') return undefined
  const raw = value as Record<string, unknown>
  const x0 = typeof raw.x0 === 'number' && Number.isFinite(raw.x0) ? raw.x0 : undefined
  const y0 = typeof raw.y0 === 'number' && Number.isFinite(raw.y0) ? raw.y0 : undefined
  const x1 = typeof raw.x1 === 'number' && Number.isFinite(raw.x1) ? raw.x1 : undefined
  const y1 = typeof raw.y1 === 'number' && Number.isFinite(raw.y1) ? raw.y1 : undefined
  if (x0 == null || y0 == null || x1 == null || y1 == null) return undefined

  const left = Math.min(x0, x1)
  const right = Math.max(x0, x1)
  const top = Math.min(y0, y1)
  const bottom = Math.max(y0, y1)
  if (right <= left || bottom <= top) return undefined
  return { x0: left, y0: top, x1: right, y1: bottom }
}

export function sanitizeDocumentPreviewAnchor(
  anchor: Partial<DocumentPreviewAnchor> | null | undefined
): DocumentPreviewAnchor | null {
  if (!anchor) return null

  const pageNumber = sanitizePageNumber(anchor.pageNumber)
  const searchText = sanitizeSearchText(anchor.searchText)
  const bbox = sanitizeBbox(anchor.bbox)
  const bboxPageNumber = bbox ? sanitizePageNumber(anchor.bboxPageNumber) || pageNumber : undefined
  if (!pageNumber && !searchText && !bbox) return null

  return {
    ...(pageNumber ? { pageNumber } : {}),
    ...(searchText ? { searchText } : {}),
    ...(bbox ? { bbox } : {}),
    ...(bbox && bboxPageNumber ? { bboxPageNumber } : {}),
  }
}

export function getDocumentPreviewAnchorFromCitation<T extends CitationLikePreviewAnchor>(
  citation: T | null | undefined
): DocumentPreviewAnchor | null {
  if (!citation) return null

  const matchedTerms = Array.isArray(citation.matched_terms) ? citation.matched_terms : []
  const searchText =
    sanitizeSearchText(citation.chunk_content) || matchedTerms.map((term) => sanitizeSearchText(term)).find(Boolean)

  return sanitizeDocumentPreviewAnchor({
    bbox: sanitizeBbox(citation.bbox),
    bboxPageNumber: citation.bbox_page_number ?? citation.page_number ?? undefined,
    pageNumber: citation.page_number ?? undefined,
    searchText,
  })
}

export function buildDocumentPreviewBboxOverlay(
  anchor: Partial<DocumentPreviewAnchor> | null | undefined
): DocumentPreviewBboxOverlay | null {
  const sanitizedAnchor = sanitizeDocumentPreviewAnchor(anchor)
  const bbox = sanitizedAnchor?.bbox
  const pageNumber = sanitizedAnchor?.bboxPageNumber || sanitizedAnchor?.pageNumber
  if (!bbox || !pageNumber) return null

  const pageIndex = pageNumber - 1
  const item: DocumentPreviewBboxOverlayItem = {
    id: DOCUMENT_PREVIEW_BBOX_ID,
    position: {
      bottom: bbox.y1,
      left: bbox.x0,
      pages: [pageIndex],
      raw: DOCUMENT_PREVIEW_BBOX_ID,
      right: bbox.x1,
      top: bbox.y0,
    },
  }
  return {
    activeBlockIds: [DOCUMENT_PREVIEW_BBOX_ID],
    blockIdToPageIndex: new Map([[DOCUMENT_PREVIEW_BBOX_ID, pageIndex]]),
    boxesByPage: new Map([[pageIndex, [item]]]),
  }
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
