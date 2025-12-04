export interface ParserBackendOption {
  value: string
  label: string
  description: string
}

export const PARSER_BACKEND_OPTIONS: ParserBackendOption[] = [
  {
    value: 'auto',
    label: '自动选择',
    description: '按优先级自动选择已启用的解析器',
  },
  {
    value: 'basic',
    label: '基础解析 (PyMuPDF)',
    description: '速度快、依赖少，适合纯文本 PDF',
  },
  {
    value: 'mineru',
    label: 'MinerU 高级解析',
    description: '依赖 MinerU 在线服务，擅长复杂排版',
  },
  {
    value: 'deepdoc',
    label: 'DeepDoc 结构化解析',
    description: '视觉 + OCR 识别，适合扫描件、图文混排',
  },
  {
    value: 'markitdown',
    label: 'MarkItDown Markdown 解析',
    description: '微软 MarkItDown，将多种格式转换成 Markdown',
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
