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
    expect(src).toContain('后端规则接口')
    expect(src).toContain('规则集')
    expect(src).toContain('测试问题')
    expect(src).toContain('术语词库')
    expect(src).toContain('匹配规则')
    expect(src).toContain('意图规则')
    expect(src).toContain('查询改写规则')
    expect(src).toContain('PreviewText')
    expect(src).not.toContain('行业规则与查询改写')
    expect(src).not.toContain('Ruleset</Label>')
    expect(src).not.toContain('Preview Query')
    expect(src).not.toContain('Glossary JSON')
    expect(src).not.toContain('Patterns JSON')
    expect(src).not.toContain('Intents JSON')
    expect(src).not.toContain('industry-rules API')
  })
})
