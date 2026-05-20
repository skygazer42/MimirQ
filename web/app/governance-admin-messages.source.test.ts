import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

const appRoot = path.resolve(__dirname)
const read = (relativePath: string) => fs.readFileSync(path.resolve(appRoot, relativePath), 'utf8')

describe('governance admin copy source', () => {
  it('pulls text from next-intl namespaces', () => {
    const auditPage = read('audit/page.tsx')
    expect(auditPage).toContain("const t = useTranslations('AuditPage')")
    expect(auditPage).toContain("t('title')")
    expect(auditPage).toContain("t('actions.refresh')")
    expect(auditPage).toContain("t('emptyState.title')")

    const accessReview = read('access-review/page.tsx')
    expect(accessReview).toContain("router.replace('/audit')")
    expect(accessReview).not.toContain("useTranslations('AccessReviewPage')")
  })
})
