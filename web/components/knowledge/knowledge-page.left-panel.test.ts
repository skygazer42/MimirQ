import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('KnowledgePage workbench side slots', () => {
  it('keeps WorkbenchScaffold side slots dormant so the shared surface owns the layout', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'knowledge-page.tsx'), 'utf8')

    expect(src).toContain('leftPanel={null}')
    expect(src).toContain('rightPanel={null}')
  })
})
