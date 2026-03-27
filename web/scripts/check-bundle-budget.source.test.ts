import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('bundle budget guard wiring', () => {
  it('exposes explicit local and CI bundle-check commands', () => {
    const pkg = JSON.parse(fs.readFileSync(path.resolve(__dirname, '..', 'package.json'), 'utf8')) as {
      scripts?: Record<string, string>
    }

    expect(pkg.scripts?.['bundle-check']).toBe('node scripts/check-bundle-budget.mjs')
    expect(pkg.scripts?.['bundle-check:ci']).toContain('pnpm run build')
  })

  it('guards the remaining heavy route entry bundles called out in optimization plans', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'check-bundle-budget.mjs'), 'utf8')

    expect(src).toContain("id: 'chunk-preview-route'")
    expect(src).toContain("re: /^app\\/chunk-preview\\/page-.*\\.js$/")
    expect(src).toContain("id: 'knowledge-similarity-route'")
    expect(src).toContain("re: /^app\\/knowledge\\/similarity\\/page-.*\\.js$/")
  })
})
