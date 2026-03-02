import { describe, expect, it } from 'vitest'

import { buildGraphLinkProvenanceTooltipHtml } from './graph-provenance'

describe('buildGraphLinkProvenanceTooltipHtml', () => {
  it('renders a compact, HTML-escaped tooltip for entity relations', () => {
    const html = buildGraphLinkProvenanceTooltipHtml({
      source: { id: 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee', label: 'Alice <Admin>' },
      target: { id: 'ffffffff-1111-2222-3333-444444444444', label: 'Bob & Co' },
      label: 'owns<script>alert(1)</script>',
      weight: 0.87654,
      meta: {
        kind: 'entity_relation',
        predicate: 'owns<script>alert(1)</script>',
        confidence: 0.87654,
        document_id: '11111111-2222-3333-4444-555555555555',
        chunk_id: '66666666-7777-8888-9999-000000000000',
        event_id: 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
      },
    })

    expect(html).toContain('Relation (triple)')
    expect(html).toContain('confidence')

    // Ensure we don't emit raw HTML from untrusted fields.
    expect(html).not.toContain('<script>')
    expect(html).toContain('&lt;Admin&gt;')
    expect(html).toContain('Bob &amp; Co')
  })
})

