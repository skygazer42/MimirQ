import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('KnowledgePage dense documents layout', () => {
  it('keeps documents and retrieval in a dense workbench layout while allowing the desktop scope rail to collapse', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'knowledge-page.tsx'), 'utf8')

    expect(src).toContain('const [desktopScopeCollapsed, setDesktopScopeCollapsed] = useState(false)')
    expect(src).toContain('leftPanel={!desktopScopeCollapsed ? (')
    expect(src).toContain('rightPanel={(activeTab === \'retrieval\' || peekingDocId || showTaskCenter) ? (')
    expect(src).toContain('setDesktopScopeCollapsed((prev) => !prev)')
  })
})
