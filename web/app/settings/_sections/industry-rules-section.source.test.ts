import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('industry rules settings section', () => {
  it('connects the industry rules CMS endpoints', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'industry-rules-section.tsx'), 'utf8')

    expect(src).toContain('industryRulesApi.listRulesets')
    expect(src).toContain('industryRulesApi.getRuleset')
    expect(src).toContain('industryRulesApi.previewRewrite')
    expect(src).toContain('industryRulesApi.updateGlossary')
    expect(src).toContain('industryRulesApi.updatePatterns')
    expect(src).toContain('industryRulesApi.updateIntents')
    expect(src).toContain('/governance/industry-rules')
    expect(src).toContain('打开完整工作台')
  })
})
