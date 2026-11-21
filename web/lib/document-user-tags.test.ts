import { describe, expect, it } from 'vitest'
import { buildTagsPatch, getUserTagsFromDocument } from './document-user-tags'

describe('stored document tags', () => {
  it('reads every stored tag without applying the input quota or stripping a literal prefix', () => {
    const tags = Array.from({ length: 50 }, (_, index) => `#标签 ${index}`)
    expect(getUserTagsFromDocument({ metadata: { user: { tags } } })).toEqual(tags)
  })

  it('sends the chosen existing tags without silently shortening or renaming the set', () => {
    const tags = Array.from({ length: 50 }, (_, index) => `#标签 ${index}`)
    expect(buildTagsPatch(tags)).toEqual({ replace: false, patch: { tags } })
  })

  it('uses the actual metadata deletion contract for an explicit empty set', () => {
    expect(buildTagsPatch([])).toEqual({ replace: false, patch: { tags: null } })
  })
})
