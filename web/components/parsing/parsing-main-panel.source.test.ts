import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('ParsingMainPanel module', () => {
  it('exists and ensures the work surface can shrink', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'parsing-main-panel.tsx'), 'utf8')
    expect(src).toContain('export function ParsingMainPanel')
    expect(src).toContain('min-w-0')
    expect(src).toContain('min-h-0')
  })
})

