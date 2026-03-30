import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

const webRoot = path.resolve(__dirname, '..')

function read(relativePath: string): string {
  return fs.readFileSync(path.resolve(webRoot, relativePath), 'utf8')
}

describe('next-intl static route routing source', () => {
  it('uses locale-aware redirects and wrappers for the remaining static route entries', () => {
    const evaluationPage = read('app/evaluation/page.tsx')

    expect(evaluationPage).toContain('@/i18n/navigation')
    expect(evaluationPage).toContain('@/i18n/routing')
    expect(evaluationPage).not.toContain("import { redirect } from 'next/navigation'")
    expect(evaluationPage).toContain("redirect({ href: '/evaluations', locale: routing.defaultLocale })")

    const localeEvaluationPage = read('app/[locale]/evaluation/page.tsx')
    expect(localeEvaluationPage).toContain('@/i18n/navigation')
    expect(localeEvaluationPage).toContain("redirect({ href: '/evaluations', locale })")

    const localeLogosPreviewPage = read('app/[locale]/logos-preview/page.tsx')
    expect(localeLogosPreviewPage).toContain("export { default } from '../../logos-preview/page'")
  })
})
