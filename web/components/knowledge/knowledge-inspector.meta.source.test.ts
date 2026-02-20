import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('KnowledgeInspector metadata', () => {
  it('uses file-type meta helpers for consistent icon/badge rendering', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'knowledge-inspector.tsx'), 'utf8')

    expect(src).toContain('getFileTypeMeta')
    expect(src).toContain('fileType.label')
  })
})

