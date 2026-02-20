import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('KnowledgeWorkbenchActions', () => {
  it('provides a consolidated import entry point', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'knowledge-workbench-actions.tsx'), 'utf8')

    expect(src).toContain('export function KnowledgeWorkbenchActions')
    expect(src).toContain('DropdownMenu')
    expect(src).toContain('导入/新增')
  })
})

