export type MarkdownHeading = {
  level: number
  text: string
  id: string
  line: number
}

const CODE_FENCE_RE = /^(```+|~~~+)\s*/
const MARKDOWN_HEADING_RE = /^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$/

function stripInlineMarkdown(text = ''): string {
  let out = text

  // Images: ![alt](url) -> alt
  out = out.replaceAll(/!\[([^\]]*)\]\([^)]+\)/g, '$1')
  // Links: [text](url) -> text
  out = out.replaceAll(/\[([^\]]+)\]\([^)]+\)/g, '$1')
  // Inline code: `code` -> code
  out = out.replaceAll(/`([^`]+)`/g, '$1')
  // Emphasis markers: ** / __ / * / _
  out = out.replaceAll(/(\*\*|__|\*|_)/g, '')
  // HTML tags
  out = out.replaceAll(/<[^>]+>/g, '')

  return out.trim()
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
  const headingMatch = MARKDOWN_HEADING_RE.exec(line)
  if (!headingMatch) return null

  const level = headingMatch[1].length
  if (level < 1 || level > Math.min(6, maxDepth)) return null

  return {
    level,
    rawText: headingMatch[2],
  }
}

export function slugifyHeading(text: string): string {
  const raw = stripInlineMarkdown(text)
  if (!raw) return ''

  try {
    return raw
      .toLowerCase()
      .normalize('NFKD')
      .replaceAll(/[^\p{L}\p{N}]+/gu, '-')
      .replaceAll(/-{2,}/g, '-')
      .replaceAll(/^-+|-+$/g, '')
  } catch {
    // Fallback for environments without unicode property escapes (very unlikely in modern browsers)
    return raw
      .toLowerCase()
      .replaceAll(/[^a-z0-9]+/g, '-')
      .replaceAll(/-{2,}/g, '-')
      .replaceAll(/^-+|-+$/g, '')
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
  options: { behavior?: ScrollBehavior; block?: ScrollLogicalPosition } = {}
): boolean {
  if (globalThis.window === undefined) return false
  const key = (id || '').replace(/^#/, '').trim()
  if (!key) return false

  const el = globalThis.window.document.getElementById(key)
  if (!el) return false

  const behavior = options.behavior ?? 'smooth'
  const block = options.block ?? 'start'
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
