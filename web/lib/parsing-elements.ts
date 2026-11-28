import type { ParsingElement } from '@/lib/api/parsing'
import type { ParsingLayoutKind } from '@/lib/parsing-layout'

const PARSING_ELEMENT_KINDS = new Set(['heading', 'paragraph', 'list', 'table', 'image', 'equation', 'seal', 'unknown'])

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function isFiniteNumber(value: unknown): boolean {
  return typeof value === 'number' && Number.isFinite(value)
}

function isOptionalNullableString(value: unknown): boolean {
  return value === undefined || value === null || typeof value === 'string'
}

export function isParsingElement(value: unknown): value is ParsingElement {
  if (!isRecord(value) || typeof value.id !== 'string') return false
  if (typeof value.kind !== 'string' || !PARSING_ELEMENT_KINDS.has(value.kind)) return false
  if (![value.visual_kind, value.text, value.source_backend, value.source_element_id].every(isOptionalNullableString)) {
    return false
  }
  for (const rawNumber of [value.page, value.confidence]) {
    if (rawNumber !== undefined && rawNumber !== null && !isFiniteNumber(rawNumber)) return false
  }
  if (value.pages !== undefined && value.pages !== null) {
    if (!Array.isArray(value.pages) || !value.pages.every(isFiniteNumber)) return false
  }
  if (value.bbox !== undefined && value.bbox !== null) {
    if (!isRecord(value.bbox) || ![value.bbox.x0, value.bbox.y0, value.bbox.x1, value.bbox.y1].every(isFiniteNumber)) {
      return false
    }
  }
  return value.attributes === undefined || value.attributes === null || isRecord(value.attributes)
}

export function readPersistedParsingElements(value: unknown): ParsingElement[] | undefined {
  if (value === undefined || value === null) return undefined
  if (!Array.isArray(value) || !value.every(isParsingElement)) throw new Error('已保存的解析元素记录格式不正确')
  return value
}

export function getParsingPages(source: Pick<ParsingElement, 'page' | 'pages'>): number[] {
  if (source.pages !== undefined && source.pages !== null) {
    const pages = Array.from(new Set(source.pages.filter((page) => Number.isInteger(page) && page > 0)))
    if (pages.length > 0) return pages
  }
  const page = source.page
  if (typeof page !== 'number' || !Number.isInteger(page) || page <= 0) return []
  return [page]
}

export function formatParsingPages(pages: readonly number[]): string | null {
  if (pages.length === 0) return null
  if (pages.length === 1) return `页 ${pages[0]}`
  if (pages.length === 2 && pages[1] === pages[0] + 1) return `跨页 ${pages[0]}-${pages[1]}`
  return `跨页 ${pages.join(',')}`
}

export function getParsingElementVisualKind(element: ParsingElement): string | null {
  if (element.visual_kind !== undefined && element.visual_kind !== null) return element.visual_kind.trim()
  const value = element.attributes?.visual_kind
  return typeof value === 'string' ? value.trim() : null
}

export function getParsingElementImageSource(element: ParsingElement): string | null {
  if (element.kind !== 'image') return null
  for (const key of ['src', 'image_src', 'url']) {
    const value = element.attributes?.[key]
    if (typeof value !== 'string') continue
    const source = value.trim()
    if (source.length > 0) return source
  }
  return null
}

export function getParsingElementLayoutKind(
  kind: ParsingElement['kind'] | null | undefined,
): ParsingLayoutKind | undefined {
  if (kind === undefined || kind === null || kind === 'unknown') return undefined
  return kind
}
