import { describe, expect, it } from 'vitest'

import { createRuleRow, parseRuleJson, rowsFromValue, serializeRows } from './rule-editor-model'

describe('industry rule editing payloads', () => {
  it('round-trips glossary arrays without splitting existing punctuation', () => {
    const source = { PLC: ['PLC, controller', '控制器', '控制器'], '__proto__': ['prototype'] }
    expect(serializeRows('glossary', rowsFromValue('glossary', source))).toEqual(source)
  })

  it('preserves arbitrary glossary keys when adding or renaming terms', () => {
    const row = { ...createRuleRow('safe-id'), term: '__proto__', words: '控制器，PLC\n设备' }
    const result = serializeRows('glossary', [row])
    expect(Object.hasOwn(result, '__proto__')).toBe(true)
    expect(result).toEqual(JSON.parse('{"__proto__":["控制器","PLC","设备"]}'))
  })

  it('rejects blank or duplicate terms rather than losing rows on save', () => {
    const row = { ...createRuleRow('one'), term: 'PLC', words: '控制器' }
    expect(() => serializeRows('glossary', [row, { ...row, id: 'two', term: ' PLC ' }])).toThrow('重复')
    expect(() => serializeRows('glossary', [{ ...row, term: ' ' }])).toThrow('术语')
  })

  it('preserves legacy pattern keys, custom fields and omitted defaults', () => {
    const source = [{ keywords: ['a,b'], followup_template: '哪个设备？', priority: 8, custom: { kind: 'alarm' } }]
    const rows = rowsFromValue('patterns', source)
    expect(serializeRows('patterns', rows)).toEqual(source)
    rows[0].followup = '请提供设备型号'
    expect(serializeRows('patterns', rows)).toEqual([{ ...source[0], followup_template: '请提供设备型号' }])
    rows[0].words = '485，通信\n设备'
    rows[0].enabled = false
    expect(serializeRows('patterns', rows)).toEqual([{ ...source[0], keywords: ['485', '通信', '设备'], followup_template: '请提供设备型号', enabled: false }])
  })

  it('keeps custom records without recognized fields intact', () => {
    const source = [{ condition: { code: 485 }, action: 'rewrite' }, { markers: 'legacy-format', enabled: null }]
    expect(serializeRows('patterns', rowsFromValue('patterns', source))).toEqual(source)
    const intents = [{ category: 'custom', route: { target: 'search' } }]
    expect(serializeRows('intents', rowsFromValue('intents', intents))).toEqual(intents)
  })

  it('updates an intent without dropping extensions or materializing the default route', () => {
    const source = [{ name: 'diagnose', keywords: ['故障,报警'], priority: 4 }]
    const rows = rowsFromValue('intents', source)
    rows[0].name = '诊断'
    expect(serializeRows('intents', rows)).toEqual([{ ...source[0], name: '诊断' }])
  })

  it('validates new structured rules instead of silently filtering them out', () => {
    expect(() => serializeRows('patterns', [createRuleRow('new')])).toThrow('触发词')
    expect(() => serializeRows('intents', [createRuleRow('new')])).toThrow('名称')
    expect(serializeRows('patterns', [{ ...createRuleRow('new'), words: '报警, 故障', followup: '设备型号？' }])).toEqual([
      { markers: ['报警', '故障'], followup: '设备型号？', enabled: true },
    ])
  })

  it('validates JSON shapes and does not coerce empty or malformed input into deletions', () => {
    for (const raw of ['', '{', '[]', '{"PLC":"控制器"}', '{"PLC":[1]}']) {
      expect(() => parseRuleJson('glossary', raw)).toThrow()
    }
    for (const raw of ['{}', '[1]', '[null]', '[[]]']) {
      expect(() => parseRuleJson('patterns', raw)).toThrow()
    }
    expect(parseRuleJson('patterns', '[{"custom":true}]')).toEqual([{ custom: true }])
    expect(parseRuleJson('glossary', '{"485":["RS-485"]}')).toEqual({ '485': ['RS-485'] })
  })
})
