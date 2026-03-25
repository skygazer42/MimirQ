import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('retrieval ablations page source', () => {
  it('avoids any-based diff score helpers', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'retrieval-ablations-page.tsx'), 'utf8')

    expect(src).not.toContain(': any')
    expect(src).not.toContain('as any')
    expect(src).not.toContain('Record<string, any>')
  })
})
