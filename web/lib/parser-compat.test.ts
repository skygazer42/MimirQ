import { describe, expect, it } from 'vitest'

import { resolveParserBackendForFilename, resolveParserBackendForFiles } from './parser-compat'

describe('retired parser selections', () => {
  it.each([
    ['colpali', 'colpali'],
    ['col-pali', 'col-pali'],
    ['col_pali', 'col-pali'],
    ['colqwen', 'colqwen'],
    ['col-qwen', 'col-qwen'],
    ['col_qwen', 'col-qwen'],
    [' ColPali ', 'colpali'],
  ])('preserves %s for explicit API rejection across file formats', (requested, backend) => {
    for (const filename of ['report.pdf', 'report.docx', 'notes.txt', 'image.png']) {
      expect(resolveParserBackendForFilename(filename, requested)).toEqual({ backend, changed: false })
    }
  })

  it('preserves a retired parser when a batch contains incompatible file formats', () => {
    const files = [new File(['source'], 'report.pdf'), new File(['source'], 'notes.txt')]

    expect(resolveParserBackendForFiles(files, 'col_qwen')).toEqual({ backend: 'col-qwen', changed: false })
  })

  it('still selects auto for a supported parser used with an incompatible file format', () => {
    expect(resolveParserBackendForFilename('report.docx', 'marker')).toEqual({
      backend: 'auto',
      changed: true,
      reason: "backend 'marker' is not supported for docx",
    })
  })
})
