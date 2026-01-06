export type MarkdownHeading = {
  level: number
  text: string
  id: string
  line: number
}

function stripInlineMarkdown(text: string): string {
  let out = text || ''

  // Images: ![alt](url) -> alt
  out = out.replace(/!\[([^\]]*)\]\([^)]+\)/g, '$1')
  // Links: [text](url) -> text
  out = out.replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
  // Inline code: `code` -> code
  out = out.replace(/`([^`]+)`/g, '$1')
  // Emphasis markers: ** / __ / * / _
  out = out.replace(/(\*\*|__|\*|_)/g, '')
  // HTML tags
  out = out.replace(/<[^>]+>/g, '')

  return out.trim()
}

export function slugifyHeading(text: string): string {
  const raw = stripInlineMarkdown(text)
  if (!raw) return ''

  try {
    return raw
      .toLowerCase()
      .normalize('NFKD')
      .replace(/[^\p{L}\p{N}]+/gu, '-')
      .replace(/-{2,}/g, '-')
      .replace(/^-+|-+$/g, '')
  } catch {
    // Fallback for environments without unicode property escapes (very unlikely in modern browsers)
    return raw
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/-{2,}/g, '-')
      .replace(/^-+|-+$/g, '')
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

    // Code fences: ``` / ~~~
    const fenceMatch = trimmed.match(/^(```+|~~~+)\s*/)
    if (fenceMatch) {
      const token = fenceMatch[1]
      if (!inCodeFence) {
        inCodeFence = true
        fenceToken = token.startsWith('```') ? '```' : '~~~'
      } else if (fenceToken && token.startsWith(fenceToken)) {
        inCodeFence = false
        fenceToken = null
      }
      continue
    }
    if (inCodeFence) continue

    const m = line.match(/^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$/)
    if (!m) continue

    const level = m[1].length
    if (level < 1 || level > Math.min(6, maxDepth)) continue

    const headingText = stripInlineMarkdown(m[2])
    const base = slugifyHeading(headingText) || `section-${headings.length + 1}`

    const prev = seen.get(base) || 0
    const nextCount = prev + 1
    seen.set(base, nextCount)
    const id = nextCount === 1 ? base : `${base}-${nextCount}`

    headings.push({
      level,
      text: headingText || m[2].trim(),
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
  if (typeof window === 'undefined') return false
  const key = (id || '').replace(/^#/, '').trim()
  if (!key) return false

  const el = window.document.getElementById(key)
  if (!el) return false

  const behavior = options.behavior ?? 'smooth'
  const block = options.block ?? 'start'
  el.scrollIntoView({ behavior, block })
  return true
}

export function flashElementId(id: string, className: string, durationMs = 900): void {
  if (typeof window === 'undefined') return
  const key = (id || '').replace(/^#/, '').trim()
  if (!key) return
  const el = window.document.getElementById(key)
  if (!el) return

  el.classList.add(...className.split(/\s+/g).filter(Boolean))
  window.setTimeout(() => {
    el.classList.remove(...className.split(/\s+/g).filter(Boolean))
  }, Math.max(0, Number(durationMs) || 0))
}

