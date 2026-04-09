import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('KG snapshots page theme source', () => {
  it('uses shared background tokens instead of hardcoded off-white fills', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'kg-snapshots-page.tsx'), 'utf8')

    expect(src).toContain('bg-background')
    expect(src).not.toContain('bg-[#fffdfa]')
    expect(src).not.toContain('bg-[#fffcf6]')
  })
})
