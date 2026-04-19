import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

function read(relativePath: string) {
  return fs.readFileSync(path.resolve(__dirname, '..', relativePath), 'utf8')
}

describe('Knowledge workspace numeric typography', () => {
  it('uses mono tabular treatment for dynamic numeric values across the main knowledge workbench surfaces', () => {
    const statsCardSrc = read('ui/stats-card.tsx')
    const docsPanelSrc = read('knowledge/knowledge-documents-panel.tsx')
    const knowledgePageSrc = read('knowledge/knowledge-page.tsx')
    const settingsPanelSrc = read('knowledge/knowledge-settings-panel.tsx')
    const scopePanelSrc = read('knowledge/knowledge-scope-panel.tsx')

    expect(statsCardSrc).toContain('font-mono tabular-nums')
    expect(docsPanelSrc).toContain('font-mono tabular-nums')
    expect(docsPanelSrc).toContain("title={`解析质量: ${qualityPercent}%`}")
    expect(knowledgePageSrc).toContain('<span className="font-mono tabular-nums">{activeTasksCount}</span>')
    expect(settingsPanelSrc).toContain("{t('connectorRuns.metrics.created')} <span className=\"font-mono tabular-nums\">{created}</span>")
    expect(settingsPanelSrc).toContain("className={cn('font-mono tabular-nums', failed > 0 && 'text-destructive')}")
    expect(settingsPanelSrc).toContain('<span className="font-mono tabular-nums">')
    expect(scopePanelSrc).toContain('font-mono tabular-nums text-[11px]')
  })
})
