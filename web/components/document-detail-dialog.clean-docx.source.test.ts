import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('document detail clean DOCX integration', () => {
  it('exposes the clean DOCX backend download on document detail', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'document-detail-dialog.tsx'), 'utf8')

    expect(src).toContain('documentApi.cleanDocx')
    expect(src).toContain('下载清洗 DOCX')
  })
})
