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

  it('uses a crafted knowledge-shelf empty state instead of a generic blank panel', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'knowledge-documents-panel.tsx'), 'utf8')

    expect(src).toContain('data-knowledge-empty-shelf="true"')
    expect(src).toContain('知识货架待入库')
    expect(src).toContain('导入路径')
    expect(src).toContain('筛选路径')
    expect(src).toContain('质量路径')
    expect(src).toContain('bg-[radial-gradient(circle_at_50%_0%,rgba(59,130,246,0.16),transparent_46%)]')
    expect(src).not.toContain('<EmptyState')
  })
})
