import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('KnowledgeDocumentsPanel list table column sizing', () => {
  it('uses explicit column widths so dense metadata columns stop stealing space from the name column', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'knowledge-documents-panel.tsx'), 'utf8')

    expect(src).toContain('table-fixed')
    expect(src).toContain('<colgroup>')
    expect(src).toContain('<col className="w-9" />')
    expect(src).toContain('{showDatasetColumn ? <col className="w-[10rem]" /> : null}')
    expect(src).toContain('<col className="w-[6.5rem]" />')
    expect(src).toContain('<col className="w-[6rem]" />')
    expect(src).toContain('<col className="w-[4.5rem]" />')
    expect(src).toContain('<col className="w-[8.5rem]" />')
  })
})
