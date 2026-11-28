// Source contract check only; this is not behavior coverage.
import fs from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'

describe('navbar active route indicator', () => {
  it('keeps the selected destination accessible without decorative gradients', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'navbar.tsx'), 'utf8')
    expect(src).toContain("aria-current={isActive ? 'page' : undefined}")
    expect(src).not.toContain('before:bg-[linear-gradient(180deg,hsl(var(--info)),hsl(var(--primary)))]')
    expect(src).not.toContain('bg-[linear-gradient')
  })
})
