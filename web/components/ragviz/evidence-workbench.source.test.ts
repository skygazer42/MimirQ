import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('evidence workbench source', () => {
  it('uses glass panel shells and surface-first citation cards', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'evidence-workbench.tsx'), 'utf8')

    expect(src).toContain('variant="glass" className="p-4"')
    expect(src).toContain('variant="glass" className="p-4 lg:col-span-1"')
    expect(src).toContain('variant="glass" className="p-4 lg:col-span-2"')
    expect(src).toContain('bg-warning/10 border-warning/20 text-warning')
    expect(src).toContain('rounded-xl border border-sidebar-border/70 bg-sidebar/55 px-3 py-3 shadow-soft backdrop-blur-sm')
    expect(src).toContain('border border-sidebar-border/70 bg-sidebar/40 shadow-soft/70')
  })
})
