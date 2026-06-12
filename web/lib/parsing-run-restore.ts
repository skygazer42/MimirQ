import { extractBlocksFromMarkdown, findPositionTagRanges, type ParsingBlock } from '@/lib/parsing-positions'

export type RestoredParsingRun = {
  cleanedMarkdown: string
  blocks: ParsingBlock[]
}

export function hasPositionTaggedMarkdown(markdown: string | null | undefined): boolean {
  const raw = (markdown || '').trim()
  if (!raw) return false
  return findPositionTagRanges(raw).length > 0
}

export function shouldRefreshParsingContentFromRemote(input: {
  fileType?: string | null
  originalMarkdownContent?: string | null
}): boolean {
  if (String(input.fileType || '').trim().toLowerCase() !== 'pdf') return false

  const original = String(input.originalMarkdownContent || '')
  if (original.includes('layout://image')) return true
  return !hasPositionTaggedMarkdown(original)
}

const MARKDOWN_IMAGE_REF_RE = /!\[([^\]]*)\]\(\s*(?:<)?([^)\s>]+)(?:>)?(?:\s+['"][^'"]*['"])?\s*\)/gi
const LAYOUT_IMAGE_REF_RE = /!\[([^\]]*)\]\(\s*(?:<)?layout:\/\/image(?:>)?(?:\s+['"][^'"]*['"])?\s*\)/gi

function extractMarkdownImageRefs(markdown: string): string[] {
  const refs: string[] = []
  MARKDOWN_IMAGE_REF_RE.lastIndex = 0
  let match = MARKDOWN_IMAGE_REF_RE.exec(markdown)
  while (match) {
    const ref = String(match[2] || '').trim()
    if (ref && ref !== 'layout://image') refs.push(ref)
    match = MARKDOWN_IMAGE_REF_RE.exec(markdown)
  }
  return refs
}

function hydrateLayoutImageRefs(rawMarkdown: string, cleanedMarkdown: string): string {
  if (!rawMarkdown.includes('layout://image')) return rawMarkdown

  const refs = extractMarkdownImageRefs(cleanedMarkdown)
  if (refs.length === 0) return rawMarkdown

  let index = 0
  return rawMarkdown.replace(LAYOUT_IMAGE_REF_RE, (whole, alt: string) => {
    const ref = refs[index]
    if (!ref) return whole
    index += 1
    return `![${String(alt || '').trim() || 'Image'}](${ref})`
  })
}

export function restoreParsingRunFromMarkdown(input: {
  rawMarkdown: string
  cleanedMarkdown?: string | null
}): RestoredParsingRun | null {
  const rawMarkdown = (input.rawMarkdown || '').trim()
  if (!rawMarkdown) return null
  const cleanedMarkdown = (input.cleanedMarkdown || '').trim()
  const hydratedRawMarkdown = hydrateLayoutImageRefs(rawMarkdown, cleanedMarkdown)

  const parsed = extractBlocksFromMarkdown(hydratedRawMarkdown)
  return {
    cleanedMarkdown: (cleanedMarkdown || parsed.cleanedMarkdown || '').trim(),
    blocks: parsed.blocks.filter((block) => (block.positions || []).length > 0),
  }
}
