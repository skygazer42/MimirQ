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

const POSITION_TAG_RE = /@@([0-9-]+)\t([0-9.]+)\t([0-9.]+)\t([0-9.]+)\t([0-9.]+)##/g

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
  return markdown.replace(POSITION_TAG_RE, '')
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
