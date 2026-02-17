import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('ParsingRightPanel module', () => {
  it('exists and provides an internal scroll container', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'parsing-right-panel.tsx'), 'utf8')
    expect(src).toContain('export function ParsingRightPanel')
    expect(src).toContain('data-page-scroll-container="true"')
    expect(src).toContain('overflow-y-auto')
  })
})

