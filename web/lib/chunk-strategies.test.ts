import { describe, expect, it } from 'vitest'
import {
  buildChunkStrategyCatalog,
  getChunkStrategyLabel,
  getChunkStrategyOption,
  isRetiredChunkStrategy,
} from './chunk-strategies'

const retiredStrategies = ['agentic_chunker', 'late_chunking', 'late_chunking_jina', 'raptor']

describe('retired chunk strategies', () => {
  it('uses the default for an empty selection and preserves a strategy missing from the catalog', () => {
    expect(getChunkStrategyOption().value).toBe('langchain_recursive')
    expect(getChunkStrategyOption('external_strategy').value).toBe('external_strategy')
  })

  it('excludes retired entries from cached capability choices while retaining real strategies', () => {
    const supported = ['semantic_sentence', 'proposition', 'llama_index', 'text_hierarchy', 'markdown_hierarchy']
    const catalog = buildChunkStrategyCatalog(
      [...retiredStrategies, ...supported].map((name) => ({ name, available: true })),
    )
    const choices = catalog.map((item) => item.value)
    for (const name of retiredStrategies) expect(choices).not.toContain(name)
    for (const name of supported) expect(choices).toContain(name)
  })

  it.each(retiredStrategies)('keeps saved %s visible as removed without displaying a replacement', (name) => {
    expect(isRetiredChunkStrategy(` ${name.toUpperCase()} `)).toBe(true)
    expect(getChunkStrategyLabel(name)).toBe(name)
    expect(getChunkStrategyOption(name)).toMatchObject({
      value: name,
      label: name,
      badge: '已移除',
      disabled: true,
    })
  })
})
