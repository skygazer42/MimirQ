import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

function read(relativePath: string) {
  return fs.readFileSync(path.resolve(__dirname, '..', '..', relativePath), 'utf8')
}

describe('data governance message sources', () => {
  it('moves data-governance route loading copy into next-intl', () => {
    const pageSrc = read('app/data-governance/page.tsx')
    const profilesSrc = read('app/data-governance/profiles/page.tsx')
    const commonLinesSrc = read('app/data-governance/common-lines/page.tsx')

    expect(pageSrc).toContain("useTranslations('DataGovernancePage')")
    expect(pageSrc).toContain("message={t('loading.message')}")
    expect(profilesSrc).toContain("useTranslations('GovernanceProfilesRoutePage')")
    expect(profilesSrc).toContain("message={t('loading.message')}")
    expect(commonLinesSrc).toContain("useTranslations('GovernanceCommonLinesRoutePage')")
    expect(commonLinesSrc).toContain("message={t('loading.message')}")
  })

  it('moves core data-governance component copy into next-intl catalogs', () => {
    const panelSrc = read('components/data-governance-panel.tsx')
    const annotatorSrc = read('components/data-governance/data-annotator.tsx')
    const classifierSrc = read('components/data-governance/data-classifier.tsx')
    const cleanerSrc = read('components/data-governance/data-cleaner.tsx')
    const qualitySrc = read('components/data-governance/quality-checker.tsx')

    expect(panelSrc).toContain("useTranslations('DataGovernancePanel')")
    expect(panelSrc).toContain("label: t(`tabs.${id}.label`)")
    expect(panelSrc).toContain("desc: t(`tabs.${id}.description`)")
    expect(panelSrc).toContain('t("header.title")')
    expect(panelSrc).toContain('t("header.subtitle")')

    expect(annotatorSrc).toContain("useTranslations('DataAnnotator')")
    expect(annotatorSrc).toContain("label: t(`types.${id}.label`)")
    expect(annotatorSrc).toContain("description: t(`types.${id}.description`)")
    expect(annotatorSrc).toContain('pipelineApi.autoAnnotations')
    expect(annotatorSrc).toContain("mode: 'document_focus'")
    expect(annotatorSrc).toContain('autoTagProvider')
    expect(annotatorSrc).toContain('AUTO_TAG_PROVIDER_OPTIONS')
    expect(annotatorSrc).toContain('providers: selectedProviderConfig.providers')
    expect(annotatorSrc).toContain('enable_llm: selectedProviderConfig.enableLlm')
    expect(annotatorSrc).toContain('enable_sensitive: selectedProviderConfig.enableSensitive')
    expect(annotatorSrc).toContain("t(`auto.providers.${option.id}.label`)")
    expect(annotatorSrc).toContain("t('auto.providerTitle')")
    expect(annotatorSrc).toContain("t('semantic.title')")
    expect(annotatorSrc).toContain("t('auto.action')")

    expect(classifierSrc).toContain("useTranslations('DataClassifier')")
    expect(classifierSrc).toContain("label: t(`categories.${id}.label`)")
    expect(classifierSrc).toContain("keywords: t.raw(`categories.${id}.keywords`) as string[]")
    expect(classifierSrc).toContain("t.raw('suggestedTags') as string[]")

    expect(cleanerSrc).toContain("useTranslations('DataCleaner')")
    expect(cleanerSrc).toContain('t("header.title")')
    expect(cleanerSrc).toContain('t("actions.apply")')

    expect(qualitySrc).toContain("useTranslations('QualityChecker')")
    expect(qualitySrc).toContain("label: t(`checkItems.${id}.label`)")
    expect(qualitySrc).toContain('t("header.title")')
    expect(qualitySrc).toContain('t("actions.scan")')
  })

  it('wires manual annotation selection to the document canvas instead of the tool panel', () => {
    const panelSrc = read('components/data-governance-panel.tsx')
    const annotatorSrc = read('components/data-governance/data-annotator.tsx')

    expect(panelSrc).toContain('data-governance-selection-root="true"')
    expect(annotatorSrc).toContain("querySelector('[data-governance-selection-root=\"true\"]')")
    expect(annotatorSrc).toContain("addEventListener('mouseup', captureSelection)")
    expect(annotatorSrc).toContain('findSelectionRange(content, selectedText)')
  })
})
