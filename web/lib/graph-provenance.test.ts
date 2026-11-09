import { describe, expect, it } from 'vitest'

import { buildGraphLinkProvenanceTooltipHtml } from './graph-provenance'

describe('graph provenance tooltip', () => {
  it('keeps external metadata escaped while mapping recognized link kinds directly', () => {
    const html = buildGraphLinkProvenanceTooltipHtml({ source: 'source', target: 'target', meta: { kind: 'entity_relation', predicate: '<script>bad</script>', confidence: 0.5 } })

    expect(html).toContain('Relation (triple)')
    expect(html).toContain('&lt;script&gt;bad&lt;/script&gt;')
    expect(html).toContain('0.500')
    expect(html).not.toContain('<script>')
    expect(buildGraphLinkProvenanceTooltipHtml({ meta: { kind: '__proto__' } })).toContain('Link (__proto__)')
    expect(buildGraphLinkProvenanceTooltipHtml(null)).toBe('')
  })
})
