import { describe, expect, it } from 'vitest'

import { normalizeParserBackendName, resolveParserBackendForFilename } from './parser-compat'

describe('parser-compat', () => {
  it('normalizes parser backend aliases consistently', () => {
    expect(normalizeParserBackendName('magic-pdf')).toBe('magicpdf')
    expect(normalizeParserBackendName('etl-4llm')).toBe('etl4llm')
    expect(normalizeParserBackendName('bisheng-unstructured')).toBe('etl4llm')
    expect(normalizeParserBackendName('olm-ocr')).toBe('olmocr')
    expect(normalizeParserBackendName('olmocr-pdf')).toBe('olmocr')
    expect(normalizeParserBackendName('textin-xparse')).toBe('textin')
    expect(normalizeParserBackendName('')).toBe('auto')
  })

  it('applies the normalized backend names when resolving file support', () => {
    expect(resolveParserBackendForFilename('example.pdf', 'magic-pdf')).toEqual({
      backend: 'magicpdf',
      changed: false,
    })
    expect(resolveParserBackendForFilename('example.pdf', 'olm-ocr')).toEqual({
      backend: 'olmocr',
      changed: false,
    })
    expect(resolveParserBackendForFilename('example.docx', 'textin-xparse')).toEqual({
      backend: 'textin',
      changed: false,
    })
  })
})
