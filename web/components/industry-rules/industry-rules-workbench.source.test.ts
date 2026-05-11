import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

import {
  expectSourceNotToContain,
  expectSourceToContain,
} from '@/lib/source-test-utils'

describe('industry rules workbench source', () => {
  it('productizes ruleset editing into a tabbed workbench with mining and preview', () => {
    const src = fs.readFileSync(
      path.resolve(__dirname, 'industry-rules-workbench.tsx'),
      'utf8'
    )

    expectSourceToContain(src, 'industryRulesApi.listRulesets')
    expectSourceToContain(src, 'industryRulesApi.getRuleset')
    expectSourceToContain(src, 'industryRulesApi.previewRewrite')
    expectSourceToContain(src, 'industryRulesApi.updateGlossary')
    expectSourceToContain(src, 'industryRulesApi.updatePatterns')
    expectSourceToContain(src, 'industryRulesApi.updateIntents')
    expectSourceToContain(src, 'datasetApi.getAnalysisRuleSuggestions')
    expectSourceToContain(src, 'TabsTrigger value="glossary"')
    expectSourceToContain(src, 'TabsTrigger value="patterns"')
    expectSourceToContain(src, 'TabsTrigger value="intents"')
    expectSourceToContain(src, '规则候选（待审核）')
    expectSourceToContain(src, '改写预览')
    expectSourceToContain(src, '行业规则库')
  })

  it('loads ruleset and dataset metadata through TanStack Query', () => {
    const src = fs.readFileSync(
      path.resolve(__dirname, 'industry-rules-workbench.tsx'),
      'utf8'
    )

    expectSourceToContain(src, "from '@tanstack/react-query'")
    expectSourceToContain(src, 'useQuery')
    expectSourceToContain(src, 'queryKey: queryKeys.industryRules.rulesets')
    expectSourceToContain(src, 'queryKey: queryKeys.datasets.list')
    expectSourceNotToContain(src, 'const [rulesets, setRulesets]')
    expectSourceNotToContain(src, 'const [datasets, setDatasets]')
    expectSourceNotToContain(src, 'setLoadingMeta')
    expectSourceNotToContain(src, 'detachPromise(loadMeta())')
  })
})
