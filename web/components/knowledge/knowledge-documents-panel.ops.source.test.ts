import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('KnowledgeDocumentsPanel document operations', () => {
  it('mounts explicit document advanced operations', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'knowledge-documents-panel.tsx'), 'utf8')

    expect(src).toContain("import { DocumentOperationsPanel } from '@/components/documents/document-operations-panel'")
    expect(src).toContain('<DocumentOperationsPanel')
  })

  it('passes dataset options into document advanced operations for bound selections', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'knowledge-documents-panel.tsx'), 'utf8')

    expect(src).toContain('datasets?: Dataset[]')
    expect(src).toContain('datasets={datasets}')
  })

  it('keeps document operations behind an inventory toolbar disclosure', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'knowledge-documents-panel.tsx'), 'utf8')

    expect(src).toContain("const [opsOpen, setOpsOpen] = useState(false)")
    expect(src).toContain('aria-expanded={opsOpen}')
    expect(src).toContain("setOpsOpen((open) => !open)")
    expect(src).toContain('运维工具')
    expect(src).toContain('{opsOpen ? (')
  })
})
