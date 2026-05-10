import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

function read(relativePath: string): string {
  return fs.readFileSync(path.resolve(__dirname, relativePath), 'utf8')
}

describe('document viewer download actions', () => {
  it('does not render href placeholders when the backend has not returned a download URL', () => {
    const header = read('./document-viewer-header.tsx')
    const preview = read('./preview-tab-panel.tsx')

    expect(header).not.toContain('downloadUrl || "#"')
    expect(preview).not.toContain('downloadUrl || "#"')
    expect(header).toContain('downloadUrl ? (')
    expect(preview).toContain('downloadUrl ? (')
  })
})
