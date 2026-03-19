import fs from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'

describe('/diagnostics embedding drift', () => {
  it('includes embedding drift snapshot probe UI', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page.tsx'), 'utf8')
    expect(src).toContain('getEmbeddingDriftSnapshot')
    expect(src).toContain('Embedding drift')
  })
})

