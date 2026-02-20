import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('Chunk preview workbench shrink-safety', () => {
  it('marks the main surface as shrink-safe (min-w-0, min-h-0)', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'index.tsx'), 'utf8')

    expect(src).toContain('min-w-0')
    expect(src).toContain('min-h-0')
  })
})

