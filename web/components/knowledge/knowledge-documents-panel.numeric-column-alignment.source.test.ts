import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('KnowledgeDocumentsPanel numeric column alignment', () => {
  it('aligns numeric headers with their right-aligned values for scannable B-end tables', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'knowledge-documents-panel.tsx'), 'utf8')

    expect(src).toContain("className=\"sticky top-0 z-10 bg-card/95 px-3 py-2.5 font-medium text-right tabular-nums\">{t('table.columns.chunks')}</th>")
    expect(src).toContain("className=\"sticky top-0 z-10 bg-card/95 px-3 py-2.5 font-medium text-right tabular-nums\">{t('table.columns.size')}</th>")
    expect(src).toContain('className="px-3 py-2.5 align-middle text-right text-xs font-mono tabular-nums text-muted-foreground"')
  })
})
