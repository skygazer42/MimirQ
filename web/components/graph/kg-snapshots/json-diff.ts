import { diffLines } from 'diff'

import type {
  DiffCell,
  DiffCellStatus,
  JsonTokenKind,
  SideBySideDiffRow,
} from './types'

export function splitCodeLines(value: string): string[] {
  const normalized = String(value ?? '').replaceAll('\r', '')
  const lines = normalized.split('\n')
  if (lines.length > 1 && lines.at(-1) === '') lines.pop()
  return lines.length ? lines : ['']
}

export function buildPairedRows(
  leftLines: string[],
  rightLines: string[],
  leftStatus: DiffCellStatus,
  rightStatus: DiffCellStatus,
  leftCounter: { value: number },
  rightCounter: { value: number }
): SideBySideDiffRow[] {
  const maxLength = Math.max(leftLines.length, rightLines.length)
  return Array.from({ length: maxLength }, (_, index) => {
    const leftText = leftLines[index]
    const rightText = rightLines[index]

    const leftCell: DiffCell = {
      lineNumber: typeof leftText === 'string' ? leftCounter.value++ : null,
      text: leftText ?? '',
      status: typeof leftText === 'string' ? leftStatus : 'empty',
    }
    const rightCell: DiffCell = {
      lineNumber: typeof rightText === 'string' ? rightCounter.value++ : null,
      text: rightText ?? '',
      status: typeof rightText === 'string' ? rightStatus : 'empty',
    }
    return { left: leftCell, right: rightCell }
  })
}

export function buildSideBySideDiffRows(
  aText: string,
  bText: string
): SideBySideDiffRow[] {
  const changes = diffLines(aText, bText)
  const leftCounter = { value: 1 }
  const rightCounter = { value: 1 }
  const rows: SideBySideDiffRow[] = []

  for (let index = 0; index < changes.length; index += 1) {
    const change = changes[index]
    if (!change) continue

    if (!change.added && !change.removed) {
      const lines = splitCodeLines(change.value)
      rows.push(
        ...buildPairedRows(
          lines,
          lines,
          'same',
          'same',
          leftCounter,
          rightCounter
        )
      )
      continue
    }

    const next = changes[index + 1]
    if (change.removed && next?.added) {
      rows.push(
        ...buildPairedRows(
          splitCodeLines(change.value),
          splitCodeLines(next.value),
          'removed',
          'added',
          leftCounter,
          rightCounter
        )
      )
      index += 1
      continue
    }

    if (change.added && next?.removed) {
      rows.push(
        ...buildPairedRows(
          splitCodeLines(next.value),
          splitCodeLines(change.value),
          'removed',
          'added',
          leftCounter,
          rightCounter
        )
      )
      index += 1
      continue
    }

    if (change.removed) {
      rows.push(
        ...buildPairedRows(
          splitCodeLines(change.value),
          [],
          'removed',
          'empty',
          leftCounter,
          rightCounter
        )
      )
      continue
    }

    if (change.added) {
      rows.push(
        ...buildPairedRows(
          [],
          splitCodeLines(change.value),
          'empty',
          'added',
          leftCounter,
          rightCounter
        )
      )
    }
  }

  return rows
}

export function readJsonStringEnd(line: string, startIndex: number) {
  let index = startIndex + 1
  while (index < line.length) {
    const char = line[index]
    if (char === '\\') {
      index += 2
      continue
    }
    if (char === '"') return index + 1
    index += 1
  }
  return line.length
}

export function readJsonKeySuffix(line: string, startIndex: number) {
  let index = startIndex
  while (index < line.length && /\s/.test(line[index])) index += 1
  return line[index] === ':' ? index + 1 : startIndex
}

const JSON_NUMBER_TOKEN_PATTERN = /-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?/y
const JSON_LITERAL_TOKEN_PATTERN = /true|false|null/y

export function tokenizeJsonLine(line: string): Array<{ text: string; kind: JsonTokenKind }> {
  const tokens: Array<{ text: string; kind: JsonTokenKind }> = []
  let index = 0

  while (index < line.length) {
    const char = line[index]

    if (char === '"') {
      const stringEnd = readJsonStringEnd(line, index)
      const suffixEnd = readJsonKeySuffix(line, stringEnd)
      const hasKeySuffix = suffixEnd > stringEnd
      tokens.push({ text: line.slice(index, stringEnd), kind: hasKeySuffix ? 'key' : 'string' })
      if (hasKeySuffix) tokens.push({ text: line.slice(stringEnd, suffixEnd), kind: 'punctuation' })
      index = suffixEnd
      continue
    }

    JSON_NUMBER_TOKEN_PATTERN.lastIndex = index
    const numberMatch = JSON_NUMBER_TOKEN_PATTERN.exec(line)
    if (numberMatch) {
      const raw = numberMatch[0]
      tokens.push({ text: raw, kind: 'number' })
      index += raw.length
      continue
    }

    JSON_LITERAL_TOKEN_PATTERN.lastIndex = index
    const literalMatch = JSON_LITERAL_TOKEN_PATTERN.exec(line)
    if (literalMatch) {
      const raw = literalMatch[0]
      tokens.push({ text: raw, kind: raw === 'null' ? 'null' : 'boolean' })
      index += raw.length
      continue
    }

    if ('{}[],:'.includes(char)) {
      tokens.push({ text: char, kind: 'punctuation' })
      index += 1
    } else {
      tokens.push({ text: char, kind: 'plain' })
      index += 1
    }
  }

  const mergedTokens: typeof tokens = []
  for (const token of tokens) {
    const previous = mergedTokens.at(-1)
    if (previous?.kind === 'plain' && token.kind === 'plain') {
      previous.text += token.text
    } else {
      mergedTokens.push({ ...token })
    }
  }

  if (mergedTokens.length === 0) return [{ text: line, kind: 'plain' }]
  return mergedTokens
}

export function lineNumberClassForStatus(status: DiffCellStatus | 'single'): string {
  if (status === 'added') return 'text-success'
  if (status === 'removed') return 'text-destructive'
  return 'text-muted-foreground'
}

export function jsonLineSurfaceClass(status: DiffCellStatus | 'single', side: 'left' | 'right' | 'single') {
  if (status === 'single') return 'bg-transparent'
  return cellSurfaceClass(status, side === 'single' ? 'left' : side)
}

export function cellSurfaceClass(status: DiffCellStatus, side: 'left' | 'right') {
  if (status === 'removed') return 'bg-destructive/5'
  if (status === 'added') return 'bg-success/5'
  if (status === 'empty')
    return side === 'left' ? 'bg-destructive/5' : 'bg-success/5'
  return 'bg-card'
}

export function tokenClassName(kind: JsonTokenKind) {
  if (kind === 'key') return 'text-info'
  if (kind === 'string') return 'text-success'
  if (kind === 'number') return 'text-warning'
  if (kind === 'boolean') return 'text-accent'
  if (kind === 'null') return 'text-destructive'
  if (kind === 'punctuation') return 'text-muted-foreground'
  return 'text-foreground/90'
}
