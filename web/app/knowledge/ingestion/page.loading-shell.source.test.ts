import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('knowledge ingestion loading shell', () => {
  it('renders the branded PageLoading fallback message', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page.tsx'), 'utf8')

    expect(src).toContain("useTranslations('KnowledgeIngestionPage')")
    expect(src).toContain("t('loadingMessage')")
    expect(src).toContain("t('loadingSrMessage')")
    expect(src).toContain('PageLoading')
    expect(src).not.toContain('<div className="min-h-dvh bg-background" />')
  })
})
