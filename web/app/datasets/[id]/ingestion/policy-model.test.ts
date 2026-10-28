import { describe, expect, it } from 'vitest'
import type { IngestionRule } from '@/types'
import { draftToRule, insertTemplate, newRuleDraft, policyPayload, ruleToDraft } from './policy-model'

const rule: IngestionRule = { id: 'html-rule', name: '网页', enabled: true, match: { extensions: ['.html'], filename_regex: '(?i)article' }, preprocess: { enabled: true, steps: [{ id: 'text.collapse_blank_lines', params: { max_blank_lines: 2 } }] }, parser_backend: 'auto', chunk_strategy: null, governance_profile_ref: 'builtin:html_web', pipeline_patch: { governance_enabled: true } }
describe('dataset ingestion policy editing', () => {
  it('preserves preprocess parameters and Python regex when only the name changes', () => {
    const draft = ruleToDraft(rule)
    draft.name = '网页正文'
    expect(draftToRule(draft, [rule], rule.id)).toEqual({ ...rule, name: '网页正文' })
  })
  it('rejects duplicate IDs, missing identity and non-object JSON at the field boundary', () => {
    const draft = { ...newRuleDraft('html-rule'), name: '文档' }
    expect(() => draftToRule(draft, [rule], null)).toThrow('ID 已存在')
    expect(() => draftToRule({ ...draft, id: '' }, [], null)).toThrow('规则 ID')
    expect(() => draftToRule({ ...draft, name: ' ' }, [], null)).toThrow('规则名称')
    expect(() => draftToRule({ ...draft, pipelinePatchJson: '[]' }, [], null)).toThrow('JSON 对象')
  })
  it('normalizes extension input while retaining explicit blank overrides', () => {
    const draft = { ...newRuleDraft('docs'), name: '文档', extensionsText: 'PDF, .DOCX PDF', parserBackend: '', chunkStrategy: '', governanceProfileRef: '' }
    expect(draftToRule(draft, [], null)).toMatchObject({ match: { extensions: ['.pdf', '.docx'] }, parser_backend: null, chunk_strategy: null, governance_profile_ref: null, pipeline_patch: {} })
  })
  it('keeps rule order and validates the documented 60-rule limit', () => {
    const extra = { ...rule, id: 'new-rule' }
    expect(insertTemplate([rule], [extra], 'prepend').map(item => item.id)).toEqual(['new-rule', 'html-rule'])
    expect(insertTemplate([rule], [extra], 'append').map(item => item.id)).toEqual(['html-rule', 'new-rule'])
    expect(insertTemplate([rule], [extra], 'replace')).toEqual([extra])
    expect(() => insertTemplate(Array.from({ length: 60 }, (_, i) => ({ ...rule, id: `r-${i}` })), [extra], 'append')).toThrow('60')
  })
  it('sends only the policy contract and distinguishes an empty policy from no read result', () => {
    expect(policyPayload({ version: '1', rules: [] })).toEqual({ version: '1', rules: [] })
    expect(policyPayload({ version: '1', rules: [rule] })).toEqual({ version: '1', rules: [rule] })
  })
})
