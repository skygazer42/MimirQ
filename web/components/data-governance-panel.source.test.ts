import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

import {
  expectSourceNotToContain,
  expectSourceToContain,
} from '@/lib/source-test-utils'

describe('data governance panel source', () => {
  it('uses explicit spans, semantic buttons, and next-intl-backed labels', () => {
    const src = fs.readFileSync(
      path.resolve(__dirname, 'data-governance-panel.tsx'),
      'utf8'
    )

    expectSourceNotToContain(src, 'role="button"')
    expectSourceNotToContain(src, '{(() => {')
    expectSourceToContain(
      src,
      "const t = useTranslations('DataGovernancePanel')"
    )
    expectSourceToContain(src, 'const headerTitle = t("header.title")')
    expectSourceToContain(src, 'const headerSubtitle = t("header.subtitle")')
    expectSourceToContain(
      src,
      '<span className="h-1.5 w-1.5 rounded-full bg-primary/20" aria-hidden="true" />'
    )
    expectSourceToContain(
      src,
      '<span className="w-1.5 h-1.5 rounded-full bg-info/10 dark:bg-info/20" aria-hidden="true" />'
    )
    expectSourceToContain(src, "aria-label={t('inbound.close')}")
    expectSourceToContain(src, "aria-label={t('emptyUpload.openUploadDialog')}")
    expectSourceToContain(
      src,
      "aria-label={t('a11y.openFile', { filename: file.filename })}"
    )
    expectSourceToContain(src, "aria-label={t('panel.collapse')}")
    expectSourceToContain(src, 'const contentBody =')
    expectSourceToContain(src, 'const activeFolderLabel = useMemo(() => {')
    expectSourceToContain(src, "t('sidebar.allFolders')")
  })
})
