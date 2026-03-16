import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('dataset category multi select source', () => {
  it('does not keep a conditional that returns the same screen-reader class on both branches', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'category-multi-select.tsx'), 'utf8')

    expect(src).not.toContain("loading ? 'sr-only' : 'sr-only'")
    expect(src).toContain('<span className="sr-only">刷新</span>')
  })
})
