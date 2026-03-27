import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('chunks toolbar panel source', () => {
  it('surfaces vim-style chunk navigation hints next to the search controls', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'chunks-toolbar-panel.tsx'), 'utf8')

    expect(src).toContain('j / k')
    expect(src).toContain('聚焦搜索')
  })
})
