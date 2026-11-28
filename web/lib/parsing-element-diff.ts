import type { ParsingElement } from '@/lib/api/parsing'
import { getParsingElementVisualKind, getParsingPages } from '@/lib/parsing-elements'

type ElementCountMap = Record<ParsingElement['kind'], number>

export type ParsingElementDiffSummary = {
  totalBase: number
  totalCompare: number
  addedByKind: ElementCountMap
  removedByKind: ElementCountMap
  addedSealTexts: string[]
  removedSealTexts: string[]
  addedImageVisualKinds: string[]
  removedImageVisualKinds: string[]
}

function normalizeElementText(text: ParsingElement['text']): string | null {
  if (text === undefined || text === null) return null
  return text.replace(/\s+/g, ' ').trim()
}

function getElementSignature(element: ParsingElement): string {
  const bbox = element.bbox
  return JSON.stringify([
    element.kind,
    getParsingPages(element),
    getParsingElementVisualKind(element)?.toLowerCase(),
    normalizeElementText(element.text),
    bbox === undefined || bbox === null ? null : [bbox.x0, bbox.y0, bbox.x1, bbox.y1],
  ])
}

function getUnmatchedElements(elements: readonly ParsingElement[], reference: readonly ParsingElement[]) {
  const remainingCounts = new Map<string, number>()
  for (const element of reference) {
    const signature = getElementSignature(element)
    const count = remainingCounts.get(signature)
    remainingCounts.set(signature, count === undefined ? 1 : count + 1)
  }

  return elements.filter((element) => {
    const signature = getElementSignature(element)
    const count = remainingCounts.get(signature)
    if (count === undefined) return true
    if (count === 1) remainingCounts.delete(signature)
    else remainingCounts.set(signature, count - 1)
    return false
  })
}

function summarizeElementChanges(elements: readonly ParsingElement[]) {
  const byKind: ElementCountMap = {
    heading: 0,
    paragraph: 0,
    list: 0,
    table: 0,
    image: 0,
    equation: 0,
    seal: 0,
    unknown: 0,
  }
  const sealTexts: string[] = []
  const imageVisualKinds = new Set<string>()

  for (const element of elements) {
    byKind[element.kind] += 1
    if (element.kind === 'seal') {
      const text = normalizeElementText(element.text)
      if (text !== null && text.length > 0) sealTexts.push(text)
    }
    if (element.kind === 'image') {
      const visualKind = getParsingElementVisualKind(element)
      if (visualKind !== null && visualKind.length > 0) imageVisualKinds.add(visualKind.toLowerCase())
    }
  }

  return {
    byKind,
    sealTexts,
    imageVisualKinds: Array.from(imageVisualKinds).sort((left, right) => left.localeCompare(right)),
  }
}

export function diffParsingElements(
  base: readonly ParsingElement[],
  compare: readonly ParsingElement[],
): ParsingElementDiffSummary {
  const added = summarizeElementChanges(getUnmatchedElements(compare, base))
  const removed = summarizeElementChanges(getUnmatchedElements(base, compare))

  return {
    totalBase: base.length,
    totalCompare: compare.length,
    addedByKind: added.byKind,
    removedByKind: removed.byKind,
    addedSealTexts: added.sealTexts,
    removedSealTexts: removed.sealTexts,
    addedImageVisualKinds: added.imageVisualKinds,
    removedImageVisualKinds: removed.imageVisualKinds,
  }
}
