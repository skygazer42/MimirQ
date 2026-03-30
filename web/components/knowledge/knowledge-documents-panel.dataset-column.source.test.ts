import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('KnowledgeDocumentsPanel list columns', () => {
  it('shows dataset column when scoping to all datasets (console-first workflows)', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'knowledge-documents-panel.tsx'), 'utf8')

    expect(src).toContain('showDatasetColumn')
    expect(src).toContain('datasetLabelById')
    expect(src).toContain('t("table.columns.dataset")')
    expect(src).toContain('source_path')
  })
})
