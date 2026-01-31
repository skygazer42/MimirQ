import { describe, expect, it } from 'vitest'

import { toSourcePathPrefix } from '@/lib/document-folders'

describe('toSourcePathPrefix', () => {
  it('returns undefined for empty input', () => {
    expect(toSourcePathPrefix(undefined)).toBeUndefined()
    expect(toSourcePathPrefix(null)).toBeUndefined()
    expect(toSourcePathPrefix('')).toBeUndefined()
    expect(toSourcePathPrefix('   ')).toBeUndefined()
  })

  it('adds a trailing slash for folder paths', () => {
    expect(toSourcePathPrefix('foo')).toBe('foo/')
    expect(toSourcePathPrefix('foo/bar')).toBe('foo/bar/')
  })

  it('avoids double trailing slashes', () => {
    expect(toSourcePathPrefix('foo/')).toBe('foo/')
    expect(toSourcePathPrefix('foo/bar/')).toBe('foo/bar/')
  })
})

