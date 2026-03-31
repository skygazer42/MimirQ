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

  it('pins Monaco runtime assets to the local offline-safe project path', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'original-preview-monaco.tsx'), 'utf8')

    expect(src).toContain("import loader from '@monaco-editor/loader'")
    expect(src).toContain('loader.config({')
    expect(src).toContain("vs: '/monaco/vs'")
  })
})
