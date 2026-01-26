import { describe, expect, it } from 'vitest'
import { parseChunkStrategyParamsJson, validateChunkStrategyParams } from './chunk-strategy-params'

describe('chunk-strategy-params', () => {
  it('parses empty as undefined', () => {
    const res = parseChunkStrategyParamsJson('   ')
    expect(res.ok).toBe(true)
    if (res.ok) expect(res.value).toBeUndefined()
  })

  it('rejects invalid JSON', () => {
    const res = parseChunkStrategyParamsJson('{')
    expect(res.ok).toBe(false)
  })

  it('accepts primitive-only objects', () => {
    const res = validateChunkStrategyParams({ child_ratio: 0.25, min_child_size: 300, keep_separator: true, separator: '\\n\\n' })
    expect(res.ok).toBe(true)
    if (res.ok) {
      expect(res.value).toEqual({ child_ratio: 0.25, min_child_size: 300, keep_separator: true, separator: '\\n\\n' })
    }
  })

  it('rejects nested objects/arrays', () => {
    const res = validateChunkStrategyParams({ bad: { nested: true } })
    expect(res.ok).toBe(false)
  })

  it('rejects too many keys', () => {
    const obj: any = {}
    for (let i = 0; i < 31; i++) obj[`k${i}`] = i
    const res = validateChunkStrategyParams(obj)
    expect(res.ok).toBe(false)
  })
})

