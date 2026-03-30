import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('ingestion detail dialog message sources', () => {
  it('moves ingestion detail copy into next-intl catalogs', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'ingestion-detail-dialog.tsx'), 'utf8')

    expect(src).toContain("useTranslations('IngestionDetailDialog')")
    expect(src).toContain('label: t(`stages.${stage.key}`)')
    expect(src).toContain('t("header.fallbackTitle")')
    expect(src).toContain('t("actions.retry")')
    expect(src).toContain('t("errors.diffFailed")')
  })
})
