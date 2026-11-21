import { extractBlocksFromMarkdown, findPositionTagRanges, type ParsingBlock } from '@/lib/parsing-positions'

type RestoredParsingRun = {
  cleanedMarkdown: string
  blocks: ParsingBlock[]
}

export function shouldRefreshParsingContentFromRemote(input: {
  fileType?: string | null
  originalMarkdownContent?: string | null
}): boolean {
  if (input.fileType?.trim().toLowerCase() !== 'pdf') return false
  const markdown = input.originalMarkdownContent
  return markdown == null || markdown.includes('layout://image') || findPositionTagRanges(markdown).length === 0
}

const MARKDOWN_IMAGE_REF_RE = /!\[([^\]]*)\]\(\s*(?:<)?([^)\s>]+)(?:>)?(?:\s+['"][^'"]*['"])?\s*\)/gi
const LAYOUT_IMAGE_REF_RE = /!\[([^\]]*)\]\(\s*(?:<)?layout:\/\/image(?:>)?(?:\s+['"][^'"]*['"])?\s*\)/gi

function extractMarkdownImageRefs(markdown: string): string[] {
  const refs: string[] = []
  for (const [, , ref] of markdown.matchAll(MARKDOWN_IMAGE_REF_RE)) {
    if (ref !== 'layout://image') refs.push(ref)
  }
  return refs
}

function hydrateLayoutImageRefs(rawMarkdown: string, cleanedMarkdown: string | null | undefined): string {
  if (!rawMarkdown.includes('layout://image') || cleanedMarkdown === null || cleanedMarkdown === undefined)
    return rawMarkdown

  const refs = extractMarkdownImageRefs(cleanedMarkdown)
  if (refs.length === 0) return rawMarkdown

  let index = 0
  return rawMarkdown.replace(LAYOUT_IMAGE_REF_RE, (whole, alt: string) => {
    const ref = refs[index]
    if (ref === undefined) return whole
    index += 1
    return `![${alt}](${ref})`
  })
}

export function restoreParsingRunFromMarkdown(input: {
  rawMarkdown: string
  cleanedMarkdown?: string | null
}): RestoredParsingRun {
  const hydratedRawMarkdown = hydrateLayoutImageRefs(input.rawMarkdown, input.cleanedMarkdown)

  const parsed = extractBlocksFromMarkdown(hydratedRawMarkdown)
  return {
    cleanedMarkdown: input.cleanedMarkdown ?? parsed.cleanedMarkdown,
    blocks: parsed.blocks.filter((block) => block.positions.length > 0),
  }
}
