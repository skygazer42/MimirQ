import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('chunk editor dialog source', () => {
  it('supports boundary correction fields and bounded post-save actions', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'chunk-editor-dialog.tsx'), 'utf8')

    expect(src).toContain('startChar')
    expect(src).toContain('endChar')
    expect(src).toContain('Start Char')
    expect(src).toContain('End Char')
    expect(src).toContain('保存并重新嵌入')
    expect(src).toContain('保存后复跑检索')
  })
})
