type ParserResolveResult = {
  backend: string
  changed: boolean
  reason?: string
}

const PARSER_BACKEND_ALIASES = new Map([
  ['pymupdf', 'basic'],
  ['fitz', 'basic'],
  ['magic-pdf', 'magicpdf'],
  ['deepseek-ocr', 'deepseek_ocr'],
  ['deepseekocr', 'deepseek_ocr'],
  ['qianfan-ocr', 'qianfan_ocr'],
  ['qianfanocr', 'qianfan_ocr'],
  ['textin-xparse', 'textin'],
  ['textinxparse', 'textin'],
  ['etl-4llm', 'etl4llm'],
  ['pan-doc', 'pandoc'],
  ['marker-pdf', 'marker'],
  ['paddle-vl', 'paddle_vl'],
  ['paddleocr-vl', 'paddle_vl'],
  ['paddleocrvl', 'paddle_vl'],
  ['olm-ocr', 'olmocr'],
  ['olmocr-pdf', 'olmocr'],
  ['bisheng-unstructured', 'etl4llm'],
  ['bishengunstructured', 'etl4llm'],
  ['bisheng', 'etl4llm'],
])

export function normalizeParserBackendName(value?: string): string {
  const raw = value?.trim().toLowerCase()
  if (raw === undefined || raw.length === 0) return 'auto'
  const normalized = raw.replaceAll('_', '-')

  return PARSER_BACKEND_ALIASES.get(normalized) ?? normalized
}

function fileExt(filename: string): string {
  const name = filename.trim()
  const extensionStart = name.lastIndexOf('.')
  if (extensionStart <= 0 || extensionStart === name.length - 1) return ''
  return name.slice(extensionStart).toLowerCase()
}

const PDF_BACKENDS = new Set([
  'auto',
  'basic',
  'marker',
  'paddle_vl',
  'olmocr',
  'mineru',
  'deepdoc',
  'deepseek_ocr',
  'qianfan_ocr',
  'textin',
  'etl4llm',
  'markitdown',
  'docling',
  'magicpdf',
])

const CONVERTER_BACKENDS = new Set(['auto', 'markitdown', 'pandoc', 'textin'])
const TEXT_BACKENDS = new Set(['auto'])
const RETIRED_PARSER_BACKENDS = new Set(['colpali', 'col-pali', 'colqwen', 'col-qwen'])

export function isRetiredParserBackend(normalizedBackend: string) {
  return RETIRED_PARSER_BACKENDS.has(normalizedBackend)
}

const FORMAT_RULES: Record<string, { format: string; backends: ReadonlySet<string> }> = {
  '.pdf': { format: 'pdf', backends: PDF_BACKENDS },
  '.docx': {
    format: 'docx',
    backends: new Set(['auto', 'markitdown', 'pandoc', 'docx', 'docling', 'deepdoc', 'textin']),
  },
  '.doc': { format: 'doc', backends: CONVERTER_BACKENDS },
  '.pptx': { format: 'pptx', backends: CONVERTER_BACKENDS },
  '.ppt': { format: 'ppt', backends: CONVERTER_BACKENDS },
  '.xlsx': { format: 'excel', backends: new Set(['auto', 'markitdown', 'pandoc', 'excel', 'textin']) },
  '.xls': { format: 'excel', backends: new Set(['auto', 'markitdown', 'pandoc', 'excel', 'textin']) },
  '.csv': { format: 'csv', backends: new Set(['auto', 'markitdown', 'pandoc', 'csv', 'textin']) },
  '.html': { format: 'html', backends: new Set(['auto', 'markitdown', 'pandoc', 'html', 'textin']) },
  '.htm': { format: 'html', backends: new Set(['auto', 'markitdown', 'pandoc', 'html', 'textin']) },
  '.json': { format: 'json', backends: new Set(['auto', 'markitdown', 'pandoc', 'json', 'textin']) },
  '.md': { format: 'markdown', backends: TEXT_BACKENDS },
  '.txt': { format: 'text', backends: TEXT_BACKENDS },
}

export function resolveParserBackendForFilename(filename: string, requestedBackend?: string): ParserResolveResult {
  const backend = normalizeParserBackendName(requestedBackend)
  // Preserve retired selections so the API can report their retirement explicitly.
  if (isRetiredParserBackend(backend)) return { backend, changed: false }
  const rule = FORMAT_RULES[fileExt(filename)]
  // Unknown formats remain permissive because the backend owns their parser selection.
  if (!rule || rule.backends.has(backend)) return { backend, changed: false }
  return {
    backend: 'auto',
    changed: backend !== 'auto',
    reason: `backend '${backend}' is not supported for ${rule.format}`,
  }
}

export function resolveParserBackendForFiles(files: readonly File[], requestedBackend?: string): ParserResolveResult {
  const normalized = normalizeParserBackendName(requestedBackend)
  for (const file of files) {
    const resolved = resolveParserBackendForFilename(file.name, normalized)
    if (resolved.changed) {
      return { backend: 'auto', changed: true, reason: 'batch upload contains mixed/unsupported file types' }
    }
  }

  return { backend: normalized, changed: false }
}
