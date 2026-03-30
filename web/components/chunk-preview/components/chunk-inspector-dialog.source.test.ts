import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('chunk inspector dialog source', () => {
  it('routes chunk inspector labels and validation copy through next-intl', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'chunk-inspector-dialog.tsx'), 'utf8')

    expect(src).toContain("useTranslations('ChunkPreview')")
    expect(src).toContain("t('chunkInspector.title')")
    expect(src).toContain("t('chunkInspector.documentFallback')")
    expect(src).toContain('chunkInspector.chunkLabel')
    expect(src).toContain("t('chunkInspector.sectionLabel')")
    expect(src).toContain("t('chunkInspector.description')")
    expect(src).toContain('chunkInspector.editedAt')
    expect(src).toContain("t('chunkInspector.contentLabel')")
    expect(src).toContain("t('chunkInspector.metadataLabel')")
    expect(src).toContain("t('chunkInspector.metadataOk')")
    expect(src).toContain("t('chunkInspector.metadataObjectError')")
    expect(src).toContain("t('chunkInspector.metadataParseError')")
    expect(src).toContain("t('chunkInspector.embeddingLabel')")
    expect(src).toContain("t('chunkInspector.prefixOn')")
    expect(src).toContain("t('chunkInspector.prefixOff')")
    expect(src).toContain("t('chunkInspector.copyEmbedding')")
    expect(src).toContain("t('chunkInspector.embeddingHint')")
    expect(src).toContain("t('chunkInspector.reset')")
    expect(src).toContain("t('chunkInspector.save')")
  })
})
