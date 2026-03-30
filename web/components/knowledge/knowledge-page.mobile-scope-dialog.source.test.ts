import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('KnowledgePage mobile scope dialog', () => {
  it('uses WorkbenchPanelDialog to expose KnowledgeScopePanel on small screens', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'knowledge-page.tsx'), 'utf8')

    expect(src).toContain('WorkbenchPanelDialog')
    expect(src).toContain("title={t('dialogs.scope.title')}")
    expect(src).toContain('<KnowledgeScopePanel')
    expect(src).toContain('lg:hidden')
  })
})
