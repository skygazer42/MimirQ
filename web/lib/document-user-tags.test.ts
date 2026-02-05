import { describe, expect, it } from 'vitest'
import { buildTagsPatch, mergeTags, normalizeTags, parseTagsText } from '@/lib/document-user-tags'

describe('document user tags utils', () => {
  it('parseTagsText splits common separators and dedupes case-insensitively', () => {
    expect(parseTagsText('a, b;A\nc，d；e、f')).toEqual(['a', 'b', 'c', 'd', 'e', 'f'])
  })

  it('parseTagsText trims, collapses whitespace, and strips leading #', () => {
    expect(parseTagsText('  #Hello   World  ')).toEqual(['Hello World'])
  })

  it('normalizeTags ignores non-strings and long tags', () => {
    const long = 'x'.repeat(100)
    expect(normalizeTags([1, null, long, 'ok'])).toEqual(['ok'])
  })

  it('mergeTags replace overwrites', () => {
    expect(mergeTags(['a', 'b'], 'replace', ['b', 'c'])).toEqual(['b', 'c'])
  })

  it('mergeTags append keeps order and avoids duplicates', () => {
    expect(mergeTags(['a', 'b'], 'append', ['B', 'c'])).toEqual(['a', 'b', 'c'])
  })

  it('mergeTags remove removes case-insensitively', () => {
    expect(mergeTags(['a', 'B', 'c'], 'remove', ['b'])).toEqual(['a', 'c'])
  })

  it('buildTagsPatch uses null when tags become empty', () => {
    expect(buildTagsPatch([])).toEqual({ replace: false, patch: { tags: null } })
    expect(buildTagsPatch(['a'])).toEqual({ replace: false, patch: { tags: ['a'] } })
  })
})

