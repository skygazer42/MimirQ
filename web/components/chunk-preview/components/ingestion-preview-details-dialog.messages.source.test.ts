import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('chunk preview ingestion preview details messages', () => {
  it('moves header, tabs, and preprocess copy into next-intl lookups', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'ingestion-preview-details-dialog.tsx'), 'utf8')

    expect(src).toContain("useTranslations('ChunkPreview')")
    expect(src).toContain('t("ingestionPreview.title")')
    expect(src).toContain('t("ingestionPreview.actions.openGovernance")')
    expect(src).toContain('t("ingestionPreview.rule.unmatched")')
    expect(src).toContain('t("ingestionPreview.tabs.preprocess")')
    expect(src).toContain('t("ingestionPreview.tabs.issuesWithCount"')
    expect(src).toContain('t("ingestionPreview.preprocess.title")')
    expect(src).toContain('t("ingestionPreview.preprocess.status.changed")')
    expect(src).toContain('t("ingestionPreview.preprocess.stepsTitle")')
    expect(src).toContain('t("ingestionPreview.preprocess.warningsTitle")')
    expect(src).toContain('t("ingestionPreview.preprocess.emptySteps")')
    expect(src).toContain('t("ingestionPreview.states.noPreviewData")')
  })
})
