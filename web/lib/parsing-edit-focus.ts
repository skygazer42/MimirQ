import type { ParsingLayoutEntry } from './parsing-layout'

type ParsingEditSelection = {
  start: number
  end: number
}

export type ParsingEditFocusHint = {
  xRatio: number
  yRatio: number
}

type ParsingBlockEditTarget = {
  blockId: string
  content: string
  /** UTF-16 offsets in the original Markdown. */
  range: ParsingEditSelection
  /** UTF-16 offsets in the textarea's LF-normalized content. */
  selection: ParsingEditSelection
}

export type ParsingEditSession = {
  fileId: string
  libraryId: string | undefined
  runId: string | undefined
} & (
  | { mode: 'document' }
  | {
      mode: 'block'
      blockId: string
      range: ParsingEditSelection
      sourceMarkdown: string
    }
)

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, String.raw`\$&`)
}

function findTextRange(markdown: string, text: string, fromIndex: number): ParsingEditSelection | null {
  const candidate = text.trim()
  if (candidate.length === 0) return null

  const directIndex = markdown.indexOf(candidate, fromIndex)
  if (directIndex >= 0) {
    return {
      start: directIndex,
      end: directIndex + candidate.length,
    }
  }

  const tokens = candidate.split(/\s+/)
  if (tokens.length <= 1) return null

  const pattern = tokens.map(escapeRegExp).join(String.raw`\s+`)
  const expression = new RegExp(pattern)
  const segment = markdown.slice(fromIndex)
  const match = expression.exec(segment)
  if (match === null) return null

  return {
    start: fromIndex + match.index,
    end: fromIndex + match.index + match[0].length,
  }
}

function clampRatio(value: number): number {
  if (!Number.isFinite(value)) return 0
  return Math.max(0, Math.min(1, value))
}

function normalizeTextareaText(text: string): string {
  return text.replaceAll('\r\n', '\n').replaceAll('\r', '\n')
}

function getTextareaOffset(markdown: string, sourceOffset: number): number {
  return normalizeTextareaText(markdown.slice(0, sourceOffset)).length
}

function buildCaretBoundaries(text: string): number[] {
  const boundaries = new Set<number>([0, text.length])
  for (let index = 1; index < text.length; index += 1) {
    const previousCharacter = text[index - 1]
    const character = text[index]
    if (/\s/.test(previousCharacter)) {
      boundaries.add(index)
      continue
    }
    if (/[.,;:!?()[\]{}\-–—/\\]/.test(previousCharacter) || /[.,;:!?()[\]{}\-–—/\\]/.test(character)) {
      boundaries.add(index)
    }
  }
  return Array.from(boundaries).sort((left, right) => left - right)
}

function estimateCaretFromHint(text: string, hint?: ParsingEditFocusHint | null): number {
  if (text.length === 0 || hint === undefined || hint === null) return 0

  const normalizedY = clampRatio(hint.yRatio)
  const normalizedX = clampRatio(hint.xRatio)
  const textareaText = normalizeTextareaText(text)
  const lines = textareaText.split('\n')

  if (lines.length > 1) {
    const targetLineIndex = Math.min(lines.length - 1, Math.floor(normalizedY * lines.length))
    let offset = 0
    for (let lineIndex = 0; lineIndex < targetLineIndex; lineIndex += 1) {
      offset += lines[lineIndex].length + 1
    }
    const activeLine = lines[targetLineIndex]
    return offset + Math.floor(activeLine.length * normalizedX)
  }

  const boundaries = buildCaretBoundaries(textareaText)
  const blendedRatio = clampRatio(normalizedY * 0.8 + normalizedX * 0.2)
  const target = Math.round(textareaText.length * blendedRatio)
  let nearestBoundary = 0
  let nearestDistance = Math.abs(nearestBoundary - target)
  for (const candidate of boundaries) {
    const distance = Math.abs(candidate - target)
    if (distance < nearestDistance) {
      nearestBoundary = candidate
      nearestDistance = distance
    }
  }
  return nearestBoundary
}

function resolveParsingEntryRanges(
  markdown: string,
  entries: readonly ParsingLayoutEntry[],
): Map<string, ParsingEditSelection | null> {
  let cursor = 0
  let blockId: string | undefined
  let blockStart = 0
  let blockRange: ParsingEditSelection | null = null
  const resolvedRanges = new Map<string, ParsingEditSelection | null>()

  for (const entry of entries) {
    if (entry.blockId !== blockId) {
      blockId = entry.blockId
      blockStart = cursor
      blockRange = null
    }
    const range = entry.coversBlockText
      ? (blockRange ??= findTextRange(markdown, entry.text, blockStart))
      : findTextRange(markdown, entry.text, cursor)
    resolvedRanges.set(entry.id, range)
    if (!range) continue

    cursor = Math.max(cursor, range.end)
  }

  return resolvedRanges
}

export function buildParsingBlockEditTarget(
  markdown: string,
  entries: readonly ParsingLayoutEntry[],
  activeEntryId: string | null,
  hint?: ParsingEditFocusHint | null,
): ParsingBlockEditTarget | null {
  if (markdown.length === 0 || activeEntryId === null || activeEntryId.length === 0) return null

  const range = resolveParsingEntryRanges(markdown, entries).get(activeEntryId)
  if (!range) return null

  const content = markdown.slice(range.start, range.end)
  const localCaret = estimateCaretFromHint(content, hint)

  return {
    blockId: activeEntryId,
    content,
    range,
    selection: {
      start: localCaret,
      end: localCaret,
    },
  }
}

export function applyBlockEditToMarkdown(
  markdown: string,
  range: Readonly<ParsingEditSelection>,
  editedContent: string,
): string {
  return markdown.slice(0, range.start) + editedContent + markdown.slice(range.end)
}

/** Return offsets for textarea.value; block matching and saved ranges use the original Markdown. */
export function findEditSelectionForActiveParsingEntry(
  markdown: string,
  entries: readonly ParsingLayoutEntry[],
  activeEntryId: string | null,
  hint?: ParsingEditFocusHint | null,
): ParsingEditSelection | null {
  if (markdown.length === 0 || activeEntryId === null || activeEntryId.length === 0) return null
  const activeIndex = entries.findIndex((entry) => entry.id === activeEntryId)
  if (activeIndex < 0) return null

  const resolvedRanges = resolveParsingEntryRanges(markdown, entries)
  const range = resolvedRanges.get(activeEntryId)
  if (range) {
    const content = markdown.slice(range.start, range.end)
    const caret = getTextareaOffset(markdown, range.start) + estimateCaretFromHint(content, hint)
    return { start: caret, end: caret }
  }

  for (let index = activeIndex - 1; index >= 0; index -= 1) {
    const previousRange = resolvedRanges.get(entries[index].id)
    if (previousRange) {
      const caret = getTextareaOffset(markdown, previousRange.end)
      return { start: caret, end: caret }
    }
  }

  for (let index = activeIndex + 1; index < entries.length; index += 1) {
    const nextRange = resolvedRanges.get(entries[index].id)
    if (nextRange) {
      const caret = getTextareaOffset(markdown, nextRange.start)
      return { start: caret, end: caret }
    }
  }

  return null
}
