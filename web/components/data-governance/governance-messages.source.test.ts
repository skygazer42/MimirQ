import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

import {
  expectSourceNotToContain,
  expectSourceToContain,
} from '@/lib/source-test-utils'

function read(relativePath: string) {
  return fs.readFileSync(
    path.resolve(__dirname, '..', '..', relativePath),
    'utf8'
  )
}

describe('data governance message sources', () => {
  it('moves data-governance route loading copy into next-intl', () => {
    const pageSrc = read('app/data-governance/page.tsx')
    const profilesSrc = read('app/data-governance/profiles/page.tsx')
    const commonLinesSrc = read('app/data-governance/common-lines/page.tsx')

    expectSourceToContain(pageSrc, "useTranslations('DataGovernancePage')")
    expectSourceToContain(pageSrc, "message={t('loading.message')}")
    expectSourceToContain(
      profilesSrc,
      "useTranslations('GovernanceProfilesRoutePage')"
    )
    expectSourceToContain(profilesSrc, "message={t('loading.message')}")
    expectSourceToContain(
      commonLinesSrc,
      "useTranslations('GovernanceCommonLinesRoutePage')"
    )
    expectSourceToContain(commonLinesSrc, "message={t('loading.message')}")
  })

  it('moves core data-governance component copy into next-intl catalogs', () => {
    const panelSrc = read('components/data-governance-panel.tsx')
    const annotatorSrc = read('components/data-governance/data-annotator.tsx')
    const classifierSrc = read('components/data-governance/data-classifier.tsx')
    const cleanerSrc = read('components/data-governance/data-cleaner.tsx')
    const qualitySrc = read('components/data-governance/quality-checker.tsx')

    expectSourceToContain(panelSrc, "useTranslations('DataGovernancePanel')")
    expectSourceToContain(panelSrc, 'label: t(`tabs.${id}.label`)')
    expectSourceToContain(panelSrc, 'desc: t(`tabs.${id}.description`)')
    expectSourceToContain(panelSrc, 't("header.title")')
    expectSourceToContain(panelSrc, 't("header.subtitle")')

    expectSourceToContain(annotatorSrc, "useTranslations('DataAnnotator')")
    expectSourceToContain(annotatorSrc, 'label: t(`types.${id}.label`)')
    expectSourceToContain(
      annotatorSrc,
      'description: t(`types.${id}.description`)'
    )
    expectSourceToContain(annotatorSrc, 'pipelineApi.autoAnnotations')
    expectSourceToContain(annotatorSrc, "mode: 'document_focus'")
    expectSourceToContain(annotatorSrc, 'autoTagProvider')
    expectSourceToContain(annotatorSrc, 'AUTO_TAG_PROVIDER_OPTIONS')
    expectSourceToContain(
      annotatorSrc,
      'providers: selectedProviderConfig.providers'
    )
    expectSourceToContain(
      annotatorSrc,
      'enable_llm: selectedProviderConfig.enableLlm'
    )
    expectSourceToContain(
      annotatorSrc,
      'enable_sensitive: selectedProviderConfig.enableSensitive'
    )
    expectSourceToContain(
      annotatorSrc,
      't(`auto.providers.${option.id}.label`)'
    )
    expectSourceToContain(annotatorSrc, "t('auto.providerTitle')")
    expectSourceToContain(annotatorSrc, "t('semantic.title')")
    expectSourceToContain(annotatorSrc, "t('auto.action')")

    expectSourceToContain(classifierSrc, "useTranslations('DataClassifier')")
    expectSourceToContain(classifierSrc, 'label: t(`categories.${id}.label`)')
    expectSourceToContain(classifierSrc, "t.raw('suggestedTags') as string[]")
    expectSourceToContain(classifierSrc, 'pipelineApi.autoAnnotations')
    expectSourceToContain(classifierSrc, "mode: 'document_focus'")
    expectSourceToContain(classifierSrc, 'document_tags')
    expectSourceNotToContain(classifierSrc, 'setTimeout(resolve, 1000)')

    expectSourceToContain(cleanerSrc, "useTranslations('DataCleaner')")
    expectSourceToContain(cleanerSrc, 't("header.title")')
    expectSourceToContain(cleanerSrc, 't("actions.apply")')

    expectSourceToContain(qualitySrc, "useTranslations('QualityChecker')")
    expectSourceToContain(qualitySrc, 'label: t(`checkItems.${id}.label`)')
    expectSourceToContain(qualitySrc, 't("header.title")')
    expectSourceToContain(qualitySrc, 't("actions.scan")')
    expectSourceToContain(
      qualitySrc,
      'const [backendScanEnabled, setBackendScanEnabled] = useState(true)'
    )
    expectSourceToContain(qualitySrc, 'pipelineApi.governanceAnalyze')
    expectSourceNotToContain(qualitySrc, 'setTimeout(resolve, step.delay)')
  })

  it('wires manual annotation selection to the document canvas instead of the tool panel', () => {
    const panelSrc = read('components/data-governance-panel.tsx')
    const annotatorSrc = read('components/data-governance/data-annotator.tsx')

    expectSourceToContain(panelSrc, 'data-governance-selection-root="true"')
    expectSourceToContain(
      annotatorSrc,
      'querySelector(\'[data-governance-selection-root="true"]\')'
    )
    expectSourceToContain(
      annotatorSrc,
      "addEventListener('mouseup', captureSelection)"
    )
    expectSourceToContain(
      annotatorSrc,
      'findSelectionRange(content, selectedText)'
    )
  })
})
