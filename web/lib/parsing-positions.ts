export interface ParsingPosition {
  pages: number[]
  left: number
  right: number
  top: number
  bottom: number
  raw: string
}

export interface ParsingBlock {
  id: string
  text: string
  positions: ParsingPosition[]
}

export type PositionTagRange = {
  start: number
  end: number
}

export interface ParsingBlockWithRange extends ParsingBlock {
  rawStart: number
  rawEnd: number
}

const POSITION_TAG_RE = /@@([0-9-]+)\s+([0-9.]+)\s+([0-9.]+)\s+([0-9.]+)\s+([0-9.]+)##/g

function parsePages(value: string): number[] {
  const parts = value
    .split('-')
    .map((part) => Number(part))
    .filter((num) => Number.isFinite(num) && num > 0)
  return parts.map((num) => num - 1)
}

function parsePosition(match: RegExpExecArray): ParsingPosition | null {
  if (!match || match.length < 6) return null
  const pages = parsePages(match[1])
  const left = Number(match[2])
  const right = Number(match[3])
  const top = Number(match[4])
  const bottom = Number(match[5])
  if (![left, right, top, bottom].every((val) => Number.isFinite(val))) return null
  return {
    pages,
    left,
    right,
    top,
    bottom,
    raw: match[0],
  }
}

export function stripPositionTags(markdown: string): string {
  if (!markdown) return ''
  POSITION_TAG_RE.lastIndex = 0
  return markdown.replace(POSITION_TAG_RE, '')
}

export function findPositionTagRanges(markdown: string): PositionTagRange[] {
  if (!markdown) return []

  const ranges: PositionTagRange[] = []
  POSITION_TAG_RE.lastIndex = 0
  let match = POSITION_TAG_RE.exec(markdown)
  while (match) {
    const start = match.index
    const end = match.index + match[0].length
    ranges.push({ start, end })
    match = POSITION_TAG_RE.exec(markdown)
  }

  return ranges
}

function upperBound(values: number[], target: number): number {
  let lo = 0
  let hi = values.length
  while (lo < hi) {
    const mid = (lo + hi) >>> 1
    if (values[mid] <= target) lo = mid + 1
    else hi = mid
  }
  return lo
}

export function createPositionTagIndexMapper(
  markdown: string,
  ranges?: PositionTagRange[]
): (rawIndex: number) => number {
  const raw = markdown || ''
  const tagRanges = (ranges || findPositionTagRanges(raw))
    .filter((r) => Number.isFinite(r.start) && Number.isFinite(r.end) && r.end > r.start)
    .sort((a, b) => a.start - b.start)

  if (tagRanges.length === 0) {
    return (rawIndex: number) => Math.max(0, Math.trunc(Number(rawIndex) || 0))
  }

  const starts: number[] = []
  const ends: number[] = []
  const removedBeforeStart: number[] = []
  let removed = 0
  for (const r of tagRanges) {
    starts.push(r.start)
    ends.push(r.end)
    removedBeforeStart.push(removed)
    removed += r.end - r.start
  }

  return (rawIndex: number) => {
    const idx = Math.trunc(Number(rawIndex) || 0)
    if (idx <= 0) return 0

    const k = upperBound(starts, idx) - 1
    if (k < 0) return idx

    const start = starts[k]
    const end = ends[k]
    const removedBefore = removedBeforeStart[k]
    const removedThrough = removedBefore + (end - start)

    if (idx < end) {
      return Math.max(0, start - removedBefore)
    }

    return Math.max(0, idx - removedThrough)
  }
}

export function extractBlocksFromMarkdown(markdown: string): {
  cleanedMarkdown: string
  blocks: ParsingBlock[]
} {
  if (!markdown) {
    return { cleanedMarkdown: '', blocks: [] }
  }

  const blocks: ParsingBlock[] = []
  let lastIndex = 0
  let blockId = 0
  let lastBlock: ParsingBlock | null = null

  POSITION_TAG_RE.lastIndex = 0
  let match = POSITION_TAG_RE.exec(markdown)
  while (match) {
    const textChunk = markdown.slice(lastIndex, match.index)
    const position = parsePosition(match)
    const text = textChunk.trim()

    if (text) {
      const block: ParsingBlock = {
        id: `block-${blockId++}`,
        text,
        positions: position ? [position] : [],
      }
      blocks.push(block)
      lastBlock = block
    } else if (position) {
      if (lastBlock) {
        lastBlock.positions.push(position)
      } else {
        const block: ParsingBlock = {
          id: `block-${blockId++}`,
          text: '',
          positions: [position],
        }
        blocks.push(block)
        lastBlock = block
      }
    }

    lastIndex = match.index + match[0].length
    match = POSITION_TAG_RE.exec(markdown)
  }

  const trailing = markdown.slice(lastIndex)
  const trailingText = trailing.trim()
  if (trailingText) {
    if (lastBlock) {
      lastBlock.text = lastBlock.text ? `${lastBlock.text}\n\n${trailingText}` : trailingText
    } else {
      blocks.push({
        id: `block-${blockId++}`,
        text: trailingText,
        positions: [],
      })
    }
  }

  return {
    cleanedMarkdown: stripPositionTags(markdown),
    blocks,
  }
}

export function extractBlocksFromMarkdownWithRanges(markdown: string): {
  cleanedMarkdown: string
  blocks: ParsingBlockWithRange[]
  tagRanges: PositionTagRange[]
} {
  if (!markdown) {
    return { cleanedMarkdown: '', blocks: [], tagRanges: [] }
  }

  const blocks: ParsingBlockWithRange[] = []
  const tagRanges: PositionTagRange[] = []
  let lastIndex = 0
  let blockId = 0
  let lastBlock: ParsingBlockWithRange | null = null

  POSITION_TAG_RE.lastIndex = 0
  let match = POSITION_TAG_RE.exec(markdown)
  while (match) {
    const tagStart = match.index
    const tagEnd = match.index + match[0].length
    tagRanges.push({ start: tagStart, end: tagEnd })

    const textChunk = markdown.slice(lastIndex, tagStart)
    const position = parsePosition(match)
    const text = textChunk.trim()

    if (text) {
      const block: ParsingBlockWithRange = {
        id: `block-${blockId++}`,
        text,
        positions: position ? [position] : [],
        rawStart: lastIndex,
        rawEnd: tagStart,
      }
      blocks.push(block)
      lastBlock = block
    } else if (position) {
      if (lastBlock) {
        lastBlock.positions.push(position)
      } else {
        const block: ParsingBlockWithRange = {
          id: `block-${blockId++}`,
          text: '',
          positions: [position],
          rawStart: lastIndex,
          rawEnd: lastIndex,
        }
        blocks.push(block)
        lastBlock = block
      }
    }

    lastIndex = tagEnd
    match = POSITION_TAG_RE.exec(markdown)
  }

  const trailing = markdown.slice(lastIndex)
  const trailingText = trailing.trim()
  if (trailingText) {
    if (lastBlock) {
      lastBlock.text = lastBlock.text ? `${lastBlock.text}\n\n${trailingText}` : trailingText
      lastBlock.rawEnd = markdown.length
    } else {
      blocks.push({
        id: `block-${blockId++}`,
        text: trailingText,
        positions: [],
        rawStart: lastIndex,
        rawEnd: markdown.length,
      })
    }
  }

  return {
    cleanedMarkdown: stripPositionTags(markdown),
    blocks,
    tagRanges,
  }
}
