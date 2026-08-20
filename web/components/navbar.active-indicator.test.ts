// Source contract check only; this is not behavior coverage.
import fs from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'

describe('navbar active route indicator', () => {
  it('uses one semantic info rail without mixing in the primary color', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'navbar.tsx'), 'utf8')
    expect(src).toContain('before:bg-info')
    expect(src).not.toContain('before:bg-[linear-gradient(180deg,hsl(var(--info)),hsl(var(--primary)))]')
    expect(src).not.toContain('bg-[linear-gradient')
  })
})
