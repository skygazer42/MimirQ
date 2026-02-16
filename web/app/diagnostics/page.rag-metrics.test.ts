import fs from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'

describe('/diagnostics rag metrics', () => {
  it('includes a prompt-preview probe and token breakdown labels', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page.tsx'), 'utf8')
    expect(src).toContain('ragApi.promptPreview')
    expect(src).toContain('Prompt tokens')
    expect(src).toContain('Context tokens')
    expect(src).toContain('History tokens')
  })
})

