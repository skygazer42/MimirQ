import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('Knowledge file-type helpers', () => {
  it('exports getFileTypeMeta and avoids gradient styling', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'file-type.ts'), 'utf8')
    expect(src).toContain('export function getFileTypeMeta')
    expect(src).not.toMatch(/\bgradient\b/)
  })
})

