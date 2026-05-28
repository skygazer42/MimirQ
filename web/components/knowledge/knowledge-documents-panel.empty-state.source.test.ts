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
    expect(src).toContain('aria-label="查看入库指引"')
    expect(src).toContain('<DropdownMenuTrigger asChild>')
    expect(src).toContain('align="end"')
    expect(src).toContain('导入路径')
    expect(src).toContain('筛选路径')
    expect(src).toContain('质量路径')
    expect(src).toContain('data-knowledge-empty-shelf-dock="integrated-canvas"')
    expect(src).toContain('flex min-h-0 flex-1 px-2 pb-2 pt-1.5')
    expect(src).toContain('relative flex min-h-[clamp(220px,30vh,320px)] w-full flex-1 overflow-hidden')
    expect(src).toContain('relative mx-auto flex h-full max-w-5xl flex-col items-center justify-center px-4 py-8 text-center')
    expect(src).not.toContain('flex min-h-0 flex-1 items-end px-2 pb-2 pt-1.5')
    expect(src).not.toContain('mt-7 grid w-full gap-3 md:grid-cols-3')
    expect(src).not.toContain('px-2 py-1.5')
    expect(src).not.toContain('relative flex min-h-[272px] w-full flex-1 overflow-hidden')
    expect(src).not.toContain('relative flex min-h-[360px] w-full flex-1 overflow-hidden')
    expect(src).toContain('bg-[radial-gradient(circle_at_50%_0%,rgba(59,130,246,0.12),transparent_44%)]')
    expect(src).not.toContain('<EmptyState')
  })
})
