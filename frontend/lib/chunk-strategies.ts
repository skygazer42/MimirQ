export interface ChunkStrategyOption {
  value: string
  label: string
  description: string
  icon: 'recursive' | 'token' | 'sentence' | 'hierarchical' | 'ragflow'
  badge?: string
  group?: 'langchain' | 'llama_index' | 'ragflow'
}

export const CHUNK_STRATEGY_OPTIONS: ChunkStrategyOption[] = [
  // LangChain 系列
  {
    value: 'langchain_recursive',
    label: 'LangChain 递归切分',
    description: '按分隔符（段落、句号等）递归切分，保留语义完整性',
    icon: 'recursive',
    badge: '推荐',
    group: 'langchain',
  },
  {
    value: 'langchain_token',
    label: 'LangChain Token 切分',
    description: '按 Token 数量切分，适合控制 LLM 输入长度（GPT-4 编码）',
    icon: 'token',
    badge: 'Token',
    group: 'langchain',
  },
  // LlamaIndex 系列
  {
    value: 'llama_index',
    label: 'LlamaIndex 句子切分',
    description: '按句子语义切片，支持多语言，保留句子边界',
    icon: 'sentence',
    group: 'llama_index',
  },
  {
    value: 'llama_index_hierarchical',
    label: 'LlamaIndex 分层切分',
    description: '父子块多级切分，保留 parent 关系，适合 AutoMerging 检索',
    icon: 'hierarchical',
    badge: '父子块',
    group: 'llama_index',
  },
  // RAGFlow 系列
  {
    value: 'ragflow_naive',
    label: 'RAGFlow 通用切分',
    description: '通用文档切分，适合大多数文档类型',
    icon: 'ragflow',
    badge: 'RAGFlow',
    group: 'ragflow',
  },
  {
    value: 'ragflow_book',
    label: 'RAGFlow 书籍切分',
    description: '针对书籍/长文档优化，保留章节结构',
    icon: 'ragflow',
    badge: '书籍',
    group: 'ragflow',
  },
  {
    value: 'ragflow_laws',
    label: 'RAGFlow 法律切分',
    description: '针对法律文档优化，保留条款结构',
    icon: 'ragflow',
    badge: '法律',
    group: 'ragflow',
  },
  {
    value: 'ragflow_email',
    label: 'RAGFlow 邮件切分',
    description: '针对邮件/通信优化，保留引用结构',
    icon: 'ragflow',
    badge: '邮件',
    group: 'ragflow',
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

export function getStrategiesByGroup(group: string) {
  return CHUNK_STRATEGY_OPTIONS.filter((option) => option.group === group)
}
