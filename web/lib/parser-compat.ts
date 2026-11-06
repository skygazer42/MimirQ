type ParserResolveResult = {
  backend: string
  changed: boolean
  reason?: string
}

export function normalizeParserBackendName(value?: string): string {
  const raw = (value || '').trim().toLowerCase()
  if (!raw) return 'auto'
  const normalized = raw.replaceAll('_', '-')

  if (normalized === 'pymupdf' || normalized === 'fitz') return 'basic'
  if (normalized === 'magic-pdf') return 'magicpdf'
  if (normalized === 'deepseek-ocr' || normalized === 'deepseekocr') return 'deepseek_ocr'
  if (normalized === 'qianfan-ocr' || normalized === 'qianfanocr') return 'qianfan_ocr'
  if (normalized === 'textin-xparse' || normalized === 'textinxparse') return 'textin'
  if (normalized === 'etl-4llm') return 'etl4llm'
  if (normalized === 'pan-doc') return 'pandoc'
  if (normalized === 'marker-pdf') return 'marker'
  if (normalized === 'paddle-vl' || normalized === 'paddleocr-vl' || normalized === 'paddleocrvl') return 'paddle_vl'
  if (normalized === 'olm-ocr' || normalized === 'olmocr-pdf') return 'olmocr'
  if (normalized === 'bisheng-unstructured' || normalized === 'bishengunstructured' || normalized === 'bisheng')
    return 'etl4llm'

  return normalized
}

function fileExt(filename: string): string {
  const name = (filename || '').trim()
  const idx = name.lastIndexOf('.')
  if (idx <= 0 || idx === name.length - 1) return ''
  return name.slice(idx).toLowerCase()
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
  const rule = FORMAT_RULES[fileExt(filename)]
  // Unknown formats remain permissive because the backend owns their parser selection.
  if (!rule || rule.backends.has(backend)) return { backend, changed: false }
  return {
    backend: 'auto',
    changed: backend !== 'auto',
    reason: `backend '${backend}' is not supported for ${rule.format}`,
  }
}

export function resolveParserBackendForFiles(files: File[], requestedBackend?: string): ParserResolveResult {
  const normalized = normalizeParserBackendName(requestedBackend)
  let changed = false
  for (const file of files) {
    const resolved = resolveParserBackendForFilename(file?.name || '', normalized)
    if (resolved.backend !== normalized) {
      changed = true
      break
    }
  }
  if (!changed) return { backend: normalized, changed: false }
  return {
    backend: 'auto',
    changed: normalized !== 'auto',
    reason: 'batch upload contains mixed/unsupported file types',
  }
}
