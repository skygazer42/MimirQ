import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

function read(relativePath: string) {
  return fs.readFileSync(path.resolve(__dirname, relativePath), 'utf8')
}

describe('document detail message sources', () => {
  it('moves document detail dialog copy into next-intl catalogs', () => {
    const mainSrc = read('document-detail-dialog.tsx')
    const accessSrc = read('document-detail-dialog/document-access-dialog.tsx')
    const versionsSrc = read('document-detail-dialog/document-versions-dialog.tsx')

    expect(mainSrc).toContain("useTranslations('DocumentDetailDialog')")
    expect(mainSrc).toContain('t("toasts.tagsUpdated")')
    expect(mainSrc).toContain('t("accessModes.inherit")')
    expect(mainSrc).toContain('t("search.placeholder")')
    expect(mainSrc).toContain('t("views.ariaLabel")')

    expect(accessSrc).toContain("useTranslations('DocumentAccessDialog')")
    expect(accessSrc).toContain('t("trigger")')
    expect(accessSrc).toContain('t("mode.placeholder")')

    expect(versionsSrc).toContain("useTranslations('DocumentVersionsDialog')")
    expect(versionsSrc).toContain('t("trigger")')
    expect(versionsSrc).toContain('t("dialogs.activate.title")')
    expect(versionsSrc).toContain('t("empty.title")')
  })
})
