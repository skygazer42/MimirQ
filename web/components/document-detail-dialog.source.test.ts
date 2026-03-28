import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('document detail dialog source', () => {
  it('extracts versions and access dialogs into dedicated submodules', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'document-detail-dialog.tsx'), 'utf8')

    expect(src).toContain("from '@/components/document-detail-dialog/document-access-dialog'")
    expect(src).toContain("from '@/components/document-detail-dialog/document-versions-dialog'")
    expect(src).toContain('<DocumentVersionsDialog')
    expect(src).toContain('<DocumentAccessDialog')
    expect(fs.existsSync(path.resolve(__dirname, 'document-detail-dialog/document-access-dialog.tsx'))).toBe(true)
    expect(fs.existsSync(path.resolve(__dirname, 'document-detail-dialog/document-versions-dialog.tsx'))).toBe(true)
  })
})
