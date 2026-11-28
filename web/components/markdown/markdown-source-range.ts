import type rehypeSanitize from 'rehype-sanitize'

export type MarkdownSourceRange = Readonly<{ start: number; end: number }>

type SanitizedTree = ReturnType<ReturnType<typeof rehypeSanitize>>
type SourceElement = Extract<SanitizedTree['children'][number], { type: 'element' }>

const SOURCE_BLOCKS = new Set(['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p', 'pre', 'tr'])

// Run after sanitizing. Positions come from the Markdown parser, never from HTML attributes.
export function rehypeSourceRange({ range }: { range?: MarkdownSourceRange | null }) {
  return (tree: SanitizedTree) => {
    if (range == null || range.end <= range.start) return
    const { start: rangeStart, end: rangeEnd } = range
    let lastSelected: SourceElement | undefined

    function visit(children: SanitizedTree['children']) {
      for (const node of children) {
        if (node.type !== 'element') continue
        const start = node.position?.start.offset
        const end = node.position?.end.offset
        if (
          SOURCE_BLOCKS.has(node.tagName) &&
          start !== undefined &&
          end !== undefined &&
          start < rangeEnd &&
          end > rangeStart
        ) {
          node.properties = { ...node.properties, 'data-source-selected': 'true' }
          if (lastSelected === undefined) node.properties['data-source-selection-start'] = 'true'
          lastSelected = node
        }
        visit(node.children)
      }
    }

    visit(tree.children)
    if (lastSelected !== undefined) {
      lastSelected.properties['data-source-selection-end'] = 'true'
    }
  }
}
