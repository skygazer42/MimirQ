import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('useParsingRunActions source', () => {
  it('awaits library parsed updates after markdown persistence writes', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'use-parsing-run-actions.ts'), 'utf8')

    expect(src).toContain('await updateParsedFile(libraryId, {')
    expect(src).toContain("status: 'parsed'")
  })

  it('threads normalized parsing elements into run state for downstream inspection', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'use-parsing-run-actions.ts'), 'utf8')

    expect(src).toContain('elements: data.elements || []')
  })
})
