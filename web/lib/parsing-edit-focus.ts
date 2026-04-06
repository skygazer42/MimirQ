import type { ParsingLayoutEntry } from './parsing-layout'

export interface ParsingEditSelection {
  start: number
  end: number
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

export function findEditSelectionForActiveParsingEntry(
  markdown: string,
  entries: ParsingLayoutEntry[],
  activeEntryId: string | null
): ParsingEditSelection | null {
  if (!markdown || !entries.length || !activeEntryId) return null

  let cursor = 0
  const resolvedRanges = new Map<string, ParsingEditSelection | null>()

  for (const entry of entries) {
    const range = findTextRange(markdown, entry.text, cursor) ?? findTextRange(markdown, entry.text, 0)
    resolvedRanges.set(entry.id, range)
    if (!range) continue

    if (entry.id === activeEntryId) {
      return range
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
