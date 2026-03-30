import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('evidence workbench source', () => {
  it('uses glass panel shells and surface-first citation cards', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'evidence-workbench.tsx'), 'utf8')

    expect(src).toContain('variant="glass" className="p-4"')
    expect(src).toContain('variant="glass" className="p-4 lg:col-span-1"')
    expect(src).toContain('variant="glass" className="p-4 lg:col-span-2"')
    expect(src).toContain('bg-warning/10 border-warning/20 text-warning')
    expect(src).toContain('rounded-xl border border-sidebar-border/70 bg-sidebar/55 px-3 py-3 shadow-soft backdrop-blur-sm')
    expect(src).toContain('border border-sidebar-border/70 bg-sidebar/40 shadow-soft/70')
  })

  it('moves workbench controls and toast copy into next-intl lookups', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'evidence-workbench.tsx'), 'utf8')

    expect(src).toContain("useTranslations('EvidenceWorkbench')")
    expect(src).toContain('t("controls.datasetScope")')
    expect(src).toContain('t("controls.datasetPlaceholder")')
    expect(src).toContain('t("controls.allDocuments")')
    expect(src).toContain('t("controls.loadingDatasets")')
    expect(src).toContain('t("controls.profile")')
    expect(src).toContain('t("controls.profilePlaceholder")')
    expect(src).toContain('t("controls.query")')
    expect(src).toContain('t("controls.queryPlaceholder")')
    expect(src).toContain('t("actions.searching")')
    expect(src).toContain('t("actions.search")')
    expect(src).toContain('t("actions.reset")')
    expect(src).toContain('t("actions.export")')
    expect(src).toContain('t("toasts.foundEvidence")')
    expect(src).toContain('t("toasts.abstainTriggered"')
    expect(src).toContain('t("toasts.noEvidence")')
    expect(src).toContain('t("toasts.exportedPack")')
    expect(src).toContain('t("errors.loadDatasetsFailed")')
    expect(src).toContain('t("errors.retrieveFailed")')
  })

  it('moves result panel headings and empty states into next-intl lookups', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'evidence-workbench.tsx'), 'utf8')

    expect(src).toContain('t("results.summary.title")')
    expect(src).toContain('t("results.summary.description")')
    expect(src).toContain('t("results.citations.title")')
    expect(src).toContain('t("results.citations.hitsHint")')
    expect(src).toContain('t("results.citations.emptyHits")')
    expect(src).toContain('t("results.citations.emptyContent")')
    expect(src).toContain('t("results.citations.noCitations")')
  })
})
