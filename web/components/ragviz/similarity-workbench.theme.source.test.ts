import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('similarity workbench theme source', () => {
  it('keeps active view controls on theme accents instead of black', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'similarity-workbench.tsx'), 'utf8')

    expect(src).toContain('bg-info text-primary-foreground hover:bg-info/90')
    expect(src).toContain('border-info bg-info text-primary-foreground')
    expect(src).not.toContain('bg-slate-950 text-info-foreground hover:bg-slate-900')
    expect(src).not.toContain('border-slate-950 bg-slate-950 text-info-foreground')
  })
})
