import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('industry rules workbench source', () => {
  it('productizes ruleset editing into a tabbed workbench with mining and preview', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'industry-rules-workbench.tsx'), 'utf8')

    expect(src).toContain('industryRulesApi.listRulesets')
    expect(src).toContain('industryRulesApi.getRuleset')
    expect(src).toContain('industryRulesApi.previewRewrite')
    expect(src).toContain('industryRulesApi.updateGlossary')
    expect(src).toContain('industryRulesApi.updatePatterns')
    expect(src).toContain('industryRulesApi.updateIntents')
    expect(src).toContain('datasetApi.getAnalysisRuleSuggestions')
    expect(src).toContain('TabsTrigger value="glossary"')
    expect(src).toContain('TabsTrigger value="patterns"')
    expect(src).toContain('TabsTrigger value="intents"')
    expect(src).toContain('规则候选（待审核）')
    expect(src).toContain('改写预览')
    expect(src).toContain('行业规则库')
  })
})
