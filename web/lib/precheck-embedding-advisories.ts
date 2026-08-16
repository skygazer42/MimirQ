import type { DatasetPrecheckEmbeddingAdvisory } from '@/types'

export type PrecheckEmbeddingAdvisoryView = {
  code: string
  title: string
  description: string
  effectiveEmbedding: string | null
  recommendedAction: string | null
  recommendedModelIds: string[]
}

function toText(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value.trim() : null
}

export function normalizePrecheckEmbeddingAdvisories(
  advisories: DatasetPrecheckEmbeddingAdvisory[] | null | undefined
): PrecheckEmbeddingAdvisoryView[] {
  if (!Array.isArray(advisories)) return []

  return advisories
    .map((advisory) => {
      const code = toText(advisory?.code) || 'unknown'
      const effectiveEmbedding = toText(advisory?.effective_embedding)
      const recommendedAction = toText(advisory?.recommended_action)
      const recommendedModelIds = Array.isArray(advisory?.recommended_model_ids)
        ? advisory.recommended_model_ids
            .filter((item): item is string => typeof item === 'string')
            .map((item) => item.trim())
            .filter(Boolean)
        : []

      const title =
        code === 'zh_or_mixed_corpus_uses_generic_embedding'
          ? '检测到中文或混合语料仍在使用通用向量模型'
          : `Embedding advisory: ${code}`

      const description =
        recommendedAction ||
        '这是预检阶段给出的建议，不代表系统已经自动切换向量模型。'

      return {
        code,
        title,
        description,
        effectiveEmbedding,
        recommendedAction,
        recommendedModelIds,
      }
    })
    .filter((item) => Boolean(item.code))
}
