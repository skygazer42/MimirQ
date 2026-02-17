import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('ParsingLeftPanel module', () => {
  it('exists and avoids h-screen', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'parsing-left-panel.tsx'), 'utf8')
    expect(src).toContain('export function ParsingLeftPanel')
    expect(src).not.toContain('h-screen')
  })
})

