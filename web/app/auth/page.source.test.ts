import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('auth page visual source', () => {
  it('keeps the auth shell on the same flat ruled boundary baseline', () => {
    const source = fs.readFileSync(path.resolve(__dirname, 'page.tsx'), 'utf8')

    expect(source).toContain('data-auth-panel="ruled"')
    expect(source).toContain('data-auth-mode-switch="true"')
    expect(source).toContain('rounded-lg border border-foreground/15 bg-background')
    expect(source).toContain('rounded-md border border-foreground/10 bg-background')
    expect(source).not.toContain('rounded-3xl')
    expect(source).not.toContain('shadow-strong')
    expect(source).not.toContain('hover:bg-[#CAF0F8]/55')
  })
})
