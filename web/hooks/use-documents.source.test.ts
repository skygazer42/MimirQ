import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('use-documents source', () => {
  it('uses extracted sub-hooks for document list reads, polling, uploads, and actions', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'use-documents.ts'), 'utf8')
    const lineCount = src.split('\n').length

    expect(src).toContain("from './use-document-list'")
    expect(src).toContain("from './use-document-polling'")
    expect(src).toContain("from './use-document-upload'")
    expect(src).toContain("from './use-document-actions'")
    expect(src).toContain('const listState = useDocumentList(')
    expect(src).toContain('const polling = useDocumentPolling(')
    expect(src).toContain('const uploadState = useDocumentUpload(')
    expect(src).toContain('const actionState = useDocumentActions(')
    expect(lineCount).toBeLessThanOrEqual(220)
  })

  it.each([
    'use-document-list.ts',
    'use-document-polling.ts',
    'use-document-upload.ts',
    'use-document-actions.ts',
  ])('keeps %s alongside the main hook', (fileName) => {
    const absolutePath = path.resolve(__dirname, fileName)

    expect(fs.existsSync(absolutePath)).toBe(true)
  })
})
