export interface ChunkStrategyOption {
  value: string
  label: string
  description: string
  icon: 'recursive' | 'token' | 'sentence'
  badge?: string
}

export const CHUNK_STRATEGY_OPTIONS: ChunkStrategyOption[] = [
  {
    value: 'langchain_recursive',
    label: 'LangChain 递归切分',
    description: '按分隔符（段落、句号等）递归切分，保留语义完整性',
    icon: 'recursive',
    badge: '推荐',
  },
  {
    value: 'langchain_token',
    label: 'LangChain Token 切分',
    description: '按 Token 数量切分，适合控制 LLM 输入长度（GPT-4 编码）',
    icon: 'token',
    badge: 'Token',
  },
  {
    value: 'llama_index',
    label: 'LlamaIndex 句子切分',
    description: '按句子语义切片，支持多语言，保留句子边界',
    icon: 'sentence',
  },
]

export function getChunkStrategyOption(value?: string) {
  return (
    CHUNK_STRATEGY_OPTIONS.find(
      (option) => option.value === (value || '').toLowerCase()
    ) || CHUNK_STRATEGY_OPTIONS[0]
  )
}

export function getChunkStrategyLabel(value?: string) {
  return getChunkStrategyOption(value).label
}
