import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('prompts page prompt management surface', () => {
  it('keeps low-frequency Prompt/RAG operations off the prompt template page', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page.tsx'), 'utf8')

    expect(src).not.toContain("import { PromptRagOperationsPanel } from '@/components/prompts/prompt-rag-operations-panel'")
    expect(src).not.toContain('<PromptRagOperationsPanel')
    expect(src).toContain('<KgExtractPromptSettings templates={templates} />')
    expect(src).toContain('更新时间')
    expect(src).toContain('setPageSize(Number(value))')
    expect(src).toContain('条/页')
    expect(src).toContain('场景绑定')
  })
})
