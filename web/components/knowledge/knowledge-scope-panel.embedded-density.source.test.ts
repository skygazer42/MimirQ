import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('KnowledgeScopePanel embedded density', () => {
  it('keeps the embedded rail compact while separating scope modules through lighter glass shells and tight gaps', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'knowledge-scope-panel.tsx'), 'utf8')

    expect(src).toContain("const sectionClassName = embedded ? 'space-y-2' : 'space-y-2'")
    expect(src).toContain("const sectionShellClassName = embedded")
    expect(src).toContain('border border-sky-100/80 bg-white/78')
    expect(src).toContain("cn('space-y-3', embedded && 'space-y-2.5 p-3')")
    expect(src).toContain('border-b border-sky-100/75 bg-white/62')
  })
})
