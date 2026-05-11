import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

import {
  expectSourceNotToContain,
  expectSourceToContain,
} from '@/lib/source-test-utils'

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

    expectSourceToContain(pageSrc, "useTranslations('KnowledgePage')")
    expectSourceToContain(pageSrc, 'label: t(`tabs.${tab.key}.label`)')
    expectSourceToContain(pageSrc, 't("header.title")')
    expectSourceToContain(pageSrc, 't("stats.totalDocuments")')
    expectSourceToContain(pageSrc, "t('dialogs.scope.title')")

    expectSourceToContain(scopeSrc, "useTranslations('KnowledgeScopePanel')")
    expectSourceToContain(scopeSrc, 'label: t(`status.${item.key}.label`)')
    expectSourceToContain(scopeSrc, 't("dataset.label")')
    expectSourceToContain(scopeSrc, 't("lifecycle.placeholder")')

    expectSourceToContain(docsSrc, "useTranslations('KnowledgeDocumentsPanel')")
    expectSourceToContain(docsSrc, 't("empty.filtered.title")')
    expectSourceToContain(docsSrc, 't("actions.clearFilters")')
    expectSourceToContain(docsSrc, 't("sort.placeholder")')

    expectSourceToContain(
      retrievalSrc,
      "useTranslations('KnowledgeRetrievalPanel')"
    )
    expectSourceToContain(retrievalSrc, 't("header.title")')
    expectSourceToContain(retrievalSrc, 't("actions.run")')

    expectSourceToContain(
      settingsSrc,
      "useTranslations('KnowledgeSettingsPanel')"
    )
    expectSourceToContain(settingsSrc, 'label: t(`runStatus.${value}`)')
    expectSourceToContain(settingsSrc, "t('header.title')")
    expectSourceToContain(settingsSrc, "t('connectorRuns.title')")
  })
})
