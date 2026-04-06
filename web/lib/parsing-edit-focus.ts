import type { ParsingLayoutEntry } from './parsing-layout'

export interface ParsingEditSelection {
  start: number
  end: number
}

export interface ParsingEditFocusHint {
  xRatio: number
  yRatio: number
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

function findTextRange(markdown: string, text: string, fromIndex: number): ParsingEditSelection | null {
  const candidate = text.trim()
  if (!candidate) return null

  const directIndex = markdown.indexOf(candidate, Math.max(0, fromIndex))
  if (directIndex >= 0) {
    return {
      start: directIndex,
      end: directIndex + candidate.length,
    }
  }

  const tokens = candidate.split(/\s+/).filter(Boolean)
  if (tokens.length <= 1) return null

  const pattern = tokens.map(escapeRegExp).join('\\s+')
  const re = new RegExp(pattern, 'm')
  const segment = markdown.slice(Math.max(0, fromIndex))
  const match = re.exec(segment)
  if (!match || match.index < 0) return null

  return {
    start: Math.max(0, fromIndex) + match.index,
    end: Math.max(0, fromIndex) + match.index + match[0].length,
  }
}

function clampRatio(value: number): number {
  if (!Number.isFinite(value)) return 0
  return Math.max(0, Math.min(1, value))
}

function buildCaretBoundaries(text: string): number[] {
  const boundaries = new Set<number>([0, text.length])
  for (let index = 1; index < text.length; index += 1) {
    const prev = text[index - 1]
    const current = text[index]
    if (/\s/.test(prev)) {
      boundaries.add(index)
      continue
    }
    if (/[.,;:!?()[\]{}\-–—/\\]/.test(prev) || /[.,;:!?()[\]{}\-–—/\\]/.test(current)) {
      boundaries.add(index)
    }
  }
  return Array.from(boundaries).sort((left, right) => left - right)
}

function estimateCaretFromHint(text: string, hint?: ParsingEditFocusHint | null): number {
  if (!text) return 0
  if (!hint) return 0

  const normalizedY = clampRatio(hint.yRatio)
  const normalizedX = clampRatio(hint.xRatio)
  const lines = text.split(/\r?\n/)

  if (lines.length > 1) {
    const targetLineIndex = Math.min(lines.length - 1, Math.floor(normalizedY * lines.length))
    let offset = 0
    for (let lineIndex = 0; lineIndex < targetLineIndex; lineIndex += 1) {
      offset += lines[lineIndex].length + 1
    }
    const activeLine = lines[targetLineIndex] || ''
    return Math.min(text.length, offset + Math.floor(activeLine.length * normalizedX))
  }

  const boundaries = buildCaretBoundaries(text)
  const blendedRatio = clampRatio(normalizedY * 0.8 + normalizedX * 0.2)
  const target = Math.round(text.length * blendedRatio)
  let best = boundaries[0] ?? 0
  let bestDistance = Math.abs(best - target)
  for (const candidate of boundaries) {
    const distance = Math.abs(candidate - target)
    if (distance < bestDistance) {
      best = candidate
      bestDistance = distance
    }
  }
  return best
}

export function findEditSelectionForActiveParsingEntry(
  markdown: string,
  entries: ParsingLayoutEntry[],
  activeEntryId: string | null,
  hint?: ParsingEditFocusHint | null
): ParsingEditSelection | null {
  if (!markdown || !entries.length || !activeEntryId) return null

  let cursor = 0
  const resolvedRanges = new Map<string, ParsingEditSelection | null>()

  for (const entry of entries) {
    const range = findTextRange(markdown, entry.text, cursor) ?? findTextRange(markdown, entry.text, 0)
    resolvedRanges.set(entry.id, range)
    if (!range) continue

    if (entry.id === activeEntryId) {
      const localCaret = estimateCaretFromHint(markdown.slice(range.start, range.end), hint)
      return range
        ? {
            start: range.start + localCaret,
            end: range.start + localCaret,
          }
        : null
    }

    cursor = Math.max(cursor, range.end)
  }

  const activeIndex = entries.findIndex((entry) => entry.id === activeEntryId)
  if (activeIndex < 0) return null

  for (let index = activeIndex - 1; index >= 0; index -= 1) {
    const fallback = resolvedRanges.get(entries[index].id)
    if (fallback) {
      return {
        start: fallback.end,
        end: fallback.end,
      }
    }
  }

  for (let index = activeIndex + 1; index < entries.length; index += 1) {
    const fallback = resolvedRanges.get(entries[index].id)
    if (fallback) {
      return {
        start: fallback.start,
        end: fallback.start,
      }
    }
  }

  return null
}
