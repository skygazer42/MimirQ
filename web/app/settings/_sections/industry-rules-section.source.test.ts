import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('industry rules settings section', () => {
  it('connects the industry rules CMS endpoints', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'industry-rules-section.tsx'), 'utf8')

    expect(src).toContain('industryRulesApi.listRulesets')
    expect(src).toContain('industryRulesApi.getRuleset')
    expect(src).toContain('industryRulesApi.previewRewrite')
    expect(src).toContain('.updateGlossary(')
    expect(src).toContain('.updatePatterns(')
    expect(src).toContain('.updateIntents(')
    expect(src).toContain('useQueryClient')
    expect(src).toContain('queryKeys.industryRules.rulesets')
    expect(src).toContain('queryKeys.industryRules.ruleset')
    expect(src).not.toMatch(/async function loadRuleset\s*\(/)
    expect(src).toContain('/governance/industry-rules')
    expect(src).toContain('打开完整工作台')
  })
})
