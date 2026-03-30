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

  it('moves clean summary copy into next-intl lookups', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'ingestion-preview-details-dialog.tsx'), 'utf8')

    expect(src).toContain('t("ingestionPreview.clean.title")')
    expect(src).toContain('t("ingestionPreview.clean.status.dropped")')
    expect(src).toContain('t("ingestionPreview.clean.status.changed")')
    expect(src).toContain('t("ingestionPreview.clean.dropReasonLabel")')
    expect(src).toContain('t("ingestionPreview.clean.metrics.chars")')
    expect(src).toContain('t("ingestionPreview.clean.metrics.lines")')
    expect(src).toContain('t("ingestionPreview.clean.metrics.rules")')
    expect(src).toContain('t("ingestionPreview.clean.metrics.diffTruncated")')
    expect(src).toContain('t("ingestionPreview.clean.metrics.diffFull")')
    expect(src).toContain('t("ingestionPreview.clean.alerts.piiHits")')
    expect(src).toContain('t("ingestionPreview.clean.alerts.secretsHits")')
    expect(src).toContain('t("ingestionPreview.clean.alerts.maskingHint")')
    expect(src).toContain('t("ingestionPreview.clean.patch.title")')
    expect(src).toContain('t("ingestionPreview.clean.patch.missingHandler")')
    expect(src).toContain('t("ingestionPreview.clean.patch.applied")')
    expect(src).toContain('t("ingestionPreview.clean.patch.apply")')
  })

  it('moves diff copy into next-intl lookups', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'ingestion-preview-details-dialog.tsx'), 'utf8')

    expect(src).toContain('t("ingestionPreview.diff.title")')
    expect(src).toContain('t("ingestionPreview.diff.copy")')
    expect(src).toContain('t("ingestionPreview.diff.copySuccess")')
    expect(src).toContain('t("ingestionPreview.diff.copyError")')
    expect(src).toContain('t("ingestionPreview.diff.diffTruncated")')
    expect(src).toContain('t("ingestionPreview.diff.diffFull")')
    expect(src).toContain('t("ingestionPreview.diff.noDiff")')
  })
})
