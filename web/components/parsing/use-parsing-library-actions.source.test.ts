import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('useParsingLibraryActions source', () => {
  it('keeps restored queue runs aligned with remote normalized elements', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'use-parsing-library-actions.ts'), 'utf8')

    expect(src).toContain('elements: remote?.elements || libEntry.elements || []')
  })
})
