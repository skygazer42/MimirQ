import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('prompts page RAG config productized surface', () => {
  it('mounts RAG configuration and retrieval operations beside prompt templates', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page.tsx'), 'utf8')

    expect(src).toContain("import { PromptRagOperationsPanel } from '@/components/prompts/prompt-rag-operations-panel'")
    expect(src).toContain('<PromptRagOperationsPanel')
  })
})
