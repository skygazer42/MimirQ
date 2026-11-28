import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { GraphLinkDetailPanel } from './graph-link-detail-panel'

function renderEvidence(meta: Record<string, unknown>) {
  return renderToStaticMarkup(
    <GraphLinkDetailPanel
      open
      selectedLink={{ source: 'source', target: 'target', meta }}
      graphLinks={[]}
      selfLoopGroupExpanded={false}
      onToggleSelfLoopGroup={() => {}}
      onClose={() => {}}
    />,
  )
}

describe('relationship evidence', () => {
  it('shows the supplied fact as a quotation and preserves its source identifiers', () => {
    const html = renderEvidence({ fact: '架构设计包含技术选型与系统边界。', document_id: 'document-42' })
    expect(html).toContain('<blockquote')
    expect(html).toContain('架构设计包含技术选型与系统边界。')
    expect(html).toContain('document-42')
  })

  it('does not invent a quotation when the relationship has no evidence text', () => {
    expect(renderEvidence({ confidence: 0.93 })).not.toContain('<blockquote')
  })
})
