import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('shared route boundary copy source', () => {
  it('moves shared not-found and root loading copy into next-intl lookups', () => {
    const notFoundSrc = fs.readFileSync(path.resolve(__dirname, 'not-found.tsx'), 'utf8')
    const loadingSrc = fs.readFileSync(path.resolve(__dirname, 'loading.tsx'), 'utf8')

    expect(notFoundSrc).toContain("useTranslations('RouteBoundaries')")
    expect(notFoundSrc).toContain('t("notFound.title")')
    expect(notFoundSrc).toContain('t("notFound.description")')
    expect(notFoundSrc).toContain('t("notFound.goHome")')
    expect(notFoundSrc).toContain('t("notFound.goKnowledge")')

    expect(loadingSrc).toContain("useTranslations('RouteBoundaries')")
    expect(loadingSrc).toContain('t("loading.pageSr")')
  })
})
