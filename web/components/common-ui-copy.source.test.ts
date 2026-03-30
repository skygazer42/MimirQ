import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

function read(relativePath: string): string {
  return fs.readFileSync(path.resolve(__dirname, relativePath), 'utf8')
}

describe('common UI copy source', () => {
  it('moves mode toggle copy into next-intl lookups', () => {
    const src = read('./mode-toggle.tsx')

    expect(src).toContain("useTranslations('CommonUi')")
    expect(src).toContain('t("modeToggle.ariaLabel")')
    expect(src).toContain('t("modeToggle.light")')
    expect(src).toContain('t("modeToggle.dark")')
    expect(src).toContain('t("modeToggle.system")')
  })

  it('moves breadcrumb route labels and aria copy into next-intl lookups', () => {
    const src = read('./ui/breadcrumb.tsx')

    expect(src).toContain("useTranslations('CommonUi')")
    expect(src).toContain('t("breadcrumb.navLabel")')
    expect(src).toContain('const ROUTE_LABEL_KEYS')
    expect(src).toContain("datasets: 'datasets'")
    expect(src).toContain("knowledge: 'knowledge'")
    expect(src).toContain("settings: 'settings'")
    expect(src).toContain("graph: 'graph'")
    expect(src).toContain("workflow: 'workflow'")
    expect(src).toContain('t(`breadcrumb.routes.${routeKey}`)')
  })

  it('moves ingestion workflow stepper copy into next-intl lookups', () => {
    const src = read('./ui/ingestion-workflow-stepper.tsx')

    expect(src).toContain("useTranslations('CommonUi')")
    expect(src).toContain('t("ingestionWorkflow.navLabel")')
    expect(src).toContain('t("ingestionWorkflow.parsing")')
    expect(src).toContain('t("ingestionWorkflow.governance")')
    expect(src).toContain('t("ingestionWorkflow.chunk")')
    expect(src).toContain('t("ingestionWorkflow.chat")')
  })
})
