export interface ChunkStrategyOption {
  value: string
  label: string
  description: string
}

export const CHUNK_STRATEGY_OPTIONS: ChunkStrategyOption[] = [
  {
    value: 'langchain_recursive',
    label: 'LangChain Recursive',
    description: '基于 RecursiveCharacterTextSplitter，按分隔符递归切分文本。',
  },
  {
    value: 'llama_index',
    label: 'LlamaIndex Sentence Splitter',
    description: '使用 LlamaIndex SentenceSplitter，按句子语义切片，可处理多语言。',
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
