import type { ParsingBlock, ParsingPosition } from './parsing-positions'

export type ParsingLayoutKind = 'heading' | 'paragraph' | 'list' | 'table' | 'image' | 'equation' | 'seal'

export type ParsingLayoutMeta = {
  label: string
  shortLabel: string
  chipClassName: string
  dotClassName: string
  overlayClassName: string
}

export type ParsingLayoutEntry = {
  id: string
  blockId: string
  text: string
  kind: ParsingLayoutKind
  position: ParsingPosition
  pageIndex: number | null
  charCount: number
  lineCount: number
}

const PARSING_LAYOUT_META: Record<ParsingLayoutKind, ParsingLayoutMeta> = {
  heading: {
    label: '标题',
    shortLabel: '标题',
    chipClassName: 'border-sky-200/80 bg-sky-50 text-sky-700 dark:border-sky-900/60 dark:bg-sky-950/40 dark:text-sky-200',
    dotClassName: 'bg-sky-500 dark:bg-sky-300',
    overlayClassName: 'border-sky-500/75 bg-sky-500/10',
  },
  paragraph: {
    label: '正文',
    shortLabel: '正文',
    chipClassName:
      'border-slate-200/80 bg-slate-50 text-slate-700 dark:border-slate-800/70 dark:bg-slate-900/40 dark:text-slate-200',
    dotClassName: 'bg-slate-400 dark:bg-slate-300',
    overlayClassName: 'border-slate-400/75 bg-slate-400/10',
  },
  list: {
    label: '列表',
    shortLabel: '列表',
    chipClassName:
      'border-info/30 bg-info/10 text-info dark:border-info/30 dark:bg-info/20 dark:text-info',
    dotClassName: 'bg-info dark:bg-info/70',
    overlayClassName: 'border-info/60 bg-info/10',
  },
  table: {
    label: '表格',
    shortLabel: '表格',
    chipClassName:
      'border-emerald-200/80 bg-emerald-50 text-emerald-700 dark:border-emerald-900/60 dark:bg-emerald-950/35 dark:text-emerald-200',
    dotClassName: 'bg-emerald-500 dark:bg-emerald-300',
    overlayClassName: 'border-emerald-500/75 bg-emerald-500/10',
  },
  image: {
    label: '图片',
    shortLabel: '图片',
    chipClassName:
      'border-amber-200/80 bg-amber-50 text-amber-700 dark:border-amber-900/60 dark:bg-amber-950/35 dark:text-amber-200',
    dotClassName: 'bg-amber-500 dark:bg-amber-300',
    overlayClassName: 'border-amber-500/75 bg-amber-500/10',
  },
  equation: {
    label: '公式',
    shortLabel: '公式',
    chipClassName:
      'border-violet-200/80 bg-violet-50 text-violet-700 dark:border-violet-900/60 dark:bg-violet-950/35 dark:text-violet-200',
    dotClassName: 'bg-violet-500 dark:bg-violet-300',
    overlayClassName: 'border-violet-500/75 bg-violet-500/10',
  },
  seal: {
    label: '印章',
    shortLabel: '印章',
    chipClassName:
      'border-rose-200/80 bg-rose-50 text-rose-700 dark:border-rose-900/60 dark:bg-rose-950/35 dark:text-rose-200',
    dotClassName: 'bg-rose-500 dark:bg-rose-300',
    overlayClassName: 'border-rose-500/75 bg-rose-500/10',
  },
}

const MARKDOWN_IMAGE_RE = /!\[[^\]]*]\([^)]+\)|<img\b/i
const ORDERED_LIST_RE = /^\s*\d+[.)]\s+/m
const UNORDERED_LIST_RE = /^\s*[-*+]\s+/m
const EQUATION_RE = /\$\$[\s\S]*?\$\$|\\(?:begin\{equation\}|frac|sum|int|alpha|beta|gamma|times|cdot|sqrt)/i
const HEADING_RE = /^\s{0,3}#{1,6}\s+\S+/m

function hasTabularRows(text: string): boolean {
  const lines = text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)

  if (lines.length < 2) return false
  const pipeLines = lines.filter((line) => line.includes('|'))
  if (pipeLines.length >= 2) return true

  return lines.some((line) => /^\|?\s*:?-{3,}/.test(line))
}

function looksLikeHeading(text: string): boolean {
  const lines = text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)

  if (lines.length !== 1) return false

  const candidate = lines[0]
  if (!candidate || candidate.length > 72) return false
  if (/[。！？.!?;；:：]$/.test(candidate)) return false
  if (candidate.includes('|')) return false

  return candidate.split(/\s+/).length <= 12
}

export function classifyParsingBlock(block: Pick<ParsingBlock, 'text'>): ParsingLayoutKind {
  const text = block.text.trim()
  if (!text) return 'paragraph'

  if (MARKDOWN_IMAGE_RE.test(text)) return 'image'
  if (hasTabularRows(text)) return 'table'
  if (EQUATION_RE.test(text)) return 'equation'
  if (ORDERED_LIST_RE.test(text) || UNORDERED_LIST_RE.test(text)) return 'list'
  if (HEADING_RE.test(text) || looksLikeHeading(text)) return 'heading'

  return 'paragraph'
}

export function getParsingLayoutMeta(kind: ParsingLayoutKind): ParsingLayoutMeta {
  return PARSING_LAYOUT_META[kind]
}

export function countParsingBlockChars(text: string): number {
  const normalized = text.replace(/\s+/g, '')
  return normalized.length
}

export function countParsingBlockLines(text: string): number {
  const lines = text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)

  return Math.max(lines.length, 1)
}

function splitTextForPositions(text: string, positionCount: number): string[] {
  const normalized = text.trim()
  if (positionCount <= 1) return [normalized]

  const lines = text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)

  if (lines.length === 0) {
    return Array.from({ length: positionCount }, () => normalized)
  }

  if (lines.length === positionCount) {
    return lines
  }

  if (lines.length > positionCount) {
    const groups = Array.from({ length: positionCount }, () => [] as string[])
    lines.forEach((line, index) => {
      const bucket = Math.min(positionCount - 1, Math.floor((index * positionCount) / lines.length))
      groups[bucket].push(line)
    })
    return groups.map((group) => group.join('\n').trim() || normalized)
  }

  return Array.from({ length: positionCount }, (_, index) => lines[index] || normalized)
}

export function buildParsingLayoutEntries(blocks: ParsingBlock[]): ParsingLayoutEntry[] {
  const entries: ParsingLayoutEntry[] = []

  for (const block of blocks) {
    const positions = (block.positions || []).filter((position) => position != null)
    if (positions.length === 0) continue

    const kind = classifyParsingBlock(block)
    const texts = splitTextForPositions(block.text, positions.length)

    positions.forEach((position, index) => {
      const pageIndex = position.pages?.[0]
      const text = texts[index] || texts[0] || block.text.trim()
      entries.push({
        id: positions.length === 1 ? block.id : `${block.id}:${index}`,
        blockId: block.id,
        charCount: countParsingBlockChars(text),
        kind,
        lineCount: countParsingBlockLines(text),
        pageIndex: typeof pageIndex === 'number' && Number.isFinite(pageIndex) ? pageIndex : null,
        position,
        text,
      })
    })
  }

  return entries
}

export function getPrimaryParsingBlockPage(block: Pick<ParsingBlock, 'positions'>): number | null {
  for (const position of block.positions || []) {
    const pageIndex = position.pages?.[0]
    if (typeof pageIndex === 'number' && Number.isFinite(pageIndex)) {
      return pageIndex
    }
  }

  return null
}
