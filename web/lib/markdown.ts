export type MarkdownHeading = {
  level: number
  text: string
  id: string
  line: number
}

const CODE_FENCE_RE = /^(```+|~~~+)\s*/

function isAsciiWhitespace(char: string | undefined): boolean {
  return (
    char === ' ' ||
    char === '\t' ||
    char === '\n' ||
    char === '\r' ||
    char === '\f' ||
    char === '\v'
  )
}

function trimAsciiWhitespace(text: string): string {
  let start = 0
  let end = text.length

  while (start < end && isAsciiWhitespace(text[start])) {
    start += 1
  }

  while (end > start && isAsciiWhitespace(text[end - 1])) {
    end -= 1
  }

  return text.slice(start, end)
}

function trimEdgeChar(text: string, char: string): string {
  let start = 0
  let end = text.length

  while (start < end && text[start] === char) {
    start += 1
  }

  while (end > start && text[end - 1] === char) {
    end -= 1
  }

  return text.slice(start, end)
}

function readBalancedSegment(
  text: string,
  startIndex: number,
  openChar: string,
  closeChar: string
): { content: string; nextIndex: number } | null {
  if (text[startIndex] !== openChar) return null

  let depth = 0

  for (let index = startIndex; index < text.length; index += 1) {
    const char = text[index]

    if (char === '\\') {
      index += 1
      continue
    }

    if (char === openChar) {
      depth += 1
      continue
    }

    if (char !== closeChar) continue

    depth -= 1
    if (depth === 0) {
      return {
        content: text.slice(startIndex + 1, index),
        nextIndex: index + 1,
      }
    }
  }

  return null
}

function readMarkdownLink(
  text: string,
  startIndex: number,
  options: { image?: boolean } = {}
): { label: string; nextIndex: number } | null {
  const labelStart = options.image ? startIndex + 1 : startIndex
  const label = readBalancedSegment(text, labelStart, '[', ']')
  if (!label) return null
  if (text[label.nextIndex] !== '(') return null

  const destination = readBalancedSegment(text, label.nextIndex, '(', ')')
  if (!destination) return null

  return {
    label: label.content,
    nextIndex: destination.nextIndex,
  }
}

function readInlineCodeSpan(
  text: string,
  startIndex: number
): { content: string; nextIndex: number } | null {
  if (text[startIndex] !== '`') return null

  let fenceLength = 1
  while (text[startIndex + fenceLength] === '`') {
    fenceLength += 1
  }

  const fence = '`'.repeat(fenceLength)
  const endIndex = text.indexOf(fence, startIndex + fenceLength)
  if (endIndex === -1) return null

  return {
    content: text.slice(startIndex + fenceLength, endIndex),
    nextIndex: endIndex + fenceLength,
  }
}

function stripTrailingHeadingFence(text: string): string {
  let end = text.length

  while (end > 0 && isAsciiWhitespace(text[end - 1])) {
    end -= 1
  }

  while (end > 0 && text[end - 1] === '#') {
    end -= 1
  }

  while (end > 0 && isAsciiWhitespace(text[end - 1])) {
    end -= 1
  }

  return text.slice(0, end)
}

type InlineMarkdownToken = {
  content: string
  nextIndex: number
}

function readImageToken(text: string, startIndex: number): InlineMarkdownToken | null {
  if (!text.startsWith('![', startIndex)) return null

  const image = readMarkdownLink(text, startIndex, { image: true })
  if (!image) return null

  return {
    content: stripInlineMarkdown(image.label),
    nextIndex: image.nextIndex,
  }
}

function readLinkToken(text: string, startIndex: number): InlineMarkdownToken | null {
  if (text[startIndex] !== '[') return null

  const link = readMarkdownLink(text, startIndex)
  if (!link) return null

  return {
    content: stripInlineMarkdown(link.label),
    nextIndex: link.nextIndex,
  }
}

function readCodeToken(text: string, startIndex: number): InlineMarkdownToken | null {
  const codeSpan = readInlineCodeSpan(text, startIndex)
  if (!codeSpan) return null

  return {
    content: codeSpan.content,
    nextIndex: codeSpan.nextIndex,
  }
}

function readHtmlTagToken(text: string, startIndex: number): InlineMarkdownToken | null {
  if (text[startIndex] !== '<') return null

  const closeIndex = text.indexOf('>', startIndex + 1)
  if (closeIndex === -1) return null

  return {
    content: '',
    nextIndex: closeIndex + 1,
  }
}

function readInlineMarkdownToken(text: string, startIndex: number): InlineMarkdownToken | null {
  return (
    readImageToken(text, startIndex) ||
    readLinkToken(text, startIndex) ||
    readCodeToken(text, startIndex) ||
    readHtmlTagToken(text, startIndex)
  )
}

function isInlineFormattingMarker(char: string): boolean {
  return char === '*' || char === '_'
}

function stripInlineMarkdown(text = ''): string {
  if (!text) return ''

  const parts: string[] = []

  for (let index = 0; index < text.length; ) {
    const token = readInlineMarkdownToken(text, index)
    if (token) {
      parts.push(token.content)
      index = token.nextIndex
      continue
    }

    const char = text[index]
    if (isInlineFormattingMarker(char)) {
      index += 1
      continue
    }

    parts.push(char)
    index += 1
  }

  return trimAsciiWhitespace(parts.join(''))
}

