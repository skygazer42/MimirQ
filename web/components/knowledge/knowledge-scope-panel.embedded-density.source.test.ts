import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('KnowledgeScopePanel embedded density', () => {
  it('keeps the embedded rail compact while separating scope modules through lighter glass shells and tight gaps', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'knowledge-scope-panel.tsx'), 'utf8')

    expect(src).toContain("const sectionClassName = embedded ? 'space-y-3' : 'space-y-2'")
    expect(src).toContain("const sectionShellClassName = embedded")
    expect(src).toContain("rounded-2xl border border-border/40 bg-muted/10")
    expect(src).toContain("cn('space-y-4', embedded && 'space-y-3 p-3.5 lg:p-4')")
  })
})
