import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('KnowledgeDocumentsPanel list table column sizing', () => {
  it('uses explicit column widths so dense metadata columns stop stealing space from the name column', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'knowledge-documents-panel.tsx'), 'utf8')

    expect(src).toContain('table-fixed')
    expect(src).toContain('<colgroup>')
    expect(src).toContain('<col className="w-10" />')
    expect(src).toContain('{showDatasetColumn ? <col className="w-[11rem]" /> : null}')
    expect(src).toContain('<col className="w-[7.5rem]" />')
    expect(src).toContain('<col className="w-[7rem]" />')
    expect(src).toContain('<col className="w-[5rem]" />')
    expect(src).toContain('<col className="w-[7rem]" />')
    expect(src).toContain('<col className="w-[9rem]" />')
    expect(src).toContain('<col className="w-[5.5rem]" />')
  })
})
