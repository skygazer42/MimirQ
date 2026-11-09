export type MarkdownSourceRange = Readonly<{ start: number; end: number }>

type SourceNode = {
  type?: string
  tagName?: string
  position?: { start?: { offset?: number }; end?: { offset?: number } }
  properties?: Record<string, unknown>
  children?: SourceNode[]
}

const SOURCE_BLOCKS = new Set(['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p', 'pre', 'tr'])

// Run after sanitizing. Positions come from the Markdown parser, never from HTML attributes.
export function rehypeSourceRange({ range }: { range?: MarkdownSourceRange | null }) {
  return (tree: SourceNode) => {
    if (!range || range.end <= range.start) return
    const selected: SourceNode[] = []
    const visit = (node: SourceNode) => {
      const start = node.position?.start?.offset
      const end = node.position?.end?.offset
      if (node.tagName && SOURCE_BLOCKS.has(node.tagName) && start != null && end != null && start < range.end && end > range.start) {
        node.properties = { ...node.properties, 'data-source-selected': 'true' }
        selected.push(node)
      }
      node.children?.forEach(visit)
    }
    visit(tree)
    if (selected.length) {
      selected[0].properties!['data-source-selection-start'] = 'true'
      selected[selected.length - 1].properties!['data-source-selection-end'] = 'true'
    }
  }
}
