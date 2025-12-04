export interface ParserBackendOption {
  value: string
  label: string
  description: string
  icon: 'auto' | 'basic' | 'mineru' | 'deepdoc' | 'markitdown'
  badge?: string
}

export const PARSER_BACKEND_OPTIONS: ParserBackendOption[] = [
  {
    value: 'auto',
    label: '自动选择',
    description: '按优先级自动选择已启用的解析器',
    icon: 'auto',
    badge: '推荐',
  },
  {
    value: 'basic',
    label: '基础解析',
    description: 'PyMuPDF · 速度快、依赖少，适合纯文本 PDF',
    icon: 'basic',
  },
  {
    value: 'mineru',
    label: 'MinerU 高级解析',
    description: '依赖 MinerU 在线服务，擅长复杂排版',
    icon: 'mineru',
  },
  {
    value: 'deepdoc',
    label: 'DeepDoc 结构化',
    description: '视觉 + OCR 识别，适合扫描件、图文混排',
    icon: 'deepdoc',
    badge: 'OCR',
  },
  {
    value: 'markitdown',
    label: 'MarkItDown',
    description: '微软 MarkItDown，多种格式转 Markdown',
    icon: 'markitdown',
  },
]

export function getParserOption(value?: string) {
  return (
    PARSER_BACKEND_OPTIONS.find(
      (option) => option.value === (value || '').toLowerCase()
    ) || PARSER_BACKEND_OPTIONS[0]
  )
}

export function getParserLabel(value?: string) {
  return getParserOption(value).label
}
