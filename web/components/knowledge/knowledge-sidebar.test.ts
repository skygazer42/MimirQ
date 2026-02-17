import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('KnowledgeSidebar', () => {
  it('exports KnowledgeSidebar', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'knowledge-sidebar.tsx'), 'utf8')
    expect(src).toContain('export function KnowledgeSidebar')
  })
})

