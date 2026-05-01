import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('PromptRagOperationsPanel source', () => {
  it('exposes prompt, retrieval, image RAG and RAG config template APIs', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'prompt-rag-operations-panel.tsx'), 'utf8')

    for (const api of [
      'promptTemplateApi.get',
      'promptTemplateApi.createVersion',
      'ragApi.indexClipImages',
      'ragApi.searchClipImages',
      'ragApi.promptPreview',
      'retrievalApi.listProfiles',
      'retrievalApi.explain',
      'retrievalApi.configHash',
      'ragConfigTemplateApi.create',
      'ragConfigTemplateApi.list',
      'ragConfigTemplateApi.get',
      'ragConfigTemplateApi.update',
      'ragConfigTemplateApi.createVersion',
    ]) {
      expect(src).toContain(api)
    }
  })
})
