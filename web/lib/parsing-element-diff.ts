import type { ParsingElement } from '@/lib/api/parsing'

type ElementKind = ParsingElement['kind']

type ElementCountMap = Partial<Record<ElementKind, number>>

export type ParsingElementDiffSummary = {
  totalBase: number
  totalCompare: number
  addedByKind: ElementCountMap
  removedByKind: ElementCountMap
  addedSealTexts: string[]
  removedSealTexts: string[]
}

function normalizeText(value: string | null | undefined): string {
  return String(value || '').replace(/\s+/g, ' ').trim()
}

function elementSignature(element: Pick<ParsingElement, 'kind' | 'page' | 'text' | 'bbox'>): string {
  const bbox = element.bbox
    ? `${element.bbox.x0}:${element.bbox.y0}:${element.bbox.x1}:${element.bbox.y1}`
    : 'na'
  return [
    String(element.kind || 'unknown'),
    typeof element.page === 'number' ? String(element.page) : 'na',
    normalizeText(element.text),
    bbox,
  ].join('|')
}

function incrementCount(map: ElementCountMap, kind: ElementKind) {
  map[kind] = (map[kind] || 0) + 1
}

export function diffParsingElements(
  base: Array<Pick<ParsingElement, 'id' | 'kind' | 'page' | 'text' | 'bbox'>> | null | undefined,
  compare: Array<Pick<ParsingElement, 'id' | 'kind' | 'page' | 'text' | 'bbox'>> | null | undefined
): ParsingElementDiffSummary {
  const baseItems = base || []
  const compareItems = compare || []
  const baseSignatures = new Set(baseItems.map(elementSignature))
  const compareSignatures = new Set(compareItems.map(elementSignature))
  const addedByKind: ElementCountMap = {}
  const removedByKind: ElementCountMap = {}
  const addedSealTexts: string[] = []
  const removedSealTexts: string[] = []

  for (const element of compareItems) {
    const signature = elementSignature(element)
    if (baseSignatures.has(signature)) continue
    incrementCount(addedByKind, element.kind)
    if (element.kind === 'seal') {
      const text = normalizeText(element.text)
      if (text) addedSealTexts.push(text)
    }
  }

  for (const element of baseItems) {
    const signature = elementSignature(element)
    if (compareSignatures.has(signature)) continue
    incrementCount(removedByKind, element.kind)
    if (element.kind === 'seal') {
      const text = normalizeText(element.text)
      if (text) removedSealTexts.push(text)
    }
  }

  return {
    totalBase: baseItems.length,
    totalCompare: compareItems.length,
    addedByKind,
    removedByKind,
    addedSealTexts,
    removedSealTexts,
  }
}

