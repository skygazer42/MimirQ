import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('KnowledgePage workbench left panel', () => {
  it('provides a leftPanel slot to WorkbenchScaffold', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'knowledge-page.tsx'), 'utf8')
    expect(src).toContain('leftPanel=')
  })
})

