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
  return String(input.fileType || '').trim().toLowerCase() === 'pdf' &&
    !hasPositionTaggedMarkdown(input.originalMarkdownContent)
}

export function restoreParsingRunFromMarkdown(input: {
  rawMarkdown: string
  cleanedMarkdown?: string | null
}): RestoredParsingRun | null {
  const rawMarkdown = (input.rawMarkdown || '').trim()
  if (!rawMarkdown) return null

  const parsed = extractBlocksFromMarkdown(rawMarkdown)
  return {
    cleanedMarkdown: (input.cleanedMarkdown || parsed.cleanedMarkdown || '').trim(),
    blocks: parsed.blocks.filter((block) => (block.positions || []).length > 0),
  }
}
