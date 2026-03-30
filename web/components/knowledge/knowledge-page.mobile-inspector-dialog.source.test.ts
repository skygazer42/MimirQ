import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('KnowledgePage mobile inspector dialog', () => {
  it('uses WorkbenchPanelDialog to expose KnowledgeInspector on small screens', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'knowledge-page.tsx'), 'utf8')

    expect(src).toContain('WorkbenchPanelDialog')
    expect(src).toContain("title={t('dialogs.inspector.title')}")
    expect(src).toContain('<KnowledgeInspector')
    expect(src).toContain('xl:hidden')
  })
})
