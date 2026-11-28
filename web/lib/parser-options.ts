import { isRetiredParserBackend, normalizeParserBackendName } from './parser-compat'

export type ParserBackendOption = {
  value: string
  label: string
  description: string
  icon: 'auto' | 'basic' | 'layout' | 'mineru' | 'deepdoc' | 'deepseekocr' | 'markitdown' | 'docling' | 'magicpdf'
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
    value: 'docling',
    label: 'Docling 结构化',
    description: 'Docling · 结构感知解析，适合高质量 PDF（可提取结构/表格）',
    icon: 'docling',
    badge: '结构化',
  },
  {
    value: 'marker',
    label: 'Marker（启发式）',
    description: 'Marker · 启发式服务 PDF→Markdown（可含图片引用）',
    icon: 'layout',
    badge: '启发式',
  },
  {
    value: 'etl4llm',
    label: 'ETL4LLM 版面解析',
    description: 'etl4llm · 版面/表格/图片感知（需自建服务）',
    icon: 'layout',
    badge: '版面',
  },
  {
    value: 'paddle_vl',
    label: 'PaddleOCR-VL（外部）',
    description: 'PaddleOCR-VL · 外部 OCR/版面解析，适合扫描件 PDF',
    icon: 'deepdoc',
    badge: '外部',
  },
  {
    value: 'textin',
    label: 'TextIn xParse（外部 API）',
    description: 'TextIn xParse · 文档解析 API，适合 PDF / Office / 图片等转 Markdown',
    icon: 'mineru',
    badge: 'API',
  },
  {
    value: 'olmocr',
    label: 'olmOCR（外部）',
    description: 'olmOCR · OCR 转 Markdown，适合扫描件/图片型 PDF（需自建服务/GPU）',
    icon: 'deepdoc',
    badge: 'OCR',
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
    value: 'deepseek_ocr',
    label: 'DeepSeek OCR',
    description: 'SiliconFlow DeepSeek-OCR · OCR 转 Markdown，适合扫描件 PDF',
    icon: 'deepseekocr',
    badge: 'OCR',
  },
  {
    value: 'qianfan_ocr',
    label: 'Qianfan-OCR（外部）',
    description: 'Qianfan-OCR · 端到端文档解析（支持 Layout-as-Thought，需自建服务）',
    icon: 'deepseekocr',
    badge: 'OCR',
  },
  {
    value: 'markitdown',
    label: 'MarkItDown',
    description: '微软 MarkItDown，多种格式转 Markdown',
    icon: 'markitdown',
  },
  {
    value: 'magicpdf',
    label: 'MagicPDF',
    description: 'magic-pdf · 高级 PDF 解析，优先使用已配置的服务',
    icon: 'magicpdf',
  },
]

const ADDITIONAL_PARSER_BACKEND_REGISTRY_OPTIONS: ParserBackendOption[] = [
  {
    value: 'pandoc',
    label: 'pandoc（Office/HTML）',
    description: 'Pandoc · 通用文档格式转换，适合 Office / HTML 类内容',
    icon: 'markitdown',
  },
  {
    value: 'excel',
    label: 'excel（.xls/.xlsx）',
    description: 'ExcelParser · 面向电子表格文件的解析后端',
    icon: 'markitdown',
  },
  {
    value: 'docx',
    label: 'docx（.docx）',
    description: 'DOCXParser · 面向 Word 文档的解析后端',
    icon: 'markitdown',
  },
  {
    value: 'pptx',
    label: 'pptx（.pptx）',
    description: 'PPTXParser · 面向 PowerPoint 的解析后端',
    icon: 'markitdown',
  },
  {
    value: 'html',
    label: 'html（.html/.htm）',
    description: 'HTMLParser · 面向 HTML 内容的解析后端',
    icon: 'markitdown',
  },
  {
    value: 'csv',
    label: 'csv（.csv）',
    description: 'CsvParser · 面向 CSV 内容的解析后端',
    icon: 'markitdown',
  },
  {
    value: 'json',
    label: 'json（.json）',
    description: 'JsonParser · 面向 JSON / JSONL 内容的解析后端',
    icon: 'markitdown',
  },
  {
    value: 'text',
    label: 'text（纯文本）',
    description: 'TextParser · 面向纯文本内容的解析后端',
    icon: 'basic',
  },
  {
    value: 'markdown',
    label: 'markdown（.md）',
    description: 'MarkdownParser · 面向 Markdown 内容的解析后端',
    icon: 'markitdown',
  },
]

export const PARSER_BACKEND_REGISTRY_OPTIONS: ParserBackendOption[] = [
  ...PARSER_BACKEND_OPTIONS,
  ...ADDITIONAL_PARSER_BACKEND_REGISTRY_OPTIONS,
]

export function getParserOption(value?: string): ParserBackendOption {
  const backend = normalizeParserBackendName(value)
  if (isRetiredParserBackend(backend)) {
    return {
      value: backend,
      label: `${backend}（已移除）`,
      description: '请选择其他解析器。',
      icon: 'basic',
    }
  }
  const option = PARSER_BACKEND_REGISTRY_OPTIONS.find((item) => item.value === backend)
  if (option !== undefined) return option
  return {
    value: backend,
    label: backend,
    description: '当前解析器不在选项列表中。',
    icon: 'basic',
  }
}

export function getParserLabel(value?: string) {
  const label = value?.trim()
  if (label === undefined || label.length === 0) return 'Auto'

  const backend = normalizeParserBackendName(label)
  const option = PARSER_BACKEND_REGISTRY_OPTIONS.find((option) => option.value === backend)
  return option?.label ?? label
}
