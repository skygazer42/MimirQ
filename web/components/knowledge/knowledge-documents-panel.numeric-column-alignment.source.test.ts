import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('KnowledgeDocumentsPanel numeric column alignment', () => {
  it('aligns numeric headers with their right-aligned values for scannable B-end tables', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'knowledge-documents-panel.tsx'), 'utf8')

    expect(src).toContain("<div className=\"text-right tabular-nums\">{t('table.columns.chunks')}</div>")
    expect(src).toContain("<div className=\"text-right tabular-nums\">{t('table.columns.size')}</div>")
    expect(src).toContain('className="text-right font-mono text-[11px] tabular-nums text-foreground/70"')
    expect(src).toContain('className="text-right font-mono text-[11px] tabular-nums text-muted-foreground"')
  })
})
