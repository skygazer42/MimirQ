import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('workbench barrel', () => {
  it('exists as a stable import surface for workbench primitives', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'index.ts'), 'utf8')
    expect(src).toContain('Workbench')
  })
})
