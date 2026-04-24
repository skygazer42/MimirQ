import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('KnowledgePage workbench side slots', () => {
  it('uses WorkbenchScaffold side slots for the colored scope and inspector rails', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'knowledge-page.tsx'), 'utf8')

    expect(src).toContain('leftPanel={!desktopScopeCollapsed ? (')
    expect(src).toContain('rightPanel={(activeTab === \'retrieval\' || peekingDocId || showTaskCenter) ? (')
  })
})
