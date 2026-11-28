import type { DatasetPrecheckEmbeddingAdvisory } from '@/types'

export type PrecheckEmbeddingAdvisoryView = {
  code: string
  title: string
  description: string
  effectiveEmbedding: string | null
  recommendedAction: string | null
  recommendedModelIds: string[]
}

function normalizeAdvisoryText(value: unknown): string | null {
  if (typeof value !== 'string') return null
  const text = value.trim()
  return text === '' ? null : text
}

export function normalizePrecheckEmbeddingAdvisories(
  advisories: DatasetPrecheckEmbeddingAdvisory[] | null | undefined,
): PrecheckEmbeddingAdvisoryView[] {
  if (!Array.isArray(advisories)) return []

  return advisories.map((advisory) => {
    const code = normalizeAdvisoryText(advisory?.code) ?? 'unknown'
    const effectiveEmbedding = normalizeAdvisoryText(advisory?.effective_embedding)
    const recommendedAction = normalizeAdvisoryText(advisory?.recommended_action)
    const recommendedModelIds: string[] = []
    if (Array.isArray(advisory?.recommended_model_ids)) {
      for (const value of advisory.recommended_model_ids) {
        const modelId = normalizeAdvisoryText(value)
        if (modelId !== null) recommendedModelIds.push(modelId)
      }
    }

    const title =
      code === 'zh_or_mixed_corpus_uses_generic_embedding' ? '检测到中文或混合语料仍在使用通用向量模型' : '向量模型建议'

    const description = recommendedAction ?? '这是预检阶段给出的建议，不代表系统已经自动切换向量模型。'

    return {
      code,
      title,
      description,
      effectiveEmbedding,
      recommendedAction,
      recommendedModelIds,
    }
  })
}
