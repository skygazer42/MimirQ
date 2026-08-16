import { describe, expect, it } from 'vitest'

import { normalizePrecheckEmbeddingAdvisories } from './precheck-embedding-advisories'

describe('normalizePrecheckEmbeddingAdvisories', () => {
  it('turns backend advisories into explicit warning copy without implying an automatic switch', () => {
    const advisories = normalizePrecheckEmbeddingAdvisories([
      {
        code: 'zh_or_mixed_corpus_uses_generic_embedding',
        effective_embedding: 'text-embedding-3-small',
        recommended_action: '建议评估中文或多语言 embedding',
        recommended_model_ids: ['text-embedding-v4', 'bge-large-zh'],
      },
    ])

    expect(advisories).toEqual([
      {
        code: 'zh_or_mixed_corpus_uses_generic_embedding',
        title: '检测到中文或混合语料仍在使用通用向量模型',
        description: '建议评估中文或多语言 embedding',
        effectiveEmbedding: 'text-embedding-3-small',
        recommendedAction: '建议评估中文或多语言 embedding',
        recommendedModelIds: ['text-embedding-v4', 'bge-large-zh'],
      },
    ])
  })
})
