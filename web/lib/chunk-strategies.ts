export interface ChunkStrategyOption {
  value: string
  label: string
  description: string
  icon: 'recursive' | 'token' | 'sentence' | 'hierarchical' | 'ragflow' | 'separator'
  badge?: string
  group?: 'preset' | 'langchain' | 'llama_index' | 'ragflow'
  disabled?: boolean
}

export const CHUNK_STRATEGY_OPTIONS: ChunkStrategyOption[] = [
  // Presets
  {
    value: 'auto',
    label: '自动选择（推荐）',
    description:
      '自动识别内容形态（Q&A/对话/论文/大纲/Markdown/JSON），选择合适的切块器。',
    icon: 'recursive',
    badge: '推荐',
    group: 'preset',
  },
  {
    value: 'manuscript',
    label: '文稿/讲稿（预设）',
    description:
      '面向文稿/讲稿/手稿/报告：优先按 Q&A / 对话 / 论文 / 大纲切块。',
    icon: 'hierarchical',
    badge: '文稿',
    group: 'preset',
  },
  {
    value: 'outline',
    label: '大纲/章节（预设）',
    description: '识别 1. / 1.1 / 第X章 等编号标题，按章节结构切块。',
    icon: 'hierarchical',
    badge: '大纲',
    group: 'preset',
  },
  {
    value: 'transcript',
    label: '访谈/会议纪要（预设）',
    description: '识别“张三：…”等说话人行，尽量保持完整发言轮次。',
    icon: 'sentence',
    badge: '对话',
    group: 'preset',
  },
  {
    value: 'qa_pairs',
    label: 'FAQ / Q&A（预设）',
    description: '识别 Q/A 或 问/答 标记，尽量保持每组问答不被拆散。',
    icon: 'sentence',
    badge: 'Q&A',
    group: 'preset',
  },
  {
    value: 'paper',
    label: '论文/报告（预设）',
    description: '识别摘要/引言/方法/结果/讨论/参考文献等常见章节并切块。',
    icon: 'hierarchical',
    badge: '论文',
    group: 'preset',
  },
  {
    value: 'book_structured',
    label: '书籍/长文档（预设）',
    description: '识别 Chapter/Part/Volume/第X章 等结构，按章节上下文切块。',
    icon: 'hierarchical',
    badge: '书籍',
    group: 'preset',
  },
  {
    value: 'laws_structured',
    label: '法律/合同/制度（预设）',
    description: '识别 第X条/（一）/Article 等条款结构，按条款切块。',
    icon: 'hierarchical',
    badge: '条款',
    group: 'preset',
  },
  {
    value: 'email_thread',
    label: '邮件线程（预设）',
    description: '识别 From/To/Subject/-----Original Message----- 等，按邮件消息切块。',
    icon: 'sentence',
    badge: '邮件',
    group: 'preset',
  },
  {
    value: 'sop_steps',
    label: 'SOP/操作步骤（预设）',
    description: '识别 Step 1/步骤一 等步骤标题，尽量保持步骤不被拆散。',
    icon: 'hierarchical',
    badge: 'SOP',
    group: 'preset',
  },
  {
    value: 'glossary',
    label: '术语表/词典（预设）',
    description: '识别“术语：定义”条目，按条目切块并保留术语列表。',
    icon: 'separator',
    badge: '术语',
    group: 'preset',
  },

  // LangChain / local strategies
  {
    value: 'langchain_recursive',
    label: 'LangChain 递归切分',
    description: '按分隔符（段落、句号等）递归切分，保留语义完整性。',
    icon: 'recursive',
    badge: '通用',
    group: 'langchain',
  },
  {
    value: 'semantic_sentence',
    label: '语义句子切分',
    description: '按句子边界聚合，减少断句（适合长文本）。',
    icon: 'sentence',
    badge: '句子',
    group: 'langchain',
  },
  {
    value: 'sentence_window',
    label: '句子窗口切分',
    description: '按句子窗口聚合，使用“按句子”重叠（避免 overlap 截断句子）。',
    icon: 'sentence',
    badge: '窗口',
    group: 'langchain',
  },
  {
    value: 'parent_child',
    label: 'Parent-Child 分层切分',
    description: '先父块再子块，保留 parent_id 便于层级展示与召回。',
    icon: 'hierarchical',
    badge: '父子',
    group: 'langchain',
  },
  {
    value: 'langchain_token',
    label: 'LangChain Token 切分',
    description: '按 Token 数量切分，适合控制 LLM 输入长度。',
    icon: 'token',
    badge: 'Token',
    group: 'langchain',
  },
  {
    value: 'separator',
    label: '自定义分隔符切分',
    description: '按指定分隔符直接切分，适合结构化/规则化文档。',
    icon: 'separator',
    badge: '自定义',
    group: 'langchain',
  },
  {
    value: 'markdown_header',
    label: 'Markdown 标题切分',
    description: '按 # / ## / ### 标题层级切分，保留标题上下文。',
    icon: 'hierarchical',
    badge: 'Markdown',
    group: 'langchain',
  },
  {
    value: 'markdown_aware',
    label: 'Markdown 感知切分',
    description: '针对 Markdown 结构优化（标题/列表/代码块）并保留字符位置。',
    icon: 'recursive',
    badge: 'Markdown',
    group: 'langchain',
  },
  {
    value: 'json',
    label: 'JSON 结构切分',
    description: '尽量按 JSON 结构拆分（数组元素/对象键），通常不使用 overlap。',
    icon: 'separator',
    badge: 'JSON',
    group: 'langchain',
  },
  {
    value: 'code',
    label: '代码切分',
    description: '按代码结构/语句块切分（适合多语言代码）。',
    icon: 'separator',
    badge: 'Code',
    group: 'langchain',
  },
  {
    value: 'smart_code',
    label: '智能代码切分（Python）',
    description: '基于 AST-like 结构切分 Python，减少函数/类被拆分。',
    icon: 'separator',
    badge: 'Python',
    group: 'langchain',
  },

  // LlamaIndex
  {
    value: 'llama_index',
    label: 'LlamaIndex 句子切分',
    description: '基于句子边界的智能切分，保持语义完整性。',
    icon: 'sentence',
    badge: 'LlamaIndex',
    group: 'llama_index',
  },
  {
    value: 'llama_index_hierarchical',
    label: 'LlamaIndex 分层切分',
    description: '多层级切分策略，适合复杂文档结构。',
    icon: 'hierarchical',
    badge: '分层',
    group: 'llama_index',
  },

  // RAGFlow (parse + chunk integrated)
  {
    value: 'ragflow_naive',
    label: 'RAGFlow 通用切分',
    description: 'RAGFlow 通用文档切分（集成解析+切块）。',
    icon: 'ragflow',
    badge: 'RAGFlow',
    group: 'ragflow',
  },
  {
    value: 'ragflow_book',
    label: 'RAGFlow 书籍切分',
    description: '针对书籍/长文档优化，尽量保留章节结构。',
    icon: 'ragflow',
    badge: '书籍',
    group: 'ragflow',
  },
  {
    value: 'ragflow_laws',
    label: 'RAGFlow 法律切分',
    description: '针对法律文档优化，尽量保留条款结构。',
    icon: 'ragflow',
    badge: '法律',
    group: 'ragflow',
  },
  {
    value: 'ragflow_email',
    label: 'RAGFlow 邮件切分',
    description: '针对邮件/通信优化，尽量保留引用结构。',
    icon: 'ragflow',
    badge: '邮件',
    group: 'ragflow',
  },
]

export function getChunkStrategyOption(value?: string) {
  const normalized = (value || '').toLowerCase()
  return (
    CHUNK_STRATEGY_OPTIONS.find((option) => option.value === normalized) ||
    CHUNK_STRATEGY_OPTIONS.find((option) => option.value === 'langchain_recursive') ||
    CHUNK_STRATEGY_OPTIONS[0]
  )
}

export function getChunkStrategyLabel(value?: string) {
  return getChunkStrategyOption(value).label
}

export function getStrategiesByGroup(group: string) {
  return CHUNK_STRATEGY_OPTIONS.filter((option) => option.group === group)
}
