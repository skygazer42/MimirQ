import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('KnowledgeDocumentsPanel document health wiring', () => {
  it('exposes the health card entry point and parse-quality warning affordance', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'knowledge-documents-panel.tsx'), 'utf8')

    expect(src).toContain('/knowledge/${doc.id}/health')
    expect(src).toContain('t("row.parseQualityLow", {')
  })
})
