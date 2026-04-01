import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('parsing active file pane source', () => {
  it('keys the PDF viewer by active file, active run, and reset token so reopening a parsed PDF remounts a fresh preview instance', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'parsing-active-file-pane.tsx'), 'utf8')

    expect(src).toContain('pdfPreviewResetToken: number')
    expect(src).toContain("const pdfViewerKey = `${activeFile.id}:${activeFile.activeRunId || activeRun?.id || 'default'}:${pdfPreviewResetToken}`")
    expect(src).toContain('key={pdfViewerKey}')
  })
})
