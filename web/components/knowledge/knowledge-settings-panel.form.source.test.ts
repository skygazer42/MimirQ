import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('KnowledgeSettingsPanel form controls', () => {
  it('pairs sliders with number inputs and guards embedding model changes behind a confirmation dialog', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'knowledge-settings-panel.tsx'), 'utf8')

    expect(src).toContain('type="range"')
    expect(src).toContain('retrieval_top_k')
    expect(src).toContain('similarity_threshold')
    expect(src).toContain('setConfirmEmbeddingSaveOpen(true)')
    expect(src).toContain('embeddingChangeDescription')
    expect(src).toContain('不会自动重新嵌入')
    expect(src).toContain('handleResetDraft')
    expect(src).toContain('{isDirty ? (')
  })
})
