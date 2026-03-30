import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

const webRoot = path.resolve(__dirname, '..')

function read(relativePath: string): string {
  return fs.readFileSync(path.resolve(webRoot, relativePath), 'utf8')
}

describe('next-intl knowledge health routing source', () => {
  it('uses locale-aware navigation helpers across the knowledge health entry flow', () => {
    const documentHealthPage = read('components/knowledge/document-health-page.tsx')
    const knowledgeDocumentsPanel = read('components/knowledge/knowledge-documents-panel.tsx')

    expect(documentHealthPage).toContain('@/i18n/navigation')
    expect(documentHealthPage).not.toContain("import { useRouter } from 'next/navigation'")

    expect(knowledgeDocumentsPanel).toContain('@/i18n/navigation')
    expect(knowledgeDocumentsPanel).not.toContain("import Link from 'next/link'")

    const localeHealthWrapper = read('app/[locale]/knowledge/[id]/health/page.tsx')
    expect(localeHealthWrapper).toContain("export { default } from '../../../../knowledge/[id]/health/page'")
  })
})
