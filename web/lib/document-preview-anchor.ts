import { extractBlocksFromMarkdownWithRanges, type ParsingPosition } from '@/lib/parsing-positions'

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

type PositionTaggedChunkLike = {
  content?: unknown
  metadata?: unknown
  page_number?: unknown
  start_char?: unknown
}

type HighlightRangeLike = {
  start?: unknown
  end?: unknown
}

type TextRange = {
  start: number
  end: number
}

type PositionCandidate = {
  bbox: DocumentPreviewBbox
  pageNumber: number
  start: number
  end: number
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

function sanitizeFiniteNumber(value: unknown): number | undefined {
  if (typeof value !== 'number' || !Number.isFinite(value)) return undefined
  return value
}

function normalizeSearchableText(value: string): { text: string; rawIndexByNormalizedIndex: number[] } {
  const rawIndexByNormalizedIndex: number[] = []
  let text = ''
  let previousWasWhitespace = true

  for (let i = 0; i < value.length; i += 1) {
    const char = value[i]
    if (/\s/.test(char)) {
      if (!previousWasWhitespace) {
        text += ' '
        rawIndexByNormalizedIndex.push(i)
        previousWasWhitespace = true
      }
      continue
    }

    text += char.toLowerCase()
    rawIndexByNormalizedIndex.push(i)
    previousWasWhitespace = false
  }

  if (text.endsWith(' ')) {
    text = text.slice(0, -1)
    rawIndexByNormalizedIndex.pop()
  }

  return { text, rawIndexByNormalizedIndex }
}

function findSearchTextRange(rawText: string, searchText: string | undefined): TextRange | null {
  const normalizedSearch = sanitizeSearchText(searchText)
  if (!normalizedSearch) return null

  const haystack = normalizeSearchableText(rawText)
  const needle = normalizeSearchableText(normalizedSearch).text
  if (!needle) return null

  const index = haystack.text.indexOf(needle)
  if (index < 0) return null

  const start = haystack.rawIndexByNormalizedIndex[index]
  const last = haystack.rawIndexByNormalizedIndex[index + needle.length - 1]
  if (start == null || last == null) return null
  return { start, end: last + 1 }
}

function findHighlightRangeInChunk(
  chunk: PositionTaggedChunkLike | null | undefined,
  range: HighlightRangeLike | null | undefined
): TextRange | null {
  const start = sanitizeFiniteNumber(range?.start)
  const end = sanitizeFiniteNumber(range?.end)
  const chunkStart = sanitizeFiniteNumber(chunk?.start_char)
  if (start == null || end == null || chunkStart == null || end <= start) return null

  return {
    start: Math.max(0, Math.trunc(start - chunkStart)),
    end: Math.max(0, Math.trunc(end - chunkStart)),
  }
}

function rangeDistance(a: TextRange, b: TextRange): number {
  if (a.end >= b.start && b.end >= a.start) return 0
  if (a.end < b.start) return b.start - a.end
  return a.start - b.end
}

function positionToBbox(position: ParsingPosition | undefined): { bbox: DocumentPreviewBbox; pageNumber: number } | null {
  if (!position) return null
  const pageIndex = position.pages.find((page) => Number.isFinite(page) && page >= 0)
  if (pageIndex == null) return null

  const bbox = sanitizeBbox({
    x0: position.left,
    y0: position.top,
    x1: position.right,
    y1: position.bottom,
  })
  if (!bbox) return null

  return { bbox, pageNumber: pageIndex + 1 }
}

function extractPositionCandidates(rawText: string): PositionCandidate[] {
  const parsed = extractBlocksFromMarkdownWithRanges(rawText)
  const candidates: PositionCandidate[] = []

  for (const block of parsed.blocks) {
    const position = positionToBbox(block.positions[0])
    if (!position) continue
    candidates.push({
      bbox: position.bbox,
      pageNumber: position.pageNumber,
      start: block.rawStart,
      end: block.rawEnd,
    })
  }

  return candidates
}

function choosePositionCandidate(candidates: PositionCandidate[], target: TextRange | null): PositionCandidate | null {
  if (candidates.length === 0) return null
  if (!target) return candidates[0]

  return candidates.reduce((best, candidate) => {
    const bestDistance = rangeDistance(best, target)
    const candidateDistance = rangeDistance(candidate, target)
    if (candidateDistance < bestDistance) return candidate
    return best
  }, candidates[0])
}

function getRecordValue(record: unknown, key: string): unknown {
  if (!record || typeof record !== 'object') return undefined
  return (record as Record<string, unknown>)[key]
}

function appendTaggedText(out: string[], value: unknown): void {
  if (typeof value === 'string') {
    if (value.includes('@@')) out.push(value)
    return
  }

  if (Array.isArray(value)) {
    const joined = value.filter((item): item is string => typeof item === 'string').join('')
    if (joined.includes('@@')) out.push(joined)
  }
}

function collectPositionTaggedTexts(chunk: PositionTaggedChunkLike | null | undefined): string[] {
  if (!chunk) return []

  const metadata = getRecordValue(chunk, 'metadata')
  const attributes = getRecordValue(metadata, 'attributes') || getRecordValue(metadata, 'element_attributes')
  const values: unknown[] = [
    chunk.content,
    getRecordValue(metadata, 'element_text'),
    getRecordValue(metadata, 'position_tagged_markdown'),
    getRecordValue(metadata, 'original_markdown_content'),
    getRecordValue(metadata, 'raw_content'),
    getRecordValue(metadata, 'text_with_positions'),
    getRecordValue(metadata, 'position_tags'),
    getRecordValue(metadata, 'position_tag'),
    getRecordValue(attributes, 'position_tags'),
    getRecordValue(attributes, 'position_tag'),
  ]

  const out: string[] = []
  for (const value of values) appendTaggedText(out, value)

  return Array.from(new Set(out))
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

export function recoverDocumentPreviewAnchorFromChunkPositions(
  anchor: Partial<DocumentPreviewAnchor> | null | undefined,
  chunk: PositionTaggedChunkLike | null | undefined,
  range?: HighlightRangeLike | null
): DocumentPreviewAnchor | null {
  const sanitizedAnchor = sanitizeDocumentPreviewAnchor(anchor)
  if (sanitizedAnchor?.bbox) return sanitizedAnchor

  const rawTexts = collectPositionTaggedTexts(chunk)
  for (const rawText of rawTexts) {
    const candidates = extractPositionCandidates(rawText)
    const target = findSearchTextRange(rawText, sanitizedAnchor?.searchText) || findHighlightRangeInChunk(chunk, range)
    const candidate = choosePositionCandidate(candidates, target)
    if (!candidate) continue

    return sanitizeDocumentPreviewAnchor({
      ...sanitizedAnchor,
      pageNumber: candidate.pageNumber,
      bbox: candidate.bbox,
      bboxPageNumber: candidate.pageNumber,
    })
  }

  return sanitizedAnchor
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