function getFenceState(
  trimmed: string,
  inCodeFence: boolean,
  fenceToken: string | null
): { inCodeFence: boolean; fenceToken: string | null; matchedFence: boolean } {
  const fenceMatch = CODE_FENCE_RE.exec(trimmed)
  if (!fenceMatch) {
    return { inCodeFence, fenceToken, matchedFence: false }
  }

  const token = fenceMatch[1]
  if (!inCodeFence) {
    return {
      inCodeFence: true,
      fenceToken: token.startsWith('```') ? '```' : '~~~',
      matchedFence: true,
    }
  }

  if (fenceToken && token.startsWith(fenceToken)) {
    return { inCodeFence: false, fenceToken: null, matchedFence: true }
  }

  return { inCodeFence, fenceToken, matchedFence: false }
}

function parseMarkdownHeadingLine(
  line: string,
  maxDepth: number
): { level: number; rawText: string } | null {
  let index = 0
  let indent = 0

  while (index < line.length && indent < 3 && (line[index] === ' ' || line[index] === '\t')) {
    index += 1
    indent += 1
  }

  let level = 0
  while (index < line.length && line[index] === '#' && level < 6) {
    level += 1
    index += 1
  }

  if (level < 1 || level > Math.min(6, maxDepth)) return null
  if (!isAsciiWhitespace(line[index])) return null

  while (index < line.length && isAsciiWhitespace(line[index])) {
    index += 1
  }

  if (index >= line.length) return null

  return {
    level,
    rawText: stripTrailingHeadingFence(line.slice(index)),
  }
}

export function slugifyHeading(text: string): string {
  const raw = stripInlineMarkdown(text)
  if (!raw) return ''

  try {
    const slug = raw
      .toLowerCase()
      .normalize('NFKD')
      .replaceAll(/[^\p{L}\p{N}]+/gu, '-')
      .replaceAll(/-{2,}/g, '-')
    return trimEdgeChar(slug, '-')
  } catch {
    // Fallback for environments without unicode property escapes (very unlikely in modern browsers)
    const slug = raw
      .toLowerCase()
      .replaceAll(/[^a-z0-9]+/g, '-')
      .replaceAll(/-{2,}/g, '-')
    return trimEdgeChar(slug, '-')
  }
}

export function extractMarkdownHeadings(
  markdown: string,
  options: { maxDepth?: number } = {}
): MarkdownHeading[] {
  const maxDepth = options.maxDepth ?? 6
  const text = markdown || ''
  if (!text.trim()) return []

  const lines = text.split(/\r?\n/)
  const headings: MarkdownHeading[] = []
  const seen = new Map<string, number>()

  let inCodeFence = false
  let fenceToken: string | null = null

  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index]
    const trimmed = line.trim()

    const nextFenceState = getFenceState(trimmed, inCodeFence, fenceToken)
    inCodeFence = nextFenceState.inCodeFence
    fenceToken = nextFenceState.fenceToken
    if (nextFenceState.matchedFence || inCodeFence) {
      continue
    }

    const heading = parseMarkdownHeadingLine(line, maxDepth)
    if (!heading) continue

    const headingText = stripInlineMarkdown(heading.rawText)
    const base = slugifyHeading(headingText) || `section-${headings.length + 1}`

    const prev = seen.get(base) || 0
    const nextCount = prev + 1
    seen.set(base, nextCount)
    const id = nextCount === 1 ? base : `${base}-${nextCount}`

    headings.push({
      level: heading.level,
      text: headingText || heading.rawText.trim(),
      id,
      line: index + 1,
    })
  }

  return headings
}

export function scrollToElementId(
  id: string,
  options: {
    behavior?: ScrollBehavior
    block?: ScrollLogicalPosition
    scrollContainerSelector?: string
  } = {}
): boolean {
  if (globalThis.window === undefined) return false
  const key = (id || '').replace(/^#/, '').trim()
  if (!key) return false

  const el = globalThis.window.document.getElementById(key)
  if (!el) return false

  const behavior = options.behavior ?? 'smooth'
  const block = options.block ?? 'start'
  const containerSelector = (options.scrollContainerSelector || '').trim()
  const container = containerSelector
    ? globalThis.window.document.querySelector<HTMLElement>(containerSelector)
    : null

  if (container?.contains(el)) {
    const containerRect = container.getBoundingClientRect()
    const elementRect = el.getBoundingClientRect()
    const elementTop = container.scrollTop + (elementRect.top - containerRect.top)
    const elementBottom = elementTop + elementRect.height
    let nextTop = elementTop

    if (block === 'center') {
      nextTop = elementTop - (container.clientHeight - elementRect.height) / 2
    } else if (block === 'end') {
      nextTop = elementBottom - container.clientHeight
    } else if (block === 'nearest') {
      const visibleTop = container.scrollTop
      const visibleBottom = visibleTop + container.clientHeight
      if (elementTop < visibleTop) {
        nextTop = elementTop
      } else if (elementBottom > visibleBottom) {
        nextTop = elementBottom - container.clientHeight
      } else {
        return true
      }
    }

    container.scrollTo({
      top: Math.max(0, nextTop),
      behavior,
    })
    return true
  }

  el.scrollIntoView({ behavior, block })
  return true
}

export function flashElementId(id: string, className: string, durationMs = 900): void {
  if (globalThis.window === undefined) return
  const key = (id || '').replace(/^#/, '').trim()
  if (!key) return
  const el = globalThis.window.document.getElementById(key)
  if (!el) return

  el.classList.add(...className.split(/\s+/g).filter(Boolean))
  globalThis.window.setTimeout(() => {
    el.classList.remove(...className.split(/\s+/g).filter(Boolean))
  }, Math.max(0, Number(durationMs) || 0))
}
