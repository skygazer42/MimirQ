import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

function read(relativePath: string) {
  return fs.readFileSync(path.resolve(__dirname, '..', relativePath), 'utf8')
}

describe('knowledge workspace message sources', () => {
  it('moves knowledge workspace page and panel copy into next-intl catalogs', () => {
    const pageSrc = read('knowledge/knowledge-page.tsx')
    const scopeSrc = read('knowledge/knowledge-scope-panel.tsx')
    const docsSrc = read('knowledge/knowledge-documents-panel.tsx')
    const retrievalSrc = read('knowledge/knowledge-retrieval-panel.tsx')
    const settingsSrc = read('knowledge/knowledge-settings-panel.tsx')

    expect(pageSrc).toContain("useTranslations('KnowledgePage')")
    expect(pageSrc).toContain("label: t(`tabs.${tab.key}.label`)")
    expect(pageSrc).toContain('t("header.title")')
    expect(pageSrc).toContain('t("stats.totalDocuments")')
    expect(pageSrc).toContain("t('dialogs.scope.title')")

    expect(scopeSrc).toContain("useTranslations('KnowledgeScopePanel')")
    expect(scopeSrc).toContain("label: t(`status.${item.key}.label`)")
    expect(scopeSrc).toContain('t("dataset.label")')
    expect(scopeSrc).toContain('t("lifecycle.placeholder")')

    expect(docsSrc).toContain("useTranslations('KnowledgeDocumentsPanel')")
    expect(docsSrc).toContain('t("empty.filtered.title")')
    expect(docsSrc).toContain('t("actions.clearFilters")')
    expect(docsSrc).toContain('t("sort.placeholder")')

    expect(retrievalSrc).toContain("useTranslations('KnowledgeRetrievalPanel')")
    expect(retrievalSrc).toContain('t("header.title")')
    expect(retrievalSrc).toContain('t("actions.run")')

    expect(settingsSrc).toContain("useTranslations('KnowledgeSettingsPanel')")
    expect(settingsSrc).toContain("label: t(`runStatus.${value}`)")
    expect(settingsSrc).toContain('t("header.title")')
    expect(settingsSrc).toContain('t("connectorRuns.title")')
  })
})
