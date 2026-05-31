export const RERANKER_PROVIDER_OPTIONS = [
  { key: 'llm', label: '大模型重排' },
  { key: 'cross_encoder', label: '交叉编码器' },
  { key: 'local_bge_v2_m3', label: '本地 BGE 重排' },
  { key: 'long_context', label: '长上下文重排' },
  { key: 'ltr', label: '学习排序模型' },
  { key: 'colbert', label: 'ColBERT 后交互' },
  { key: 'pc', label: '父子片段重排' },
  { key: 'weighted', label: '加权重排' },
  { key: 'mmr', label: '多样性重排' },
  { key: 'kg_pagerank', label: '图谱 PageRank' },
  { key: 'kg_rrf', label: '图谱 RRF' },
  { key: 'openai', label: 'OpenAI 兼容重排' },
  { key: 'dashscope', label: '通义千问重排' },
  { key: 'none', label: '不使用重排' },
] as const

function primitiveProviderString(value: unknown): string {
  if (typeof value === 'string') return value
  if (typeof value === 'number' || typeof value === 'boolean' || typeof value === 'bigint') {
    return String(value)
  }
  return ''
}

export function normalizeRerankerProvider(value: unknown): string {
  const provider = primitiveProviderString(value).trim().toLowerCase().replaceAll('-', '_')
  if (!provider) return 'llm'
  if (provider === 'parent_child') return 'pc'
  if (provider === 'bge_v2_m3') return 'local_bge_v2_m3'
  if (provider === 'xgboost_ltr') return 'ltr'
  if (
    provider === 'sentence_transformers' ||
    provider === 'sentence_transformer'
  ) {
    return 'cross_encoder'
  }
  if (provider === 'off' || provider === 'false' || provider === '0') {
    return 'none'
  }
  return RERANKER_PROVIDER_OPTIONS.some((option) => option.key === provider)
    ? provider
    : 'llm'
}
