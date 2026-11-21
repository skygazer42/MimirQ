import { extractBlocksFromMarkdownWithRanges, type ParsingPosition } from '@/lib/parsing-positions'
import { createCodePointToUtf16Converter } from '@/lib/text-offsets'

export const DOCUMENT_PREVIEW_BBOX_ID = 'citation-bbox'

type DocumentPreviewBbox = {
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

type DocumentPreviewBboxOverlayItem = {
  id: typeof DOCUMENT_PREVIEW_BBOX_ID
  position: ParsingPosition
}

type DocumentPreviewBboxOverlay = {
  activeBlockIds: string[]
  blockIdToPageIndex: Map<string, number>
  boxesByPage: Map<number, DocumentPreviewBboxOverlayItem[]>
}

function sanitizePageNumber(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isInteger(value) && value > 0 ? value : undefined
}

function sanitizeSearchText(value: unknown): string | undefined {
  if (typeof value !== 'string') return undefined
  const normalized = value.replace(/\s+/g, ' ').trim()
  if (!normalized) return undefined
  return Array.from(normalized).slice(0, 120).join('')
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function sanitizeBbox(value: unknown): DocumentPreviewBbox | undefined {
  if (!isRecord(value)) return undefined
  const x0 = sanitizeFiniteNumber(value.x0)
  const y0 = sanitizeFiniteNumber(value.y0)
  const x1 = sanitizeFiniteNumber(value.x1)
  const y1 = sanitizeFiniteNumber(value.y1)
  if (x0 === undefined || y0 === undefined || x1 === undefined || y1 === undefined) return undefined

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

function normalizeSearchableText(value: string) {
  const rawStartByNormalizedIndex: number[] = []
  const rawEndByNormalizedIndex: number[] = []
  let text = ''
  let previousWasWhitespace = true
  let rawOffset = 0
  for (const character of value) {
    const start = rawOffset
    rawOffset += character.length
    if (/\s/.test(character)) {
      if (!previousWasWhitespace) {
        text += ' '
        rawStartByNormalizedIndex.push(start)
        rawEndByNormalizedIndex.push(rawOffset)
        previousWasWhitespace = true
      }
      continue
    }

    const lowercase = character.toLowerCase()
    text += lowercase
    for (let index = 0; index < lowercase.length; index += 1) {
      rawStartByNormalizedIndex.push(start)
      rawEndByNormalizedIndex.push(rawOffset)
    }
    previousWasWhitespace = false
  }

  if (text.endsWith(' ')) {
    text = text.slice(0, -1)
    rawStartByNormalizedIndex.pop()
    rawEndByNormalizedIndex.pop()
  }

  return { text, rawStartByNormalizedIndex, rawEndByNormalizedIndex }
}

function findSearchTextRanges(rawText: string, searchText: string): TextRange[] {
  const normalizedSearch = sanitizeSearchText(searchText)
  if (!normalizedSearch) return []

  const haystack = normalizeSearchableText(rawText)
  const needle = normalizeSearchableText(normalizedSearch).text
  const ranges: TextRange[] = []
  let index = haystack.text.indexOf(needle)
  while (index >= 0) {
    const start = haystack.rawStartByNormalizedIndex[index]
    const end = haystack.rawEndByNormalizedIndex[index + needle.length - 1]
    ranges.push({ start, end })
    index = haystack.text.indexOf(needle, index + 1)
  }
  return ranges
}

function findHighlightRangeInChunk(
  chunk: PositionTaggedChunkLike | null | undefined,
  range: HighlightRangeLike | null | undefined,
  text: string,
): TextRange | null {
  const start = sanitizeFiniteNumber(range?.start)
  const end = sanitizeFiniteNumber(range?.end)
  const chunkStart = sanitizeFiniteNumber(chunk?.start_char)
  if (start == null || end == null || chunkStart == null || end <= start) return null

  if (start < 0 || chunkStart < 0) return null
  const converter = createCodePointToUtf16Converter(text)
  const localStart = converter.toUtf16(Math.max(0, start - chunkStart))
  const localEnd = converter.toUtf16(Math.min(converter.codePointLength, Math.max(0, end - chunkStart)))
  return localStart === undefined || localEnd === undefined ? null : { start: localStart, end: localEnd }
}

function extractPositionCandidates(rawText: string): PositionCandidate[] {
  const parsed = extractBlocksFromMarkdownWithRanges(rawText)
  const candidates: PositionCandidate[] = []

  for (const block of parsed.blocks) {
    for (const position of block.positions) {
      const bbox = sanitizeBbox({ x0: position.left, y0: position.top, x1: position.right, y1: position.bottom })
      if (bbox === undefined) continue
      for (const pageIndex of position.pages) {
        candidates.push({ bbox, pageNumber: pageIndex + 1, start: block.rawStart, end: block.rawEnd })
      }
    }
  }

  return candidates
}

function choosePositionCandidate(
  candidates: PositionCandidate[],
  targets: TextRange[] | null,
  pageNumber?: number,
): PositionCandidate | null {
  const locations = new Map<string, PositionCandidate>()
  for (const candidate of candidates) {
    if (pageNumber !== undefined && candidate.pageNumber !== pageNumber) continue
    if (targets !== null && !targets.some((target) => candidate.end > target.start && candidate.start < target.end))
      continue
    const { bbox } = candidate
    const key = `${candidate.pageNumber}:${bbox.x0}:${bbox.x1}:${bbox.y0}:${bbox.y1}`
    locations.set(key, candidate)
  }
  return locations.size === 1 ? locations.values().next().value! : null
}

function getRecordValue(record: unknown, key: string): unknown {
  return isRecord(record) ? record[key] : undefined
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
  const attributes = getRecordValue(metadata, 'attributes')
  const elementAttributes = getRecordValue(metadata, 'element_attributes')
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
    getRecordValue(elementAttributes, 'position_tags'),
    getRecordValue(elementAttributes, 'position_tag'),
  ]

  const out: string[] = []
  for (const value of values) appendTaggedText(out, value)

  return Array.from(new Set(out))
}

export function sanitizeDocumentPreviewAnchor(anchor: unknown): DocumentPreviewAnchor | null {
  if (!isRecord(anchor)) return null

  const pageNumber = sanitizePageNumber(anchor.pageNumber)
  const searchText = sanitizeSearchText(anchor.searchText)
  const bbox = sanitizeBbox(anchor.bbox)
  const bboxPageNumber = bbox ? (sanitizePageNumber(anchor.bboxPageNumber) ?? pageNumber) : undefined
  if (!pageNumber && !searchText && !bbox) return null

  return {
    ...(pageNumber ? { pageNumber } : {}),
    ...(searchText ? { searchText } : {}),
    ...(bbox ? { bbox } : {}),
    ...(bbox && bboxPageNumber ? { bboxPageNumber } : {}),
  }
}

export function getDocumentPreviewAnchorFromCitation(
  citation: CitationLikePreviewAnchor | null | undefined,
): DocumentPreviewAnchor | null {
  if (!citation) return null

  let searchText = sanitizeSearchText(citation.chunk_content)
  if (searchText === undefined && Array.isArray(citation.matched_terms)) {
    for (const term of citation.matched_terms) {
      const text = sanitizeSearchText(term)
      if (text === undefined) continue
      searchText = text
      break
    }
  }

  return sanitizeDocumentPreviewAnchor({
    bbox: citation.bbox,
    bboxPageNumber: citation.bbox_page_number,
    pageNumber: citation.page_number,
    searchText,
  })
}

export function recoverDocumentPreviewAnchorFromChunkPositions(
  anchor: Partial<DocumentPreviewAnchor> | null | undefined,
  chunk: PositionTaggedChunkLike | null | undefined,
  range?: HighlightRangeLike | null,
): DocumentPreviewAnchor | null {
  const sanitizedAnchor = sanitizeDocumentPreviewAnchor(anchor)
  if (
    sanitizedAnchor?.bbox &&
    (sanitizedAnchor.bboxPageNumber !== undefined || sanitizedAnchor.pageNumber !== undefined)
  )
    return sanitizedAnchor

  const rawTexts = collectPositionTaggedTexts(chunk)
  for (const rawText of rawTexts) {
    const candidates = extractPositionCandidates(rawText)
    const highlightRange = rawText === chunk?.content ? findHighlightRangeInChunk(chunk, range, rawText) : null
    let targets: TextRange[] | null = null
    if (highlightRange !== null) targets = [highlightRange]
    else if (sanitizedAnchor?.searchText !== undefined)
      targets = findSearchTextRanges(rawText, sanitizedAnchor.searchText)
    else if (range != null) continue
    const candidate = choosePositionCandidate(candidates, targets, sanitizedAnchor?.pageNumber)
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
  anchor: Partial<DocumentPreviewAnchor> | null | undefined,
): DocumentPreviewBboxOverlay | null {
  const sanitizedAnchor = sanitizeDocumentPreviewAnchor(anchor)
  const bbox = sanitizedAnchor?.bbox
  const pageNumber = sanitizedAnchor?.bboxPageNumber ?? sanitizedAnchor?.pageNumber
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
