import { extractBlocksFromMarkdown, type ParsingBlock } from '@/lib/parsing-positions'

export type RestoredParsingRun = {
  cleanedMarkdown: string
  blocks: ParsingBlock[]
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
