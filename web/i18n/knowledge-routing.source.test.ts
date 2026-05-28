import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

const webRoot = path.resolve(__dirname, '..')

function read(relativePath: string): string {
  return fs.readFileSync(path.resolve(webRoot, relativePath), 'utf8')
}

describe('next-intl knowledge routing source', () => {
  it('uses locale-aware navigation helpers across the remaining knowledge entry points', () => {
    const feedbackPage = read('app/knowledge/feedback/page-client.tsx')
    const knowledgePage = read('components/knowledge/knowledge-page.tsx')

    expect(feedbackPage).toContain('@/i18n/navigation')
    expect(feedbackPage).not.toContain("import { useRouter } from 'next/navigation'")

    expect(knowledgePage).toContain('@/i18n/navigation')
    expect(knowledgePage).toContain("import { useSearchParams } from 'next/navigation'")
    expect(knowledgePage).not.toContain("import { useRouter, useSearchParams } from 'next/navigation'")

    const localeEvidenceWrapper = read('app/[locale]/knowledge/evidence/page.tsx')
    expect(localeEvidenceWrapper).toContain("export { default } from '../../../knowledge/evidence/page'")

    const localeNebulaWrapper = read('app/[locale]/knowledge/nebula/page.tsx')
    expect(localeNebulaWrapper).toContain("export { default } from '../../../knowledge/nebula/page'")
  })
})
