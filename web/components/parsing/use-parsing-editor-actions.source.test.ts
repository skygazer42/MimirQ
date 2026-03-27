import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('useParsingEditorActions source', () => {
  it('awaits parsed library updates when saving edited markdown', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'use-parsing-editor-actions.ts'), 'utf8')

    expect(src).toContain('await updateParsedFile(libId, {')
    expect(src).toContain("status: 'parsed'")
  })
})
