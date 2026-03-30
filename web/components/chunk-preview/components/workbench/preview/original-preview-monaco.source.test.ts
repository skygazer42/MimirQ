import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('original preview monaco source', () => {
  it('uses a branded loading fallback while Monaco is still streaming in', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'original-preview-monaco.tsx'), 'utf8')

    expect(src).toContain("useTranslations('ChunkPreview')")
    expect(src).toContain("t('originalPreview.monaco.loadingMessage')")
    expect(src).toContain("t('originalPreview.monaco.loadingSrMessage')")
    expect(src).toContain('PageLoading')
    expect(src).toContain('dynamic(() => import(\'@monaco-editor/react\')')
  })
})
