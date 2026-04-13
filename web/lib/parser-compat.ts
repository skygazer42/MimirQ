type ParserResolveResult = {
  backend: string
  changed: boolean
  reason?: string
}

export function normalizeParserBackendName(value?: string): string {
  const raw = (value || '').trim().toLowerCase()
  if (!raw) return 'auto'
  const normalized = raw.replaceAll("_", '-')

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
  if (normalized === 'bisheng-unstructured' || normalized === 'bishengunstructured' || normalized === 'bisheng') return 'etl4llm'

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

export function resolveParserBackendForFilename(filename: string, requestedBackend?: string): ParserResolveResult {
  const backend = normalizeParserBackendName(requestedBackend)
  const ext = fileExt(filename)

  if (ext === '.pdf') {
    if (PDF_BACKENDS.has(backend)) return { backend, changed: false }
    return {
      backend: 'auto',
      changed: backend !== 'auto',
      reason: `backend '${backend}' is not supported for pdf`,
    }
  }

  if (ext === '.docx') {
    // Docx supports general converters and some "advanced" parsers (when enabled server-side).
    const allowed = new Set(['auto', 'markitdown', 'pandoc', 'docx', 'docling', 'deepdoc', 'textin'])
    if (allowed.has(backend)) return { backend, changed: false }
    return { backend: 'auto', changed: backend !== 'auto', reason: `backend '${backend}' is not supported for docx` }
  }

  if (ext === '.doc') {
    const allowed = new Set(['auto', 'markitdown', 'pandoc', 'textin'])
    if (allowed.has(backend)) return { backend, changed: false }
    return { backend: 'auto', changed: backend !== 'auto', reason: `backend '${backend}' is not supported for doc` }
  }

  if (ext === '.pptx') {
    const allowed = new Set(['auto', 'markitdown', 'pandoc', 'textin'])
    if (allowed.has(backend)) return { backend, changed: false }
    return { backend: 'auto', changed: backend !== 'auto', reason: `backend '${backend}' is not supported for pptx` }
  }

  if (ext === '.ppt') {
    const allowed = new Set(['auto', 'markitdown', 'pandoc', 'textin'])
    if (allowed.has(backend)) return { backend, changed: false }
    return { backend: 'auto', changed: backend !== 'auto', reason: `backend '${backend}' is not supported for ppt` }
  }

  if (ext === '.xlsx' || ext === '.xls') {
    const allowed = new Set(['auto', 'markitdown', 'pandoc', 'excel', 'textin'])
    if (allowed.has(backend)) return { backend, changed: false }
    return { backend: 'auto', changed: backend !== 'auto', reason: `backend '${backend}' is not supported for excel` }
  }

  if (ext === '.csv') {
    const allowed = new Set(['auto', 'markitdown', 'pandoc', 'csv', 'textin'])
    if (allowed.has(backend)) return { backend, changed: false }
    return { backend: 'auto', changed: backend !== 'auto', reason: `backend '${backend}' is not supported for csv` }
  }

  if (ext === '.html' || ext === '.htm') {
    const allowed = new Set(['auto', 'markitdown', 'pandoc', 'html', 'textin'])
    if (allowed.has(backend)) return { backend, changed: false }
    return { backend: 'auto', changed: backend !== 'auto', reason: `backend '${backend}' is not supported for html` }
  }

  if (ext === '.json') {
    const allowed = new Set(['auto', 'markitdown', 'pandoc', 'json', 'textin'])
    if (allowed.has(backend)) return { backend, changed: false }
    return { backend: 'auto', changed: backend !== 'auto', reason: `backend '${backend}' is not supported for json` }
  }

  if (ext === '.md') {
    const allowed = new Set(['auto'])
    if (allowed.has(backend)) return { backend, changed: false }
    return { backend: 'auto', changed: backend !== 'auto', reason: `backend '${backend}' is not supported for markdown` }
  }

  if (ext === '.txt') {
    const allowed = new Set(['auto'])
    if (allowed.has(backend)) return { backend, changed: false }
    return { backend: 'auto', changed: backend !== 'auto', reason: `backend '${backend}' is not supported for text` }
  }

  // Text-like/unknown formats: backend is ignored or auto-selected server-side; keep it permissive.
  return { backend, changed: false }
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
  return { backend: 'auto', changed: normalized !== 'auto', reason: 'batch upload contains mixed/unsupported file types' }
}
