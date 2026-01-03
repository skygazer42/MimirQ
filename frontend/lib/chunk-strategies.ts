export interface ChunkStrategyOption {
  value: string
  label: string
  description: string
  icon: 'recursive' | 'token' | 'sentence' | 'hierarchical' | 'ragflow' | 'separator'
  badge?: string
  group?: 'langchain' | 'llama_index' | 'ragflow'
  disabled?: boolean
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
    value: 'parent_child',
    label: 'Parent-Child 分层切分',
    description: '先父块再子块，保留 parent_id 方便层级展示与重排',
    icon: 'hierarchical',
    badge: '父子',
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
  {
    value: 'separator',
    label: '自定义分隔符切分',
    description: '按指定分隔符直接切分，适合结构化文档（类似 Dify）',
    icon: 'separator',
    badge: '自定义',
    group: 'langchain',
  },
  // LlamaIndex 系列
  {
    value: 'llama_index',
    label: 'LlamaIndex 句子切分',
    description: '基于句子边界的智能切分，保持语义完整性',
    icon: 'sentence',
    badge: 'LlamaIndex',
    group: 'llama_index',
  },
  {
    value: 'llama_index_hierarchical',
    label: 'LlamaIndex 分层切分',
    description: '多层级切分策略，适合复杂文档结构',
    icon: 'hierarchical',
    badge: '分层',
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
