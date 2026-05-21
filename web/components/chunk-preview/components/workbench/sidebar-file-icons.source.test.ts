import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('Chunk preview sidebar file icons', () => {
  it('maps common document formats to distinct visual icons', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'sidebar-client.tsx'), 'utf8')

    expect(src).toContain('function getFileVisual')
    expect(src).toContain("ext === 'pdf'")
    expect(src).toContain("['doc', 'docx', 'rtf']")
    expect(src).toContain("['xls', 'xlsx', 'csv', 'tsv']")
    expect(src).toContain("['md', 'markdown', 'txt']")
    expect(src).toContain('const FileVisualIcon = fileVisual.icon')
  })
})
