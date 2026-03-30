import { describe, expect, it } from 'vitest'

import {
  PARSER_BACKEND_OPTIONS,
  PARSER_BACKEND_REGISTRY_OPTIONS,
  getParserLabel,
} from '@/lib/parser-options'

describe('parser options registry', () => {
  it('keeps the interactive parser dropdown focused while exposing a broader shared registry', () => {
    expect(PARSER_BACKEND_OPTIONS.some((option) => option.value === 'pandoc')).toBe(false)
    expect(PARSER_BACKEND_REGISTRY_OPTIONS.some((option) => option.value === 'pandoc')).toBe(true)
    expect(PARSER_BACKEND_REGISTRY_OPTIONS.some((option) => option.value === 'excel')).toBe(true)
    expect(PARSER_BACKEND_REGISTRY_OPTIONS.some((option) => option.value === 'markdown')).toBe(true)
  })

  it('resolves labels for registry-only parser backends through the shared definition table', () => {
    expect(getParserLabel('pandoc')).toBe('pandoc（Office/HTML）')
    expect(getParserLabel('excel')).toBe('excel（.xls/.xlsx）')
    expect(getParserLabel('markdown')).toBe('markdown（.md）')
  })
})
