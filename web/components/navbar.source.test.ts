import fs from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'

describe('navbar source', () => {
  it('skips dev route prefetch in automated browsers', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'navbar.tsx'), 'utf8')

    expect(src).toContain("if (globalThis.navigator?.webdriver) return")
    expect(src).toContain('router.prefetch(href)')
  })
})
