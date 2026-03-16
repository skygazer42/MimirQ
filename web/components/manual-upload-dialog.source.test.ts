import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('manual upload dialog source', () => {
  it('merges utils imports and extracts render helpers for upload and preview states', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'manual-upload-dialog.tsx'), 'utf8')

    expect(src).toContain("import { cn, formatFileSize } from '@/lib/utils'")
    expect(src.match(/from '@\/lib\/utils'/g)).toHaveLength(1)
    expect(src).not.toContain('{(() => {')
    expect(src).toContain('<span>源文档</span>')
    expect(src).toContain('<span>切片策略</span>')
    expect(src).toContain('<span>入库管线</span>')
    expect(src).toContain('function renderUploadState(')
    expect(src).toContain('function renderPreviewState(')
  })
})
