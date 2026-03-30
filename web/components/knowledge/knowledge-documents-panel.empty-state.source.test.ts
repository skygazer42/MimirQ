import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('KnowledgeDocumentsPanel empty states', () => {
  it('offers an escape hatch to widen scope when a dataset is empty', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'knowledge-documents-panel.tsx'), 'utf8')

    expect(src).toContain('onSwitchToAllDatasets')
    expect(src).toContain("useTranslations('KnowledgeDocumentsPanel')")
    expect(src).toContain('t("empty.emptyDataset.actions.switchToAllDatasets")')
    expect(src).toContain('t("empty.emptyDataset.description", {')
  })
})
