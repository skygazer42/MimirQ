import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('KnowledgeScopePanel empty folder hint', () => {
  it('renders the inactive folder area as a dashed hoverable affordance instead of flat body copy', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'knowledge-scope-panel.tsx'), 'utf8')

    expect(src).toContain("import { ChevronDown, Filter, FolderSearch } from 'lucide-react'")
    expect(src).toContain("group/empty rounded-2xl border border-dashed border-border/60")
    expect(src).toContain('hover:scale-[1.015]')
    expect(src).toContain("t('folder.pendingTitle')")
    expect(src).not.toContain('Pending Scope')
  })
})
