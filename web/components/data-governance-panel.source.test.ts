import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('data governance panel source', () => {
  it('uses explicit spans, semantic buttons, and next-intl-backed labels', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'data-governance-panel.tsx'), 'utf8')

    expect(src).not.toContain('role="button"')
    expect(src).not.toContain('{(() => {')
    expect(src).toContain("const t = useTranslations('DataGovernancePanel')")
    expect(src).toContain('const headerTitle = t("header.title")')
    expect(src).toContain('const headerSubtitle = t("header.subtitle")')
    expect(src).toContain('<span className="h-1.5 w-1.5 rounded-full bg-primary/20" aria-hidden="true" />')
    expect(src).toContain('<span className="w-1.5 h-1.5 rounded-full bg-info/10 dark:bg-info/20" aria-hidden="true" />')
    expect(src).toContain("aria-label={t('inbound.close')}")
    expect(src).toContain("aria-label={t('emptyUpload.openUploadDialog')}")
    expect(src).toContain("aria-label={t('a11y.openFile', { filename: file.filename })}")
    expect(src).toContain("aria-label={t('panel.collapse')}")
    expect(src).toContain('const contentBody =')
    expect(src).toContain("const activeFolderLabel = useMemo(() => {")
    expect(src).toContain("t('sidebar.allFolders')")
  })
})
